"""Upgrade only the isolated restore database; never run against jobfinder."""
from sqlalchemy.engine import make_url
from .config import settings

url = make_url(settings.database_url)
if url.database != 'jobfinder':
    raise SystemExit('Restore migration expects the compose source database URL')
settings.database_url = url.set(database='jobfinder_test').render_as_string(hide_password=False)

from alembic import command
from alembic.config import Config

command.upgrade(Config('alembic.ini'), 'head')
