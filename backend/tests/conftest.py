import pytest
from sqlalchemy import text
from fastapi.testclient import TestClient
from app.db import engine, Session
from app.main import app, attempts
from app.config import settings


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    assert engine.url.database == 'jobfinder_test', 'Tests must never run against the application database'
    with engine.begin() as connection:
        connection.execute(text('TRUNCATE users, records, jobs, knowledge, sessions, usage, budgets CASCADE'))
    monkeypatch.setattr(settings, 'storage_path', tmp_path)
    monkeypatch.setattr(settings, 'openai_api_key', '')
    monkeypatch.setattr(settings, 'gemini_api_key', '')
    monkeypatch.setattr(settings, 'text_provider', 'openai')
    monkeypatch.setattr(settings, 'admin_email', 'owner@example.com')
    attempts.clear()
    yield


@pytest.fixture
def client():
    with TestClient(app) as value:
        yield value


def register(client, email='person@example.com'):
    response = client.post('/api/v1/auth/register', json={'email': email, 'password': 'correct-horse-42'})
    assert response.status_code == 200, response.text
    result = response.json()
    client.headers['x-csrf-token'] = result['csrf']
    return result['user']


@pytest.fixture
def user(client):
    return register(client)
