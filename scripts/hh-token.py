"""Get an HH application access token without printing or storing client credentials.

Run interactively: .venv/bin/python scripts/hh-token.py
Copies a successful, verified token to the private root .env.
"""
import getpass
import os
from pathlib import Path
import re
import sys
import tempfile
import httpx
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
env_path = root / '.env'
values = dotenv_values(env_path)
agent = values.get('HH_USER_AGENT') or 'JobFinderKZ/0.1 (owner@example.com)'
print('HH application token. Values entered here are not echoed or saved.')
client_id = getpass.getpass('Client ID: ').strip()
client_secret = getpass.getpass('Client secret: ').strip()
if not client_id or not client_secret:
    raise SystemExit('Both client ID and client secret are required.')
try:
    with httpx.Client(timeout=30, headers={'HH-User-Agent': agent}) as client:
        response = client.post('https://api.hh.ru/token', data={
            'grant_type': 'client_credentials', 'client_id': client_id, 'client_secret': client_secret})
        if response.status_code != 200:
            raise SystemExit(f'HH token request returned HTTP {response.status_code}. Check app credentials and the five-minute limit.')
        token = response.json().get('access_token')
        if not isinstance(token, str) or not token or '\n' in token:
            raise SystemExit('HH did not return a valid access_token field.')
        check = client.get('https://api.hh.ru/me', headers={'Authorization': 'Bearer ' + token})
        if check.status_code != 200:
            raise SystemExit(f'HH returned a token, but /me verification failed with HTTP {check.status_code}.')
    before = env_path.read_text()
    if re.search(r'^HH_ACCESS_TOKEN=', before, flags=re.M):
        after = re.sub(r'^HH_ACCESS_TOKEN=.*$', lambda _: 'HH_ACCESS_TOKEN=' + token, before, flags=re.M)
    else:
        after = before.rstrip('\n') + '\nHH_ACCESS_TOKEN=' + token + '\n'
    with tempfile.NamedTemporaryFile(mode='w', dir=root, prefix='.env.hh-', delete=False) as output:
        temporary = Path(output.name)
        os.chmod(temporary, 0o600)
        output.write(after)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, env_path)
    print('HH access token verified and saved to private .env. Restart api and worker to use it.')
except httpx.HTTPError as exc:
    raise SystemExit(f'HH connection failed: {type(exc).__name__}') from None
