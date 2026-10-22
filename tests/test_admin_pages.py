"""Admin pages moved out of main.py into feature blueprints must stay admin-only.

Uses a stub Flask-Login user loader, so no database is needed.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ.pop('KIT', None)  # KIT unset: every feature on, so every admin page is served
os.environ.pop('FEATURES', None)

from flask_login import UserMixin  # noqa: E402

from main import app, login_manager  # noqa: E402

ADMIN_PAGES = [('GET', '/kasm_users'), ('DELETE', '/delete_user/123'), ('GET', '/persona/')]


class _StubUser(UserMixin):
    def __init__(self, uid, role):
        self.id, self.role = uid, role


_USERS = {'1': _StubUser('1', 'Admin'), '2': _StubUser('2', 'User')}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(login_manager, '_user_callback', lambda uid: _USERS.get(uid))
    app.config['TESTING'] = True
    return app.test_client()


def _login(client, uid):
    with client.session_transaction() as sess:
        sess['_user_id'] = uid
        sess['_fresh'] = True


@pytest.mark.parametrize('method,url', ADMIN_PAGES)
def test_anonymous_is_sent_to_login(client, method, url):
    r = client.open(url, method=method)
    assert r.status_code in (302, 401)
    if r.status_code == 302:
        assert '/login' in r.headers['Location']


@pytest.mark.parametrize('method,url', ADMIN_PAGES)
def test_non_admin_is_forbidden(client, method, url):
    _login(client, '2')
    assert client.open(url, method=method).status_code == 403


def test_admin_passes_the_check(client, monkeypatch):
    monkeypatch.setitem(app.config, 'KASM_SERVER', None)
    _login(client, '1')
    # No Kasm server is configured in tests, so the page reports missing keys (400) -- past auth.
    assert client.get('/kasm_users').status_code == 400
