"""Shared test setup: a throwaway SQLite database and a fixed kit configuration.

The environment is set before the app is imported, and every value the repo's .env could
supply is set here, so a developer's .env (or running stack) never leaks into the tests.
Kit under test: education, with FEATURES=+examples,+kasm,-hallpass,-social.
"""
import os
import shutil
import sys
import tempfile

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

PASSWORD = '123Qwerty!'
SECRET_GEMINI = 'test-secret-gemini-value-9f3k2'
_TMP = tempfile.mkdtemp(prefix='ocs-flask-tests-')

os.environ.update({
    'SQLALCHEMY_DATABASE_URI': f"sqlite:///{os.path.join(_TMP, 'test.db')}",
    'KIT': 'education',
    'FEATURES': '+examples,+kasm,-hallpass,-social',
    'IS_PRODUCTION': 'false',
    'SECRET_KEY': 'test-secret-key',
    'DEFAULT_PASSWORD': PASSWORD, 'ADMIN_PASSWORD': PASSWORD, 'TEACHER_PASSWORD': PASSWORD,
    'USER_PASSWORD': PASSWORD, 'MY_PASSWORD': PASSWORD,
    'ADMIN_UID': '', 'TEACHER_UID': '', 'USER_UID': '', 'MY_UID': '',
    'ADMIN_USER': '', 'TEACHER_USER': '', 'USER_NAME': '', 'MY_NAME': '', 'MY_ROLE': '',
    'GEMINI_API_KEY': SECRET_GEMINI, 'GROQ_API_KEY': '',
    'KASM_SERVER': '', 'KASM_API_KEY': '', 'KASM_API_KEY_SECRET': '',
    'GITHUB_TOKEN': '', 'ALLOWED_EMAIL_DOMAINS': '', 'RESET_TOKEN_SECRET': '',
})


@pytest.fixture(scope='session')
def app():
    from main import app as flask_app, db
    import features
    flask_app.config['TESTING'] = True
    with flask_app.app_context():
        db.create_all()
        features.run_hooks("seed")
    yield flask_app


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def _no_overrides(request):
    """Every test starts and ends without admin overrides."""
    if 'app' not in request.fixturenames:
        yield
        return
    flask_app = request.getfixturevalue('app')
    from model.feature_override import FeatureOverride
    from __init__ import db

    def clear():
        with flask_app.app_context():
            FeatureOverride.query.delete()
            db.session.commit()
    clear()
    yield
    clear()


def login(app, uid):
    """A test client logged in (Flask-Login session) as uid; None = anonymous."""
    client = app.test_client()
    if uid:
        r = client.post('/login', data={'username': uid, 'password': PASSWORD})
        assert r.status_code == 302, f'login as {uid} failed'
    return client


ADMIN, STAFF, MEMBER = 'admin', 'teacher', 'student'  # education kit seed uids
