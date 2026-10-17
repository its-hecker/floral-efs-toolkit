#!/usr/bin/env python3
"""Read-only Android/recovery evidence collection for a failed first EFS boot."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED

SIZES = {'modemst1': 2097152, 'modemst2': 2097152, 'fsg': 2097152, 'fsc': 131072}
PROPERTIES = (
    'ro.product.device', 'ro.build.product', 'ro.product.vendor.device',
    'ro.build.fingerprint', 'ro.vendor.build.fingerprint', 'ro.bootloader',
    'ro.boot.slot_suffix', 'ro.bootmode', 'ro.boot.mode', 'gsm.version.baseband',
    'persist.radio.multisim.config', 'persist.vendor.radio.multisim_switch_support',
    'persist.vendor.mdm.multisim.cfg',
    'sys.boot_completed', 'init.svc.rmt_storage', 'init.svc.modem_svc',
    'init.svc.vendor.qcrild', 'init.svc.vendor.qcrild2',
    'ro.twrp.version', 'ro.orangefox.version', 'ro.fox.version',
)
PROPERTY_SCRIPT = '\n'.join(f"printf '%s=' '{name}'; getprop '{name}'" for name in PROPERTIES)

# These shell snippets perform reads only. Never start radio services or
# modify Android settings, flags, partitions, mounts or reboot state.
HASH_SCRIPT = r'''
[ "$(id -u)" = 0 ] || { echo 'Recovery root required' >&2; exit 1; }
for service in rmt_storage vendor.rmt_storage vendor.qti.rmt_storage modem_svc tftp_server vendor.ril-daemon vendor.qcrild vendor.qcrild2; do
    [ "$(getprop "init.svc.$service")" != running ] || { echo "Radio service running: $service" >&2; exit 1; }
done
for part in modemst1 modemst2 fsg fsc; do
    target=''
    for base in /dev/block/bootdevice/by-name /dev/block/by-name /dev/block/platform/*/by-name /dev/block/platform/*/*/by-name; do
        [ -e "$base/$part" ] || continue
        resolved=$(readlink -f "$base/$part") || continue
        case "$resolved" in /dev/block/*) ;; *) continue;; esac
        [ -b "$resolved" ] || continue
        target=$resolved
        break
    done
    [ -n "$target" ] || { echo "Missing partition: $part" >&2; exit 1; }
    size=$(blockdev --getsize64 "$target") || exit 1
    checksum=$(sha256sum "$target") || exit 1
    printf '%s|%s|%s\n' "$part" "$size" "${checksum%% *}"
done
'''

METADATA_SCRIPT = r'''
for path in /data/vendor/modem_fdr /data/vendor/modem_fdr/fdr_check /data/vendor/rfs/mpss /data/vendor/radio/copy_complete /data/vendor/radio/db_check_done /data/property/persistent_properties /mnt/vendor/persist/rfs/msm/mpss; do
    ls -ldZ "$path" 2>&1
done
'''

RESTORE_LOG_SCRIPT = r'''
for directory in /tmp/hecker-efs-coral.*; do
    [ -d "$directory" ] || continue
    for name in restore.log partition-state.tsv before-restore/SHA256SUMS; do
        file="$directory/$name"
        [ -f "$file" ] && [ ! -L "$file" ] || continue
        printf '\n=== %s ===\n' "$file"
        head -c 131072 "$file"
    done
done
'''


def adb_run(adb: str, serial: str | None, arguments: list[str]) -> subprocess.CompletedProcess:
    prefix = [adb] + (['-s', serial] if serial else [])
    return subprocess.run(prefix + arguments, capture_output=True, timeout=45)


def choose_device(adb: str, serial: str | None) -> str:
    result = adb_run(adb, None, ['devices'])
    if result.returncode:
        raise ValueError('adb devices failed; check platform-tools and the USB connection')
    connected = {}
    for line in result.stdout.decode('utf-8', errors='replace').splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1] in ('device', 'unauthorized', 'offline', 'recovery', 'sideload'):
            connected[fields[0]] = fields[1]
    if serial:
        if connected.get(serial) not in ('device', 'recovery'):
            raise ValueError('Selected device is unavailable or unauthorized; exit sideload if active')
        return serial
    available = [name for name, state in connected.items() if state in ('device', 'recovery')]
    if len(available) != 1:
        raise ValueError('Connect exactly one authorized phone, or select it with --serial; exit sideload if active')
    return available[0]


def private_write(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(data)


def parse_properties(data: bytes) -> dict[str, str]:
    return dict(line.split('=', 1) for line in data.decode('utf-8', errors='replace').splitlines() if '=' in line)


def verify_mode(properties: dict[str, str], mode: str) -> None:
    devices = [properties.get(name, '') for name in ('ro.product.device', 'ro.build.product', 'ro.product.vendor.device')]
    if 'flame' in devices or 'coral' not in devices:
        raise ValueError('This diagnostic collector requires Pixel 4 XL (coral)')
    recovery = any(properties.get(name) for name in ('ro.twrp.version', 'ro.orangefox.version', 'ro.fox.version')) or any(
        properties.get(name) == 'recovery' for name in ('ro.bootmode', 'ro.boot.mode'))
    if (mode == 'recovery') != recovery:
        raise ValueError(f'The selected phone is not in the requested {mode} environment')


def expected_hashes(restore_zip: Path) -> dict[str, str]:
    expected = {}
    with ZipFile(restore_zip) as archive:
        for name, size in SIZES.items():
            info = archive.getinfo('efs_backup/' + name)
            if info.file_size != size:
                raise ValueError(f'Unexpected backup size in comparison ZIP: {name}')
            expected[name] = hashlib.sha256(archive.read(info)).hexdigest()
    return expected


def compare_partitions(data: bytes, expected: dict[str, str] | None = None) -> dict:
    current = {}
    for line in data.decode('ascii').splitlines():
        fields = line.split('|')
        if len(fields) != 3:
            raise ValueError('Malformed partition digest report')
        name, size, digest = fields
        if name not in SIZES or name in current or size != str(SIZES[name]) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('Invalid partition digest/size report')
        current[name] = digest
    if set(current) != set(SIZES):
        raise ValueError('Incomplete partition digest report')
    if expected is None:
        return {name: 'not_compared' for name in SIZES}
    return {name: ('unchanged_from_backup' if current[name] == expected[name] else 'different_from_backup') for name in SIZES}


def collect(mode: str, output: Path, adb: str, serial: str | None = None, restore_zip: Path | None = None) -> Path:
    serial = choose_device(adb, serial)
    properties = adb_run(adb, serial, ['shell', PROPERTY_SCRIPT])
    if properties.returncode:
        raise ValueError('Cannot read device properties; check ADB authorization and exit sideload')
    verify_mode(parse_properties(properties.stdout), mode)
    expected = expected_hashes(restore_zip) if restore_zip else None
    output = Path(output).expanduser().absolute()
    archive_path = output.with_name(output.name + '.zip')
    if output.exists() or output.is_symlink() or archive_path.exists() or archive_path.is_symlink():
        raise ValueError('Output folder or archive already exists; choose a new --output name')
    output.mkdir(parents=True, mode=0o700)
    private_write(output / 'properties.txt', properties.stdout)
    records = [{'name': 'properties', 'returncode': properties.returncode, 'required': True}]
    commands = ([('radio', ['logcat', '-b', 'radio', '-d', '-v', 'threadtime'], True),
                 ('all-logcat', ['logcat', '-b', 'all', '-d', '-v', 'threadtime'], True),
                 ('dmesg', ['shell', 'dmesg'], False)] if mode == 'android' else
                [('partition-digests', ['shell', HASH_SCRIPT], True),
                 ('modem-path-metadata', ['shell', METADATA_SCRIPT], False),
                 ('recovery-restore-logs', ['shell', RESTORE_LOG_SCRIPT], False)])
    comparison = None
    for name, arguments, required in commands:
        try:
            result = adb_run(adb, serial, arguments)
        except subprocess.TimeoutExpired as error:
            result = subprocess.CompletedProcess(arguments, 124, error.stdout or b'', b'Capture command timed out\n')
        private_write(output / (name + '.txt'), result.stdout)
        private_write(output / (name + '.stderr.txt'), result.stderr)
        records.append({'name': name, 'returncode': result.returncode, 'required': required})
        if name == 'partition-digests' and result.returncode == 0:
            try:
                comparison = compare_partitions(result.stdout, expected)
            except (ValueError, UnicodeError) as error:
                records[-1]['returncode'] = 1
                records[-1]['validation_error'] = str(error)
    complete = all(record['returncode'] == 0 for record in records if record['required'])
    manifest = {'format': 1, 'mode': mode, 'captured_utc': datetime.now(timezone.utc).isoformat(),
                'complete': complete, 'commands': records, 'partition_comparison': comparison,
                'interpretation': 'Different hashes alone do not prove corruption: the modem normally writes its storage. Correlate with failed-boot radio logs.',
                'privacy': 'Keep private. Logs may contain identifiers, phone numbers, or other personal information. No raw EFS images were collected.'}
    private_write(output / 'capture.json', (json.dumps(manifest, indent=2) + '\n').encode('utf-8'))
    descriptor = os.open(archive_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        with ZipFile(stream, 'w', ZIP_DEFLATED, compresslevel=9) as archive:
            for file in sorted(output.iterdir()):
                archive.write(file, file.name)
    return archive_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('android', 'recovery'))
    parser.add_argument('--output', type=Path, required=True, help='New local evidence folder and ZIP; existing names are refused')
    parser.add_argument('--serial', help='Select one authorized device when several are connected')
    parser.add_argument('--restore-zip', type=Path, help='Optional personal restore ZIP for digest comparison in recovery')
    args = parser.parse_args()
    adb = shutil.which('adb')
    if not adb:
        parser.exit(1, 'adb is not on PATH. Install Android platform-tools first.\n')
    if args.restore_zip and args.mode != 'recovery':
        parser.error('--restore-zip is only used with recovery capture')
    args.output = args.output.expanduser().absolute()
    try:
        archive = collect(args.mode, args.output, adb, args.serial, args.restore_zip)
    except (OSError, ValueError, KeyError, BadZipFile, subprocess.TimeoutExpired) as error:
        parser.exit(1, f'Capture failed: {error}\n')
    manifest = json.loads((args.output / 'capture.json').read_text(encoding='utf-8'))
    print(f'Captured: {archive}')
    print('Keep this evidence private. No phone settings or partitions were changed.')
    if not manifest['complete']:
        parser.exit(1, 'Some required reads failed. The ZIP contains the errors; do not treat it as a complete capture.\n')


if __name__ == '__main__':
    main()
