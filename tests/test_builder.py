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
from build import build_zip, SIZES
from scripts.package_source import PUBLIC_FILES, package_source


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
