"""Optional official portable runtime; no system installation, no silent download."""
import argparse
import hashlib
import json
import platform
import urllib.request
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true', help='explicitly download official Windows portable runtime')
    parser.add_argument('--tag', default='latest')
    args = parser.parse_args()
    if not args.download:
        parser.error('Pass --download to opt in. Existing runtimes can use DRAWIO_BIN instead.')
    if platform.system() != 'Windows' or platform.machine().lower() not in ('amd64', 'x86_64'):
        parser.error('This installer supports Windows x64 only; set DRAWIO_BIN for other platforms.')
    cache = Path(__file__).resolve().parents[1]/'.cache'/'drawio'
    cache.mkdir(parents=True, exist_ok=True)
    url = 'https://api.github.com/repos/jgraph/drawio-desktop/releases/' + ('latest' if args.tag == 'latest' else 'tags/'+args.tag)
    req = urllib.request.Request(url, headers={'User-Agent':'PaperFigureAgent'})
    with urllib.request.urlopen(req, timeout=40) as response:
        release = json.load(response)
    asset = next(a for a in release['assets'] if a['name'].endswith('-windows.zip'))
    expected = asset.get('digest', '')
    if not expected.startswith('sha256:'):
        raise ValueError('Official SHA256 missing; supply a verified runtime manually.')
    archive = cache/asset['name']
    if not archive.exists():
        urllib.request.urlretrieve(asset['browser_download_url'], archive)
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != expected.split(':',1)[1]:
        raise ValueError('Downloaded runtime hash mismatch')
    dest = cache/release['tag_name']
    with zipfile.ZipFile(archive) as zipped:
        for info in zipped.infolist():
            if not (dest/info.filename).resolve().is_relative_to(dest.resolve()):
                raise ValueError('Unsafe archive path')
        zipped.extractall(dest)
    exe = next(dest.rglob('draw.io.exe'))
    receipt = {'source':asset['browser_download_url'], 'sha256':actual, 'tag':release['tag_name'], 'executable':str(exe)}
    (cache/'runtime.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
