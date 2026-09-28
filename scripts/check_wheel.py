"""Build and install a wheel into a fresh environment, outside the source tree."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--uv', default=shutil.which('uv'))
    args = parser.parse_args()
    if not args.uv:
        parser.error('uv is not on PATH; pass --uv with its executable path')
    uv = str(Path(args.uv).resolve())
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='cinema-wheel-check-') as folder:
        work = Path(folder)
        subprocess.run([uv, 'build', '--wheel', '--out-dir', str(work / 'wheel')], cwd=root, check=True)
        wheel, = (work / 'wheel').glob('*.whl')
        env = work / 'environment'
        subprocess.run([uv, 'venv', '--python', sys.executable, str(env)], check=True)
        python = env / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
        subprocess.run([
            uv, 'pip', 'sync', '--python', str(python), '--require-hashes',
            str(root / 'requirements.txt'),
        ], check=True)
        subprocess.run([
            uv, 'pip', 'install', '--python', str(python), '--no-deps', str(wheel),
        ], check=True)
        # -I and a different cwd ensure source-tree imports cannot hide a broken wheel.
        subprocess.run([
            str(python), '-I', '-c',
            'from importlib.metadata import version; '
            'from cinema_agg.config import CINEMAS; '
            'from cinema_agg.build import PosterService; '
            'from cinema_agg.seat_availability import SeatAvailability; '
            'from cinema_agg.server.app import create_app; '
            'assert create_app(); '
            'assert CINEMAS; print("Installed wheel:", version("warsaw-cinema-aggregator"))',
        ], cwd=work, check=True)
    print('Fresh wheel installation and imports passed; no cinema requests made.')


if __name__ == '__main__':
    main()
