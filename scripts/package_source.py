#!/usr/bin/env python3
"""Package only explicitly listed public text files; never recovery payloads."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import stat
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = (
    '.github/workflows/ci.yml',
    '.gitignore',
    'LICENSE',
    'README.md',
    'VERSION',
    'build.py',
    'requirements-test.txt',
    'docs/DESIGN.md',
    'docs/INSTALLATION.txt',
    'docs/RELEASE_NOTES.md',
    'recovery/META-INF/com/google/android/update-binary',
    'recovery/META-INF/com/google/android/updater-script',
    'recovery/install/dsds.sh',
    'recovery/install/persistent-dsds.awk',
    'recovery/install/restore.sh.in',
    'scripts/package_source.py',
    'tests/test_builder.py',
    'tests/test_dsds_editor.py',
    'tests/test_recovery_restore.py',
)


def package_source(root: Path = ROOT, output_dir: Path | None = None) -> Path:
    root = Path(root).resolve()
    release = (root / 'VERSION').read_text(encoding='ascii').strip()
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', release):
        raise ValueError('Invalid source version')
    payloads = {}
    for name in PUBLIC_FILES:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Missing regular public source: {name}')
        data = path.read_bytes()
        data.decode('utf-8')  # All published files must be readable source text.
        if b'\x00' in data or len(data) > 131071:
            raise ValueError(f'Unexpected binary/oversized public source: {name}')
        payloads[name] = data
    payloads['SOURCE_SHA256SUMS'] = ''.join(f'{hashlib.sha256(data).hexdigest()}  {name}\n'
                                          for name, data in sorted(payloads.items())).encode('ascii')
    output_dir = Path(output_dir or root / 'public-dist')
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f'Floral-EFS-Toolkit-v{release}-source.zip'
    with ZipFile(output, 'w', ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(payloads.items()):
            entry = ZipInfo(f'floral-efs-toolkit-v{release}/{name}', date_time=(2026, 10, 17, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            entry.compress_type = ZIP_DEFLATED
            archive.writestr(entry, data, compresslevel=9)
    with ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError('Source archive CRC validation failed')
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(f'{checksum}  {output.name}\n', encoding='ascii')
    return output


if __name__ == '__main__':
    print(package_source())
