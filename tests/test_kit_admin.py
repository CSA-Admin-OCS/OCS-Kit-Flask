"""Feature management API, override precedence, dynamic gating, seeding on enable, roles.

Kit under test (conftest.py): KIT=education, FEATURES=+examples,+kasm,-hallpass,-social.
"""
import json

import pytest

import features
import roles
from conftest import ADMIN, MEMBER, PASSWORD, SECRET_GEMINI, STAFF, login

ENDPOINTS = [('GET', '/api/kit/admin', None),
             ('PUT', '/api/kit/admin/features', {'features': {'examples': False}}),
             ('DELETE', '/api/kit/admin/features/examples', None)]


def _put(client, changes):
    return client.put('/api/kit/admin/features', json={'features': changes})


def _detail(payload, fid):
    return next(d for d in payload['feature_details'] if d['id'] == fid)


# --- permissions ------------------------------------------------------------------------------

@pytest.mark.parametrize('method,url,body', ENDPOINTS)
def test_anonymous_gets_401(app, method, url, body):
    assert login(app, None).open(url, method=method, json=body).status_code == 401


@pytest.mark.parametrize('uid', [STAFF, MEMBER])
@pytest.mark.parametrize('method,url,body', ENDPOINTS)
def test_staff_and_member_get_403(app, uid, method, url, body):
    assert login(app, uid).open(url, method=method, json=body).status_code == 403
    assert 'examples' in login(app, None).get('/api/kit').get_json()['features']  # nothing changed


@pytest.mark.parametrize('method,url,body', ENDPOINTS)
def test_admin_allowed(app, method, url, body):
    assert login(app, ADMIN).open(url, method=method, json=body).status_code == 200


def test_admin_with_jwt_cookie(app):
    client = app.test_client()
    r = client.post('/api/authenticate', json={'uid': ADMIN, 'password': PASSWORD},
                    headers={'X-Origin': 'client'})
    assert r.status_code == 200
    assert client.get('/api/kit/admin').status_code == 200


# --- public payload ---------------------------------------------------------------------------

def test_public_kit_payload(app):
    k = login(app, None).get('/api/kit').get_json()
    assert k['kit'] == 'education' and k['kit_name'] == 'OCS Education'
    assert k['roles'] == {'admin': {'label': 'Admin'}, 'staff': {'label': 'Teacher'},
                          'member': {'label': 'Student'}}
    assert k['signup_role'] == 'member'
    assert [d['id'] for d in k['feature_details']] == features.feature_ids()
    assert {d['id'] for d in k['feature_details'] if d['enabled']} == set(k['features'])
    assert 'examples' in k['features'] and 'hallpass' not in k['features']
    assert 'setup' not in json.dumps(k) and 'source' not in k['feature_details'][0]


# --- precedence: kit -> env -> admin ----------------------------------------------------------

def test_sources_and_override_precedence(app):
    admin = login(app, ADMIN)
    info = admin.get('/api/kit/admin').get_json()
    assert _detail(info, 'ai-chatbot')['source'] == 'kit'
    assert _detail(info, 'examples')['source'] == 'env'
    assert _detail(info, 'hallpass')['source'] == 'env' and not _detail(info, 'hallpass')['enabled']

    info = _put(admin, {'examples': False, 'hallpass': True}).get_json()
    assert _detail(info, 'examples')['source'] == 'admin' and not _detail(info, 'examples')['enabled']
    assert _detail(info, 'hallpass')['source'] == 'admin' and _detail(info, 'hallpass')['enabled']
    assert 'examples' in info['base_features']  # the operator's KIT/FEATURES are unchanged

    info = admin.delete('/api/kit/admin/features/examples').get_json()
    assert _detail(info, 'examples')['source'] == 'env' and _detail(info, 'examples')['enabled']


def test_apply_overrides_is_pure_and_keeps_core():
    assert features.apply_overrides(['core', 'ai-chatbot'], {'ai-chatbot': False, 'resume': True}) \
        == ['core', 'resume']
    assert 'core' in features.apply_overrides([], {'core': False})


@pytest.mark.parametrize('body', [{'features': {'nope': True}}, {'features': {'core': False}},
                                  {'features': {'examples': 'yes'}}, {'features': {}}, {}])
def test_bad_requests_are_rejected(app, body):
    admin = login(app, ADMIN)
    assert admin.put('/api/kit/admin/features', json=body).status_code == 400
    assert admin.delete('/api/kit/admin/features/nope').status_code == 400


# --- dynamic gating without restart -----------------------------------------------------------

def test_disable_answers_404_without_restart(app):
    admin, anon = login(app, ADMIN), login(app, None)
    assert anon.get('/api/jokes/').status_code == 200
    _put(admin, {'examples': False})
    assert anon.get('/api/jokes/').status_code == 404
    assert 'examples' not in anon.get('/api/kit').get_json()['features']
    admin.delete('/api/kit/admin/features/examples')
    assert anon.get('/api/jokes/').status_code == 200


def test_shared_blueprint_follows_either_feature(app):
    admin, anon = login(app, ADMIN), login(app, None)
    _put(admin, {'ai-chatbot': False})
    assert anon.get('/api/groq/health').status_code == 404
    assert anon.get('/api/gemini/health').status_code != 404  # still needed by ai-grading
    _put(admin, {'ai-grading': False})
    assert anon.get('/api/gemini/health').status_code == 404


def test_admin_navbar_follows_overrides(app):
    admin = login(app, ADMIN)
    assert 'Kasm User Report' in admin.get('/users/table2').get_data(as_text=True)
    _put(admin, {'kasm': False})
    assert 'Kasm User Report' not in admin.get('/users/table2').get_data(as_text=True)


def test_changes_are_audited(app):
    admin = login(app, ADMIN)
    _put(admin, {'resume': False})
    info = admin.delete('/api/kit/admin/features/resume').get_json()
    assert info['recent_changes'][0]['feature'] == 'resume' and info['recent_changes'][0]['action'] == 'clear'
    assert info['recent_changes'][1]['action'] == 'disable'
    assert all(c['by'] == ADMIN and c['at'] for c in info['recent_changes'][:2])


# --- seeding on enable ------------------------------------------------------------------------

def test_enabling_a_feature_seeds_empty_tables_once(app):
    from model.persona import Persona
    admin = login(app, ADMIN)
    with app.app_context():
        assert Persona.query.count() == 0  # social is off (FEATURES=-social), so never seeded
    assert login(app, None).get('/api/microblog').status_code == 404
    _put(admin, {'social': True})
    with app.app_context():
        seeded = Persona.query.count()
    assert seeded > 0
    _put(admin, {'social': False})
    _put(admin, {'social': True})
    with app.app_context():
        assert Persona.query.count() == seeded  # tables not empty: no second seeding


# --- setup guide never leaks secrets ----------------------------------------------------------

def test_admin_payload_reports_configured_but_never_values(app):
    raw = login(app, ADMIN).get('/api/kit/admin').get_data(as_text=True)
    assert SECRET_GEMINI not in raw
    info = json.loads(raw)
    ai = _detail(info, 'ai-chatbot')
    settings = {s['key']: s for s in ai['setup']['settings']}
    assert settings['GEMINI_API_KEY']['configured'] is True
    assert settings['GROQ_API_KEY']['configured'] is False
    assert ai['ready'] is True
    assert all(s['service'] == 'flask' for d in info['feature_details'] for s in d['setup']['settings'])
    assert all(set(s) == {'key', 'service', 'required', 'secret', 'help', 'get_it', 'example', 'configured'}
               for d in info['feature_details'] for s in d['setup']['settings'])
    assert all('summary' in d['setup'] and 'steps' in d['setup'] and 'verify' in d['setup']
               for d in info['feature_details'])


# --- roles per kit ----------------------------------------------------------------------------

@pytest.mark.parametrize('kit,staff,member,staff_uid,member_uid', [
    ('vanilla', 'Editor', 'User', 'editor', 'user'),
    ('education', 'Teacher', 'Student', 'teacher', 'student'),
    ('business', 'Manager', 'Member', 'manager', 'member'),
    ('', 'Teacher', 'User', 'teacher', 'user'),
])
def test_role_labels_and_seed_uids_per_kit(monkeypatch, kit, staff, member, staff_uid, member_uid):
    monkeypatch.setenv('KIT', kit)
    assert roles.labels() == {'Admin': 'Admin', 'Teacher': staff, 'User': member}
    assert (roles.seed_uid('admin'), roles.seed_uid('staff'), roles.seed_uid('member')) == ('admin', staff_uid, member_uid)
    assert roles.signup_role() == 'User'


def test_seed_accounts_follow_the_kit(app):
    from model.user import User
    with app.app_context():
        found = {u.uid: u.role for u in User.query.filter(User._uid.in_(['admin', 'teacher', 'student'])).all()}
    assert found == {'admin': 'Admin', 'teacher': 'Teacher', 'student': 'User'}


def test_signup_gets_signup_role_and_password_rule(app):
    anon = login(app, None)
    weak = anon.post('/api/user', json={'name': 'New Person', 'uid': 'newweak', 'password': 'password'})
    assert weak.status_code == 400
    r = anon.post('/api/user', json={'name': 'New Person', 'uid': 'newperson', 'password': PASSWORD})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['role'] == 'User' and r.get_json()['role_label'] == 'Student'
