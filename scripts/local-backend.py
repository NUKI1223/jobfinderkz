"""Run the local venv backend against Docker Postgres on Linux, without logging secrets.

Usage: .venv/bin/python scripts/local-backend.py test|migrate|serve-tests|probe
Destructive tests are hard-wired to jobfinder_test. Use compose for production.
"""
import os
from pathlib import Path
import subprocess
import sys
from dotenv import dotenv_values
from sqlalchemy.engine import URL

root = Path(__file__).resolve().parents[1]
mode = sys.argv[1]
commands = {'test': ['pytest', '-q', '-p', 'no:cacheprovider'],
    'migrate': ['alembic', 'upgrade', 'head'], 'serve-tests': ['python', '-m', 'tests.e2e_server'],
    'probe': ['python', '-m', 'app.openai_probe']}
if mode not in commands:
    raise SystemExit('Expected test, migrate, serve-tests or probe')
values = dotenv_values(root / '.env')
ip = subprocess.check_output(['docker', 'inspect', '-f',
    '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}', 'jobfinderkz-db-1'], text=True).strip()
env = {**os.environ, **{k: v for k, v in values.items() if v is not None}}
env['DATABASE_URL'] = URL.create('postgresql+psycopg', username='jobfinder',
    password=values.get('POSTGRES_PASSWORD', 'local-jobfinder-password'), host=ip,
    database='jobfinder_test').render_as_string(hide_password=False)
env['PATH'] = str(root / '.venv/bin') + os.pathsep + env['PATH']
env['STORAGE_PATH'] = str(root / 'backups/test-storage')
env['E2E_PORT'] = '8001'
if mode == 'serve-tests':
    env['APP_ORIGIN'] = 'http://localhost:5174'
if mode != 'probe':
    env.update(OPENAI_API_KEY='', GEMINI_API_KEY='', HH_ACCESS_TOKEN='', LIVE_CHECK_MODE='false')
raise SystemExit(subprocess.call(commands[mode] + sys.argv[2:], cwd=root / 'backend', env=env))
