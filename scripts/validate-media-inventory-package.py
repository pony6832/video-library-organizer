"""Validate this package's deliberately simple frontmatter using stdlib only.

This is a package integrity check, not a general YAML parser or security audit.
"""
import argparse
from pathlib import Path
import sys


REQUIRED = (
    'SKILL.md', 'agents/openai.yaml', 'scripts/run_media_catalog.ps1',
    'scripts/run_media_analysis.ps1', 'scripts/run_media_analysis_ui.ps1',
)


def validate(root: Path) -> None:
    for relative in REQUIRED:
        path = root / relative
        if not path.is_file() or not path.stat().st_size:
            raise ValueError(f'Missing or empty required file: {relative}')
    lines = (root / 'SKILL.md').read_text(encoding='utf-8-sig').splitlines()
    if not lines or lines[0] != '---':
        raise ValueError('SKILL.md must begin with frontmatter delimiter')
    try:
        end = lines.index('---', 1)
    except ValueError:
        raise ValueError('Missing closing frontmatter delimiter') from None
    fields = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key, separator, value = line.partition(':')
        if not separator or key not in ('name', 'description') or key in fields:
            raise ValueError('Expected unique name and description scalar fields')
        value = value.strip()
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f'Unclosed quoted {key}')
            value = value[1:-1].strip()
        if not value or value in ('|', '>', 'null', '~') or value.startswith(('[', '{')):
            raise ValueError(f'{key} must be a nonempty single-line string')
        fields[key] = value
    if fields.get('name') != 'media-inventory' or not fields.get('description'):
        raise ValueError('Expected name: media-inventory and nonempty description')
    if not '\n'.join(lines[end + 1:]).strip():
        raise ValueError('SKILL.md instructions are empty')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    args = parser.parse_args()
    try:
        validate(args.package)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f'MEDIA_INVENTORY_PACKAGE_ERROR {exc}', file=sys.stderr)
        return 1
    print('MEDIA_INVENTORY_PACKAGE_VALID')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
