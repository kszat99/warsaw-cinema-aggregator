"""Scan source/configuration without printing secret values or contacting providers."""
import json
from pathlib import Path
import subprocess
import sys


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    files = subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=root,
    ).decode('utf-8').split('\0')
    paths = sorted({
        name for name in files if name and Path(root / name).is_file()
        and Path(name).parts[0] not in {'tmp', 'dist', 'outputs'}
        and name not in {'uv.lock', 'requirements.txt', '.secrets.baseline'}
    })
    result = subprocess.run(
        [sys.executable, '-m', 'detect_secrets', 'scan', '--no-verify', *paths],
        cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=120,
    )
    if result.returncode:
        print('Secret scanner failed; inspect its configuration, not raw secret values.')
        return 1
    findings = json.loads(result.stdout)['results']
    for filename, items in findings.items():
        for item in items:
            print(f"Potential secret: {filename}:{item['line_number']} ({item['type']})")
    count = sum(len(items) for items in findings.values())
    print(f'Scanned {len(paths)} source/configuration files; findings: {count}.')
    return int(count > 0)


if __name__ == '__main__':
    raise SystemExit(main())
