"""Fail closed on missing runtime, credentials, private paths and non-lite assets."""
from pathlib import Path
import argparse
import json
import re
import marshal
import zipfile


def audit(root, *, frozen_archive=False):
    root = Path(root)
    errors = []
    for pattern in ('MediaCatalogVideoDesktop.exe', '_internal/python3*.dll',
                    '_internal/_tkinter.pyd', '_internal/base_library.zip',
                    'README-zh-TW.md', 'THIRD-PARTY-NOTICES.txt'):
        if not any(root.glob(pattern)):
            errors.append(f'missing runtime component: {pattern}')
    for path in root.rglob('*'):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            errors.append('reparse point in bundle')
            continue
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part.lower() in {'.git', '.venv', '.env', 'node_modules', 'tests', 'pytest', '_pytest'} for part in relative.parts):
            errors.append(f'forbidden bundle entry: {relative}')
        if path.suffix.lower() in {'.gguf', '.safetensors', '.onnx', '.mp4', '.mov', '.jpg', '.jpeg', '.sqlite', '.db'}:
            errors.append(f'non-lite content: {relative}')
        data = path.read_bytes()
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                data += b''.join(archive.read(name) for name in archive.namelist())
        if frozen_archive and path.name == 'MediaCatalogVideoDesktop.exe':
            from PyInstaller.archive.readers import CArchiveReader
            archive = CArchiveReader(str(path))
            for name in archive.toc:
                if name != 'PYZ.pyz':
                    data += archive.extract(name)
            pyz = archive.open_embedded_archive('PYZ.pyz')
            for name in pyz.toc:
                if name.startswith(('pytest', '_pytest', 'setuptools', 'pip.')):
                    errors.append('development module in frozen archive: ' + name)
                data += marshal.dumps(pyz.extract(name))
        if re.search(b'AI' + rb'za[0-9A-Za-z_-]{35}', data):
            errors.append(f'credential-shaped content: {relative}')
        # python-build-standalone's vendor C assertion/debug paths are not this
        # user's private data. Keep upstream DLLs untouched; allow only that
        # exact vendor build prefix in compiled third-party runtime files.
        path_data = data
        if path.suffix.lower() in {'.dll', '.pyd'}:
            path_data = re.sub(rb'C:\\Users\\(?:Administrator|ADMINI~1)\\AppData\\Local\\Temp\\(?:python|openssl|libffi)-build-[a-z0-9_]+\\', b'', path_data)
        if re.search(rb'[A-Za-z]:[\\/]Users[\\/][^\\/\x00\r\n]+[\\/](?:Documents|AppData|Desktop)[\\/]', path_data, re.I):
            errors.append(f'private build path: {relative}')
    return errors


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--frozen-archive', action='store_true')
    arguments = parser.parse_args()
    findings = audit(arguments.bundle, frozen_archive=arguments.frozen_archive)
    print(json.dumps({'passed': not findings, 'findings': findings}, ensure_ascii=False))
    raise SystemExit(bool(findings))
