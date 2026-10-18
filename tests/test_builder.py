from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from build import build_zip, build_template, SIZES
from scripts.package_source import PUBLIC_FILES, package_source
from scripts.package_release import audit_template, package_release


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='public-efs-builder-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / 'backups'
        self.inputs.mkdir()
        for index, (name, size) in enumerate(SIZES.items()):
            (self.inputs / name).write_bytes(bytes([index + 111]) * size)
        self.output = self.root / 'restore.zip'

    def test_generated_zip_contains_identical_synthetic_backups(self):
        build_zip(self.inputs, self.output)
        with ZipFile(self.output) as archive:
            self.assertIsNone(archive.testzip())
            for name in SIZES:
                self.assertEqual(archive.read(f'efs_backup/{name}'), (self.inputs / name).read_bytes())
            script = archive.read('install/restore.sh').decode()
            self.assertNotIn('@SHA256_', script)
            self.assertIn('RESTORE_DSDS=1', script)
            self.assertIn('tools/capture_diagnostics.py', archive.namelist())
            self.assertIn('DIAGNOSTICS.md', archive.namelist())
            for record in archive.read('SHA256SUMS').decode().splitlines():
                digest, name = record.split('  ', 1)
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)
            entry = archive.getinfo('META-INF/com/google/android/update-binary')
            self.assertEqual((entry.external_attr >> 16) & 0o777, 0o755)

    def test_no_dsds_build_disables_property_updates(self):
        build_zip(self.inputs, self.output, enable_dsds=False)
        with ZipFile(self.output) as archive:
            self.assertIn(b'RESTORE_DSDS=0', archive.read('install/restore.sh'))
            self.assertIn(b'DSDS: unchanged', archive.read('README.txt'))

    def test_public_template_contains_only_installer_and_backup_guidance(self):
        # Neighboring input backups exist, but the public path must never read
        # or package them, nor insert their hashes in the public installer.
        build_template(self.output)
        audit_template(self.output)
        with ZipFile(self.output) as archive:
            self.assertEqual([n for n in archive.namelist() if n.startswith('efs_backup/')],
                             ['efs_backup/README.txt'])
            script = archive.read('install/restore.sh')
            self.assertIn(b'BACKUP_HASH_MODE=archive', script)
            self.assertIn(b'TARGET_DEVICE=floral', script)
            self.assertNotIn(b'@SHA256_', script)
            for name in SIZES:
                self.assertNotIn('efs_backup/' + name, archive.namelist())
                digest = hashlib.sha256((self.inputs / name).read_bytes()).hexdigest().encode()
                self.assertNotIn(digest, script)
            self.assertIn(b'efs_backup/modemst1', archive.read('efs_backup/README.txt'))

    def test_template_cli_requires_no_backup_directory(self):
        result = subprocess.run([sys.executable, str(ROOT / 'build.py'), '--template',
                                 '--output', str(self.output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        audit_template(self.output)

    def test_flame_personal_build_records_the_selected_model(self):
        build_zip(self.inputs, self.output, device='flame')
        with ZipFile(self.output) as archive:
            self.assertIn(b'TARGET_DEVICE=flame', archive.read('install/restore.sh'))
            self.assertIn(b'ORIGINAL FLAME HANDSET', archive.read('README.txt'))

    def test_personal_builder_rejects_unsupported_models(self):
        with self.assertRaises(ValueError): build_zip(self.inputs, self.output, device='sunfish')
        self.assertFalse(self.output.exists())

    def test_release_packages_only_source_and_empty_template_with_checksums(self):
        assets = package_release(self.root / 'public')
        self.assertEqual(len(assets), 2)
        audit_template(assets[1])
        for asset in assets:
            expected = hashlib.sha256(asset.read_bytes()).hexdigest() + '  ' + asset.name + '\n'
            self.assertEqual(asset.with_suffix('.zip.sha256').read_text(), expected)

    def test_public_release_audit_rejects_added_backup_payload(self):
        build_template(self.output)
        with ZipFile(self.output, 'a') as archive:
            archive.writestr('efs_backup/modemst1', b'private backup placeholder')
        with self.assertRaises(ValueError): audit_template(self.output)

    def test_public_release_audit_rejects_binary_disguised_as_guidance(self):
        build_template(self.output)
        with ZipFile(self.output) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        entries['efs_backup/README.txt'] = b'private\x00bytes'
        with ZipFile(self.output, 'w') as archive:
            for name, data in entries.items(): archive.writestr(name, data)
        with self.assertRaises(ValueError): audit_template(self.output)

    def test_missing_file_prevents_output(self):
        (self.inputs / 'fsc').unlink()
        with self.assertRaises(ValueError): build_zip(self.inputs, self.output)
        self.assertFalse(self.output.exists())

    def test_wrong_size_prevents_output(self):
        (self.inputs / 'modemst2').write_bytes(b'truncated')
        with self.assertRaises(ValueError): build_zip(self.inputs, self.output)
        self.assertFalse(self.output.exists())

    def test_symlink_input_prevents_output(self):
        path = self.inputs / 'fsc'
        path.rename(self.inputs / 'real-fsc')
        path.symlink_to(self.inputs / 'real-fsc')
        with self.assertRaises(ValueError): build_zip(self.inputs, self.output)
        self.assertFalse(self.output.exists())

    def test_existing_output_is_never_overwritten(self):
        self.output.write_bytes(b'important-existing-file')
        with self.assertRaises(FileExistsError): build_zip(self.inputs, self.output)
        self.assertEqual(self.output.read_bytes(), b'important-existing-file')

    def test_output_symlink_is_not_followed(self):
        target = self.root / 'important'
        target.write_bytes(b'keep')
        self.output.symlink_to(target)
        with self.assertRaises(FileExistsError): build_zip(self.inputs, self.output)
        self.assertEqual(target.read_bytes(), b'keep')

    def test_output_is_private_on_posix(self):
        build_zip(self.inputs, self.output)
        if os.name == 'posix': self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)

    def test_build_cli_accepts_spaces_in_paths(self):
        result = subprocess.run([sys.executable, str(ROOT / 'build.py'), '--backup-dir', str(self.inputs),
                                 '--output', str(self.root / 'folder with spaces' / 'private restore.zip')],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_source_release_contains_only_allowlisted_public_files(self):
        archive_path = package_source(ROOT, self.root / 'source')
        with ZipFile(archive_path) as archive:
            names = [name.split('/', 1)[1] for name in archive.namelist()]
            self.assertEqual(set(names), set(PUBLIC_FILES) | {'SOURCE_SHA256SUMS'})
            self.assertFalse(any('efs_backup' in name or name.endswith('.zip') for name in names))
            for item in archive.infolist():
                data = archive.read(item)
                data.decode('utf-8')
                self.assertNotIn(b'\0', data)
        self.assertTrue(archive_path.with_suffix('.zip.sha256').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
