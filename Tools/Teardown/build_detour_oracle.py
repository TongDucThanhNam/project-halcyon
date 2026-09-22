"""Build the diagnostic public Detour oracle into a new external directory.

Requires an activated MSVC x64 developer shell and the pinned v1.6.0 source
archive. No automatic download, native-client call, or production installation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_SHA256 = '8b50c62177249554b226514b307e6c529934a62b3926822777bf6abb8906a155'
ARCHIVE_URL = 'https://codeload.github.com/recastnavigation/recastnavigation/zip/refs/tags/v1.6.0'
PREFIX = 'recastnavigation-1.6.0/'


def build(archive, output):
    archive, output = Path(archive).resolve(), Path(output).resolve()
    if output.is_relative_to(ROOT):
        raise ValueError('oracle artifacts must stay outside the checkout')
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError('public Detour archive digest differs from pinned v1.6.0')
    output.mkdir(parents=True, exist_ok=False)
    inputs = []
    with zipfile.ZipFile(archive) as source:
        for name in source.namelist():
            wanted = (name.startswith(PREFIX+'Detour/Include/') and name.endswith('.h') or
                      name.startswith(PREFIX+'Detour/Source/') and name.endswith('.cpp') or
                      name == PREFIX+'License.txt')
            if not wanted:
                continue
            relative = Path(name.removeprefix(PREFIX))
            destination = (output/relative).resolve()
            if not destination.is_relative_to(output):
                raise ValueError('archive member escaped build directory')
            destination.parent.mkdir(parents=True, exist_ok=True)
            data = source.read(name)
            destination.write_bytes(data)
            inputs.append({'path':str(relative), 'sha256':hashlib.sha256(data).hexdigest()})
    source = Path(__file__).with_name('detour_route_oracle.cpp')
    library = output/'detour_route_oracle.dll'
    commands = [['cl.exe', '/nologo', '/O2', '/EHsc', '/fp:strict', '/MD', '/LD',
                 '/I', str(output/'Detour/Include'), str(source),
                 *map(str, sorted((output/'Detour/Source').glob('*.cpp'))),
                 '/link', '/OUT:'+str(library)]]
    for index, command in enumerate(commands):
        process = subprocess.run(command, cwd=output, capture_output=True, timeout=60)
        (output/f'build-{index}.stdout.log').write_bytes(process.stdout)
        (output/f'build-{index}.stderr.log').write_bytes(process.stderr)
        process.check_returncode()
    manifest = {'schema':1, 'scope':'diagnostic native-path comparison only',
                'archive_url':ARCHIVE_URL, 'archive_sha256':ARCHIVE_SHA256,
                'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                'library_sha256':hashlib.sha256(library.read_bytes()).hexdigest(),
                'public_source_inputs':inputs, 'commands':commands}
    library.with_suffix('.build.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return library


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recast-archive',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    print(build(args.recast_archive,args.output))


if __name__ == '__main__':
    main()
