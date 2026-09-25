"""Consistent private backup, or isolated restore verification, using Docker Compose.

python scripts/backup-linux.py backup backups/transfer-YYYYMMDD
python scripts/backup-linux.py verify backups/transfer-YYYYMMDD jobfinder-restore-YYYYMMDD
Verification never starts API/worker and refuses existing volumes.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
os.chdir(root)


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def backup(directory):
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    running = subprocess.check_output(['docker', 'compose', 'ps', '--status', 'running', '--services', 'api', 'worker'], text=True).split()
    try:
        if running:
            run(['docker', 'compose', 'stop', *running], stdout=subprocess.DEVNULL)
        with open(directory / 'jobfinder.dump', 'wb') as output:
            run(['docker', 'exec', 'jobfinderkz-db-1', 'pg_dump', '-U', 'jobfinder', '-d', 'jobfinder', '-Fc'], stdout=output)
        with open(directory / 'storage.tar', 'wb') as output:
            run(['docker', 'run', '--rm', '-v', 'jobfinderkz_storage:/storage:ro',
                 'pgvector/pgvector:pg18', 'tar', '-C', '/storage', '-cf', '-', '.'], stdout=output)
        shutil.copyfile(root / '.env', directory / '.env')
        (directory / '.env').chmod(0o600)
        files = ['jobfinder.dump', 'storage.tar', '.env']
        (directory / 'SHA256.json').write_text(json.dumps({f: digest(directory / f) for f in files}, indent=2))
        run(['pg_restore', '--list', str(directory / 'jobfinder.dump')], stdout=subprocess.DEVNULL)
    finally:
        if running:
            run(['docker', 'compose', 'up', '-d', *running], stdout=subprocess.DEVNULL)
    print('Consistent backup and manifest created. Private data: keep this directory out of Git.')


def verify(directory, project):
    if not re.fullmatch(r'jobfinder-restore-[a-z0-9-]+', project):
        raise SystemExit('Use a unique jobfinder-restore-* project name')
    for filename, expected in json.loads((directory / 'SHA256.json').read_text()).items():
        if filename not in ('jobfinder.dump', 'storage.tar', '.env') or digest(directory / filename) != expected:
            raise SystemExit('Backup checksum mismatch')
    volumes = subprocess.check_output(['docker', 'volume', 'ls', '--format', '{{.Name}}'], text=True).split()
    if any(v.startswith(project + '_') for v in volumes):
        raise SystemExit('Refusing to overwrite existing restore volumes')
    compose = ['docker', 'compose', '-p', project]
    run(compose + ['up', '-d', '--wait', 'db'])
    container = project + '-db-1'
    run(['docker', 'exec', container, 'createdb', '-U', 'jobfinder', 'jobfinder_test'])
    with open(directory / 'jobfinder.dump', 'rb') as stream:
        run(['docker', 'exec', '-i', container, 'pg_restore', '-U', 'jobfinder', '-d', 'jobfinder_test',
            '--no-owner', '--no-privileges', '--exit-on-error'], stdin=stream)
    run(compose + ['run', '--rm', '--no-deps', 'api', 'python', '-m', 'app.migrate_restore'],
        stdout=subprocess.DEVNULL)
    run(['docker', 'volume', 'create', project + '_storage'], stdout=subprocess.DEVNULL)
    with open(directory / 'storage.tar', 'rb') as stream:
        run(['docker', 'run', '--rm', '-i', '-v', project + '_storage:/storage', 'pgvector/pgvector:pg18',
             'tar', '-C', '/storage', '-xf', '-'], stdin=stream)
    counts = subprocess.check_output(['docker', 'exec', container, 'psql', '-U', 'jobfinder', '-d', 'jobfinder_test', '-Atc',
        "SELECT kind||':'||status||':'||count(*) FROM records GROUP BY kind,status ORDER BY kind,status"], text=True)
    # Archive itself was checksummed before restore; validate extracted archive too.
    with open(directory / 'storage.tar', 'rb') as stream:
        run(['docker', 'run', '--rm', '-i', '-v', project + '_storage:/storage:ro',
            'pgvector/pgvector:pg18', 'tar', '-C', '/storage', '--compare', '-f', '-'], stdin=stream)
    print('Restore succeeded in isolated jobfinder_test. Record aggregates:\n' + counts)
    run(compose + ['stop', 'db'], stdout=subprocess.DEVNULL)
    print('Verification database stopped. Volumes retained for inspection: ' + project)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'backup':
        backup(Path(sys.argv[2]).resolve())
    elif len(sys.argv) == 4 and sys.argv[1] == 'verify':
        verify(Path(sys.argv[2]).resolve(), sys.argv[3])
    else:
        raise SystemExit(__doc__)
