#!/usr/bin/env python3
"""Package public source and an empty, text-only recovery ZIP for GitHub."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from build import build_template, version
from scripts.package_source import package_source

TEMPLATE_FILES = {
    'META-INF/com/google/android/update-binary',
    'META-INF/com/google/android/updater-script',
    'install/restore.sh',
    'install/dsds.sh',
    'install/persistent-dsds.awk',
    'README.txt',
    'DIAGNOSTICS.md',
    'tools/capture_diagnostics.py',
    'efs_backup/README.txt',
    'SHA256SUMS',
}


def audit_template(path: Path) -> None:
    with ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(TEMPLATE_FILES) or set(names) != TEMPLATE_FILES:
            raise ValueError('Public template contains unexpected entries')
        for item in archive.infolist():
            data = archive.read(item)
            data.decode('utf-8')
            if b'\x00' in data or len(data) > 131071:
                raise ValueError(f'Public template contains non-text/oversized data: {item.filename}')
        if archive.testzip() is not None:
            raise ValueError('Public template failed ZIP CRC validation')


def package_release(output_dir: Path | None = None) -> tuple[Path, Path]:
    output_dir = Path(output_dir or ROOT / 'public-dist')
    output_dir.mkdir(parents=True, exist_ok=True)
    release = version()
    source = output_dir / f'Floral-EFS-Toolkit-v{release}-source.zip'
    template = output_dir / f'Floral-EFS-Restore-coral-v{release}-TEMPLATE.zip'
    for path in (source, source.with_suffix('.zip.sha256'), template, template.with_suffix('.zip.sha256')):
        if path.exists() or path.is_symlink():
            raise FileExistsError(f'Refusing to replace release asset: {path.name}')
    package_source(ROOT, output_dir)
    build_template(template)
    audit_template(template)
    checksum = hashlib.sha256(template.read_bytes()).hexdigest()
    template.with_suffix('.zip.sha256').write_text(f'{checksum}  {template.name}\n', encoding='ascii')
    return source, template


if __name__ == '__main__':
    for artifact in package_release():
        print(artifact)
