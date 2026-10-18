from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import capture_diagnostics as capture


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='efs-readonly-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = []
        self.properties = b'ro.product.device=coral\nro.build.product=coral\nsys.boot_completed=1\npersist.radio.multisim.config=dsds\n'
        self.digest_report = ''.join(f'{name}|{size}|{"a" * 64}\n' for name, size in capture.SIZES.items()).encode()

    def adb(self, adb, serial, arguments):
        self.calls.append(arguments)
        if arguments == ['devices']:
            return subprocess.CompletedProcess(arguments, 0, b'List of devices attached\nMOCK-SERIAL\tdevice\n', b'')
        if arguments == ['shell', capture.PROPERTY_SCRIPT]:
            return subprocess.CompletedProcess(arguments, 0, self.properties, b'')
        if arguments == ['shell', capture.HASH_SCRIPT]:
            return subprocess.CompletedProcess(arguments, 0, self.digest_report, b'')
        if arguments == ['shell', 'dmesg']:
            return subprocess.CompletedProcess(arguments, 1, b'', b'Permission denied\n')
        return subprocess.CompletedProcess(arguments, 0, b'synthetic log evidence\n', b'')

    def manifest(self, folder):
        return json.loads((folder / 'capture.json').read_text())

    def test_android_capture_collects_logs_with_optional_dmesg_failure(self):
        folder = self.root / 'android'
        with patch.object(capture, 'adb_run', side_effect=self.adb):
            archive = capture.collect('android', folder, 'adb')
        self.assertTrue(self.manifest(folder)['complete'])
        with ZipFile(archive) as contents:
            self.assertIn('radio.txt', contents.namelist())
            self.assertIn('all-logcat.txt', contents.namelist())
            self.assertNotIn('efs_backup', ' '.join(contents.namelist()))
        for arguments in self.calls:
            self.assertIn(arguments[0], ('devices', 'shell', 'logcat'))
            self.assertNotIn('root', arguments)
            self.assertNotIn('reboot', arguments)

    def test_recovery_capture_reads_hashes_without_comparison_archive(self):
        self.properties += b'ro.twrp.version=3.7\n'
        folder = self.root / 'recovery'
        with patch.object(capture, 'adb_run', side_effect=self.adb):
            capture.collect('recovery', folder, 'adb')
        self.assertTrue(self.manifest(folder)['complete'])
        self.assertEqual(set(self.manifest(folder)['partition_comparison'].values()), {'not_compared'})

    def test_wrong_environment_rejected_before_output_creation(self):
        folder = self.root / 'wrong-mode'
        with patch.object(capture, 'adb_run', side_effect=self.adb):
            with self.assertRaises(ValueError): capture.collect('recovery', folder, 'adb')
        self.assertFalse(folder.exists())

    def test_conflicting_flame_and_coral_identity_is_rejected(self):
        self.properties = b'ro.product.device=flame\nro.build.product=coral\n'
        folder = self.root / 'wrong-device'
        with patch.object(capture, 'adb_run', side_effect=self.adb):
            with self.assertRaises(ValueError): capture.collect('android', folder, 'adb')
        self.assertFalse(folder.exists())

    def test_flame_android_capture_is_supported(self):
        self.properties = self.properties.replace(b'coral', b'flame')
        folder = self.root / 'flame'
        with patch.object(capture, 'adb_run', side_effect=self.adb):
            capture.collect('android', folder, 'adb')
        self.assertTrue(self.manifest(folder)['complete'])

    def test_primary_identity_from_other_phone_is_rejected(self):
        self.properties = b'ro.product.device=sunfish\nro.build.product=coral\n'
        folder = self.root / 'other-phone'
        with patch.object(capture, 'adb_run', side_effect=self.adb):
            with self.assertRaises(ValueError): capture.collect('android', folder, 'adb')
        self.assertFalse(folder.exists())

    def test_multiple_phones_require_selection(self):
        result = subprocess.CompletedProcess([], 0, b'List of devices attached\nA\tdevice\nB\tdevice\n', b'')
        with patch.object(capture, 'adb_run', return_value=result):
            with self.assertRaises(ValueError): capture.choose_device('adb', None)
            self.assertEqual(capture.choose_device('adb', 'B'), 'B')

    def test_unauthorized_device_rejected(self):
        result = subprocess.CompletedProcess([], 0, b'List of devices attached\nA\tunauthorized\n', b'')
        with patch.object(capture, 'adb_run', return_value=result):
            with self.assertRaises(ValueError): capture.choose_device('adb', None)

    def test_existing_output_is_not_overwritten(self):
        folder = self.root / 'existing'
        folder.mkdir()
        (folder / 'keep').write_text('original')
        with patch.object(capture, 'adb_run', side_effect=self.adb):
            with self.assertRaises(ValueError): capture.collect('android', folder, 'adb')
        self.assertEqual((folder / 'keep').read_text(), 'original')

    def test_required_failure_is_recorded_as_incomplete(self):
        def failing(adb, serial, arguments):
            if arguments[:3] == ['logcat', '-b', 'radio']:
                return subprocess.CompletedProcess(arguments, 1, b'', b'log failure')
            return self.adb(adb, serial, arguments)
        folder = self.root / 'partial'
        with patch.object(capture, 'adb_run', side_effect=failing):
            capture.collect('android', folder, 'adb')
        self.assertFalse(self.manifest(folder)['complete'])

    def test_timeout_is_kept_as_partial_evidence(self):
        def timing_out(adb, serial, arguments):
            if arguments[:3] == ['logcat', '-b', 'radio']:
                raise subprocess.TimeoutExpired(arguments, 45, output=b'partial radio')
            return self.adb(adb, serial, arguments)
        folder = self.root / 'timeout'
        with patch.object(capture, 'adb_run', side_effect=timing_out):
            capture.collect('android', folder, 'adb')
        self.assertFalse(self.manifest(folder)['complete'])
        self.assertEqual((folder / 'radio.txt').read_bytes(), b'partial radio')

    def test_incomplete_partition_report_is_not_called_complete(self):
        self.properties += b'ro.twrp.version=3.7\n'
        self.digest_report = b''
        folder = self.root / 'bad-hashes'
        with patch.object(capture, 'adb_run', side_effect=self.adb):
            capture.collect('recovery', folder, 'adb')
        self.assertFalse(self.manifest(folder)['complete'])

    def test_comparison_distinguishes_equal_and_different_without_claiming_corruption(self):
        expected = {name: 'a' * 64 for name in capture.SIZES}
        expected['fsc'] = 'b' * 64
        result = capture.compare_partitions(self.digest_report, expected)
        self.assertEqual(result['modemst1'], 'unchanged_from_backup')
        self.assertEqual(result['fsc'], 'different_from_backup')

    def test_malformed_or_duplicate_partition_reports_rejected(self):
        for data in [b'wrong', self.digest_report + self.digest_report, self.digest_report.replace(b'131072', b'1')]:
            with self.subTest(data=data[:40]):
                with self.assertRaises(ValueError): capture.compare_partitions(data)

    def test_comparison_zip_reads_backup_bytes_without_exporting_them(self):
        path = self.root / 'personal.zip'
        with ZipFile(path, 'w') as archive:
            for name, size in capture.SIZES.items(): archive.writestr('efs_backup/' + name, b'x' * size)
        expected = capture.expected_hashes(path)
        self.assertEqual(expected['fsc'], hashlib.sha256(b'x' * capture.SIZES['fsc']).hexdigest())


if __name__ == '__main__':
    unittest.main(verbosity=2)
