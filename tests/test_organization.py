"""'School' became 'organization': new names in the API and code, old names still accepted, and the stored
column names unchanged so an existing database keeps working with no migration."""
import os
import subprocess
import sys

import pytest
from sqlalchemy import inspect

from conftest import PASSWORD, ROOT, STAFF, login


def _make_user(app, uid, organization=None):
    from model.user import User
    with app.app_context():
        kwargs = {'organization': organization} if organization else {}
        User(name=uid, uid=uid, password=PASSWORD, **kwargs).create()
    return uid


def _organization_of(app, uid):
    from model.user import User
    with app.app_context():
        return User.query.filter_by(_uid=uid).first().organization


def test_a_user_reads_back_as_organization_not_school(app):
    uid = _make_user(app, 'org-read', 'Acme')
    body = login(app, uid).get('/api/id').get_json()
    assert body['organization'] == 'Acme' and 'school' not in body


def test_stored_columns_keep_their_old_names_so_no_migration_is_needed(app):
    from __init__ import db
    with app.app_context():
        columns = lambda table: {c['name'] for c in inspect(db.engine).get_columns(table)}
        assert '_school' in columns('users') and '_organization' not in columns('users')
        assert '_school_name' in columns('classrooms') and '_organization_name' not in columns('classrooms')


@pytest.mark.parametrize('field', ['organization', 'school'])
def test_updating_your_profile_accepts_the_new_and_the_old_field(app, field):
    uid = _make_user(app, f'org-put-{field}')
    r = login(app, uid).put('/api/user', json={field: 'Initech'})
    assert r.status_code == 200
    assert _organization_of(app, uid) == 'Initech'


def test_the_new_field_wins_when_both_are_sent(app):
    uid = _make_user(app, 'org-both')
    login(app, uid).put('/api/user', json={'organization': 'New Name', 'school': 'Old Name'})
    assert _organization_of(app, uid) == 'New Name'


@pytest.mark.parametrize('url', ['/api/organization', '/api/school'])
@pytest.mark.parametrize('field', ['organization', 'school'])
def test_organization_endpoint_and_its_old_address_take_either_field(app, url, field):
    uid = _make_user(app, f'org-ep-{url[5:]}-{field}')
    client = login(app, uid)
    r = client.post(url, json={field: 'Globex'})
    assert r.status_code == 200 and r.get_json()['organization'] == 'Globex'
    assert client.get(url).get_json() == {'uid': uid, 'organization': 'Globex'}


def test_organization_endpoint_refuses_an_empty_value(app):
    uid = _make_user(app, 'org-empty')
    r = login(app, uid).post('/api/organization', json={})
    assert r.status_code == 400 and 'Organization data is missing' in r.get_json()['message']


def test_signup_accepts_the_old_school_field(app):
    r = app.test_client().post('/api/user', json={'name': 'New Person', 'uid': 'org-signup', 'password': PASSWORD,
                                                  'email': 'p@example.org', 'school': 'Hooli'})
    assert r.status_code == 200
    assert _organization_of(app, 'org-signup') == 'Hooli'


def test_classroom_carries_the_organization_of_its_teacher(app):
    from model.user import User
    with app.app_context():
        teacher_organization = User.query.filter_by(_uid=STAFF).first().organization
    r = login(app, STAFF).post('/api/classrooms/', json={'name': 'Period 1'})
    assert r.status_code == 201
    body = r.get_json()
    assert body['organization_name'] == teacher_organization and 'school_name' not in body


def test_old_and_new_classroom_field_names_are_both_read():
    from model.classroom import pick_organization_name
    assert pick_organization_name({'organization_name': 'A', 'school_name': 'B'}) == 'A'
    assert pick_organization_name({'school_name': 'B'}) == 'B'
    assert pick_organization_name({'schoolName': 'C'}) == 'C'
    assert pick_organization_name({}) is None


def test_the_navbar_logo_comes_from_org_logo_url(app, monkeypatch):
    monkeypatch.setitem(app.config, 'ORG_LOGO_URL', '/static/assets/my-org.svg')
    assert 'src="/static/assets/my-org.svg"' in login(app, None).get('/login').get_data(as_text=True)


@pytest.mark.parametrize('env,expected', [
    ({'ORG_NAME': 'New', 'SCHOOL_NAME': 'Old', 'ORG_LOGO_URL': '/new.svg', 'SCHOOL_LOGO_URL': '/old.svg'}, ('New', '/new.svg')),
    ({'ORG_NAME': '', 'SCHOOL_NAME': 'Old', 'ORG_LOGO_URL': '', 'SCHOOL_LOGO_URL': '/old.svg'}, ('Old', '/old.svg')),
    ({'ORG_NAME': '', 'SCHOOL_NAME': '', 'ORG_LOGO_URL': '', 'SCHOOL_LOGO_URL': ''}, ('OCS Kit', '/static/assets/ocs_backend_mark.png')),
], ids=['new-names-win', 'old-names-still-work', 'defaults'])
def test_settings_accept_the_old_env_names(env, expected):
    code = "from __init__ import app; print(app.config['ORG_NAME'], app.config['ORG_LOGO_URL'], sep='|')"
    out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env={**os.environ, **env},
                         capture_output=True, text=True).stdout.strip().splitlines()[-1]
    assert tuple(out.split('|')) == expected
