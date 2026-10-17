"""Exercise production restore logic against regular files, never block devices.

Only Android properties and kernel block-device operations are simulated.
Source validation, snapshots, actual dd copies, hashes, UI, and error handling
are the packaged implementation.
"""
from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build import build_zip, SIZES
from test_dsds_editor import BUSYBOX, TARGET, MODEM_TARGET, DSDS_RECORDS, encode_properties, decode_properties

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('modemst1', 'modemst2', 'fsg', 'fsc')

MOCKS = r'''
id() { echo 0; }
pidof() { return 1; }
getprop() {
    case "$1" in
        sys.boot_completed) [ "$SCENARIO" = android ] && echo 1 || echo 0;;
        ro.twrp.version) [ "$SCENARIO" = no_recovery ] || echo '3.7.0';;
        ro.product.device|ro.build.product)
            case "$SCENARIO" in flame) echo flame;; unknown_device) echo floral;; *) echo coral;; esac;;
        ro.product.vendor.device) [ "$SCENARIO" != conflicting_device ] || echo flame;;
        init.svc.rmt_storage) [ "$SCENARIO" != active_radio ] || echo running;;
        ro.persistent_properties.ready) [ "$SCENARIO" != property_service_active ] || echo true;;
    esac
    return 0
}
find_partition() {
    [ "$SCENARIO:$1" != missing_partition:fsc ] || return 1
    if [ "$SCENARIO:$1" = duplicate_target:modemst2 ]; then
        printf '%s/modemst1\n' "$MOCK_BLOCKS"
    else
        printf '%s/%s\n' "$MOCK_BLOCKS" "$1"
    fi
}
get_block_size() { wc -c < "$1" | tr -d '[:space:]'; }
get_block_readonly() {
    if [ "$SCENARIO:${1##*/}" = readonly:fsc ]; then echo 1; else echo 0; fi
}
flush_partition() {
    [ "$SCENARIO:${1##*/}" != flush_failure:modemst1 ]
}
dsds_property_file() { printf '%s/property/persistent_properties\n' "$MOCK_DATA"; }
dsds_modem_marker() { printf '%s/vendor/modem_fdr/fdr_check\n' "$MOCK_DATA"; }
dsds_data_mounted_rw() { [ "$SCENARIO" != data_unavailable ]; }
dsds_require_data() {
    dsds_data_mounted_rw || die 'Mount/decrypt Data in OrangeFox, then flash again.'
}
chcon() { [ "$SCENARIO" != label_failure ]; }
chown() { return 0; }
stat() {
    if [ "$1:$2" = '-c:%u:%g:%a:%h' ]; then
        if [ "$SCENARIO" = wrong_property_owner ]; then
            command stat -c '1000:0:%a:%h' "$3"
        else
            command stat -c '0:0:%a:%h' "$3"
        fi
    else
        command stat "$@"
    fi
}
ls() {
    if [ "$SCENARIO" = bad_selinux_label ]; then
        printf 'u:object_r:unlabeled:s0 %s\n' "$*"
    else
        printf 'u:object_r:property_data_file:s0 %s\n' "$*"
    fi
}
mv() {
    MOCK_DEST=''
    MOCK_STAGE=''
    for MOCK_ARG in "$@"; do
        [ "$MOCK_ARG" != -f ] || continue
        if [ -z "$MOCK_STAGE" ]; then MOCK_STAGE=$MOCK_ARG; else MOCK_DEST=$MOCK_ARG; fi
    done
    if [ "$SCENARIO" = dsds_commit_failure ]; then return 1; fi
    command mv "$@" || return $?
    case "$SCENARIO:$MOCK_STAGE" in
        dsds_readback_corrupt:*/.hecker-dsds.*)
            printf 'CORRUPTED-PROPERTY' > "$MOCK_DEST";;
    esac
}
SYNC_CALLS=0
sync() {
    SYNC_CALLS=$((SYNC_CALLS + 1))
    if [ "$SCENARIO:$SYNC_CALLS" = dsds_sync_failure:3 ]; then return 1; fi
    command sync
}
dd() {
    MOCK_INPUT=''
    MOCK_OUTPUT=''
    for MOCK_ARG in "$@"; do
        case "$MOCK_ARG" in if=*) MOCK_INPUT=${MOCK_ARG#if=};; of=*) MOCK_OUTPUT=${MOCK_ARG#of=};; esac
    done
    case "$MOCK_OUTPUT" in
        "$MOCK_BLOCKS"/*)
            printf '%s\n' "$MOCK_OUTPUT" >> "$WORKDIR/write-attempts.txt"
            [ "$SCENARIO:${MOCK_OUTPUT##*/}" != write_failure:modemst1 ] || return 1
            [ "$SCENARIO:${MOCK_OUTPUT##*/}" != late_write_failure:fsg ] || return 1
            ;;
    esac
    case "$MOCK_INPUT" in
        "$MOCK_BLOCKS"/*)
            [ "$SCENARIO:${MOCK_INPUT##*/}" != snapshot_read_failure:modemst2 ] || return 1
            ;;
    esac
    command dd "$@" || return $?
    case "$MOCK_OUTPUT" in
        "$WORKDIR/before-restore"/*)
            if [ "$SCENARIO:${MOCK_OUTPUT##*/}" = snapshot_corrupt:modemst2 ]; then
                printf 'CORRUPTED-SNAPSHOT' | command dd of="$MOCK_OUTPUT" bs=1 conv=notrunc
            fi
            ;;
        "$MOCK_BLOCKS"/*)
            if [ "$SCENARIO:${MOCK_OUTPUT##*/}" = readback_corrupt:modemst2 ]; then
                printf 'SIMULATED-CORRUPTION' | command dd of="$MOCK_OUTPUT" bs=1 conv=notrunc
            fi
            if [ "$SCENARIO:${MOCK_OUTPUT##*/}" = settings_changed:fsc ]; then
                command cp "$MOCK_DATA/newer-properties" "$MOCK_DATA/property/persistent_properties"
            fi
            ;;
    esac
    return 0
}
'''


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='coral-restore-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.work = self.root / 'work'
        self.blocks = self.root / 'blocks'
        self.work.mkdir()
        self.blocks.mkdir()
        self.backups = self.root / 'input-backups'
        self.backups.mkdir()
        for index, (name, size) in enumerate(SIZES.items()):
            (self.backups / name).write_bytes(bytes([index + 81]) * size)
        self.zip_path = self.root / 'personal.zip'
        build_zip(self.backups, self.zip_path)
        with ZipFile(self.zip_path) as archive:
            archive.extractall(self.work)
        self.data = self.root / 'data'
        self.property_dir = self.data / 'property'
        self.property_dir.mkdir(parents=True, mode=0o700)
        self.settings = self.property_dir / 'persistent_properties'
        self.initial_settings = encode_properties([('persist.sys.locale', 'en-PK'), (TARGET, 'dsds'),
                                                   (MODEM_TARGET, 'ss'), ('persist.keep', 'unchanged')])
        self.settings.write_bytes(self.initial_settings)
        self.settings.chmod(0o600)
        self.modem_marker = self.data / 'vendor/modem_fdr/fdr_check'
        self.modem_marker.parent.mkdir(parents=True)
        self.modem_marker.touch(mode=0o600)
        (self.data / 'newer-properties').write_bytes(encode_properties([('persist.keep', 'newer')]))
        self.log = self.work / 'restore.log'
        self.log.touch()
        self.before = {}
        for index, name in enumerate(NAMES):
            size = (self.work / 'efs_backup' / name).stat().st_size
            block = self.blocks / name
            block.write_bytes(bytes([index + 33]) * size)
            self.before[name] = sha(block)

    def run_installer(self, scenario='success'):
        shell = '\n'.join([
            'set -u',
            f'. {shlex.quote(str(self.work / "install/dsds.sh"))}',
            f'. {shlex.quote(str(self.work / "install/restore.sh"))}',
            MOCKS,
            f'WORKDIR={shlex.quote(str(self.work))}',
            f'LOG={shlex.quote(str(self.log))}',
            f'MOCK_BLOCKS={shlex.quote(str(self.blocks))}',
            f'MOCK_DATA={shlex.quote(str(self.data))}',
            f'SCENARIO={shlex.quote(scenario)}',
            'OUTFD=3',
            'exec 3>&1',
            'run_restore "$WORKDIR"',
        ])
        env = os.environ.copy()
        if BUSYBOX.exists():
            applets = self.root / 'bin'
            applets.mkdir(exist_ok=True)
            for name in ['awk', 'od', 'stat', 'cp', 'mv', 'rm', 'mktemp', 'chmod', 'chown',
                         'dd', 'sha256sum', 'wc', 'tr', 'readlink', 'sync', 'mkdir']:
                link = applets / name
                if not link.exists(): link.symlink_to(BUSYBOX)
            env['PATH'] = str(applets) + ':' + env['PATH']
            command = [str(BUSYBOX), 'ash', '-c', shell]
        else:
            command = ['sh', '-c', shell]
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
        return result

    def assert_untouched(self):
        self.assertFalse((self.work / 'write-attempts.txt').exists())
        for name in NAMES:
            self.assertEqual(sha(self.blocks / name), self.before[name])

    def assert_snapshots(self):
        for name in NAMES:
            self.assertEqual(sha(self.work / 'before-restore' / name), self.before[name])

    def assert_rejected(self, scenario, message):
        result = self.run_installer(scenario)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(message, result.stdout)
        self.assertNotIn('SUCCESS:', result.stdout)
        self.assert_untouched()

    def test_success_restores_every_partition_and_keeps_originals(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr + self.log.read_text())
        self.assertIn('SUCCESS: all four partitions restored and verified.', result.stdout)
        self.assertIn('SUCCESS: DSDS enabled for the next Android boot.', result.stdout)
        self.assertEqual(decode_properties(self.settings.read_bytes()),
                         [('persist.sys.locale', 'en-PK'), ('persist.keep', 'unchanged')] + DSDS_RECORDS)
        self.assertEqual((self.work / 'before-restore/persistent_properties').read_bytes(), self.initial_settings)
        self.assertFalse(list(self.property_dir.glob('.hecker-dsds*')))
        self.assertEqual(self.modem_marker.read_bytes(), b'')
        for name in NAMES:
            self.assertEqual(sha(self.blocks / name), sha(self.backups / name))
        self.assert_snapshots()
        self.assertEqual(len((self.work / 'write-attempts.txt').read_text().splitlines()), 4)
        report = (self.work / 'partition-state.tsv').read_text().splitlines()
        self.assertEqual(len(report), 5)
        for row in report[1:]:
            name, expected, before, after = row.split('|')
            self.assertEqual(before, self.before[name])
            self.assertEqual(expected, sha(self.backups / name))
            self.assertEqual(after, expected)

    def test_flame_rejected(self):
        self.assert_rejected('flame', 'This backup is for coral')

    def test_unknown_device_rejected(self):
        self.assert_rejected('unknown_device', 'Cannot verify Pixel 4 XL')

    def test_conflicting_flame_identity_rejected(self):
        self.assert_rejected('conflicting_device', 'flame) is not supported')

    def test_android_rejected_even_if_recovery_properties_present(self):
        self.assert_rejected('android', 'Flash this ZIP in recovery')

    def test_unidentified_recovery_rejected(self):
        self.assert_rejected('no_recovery', 'recovery was not detected')

    def test_running_radio_rejected(self):
        self.assert_rejected('active_radio', 'Radio service rmt_storage is running')

    def test_missing_backup_rejected_before_any_write(self):
        (self.work / 'efs_backup/fsc').unlink()
        self.assert_rejected('success', 'Missing or invalid backup: fsc')

    def test_corrupt_backup_rejected_before_any_write(self):
        path = self.work / 'efs_backup/modemst2'
        with path.open('r+b') as stream:
            first = stream.read(1)[0]
            stream.seek(0)
            stream.write(bytes([first ^ 255]))
        self.assert_rejected('success', 'Backup checksum mismatch: modemst2')

    def test_truncated_backup_rejected(self):
        path = self.work / 'efs_backup/fsg'
        with path.open('r+b') as stream:
            stream.truncate(100)
        self.assert_rejected('success', 'Backup size mismatch: fsg')

    def test_target_size_mismatch_rejected(self):
        with (self.blocks / 'fsc').open('ab') as stream:
            stream.write(b'x')
        self.before['fsc'] = sha(self.blocks / 'fsc')
        self.assert_rejected('success', 'Target size mismatch: fsc')

    def test_missing_partition_rejected(self):
        self.assert_rejected('missing_partition', 'Missing block partition: fsc')

    def test_readonly_partition_rejected(self):
        self.assert_rejected('readonly', 'Target is read-only: fsc')

    def test_duplicate_partition_rejected(self):
        self.assert_rejected('duplicate_target', 'same block device')

    def test_snapshot_read_failure_prevents_restore(self):
        self.assert_rejected('snapshot_read_failure', 'Cannot back up current modemst2')

    def test_snapshot_mismatch_prevents_restore(self):
        self.assert_rejected('snapshot_corrupt', 'Current partition changed while reading: modemst2')

    def test_write_failure_reports_failure_and_retains_snapshots(self):
        result = self.run_installer('write_failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Write failed: modemst1', result.stdout)
        self.assertIn('Keep recovery open', result.stdout)
        self.assertNotIn('SUCCESS:', result.stdout)
        self.assert_snapshots()

    def test_late_failure_stops_further_writes_and_retains_snapshots(self):
        result = self.run_installer('late_write_failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Write failed: fsg', result.stdout)
        self.assertNotIn('SUCCESS:', result.stdout)
        self.assertEqual(sha(self.blocks / 'fsc'), self.before['fsc'])
        self.assert_snapshots()

    def test_readback_failure_stops_and_retains_snapshots(self):
        result = self.run_installer('readback_corrupt')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Readback verification failed: modemst2', result.stdout)
        self.assertNotIn('SUCCESS:', result.stdout)
        self.assertEqual(sha(self.blocks / 'fsg'), self.before['fsg'])
        self.assertEqual(sha(self.blocks / 'fsc'), self.before['fsc'])
        self.assert_snapshots()

    def test_flush_failure_does_not_claim_success(self):
        result = self.run_installer('flush_failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Flush failed: modemst1', result.stdout)
        self.assertNotIn('SUCCESS:', result.stdout)
        self.assert_snapshots()

    def test_unavailable_data_rejects_before_efs_write(self):
        self.assert_rejected('data_unavailable', 'Mount/decrypt Data')

    def test_initialized_android_settings_required(self):
        self.settings.unlink()
        self.assert_rejected('success', 'Cannot read Android settings')

    def test_missing_modem_marker_stops_before_any_efs_write(self):
        self.modem_marker.unlink()
        self.assert_rejected('success', 'Modem initialization marker is missing or unsafe')
        self.assertEqual(self.settings.read_bytes(), self.initial_settings)
        self.assertFalse(self.modem_marker.exists())

    def test_symlinked_modem_marker_is_not_accepted(self):
        self.modem_marker.unlink()
        self.modem_marker.symlink_to(self.settings)
        self.assert_rejected('success', 'Modem initialization marker is missing or unsafe')

    def test_property_service_active_rejects_without_efs_writes(self):
        self.assert_rejected('property_service_active', 'active persistent-property service')

    def test_invalid_property_data_is_not_overwritten(self):
        self.settings.write_bytes(b'NOT-A-PROTOBUF')
        self.assert_rejected('success', 'property file is invalid or unsupported')
        self.assertEqual(self.settings.read_bytes(), b'NOT-A-PROTOBUF')

    def test_property_symlink_rejected(self):
        self.settings.unlink()
        self.settings.symlink_to(self.data / 'newer-properties')
        self.assert_rejected('success', 'Cannot read Android settings')

    def test_property_hardlink_rejected(self):
        (self.property_dir / 'linked').hardlink_to(self.settings)
        self.assert_rejected('success', 'property-file permissions or SELinux label')

    def test_unsafe_property_permissions_rejected(self):
        self.settings.chmod(0o644)
        self.assert_rejected('success', 'property-file permissions or SELinux label')

    def test_wrong_property_owner_rejected(self):
        self.assert_rejected('wrong_property_owner', 'property-file permissions or SELinux label')

    def test_efs_only_restore_succeeds_without_readable_data(self):
        archive_path = self.root / 'efs-only.zip'
        build_zip(self.backups, archive_path, enable_dsds=False)
        with ZipFile(archive_path) as archive:
            archive.extractall(self.work)
        self.settings.unlink()
        self.modem_marker.unlink()
        result = self.run_installer('data_unavailable')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('SUCCESS: all four partitions restored and verified.', result.stdout)
        self.assertIn('DSDS left unchanged', result.stdout)
        self.assertNotIn('SUCCESS: DSDS', result.stdout)
        self.assertFalse((self.work / 'before-restore/persistent_properties').exists())
        for name in NAMES:
            self.assertEqual(sha(self.blocks / name), sha(self.backups / name))

    def test_wrong_selinux_label_rejected(self):
        self.assert_rejected('bad_selinux_label', 'property-file permissions or SELinux label')

    def test_cannot_label_staged_file_leaves_settings_and_efs_untouched(self):
        self.assert_rejected('label_failure', 'Cannot set safe DSDS file permissions')
        self.assertEqual(self.settings.read_bytes(), self.initial_settings)
        self.assertFalse(list(self.property_dir.glob('.hecker-dsds*')))

    def test_efs_write_failure_does_not_commit_dsds(self):
        result = self.run_installer('late_write_failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.settings.read_bytes(), self.initial_settings)
        self.assertFalse(list(self.property_dir.glob('.hecker-dsds*')))

    def test_dsds_rename_failure_keeps_original_settings(self):
        result = self.run_installer('dsds_commit_failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('EFS restored, but saving DSDS failed', result.stdout)
        self.assertNotIn('SUCCESS:', result.stdout)
        self.assertEqual(self.settings.read_bytes(), self.initial_settings)
        self.assertFalse(list(self.property_dir.glob('.hecker-dsds*')))
        for name in NAMES:
            self.assertEqual(sha(self.blocks / name), sha(self.backups / name))

    def test_dsds_readback_failure_rolls_back_original_settings(self):
        result = self.run_installer('dsds_readback_corrupt')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Original Android settings restored', result.stdout)
        self.assertNotIn('SUCCESS:', result.stdout)
        self.assertEqual(self.settings.read_bytes(), self.initial_settings)

    def test_sync_failure_after_dsds_commit_rolls_back(self):
        result = self.run_installer('dsds_sync_failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Original Android settings restored', result.stdout)
        self.assertEqual(self.settings.read_bytes(), self.initial_settings)

    def test_settings_changed_mid_install_are_not_overwritten(self):
        result = self.run_installer('settings_changed')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Android settings changed during installation', result.stdout)
        self.assertEqual(self.settings.read_bytes(), (self.data / 'newer-properties').read_bytes())

    def test_repeated_restore_keeps_dsds_setting_stable(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        first = self.settings.read_bytes()
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.settings.read_bytes(), first)

    def test_archive_contains_unchanged_backups_and_executable_entrypoint(self):
        with ZipFile(self.zip_path) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual((archive.getinfo('META-INF/com/google/android/update-binary').external_attr >> 16) & 0o777, 0o755)
            for name in NAMES:
                self.assertEqual(archive.read('efs_backup/' + name), (self.backups / name).read_bytes())
            for record in archive.read('SHA256SUMS').decode().splitlines():
                checksum, name = record.split('  ', 1)
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), checksum)

    def test_real_entrypoint_extracts_zip_and_refuses_android(self):
        # Actual packaged bootstrap + production script. It must reject Android
        # before looking for or opening any real device partitions.
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        getprop = bin_dir / 'getprop'
        getprop.write_text('#!/bin/sh\n[ "$1" != sys.boot_completed ] || echo 1\nexit 0\n')
        getprop.chmod(0o755)
        # Recovery identity is simulated even when the CI host is unprivileged.
        identity = bin_dir / 'id'
        identity.write_text('#!/bin/sh\nprintf "0\\n"\n')
        identity.chmod(0o755)
        entry = self.work / 'META-INF/com/google/android/update-binary'
        env = os.environ.copy()
        env['PATH'] = str(bin_dir) + ':' + env['PATH']
        script = 'exec 3>&1\nexec sh "$1" 3 3 "$2"'
        result = subprocess.run(['sh', '-c', script, 'entry-test', str(entry), str(self.zip_path)], env=env, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Flash this ZIP in recovery, not in Android.', result.stdout)
        self.assertIn('No restore writes were started.', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
