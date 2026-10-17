#!/usr/bin/env python3
"""Build an offline personal coral recovery ZIP; never upload modem backups."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import stat
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parent
SIZES = {'modemst1': 2097152, 'modemst2': 2097152, 'fsg': 2097152, 'fsc': 131072}
TEMPLATES = (
    'META-INF/com/google/android/update-binary',
    'META-INF/com/google/android/updater-script',
    'install/restore.sh.in',
    'install/dsds.sh',
    'install/persistent-dsds.awk',
)


def version() -> str:
    value = (ROOT / 'VERSION').read_text(encoding='ascii').strip()
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', value):
        raise ValueError('VERSION must contain a numeric major.minor.patch version')
    return value


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_zip(backup_dir: Path, output: Path, *, enable_dsds: bool = True) -> Path:
    """Validate all input bytes before creating any output; never overwrite a ZIP."""
    backup_dir = Path(backup_dir).expanduser().resolve()
    output = Path(output).expanduser().absolute()
    if not backup_dir.is_dir():
        raise ValueError('Backup directory does not exist')
    backups = {}
    hashes = {}
    for name, size in SIZES.items():
        source = backup_dir / name
        if source.is_symlink() or not source.is_file():
            raise ValueError(f'Missing regular backup file: {name}')
        if source.stat().st_size != size:
            raise ValueError(f'Wrong size for {name}: expected {size} bytes')
        data = source.read_bytes()
        if len(data) != size:
            raise ValueError(f'Backup changed while being read: {name}')
        backups[name] = data
        hashes[name] = sha256(data)

    release = version()
    replacements = {'@VERSION@': release, '@RESTORE_DSDS@': '1' if enable_dsds else '0'}
    replacements.update({f'@SHA256_{name.upper()}@': value for name, value in hashes.items()})
    entries = {}
    for name in TEMPLATES:
        text = (ROOT / 'recovery' / name).read_text(encoding='utf-8')
        for token, value in replacements.items():
            text = text.replace(token, value)
        if re.search(r'@[A-Z0-9_]+@', text):
            raise ValueError(f'Unresolved installer template token: {name}')
        entries[name.removesuffix('.in')] = text.encode('utf-8')
    entries.update({f'efs_backup/{name}': data for name, data in backups.items()})
    entries['tools/capture_diagnostics.py'] = (ROOT / 'tools/capture_diagnostics.py').read_bytes()
    entries['DIAGNOSTICS.md'] = (ROOT / 'docs/DIAGNOSTICS.md').read_bytes()
    note = ('DSDS: both radio and saved modem mode configured. Initialized Data and modem marker required.\n'
            if enable_dsds else 'DSDS: unchanged. This package restores EFS only.\n')
    entries['README.txt'] = (f'Floral EFS Toolkit v{release} | Hecker (Maintainer)\n'
                           'PERSONAL BACKUP - ORIGINAL PIXEL 4 XL (CORAL) ONLY\n'
                           + note + '\n' + (ROOT / 'docs/INSTALLATION.txt').read_text(encoding='utf-8')).encode('utf-8')
    entries['SHA256SUMS'] = ''.join(f'{sha256(data)}  {name}\n' for name, data in sorted(entries.items())).encode('ascii')

    output.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        # O_EXCL protects existing artifacts and rejects symlink destinations.
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(fd, 'wb') as stream:
            with ZipFile(stream, 'w', ZIP_DEFLATED, compresslevel=9) as archive:
                for name, data in sorted(entries.items()):
                    entry = ZipInfo(name, date_time=(2026, 10, 17, 0, 0, 0))
                    entry.create_system = 3
                    mode = 0o755 if name.endswith(('update-binary', '.sh')) else 0o600 if name.startswith('efs_backup/') else 0o644
                    entry.external_attr = (stat.S_IFREG | mode) << 16
                    entry.compress_type = ZIP_DEFLATED
                    archive.writestr(entry, data, compresslevel=9)
        with ZipFile(output) as archive:
            if archive.testzip() is not None:
                raise ValueError('Generated ZIP failed CRC verification')
            for name, data in backups.items():
                if archive.read('efs_backup/' + name) != data:
                    raise ValueError(f'Packaged backup mismatch: {name}')
            for record in archive.read('SHA256SUMS').decode('ascii').splitlines():
                checksum, name = record.split('  ', 1)
                if sha256(archive.read(name)) != checksum:
                    raise ValueError(f'Generated manifest mismatch: {name}')
    except BaseException:
        if created:
            output.unlink(missing_ok=True)
        raise
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-dir', required=True, type=Path,
                        help='Directory with your own modemst1, modemst2, fsg and fsc files')
    parser.add_argument('--output', type=Path, help='New private ZIP path; existing files are never overwritten')
    parser.add_argument('--no-dsds', action='store_true', help='Build an EFS-only ZIP that does not need Data access')
    args = parser.parse_args()
    suffix = 'EFS-only' if args.no_dsds else 'DSDS'
    output = args.output or ROOT / 'dist' / f'Floral-EFS-Restore-coral-v{version()}-{suffix}-PERSONAL.zip'
    try:
        result = build_zip(args.backup_dir, output, enable_dsds=not args.no_dsds)
    except (OSError, ValueError) as error:
        parser.exit(1, f'Build failed: {error}\n')
    print(f'Built: {result}')
    print(f'SHA256: {sha256(result.read_bytes())}')
    print('Keep this ZIP private. Flash it only on the original coral handset.')


if __name__ == '__main__':
    main()
