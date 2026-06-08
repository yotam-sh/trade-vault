"""Per-session TOTP gate: blocks unauthenticated access, lets valid codes in."""

import pyotp
import pytest

import server


@pytest.fixture
def auth(monkeypatch):
    from app import auth_store
    monkeypatch.delenv('TOTP_SECRET', raising=False)
    secret = pyotp.random_base32()
    auth_store.set_totp_secret(secret)  # enable the gate via the sidecar store
    monkeypatch.setitem(server.app.config, 'WTF_CSRF_ENABLED', False)
    server._login_failures.clear()
    return server.app.test_client(), secret


def test_unauthenticated_html_redirects_to_login(auth):
    client, _secret = auth
    r = client.get('/transactions')
    assert r.status_code == 302 and '/login' in r.headers['Location']


def test_unauthenticated_api_returns_401(auth):
    client, _secret = auth
    assert client.get('/api/daily-details').status_code == 401


def test_health_and_login_are_exempt(auth):
    client, _secret = auth
    assert client.get('/health').status_code == 200
    assert client.get('/login').status_code == 200


def test_valid_totp_logs_in(auth):
    client, secret = auth
    r = client.post('/login', data={'code': pyotp.TOTP(secret).now()})
    assert r.status_code == 302 and '/login' not in r.headers['Location']
    # Session now valid: GET /login redirects to index instead of showing the form.
    r2 = client.get('/login')
    assert r2.status_code == 302 and r2.headers['Location'].rstrip('/').endswith('')


def test_invalid_code_is_rejected(auth):
    client, _secret = auth
    r = client.post('/login', data={'code': '000000'})
    assert r.status_code == 302 and '/login' in r.headers['Location']
    assert client.get('/transactions').status_code == 302  # still gated


def test_lockout_after_repeated_failures(auth):
    client, _secret = auth
    for _ in range(server._LOGIN_MAX_FAILS):
        client.post('/login', data={'code': '000000'})
    # Next attempt is locked out; even a valid code is refused during cooldown.
    secret = _secret
    r = client.post('/login', data={'code': pyotp.TOTP(secret).now()})
    assert r.status_code == 302 and '/login' in r.headers['Location']
    assert client.get('/transactions').status_code == 302
