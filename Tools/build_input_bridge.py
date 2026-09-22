"""Compile the nonvisual ordinary-input wrapper into a new external directory.

Requires JDK17 and pinned public R8/D8 8.3.37 supplied with --r8. Downloads,
compiled artifacts and device deployment are intentionally separate actions.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
R8_SHA256 = '59753e70a74f918389cc87f1b7d66b5c0862932559167425708ded159e3de439'
R8_URL = 'https://dl.google.com/dl/android/maven2/com/android/tools/r8/8.3.37/r8-8.3.37.jar'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--r8', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        parser.error('build evidence must be outside the checkout')
    if hashlib.sha256(args.r8.read_bytes()).hexdigest() != R8_SHA256:
        parser.error('R8/D8 artifact does not match the pinned public8.3.37 build')
    source = ROOT/'Tools/android/HalcyonInput.java'
    output.mkdir(parents=True, exist_ok=False)
    commands = [
        ['javac', '--release', '8', '-d', str(output), str(source)],
        ['java', '-cp', str(args.r8.resolve()), 'com.android.tools.r8.D8',
         '--min-api', '28', '--output', str(output), str(output/'HalcyonInput.class')],
    ]
    for i, command in enumerate(commands):
        process = subprocess.run(command, capture_output=True, timeout=60)
        (output/f'build-{i}.stdout.log').write_bytes(process.stdout)
        (output/f'build-{i}.stderr.log').write_bytes(process.stderr)
        process.check_returncode()
    dex = output/'classes.dex'
    manifest = {'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'dex_sha256': hashlib.sha256(dex.read_bytes()).hexdigest(),
                'd8': {'url': R8_URL, 'version': '8.3.37', 'sha256': R8_SHA256},
                'javac_release': 8, 'min_api': 28, 'commands': commands}
    dex.with_suffix('.build.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(dex)


if __name__ == '__main__':
    main()
