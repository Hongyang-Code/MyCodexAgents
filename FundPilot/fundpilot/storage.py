"""Versioned private snapshot transport primitives; no embedded cloud credentials.

Use Library tool uploads for immutable bytes, read back hash, then CAS HEAD.
The filesystem here is a staging area, never the durable backend.
"""
import hashlib
import json
import os
import sqlite3
import stat
import zipfile
from pathlib import Path, PurePosixPath

PROJECT = 'FundPilot'
LIMIT = 128 * 1024 * 1024


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _safe(name):
    path = PurePosixPath(name)
    if (not name or '\\' in name or path.is_absolute() or '..' in path.parts
            or ':' in name or str(path) != name or name == 'manifest.json'):
        raise ValueError('unsafe or reserved archive path')
    return path


def pack(directory, output, *, run_id, test_only):
    if type(test_only) is not bool or not isinstance(run_id, str) or not run_id.strip():
        raise ValueError('explicit test flag and run ID required')
    root = Path(directory)
    if not root.is_dir() or root.is_symlink():
        raise ValueError('real source directory required')
    files = []
    total = 0
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('symlinks forbidden')
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError('regular files required')
        name = path.relative_to(root).as_posix()
        _safe(name)
        size = path.stat().st_size
        total += size
        if total > LIMIT:
            raise ValueError('snapshot limit exceeded')
        files.append({'path': name, 'size': size, 'sha256': sha256(path)})
    if not files:
        raise ValueError('empty snapshots forbidden')
    manifest = {'schema_version': 1, 'project': PROJECT, 'run_id': run_id,
                'test_only': test_only, 'files': files}
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream, zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', json.dumps(manifest, sort_keys=True))
        for item in files:
            archive.write(root / item['path'], item['path'])
    verify(output, expected_sha=sha256(output), allow_test=test_only)
    return {'sha256': sha256(output), 'manifest': manifest}


def verify(snapshot, *, expected_sha, allow_test=False):
    if type(allow_test) is not bool or sha256(snapshot) != expected_sha:
        raise ValueError('snapshot hash mismatch or invalid test flag')
    with zipfile.ZipFile(snapshot) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        if len(names) != len(set(names)) or names.count('manifest.json') != 1:
            raise ValueError('duplicate members or missing manifest')
        if sum(i.file_size for i in infos) > LIMIT + 1024 * 1024:
            raise ValueError('snapshot too large')
        for item in infos:
            if (item.is_dir() or stat.S_ISLNK(item.external_attr >> 16)
                    or item.flag_bits & 1):
                raise ValueError('directories, symlinks and encryption forbidden')
            if item.filename != 'manifest.json':
                _safe(item.filename)
        mi = archive.getinfo('manifest.json')
        if mi.file_size > 1024 * 1024:
            raise ValueError('manifest too large')
        manifest = json.loads(archive.read(mi))
        if (manifest.get('project') != PROJECT or type(manifest.get('schema_version')) is not int
                or manifest['schema_version'] != 1 or type(manifest.get('test_only')) is not bool
                or not isinstance(manifest.get('run_id'), str) or not manifest['run_id'].strip()):
            raise ValueError('invalid snapshot identity')
        if manifest['test_only'] and not allow_test:
            raise ValueError('test snapshot cannot seed production')
        entries = manifest.get('files')
        if not isinstance(entries, list) or not entries:
            raise ValueError('files required')
        expected = set()
        for item in entries:
            name = item['path']
            _safe(name)
            if name in expected or type(item['size']) is not int or item['size'] < 0:
                raise ValueError('duplicate or invalid manifest entry')
            expected.add(name)
            data = archive.read(name)
            if len(data) != item['size'] or hashlib.sha256(data).hexdigest() != item['sha256']:
                raise ValueError('member hash mismatch')
        if expected != set(names) - {'manifest.json'}:
            raise ValueError('unmanifested members')
        return manifest


def restore(snapshot, target, *, expected_sha, allow_test=False):
    manifest = verify(snapshot, expected_sha=expected_sha, allow_test=allow_test)
    target = Path(target)
    # Resolve existing ancestors; never follow an attacker-controlled symlink.
    if any(p.is_symlink() for p in [target, *target.parents]):
        raise ValueError('symlink ancestor forbidden')
    target.mkdir(parents=True, exist_ok=False, mode=0o700)
    with zipfile.ZipFile(snapshot) as archive:
        for item in manifest['files']:
            path = target / item['path']
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            for parent in path.parents:
                if parent == target.parent:
                    break
                os.chmod(parent, 0o700)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(archive.read(item['path']))
    return manifest


def verify_sqlite(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        return connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    finally:
        connection.close()
