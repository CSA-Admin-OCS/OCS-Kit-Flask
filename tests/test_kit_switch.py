"""Applying a whole kit at runtime: PUT and DELETE /api/kit/admin/kit.

Server configuration under test (conftest.py): KIT=education, FEATURES=+examples,+kasm,-hallpass,-social.
Expected values come from kits/catalog.json, so nothing here is specific to one kit's contents.
"""
import json
import os
import subprocess
import sys
import textwrap

import pytest

import features
from conftest import ADMIN, MEMBER, PASSWORD, ROOT, STAFF, login

KITS = ['vanilla', 'education', 'business']
URL = '/api/kit/admin/kit'
CATALOG = features.load_catalog()

# One GET per feature with Flask routes; each answers 200 for an admin while the feature is on.
PROBES = {
    'ai-chatbot': '/api/groq/models',
    'analytics': '/api/user/skill-passport',
    'assignments': '/api/study',
    'examples': '/api/jokes',
    'game-engine': '/api/dynamic/leaderboard',
    'social': '/api/microblog',
}


def _preset(kit):
    return set(CATALOG['kits'][kit]['features'])


def _detail(payload, fid):
    return next(d for d in payload['feature_details'] if d['id'] == fid)


def _switch(admin, kit):
    r = admin.put(URL, json={'kit': kit})
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _override(admin, changes):
    r = admin.put('/api/kit/admin/features', json={'features': changes})
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def _public(app):
    return login(app, None).get('/api/kit').get_json()


def _env(monkeypatch, kit, feature_list):
    """Pretend the server was started with this KIT and FEATURES."""
    monkeypatch.setenv('KIT', kit)
    monkeypatch.setenv('FEATURES', feature_list)
    monkeypatch.setattr(features, '_resolved', None)


def _jwt_client(app, uid):
    client = app.test_client()
    r = client.post('/api/authenticate', json={'uid': uid, 'password': PASSWORD}, headers={'X-Origin': 'client'})
    assert r.status_code == 200
    return client


# --- permissions ------------------------------------------------------------------------------

@pytest.mark.parametrize('method,body', [('PUT', {'kit': 'business'}), ('DELETE', None)])
def test_anonymous_gets_401(app, method, body):
    assert login(app, None).open(URL, method=method, json=body).status_code == 401


@pytest.mark.parametrize('uid', [STAFF, MEMBER])
def test_staff_and_member_get_403_and_change_nothing(app, uid):
    admin = login(app, ADMIN)
    _switch(admin, 'vanilla')
    client = login(app, uid)
    assert client.put(URL, json={'kit': 'business'}).status_code == 403
    assert client.delete(URL).status_code == 403
    assert _public(app)['kit'] == 'vanilla'


def test_admin_allowed_with_session_and_jwt(app):
    assert login(app, ADMIN).put(URL, json={'kit': 'business'}).status_code == 200
    assert _jwt_client(app, ADMIN).put(URL, json={'kit': 'vanilla'}).status_code == 200
    assert _public(app)['kit'] == 'vanilla'
    assert login(app, ADMIN).delete(URL).status_code == 200


@pytest.mark.parametrize('body', [{'kit': 'nope'}, {'kit': 'Education'}, {'kit': 'default'}, {'kit': 'custom'},
                                  {'kit': ''}, {'kit': None}, {'kit': 1}, {'kit': ['vanilla']}, {}, ['vanilla']])
def test_unknown_kit_is_400_and_changes_nothing(app, body):
    admin = login(app, ADMIN)
    _override(admin, {'resume': False})
    assert admin.put(URL, json=body).status_code == 400
    k = _public(app)
    assert k['kit_source'] == 'env' and 'resume' not in k['features']


def test_missing_body_is_400(app):
    assert login(app, ADMIN).put(URL, data='not json').status_code == 400


# --- applying a preset ------------------------------------------------------------------------

@pytest.mark.parametrize('kit', KITS)
def test_preset_is_applied_exactly(app, kit):
    info = _switch(login(app, ADMIN), kit)
    for payload in (info, _public(app)):
        assert set(payload['features']) == _preset(kit)
        assert payload['kit'] == kit and payload['kit_name'] == CATALOG['kits'][kit]['name']
        assert payload['kit_source'] == 'admin' and payload['customized'] is False
        assert {d['id'] for d in payload['feature_details'] if d['enabled']} == _preset(kit)
    assert all(d['source'] == 'kit' and d['override'] is None for d in info['feature_details'])
    assert set(info['base_features']) == _preset(kit)


def test_exact_lists_of_the_catalog():
    assert _preset('vanilla') == {'core'}
    assert _preset('business') == {'core', 'ai-chatbot', 'social', 'calendar', 'analytics', 'resume'}
    assert _preset('education') == {'core', 'lessons', 'code-runner', 'assignments', 'game-engine', 'ai-chatbot',
                                    'ai-grading', 'calendar', 'analytics', 'hallpass', 'social', 'resume'}


@pytest.mark.parametrize('kit', KITS)
def test_endpoints_answer_200_or_404_by_preset(app, kit):
    admin = login(app, ADMIN)
    _switch(admin, kit)
    for fid, url in PROBES.items():
        assert admin.get(url).status_code == (200 if fid in _preset(kit) else 404), f'{kit}: {fid} {url}'
    assert admin.get('/kasm_users').status_code == 404  # in no preset
    assert admin.get('/api/section').status_code == 200  # core is always on


def test_shared_blueprint_stays_on_through_the_feature_in_the_preset(app):
    admin = login(app, ADMIN)
    _switch(admin, 'business')  # ai-chatbot on, ai-grading off
    assert admin.get('/api/gemini/health').status_code == 200
    _switch(admin, 'vanilla')
    assert admin.get('/api/gemini/health').status_code == 404


def test_admin_payload_lists_presets_from_the_catalog(app):
    info = login(app, ADMIN).get('/api/kit/admin').get_json()
    assert info['presets'] == {
        kid: {'name': kit['name'], 'description': kit['description'], 'features': kit['features'],
              'roles': {rid: {'label': r['label']} for rid, r in kit['roles'].items()}}
        for kid, kit in CATALOG['kits'].items()
    }
    assert set(info['presets']) == set(KITS)
    assert 'presets' not in _public(app)


def test_switch_is_audited_and_stored(app):
    from model.feature_override import KitSetting
    admin = login(app, ADMIN)
    _override(admin, {'resume': False})
    changes = _switch(admin, 'business')['recent_changes']
    assert (changes[0]['feature'], changes[0]['action'], changes[0]['by']) == ('kit:business', 'apply-kit', ADMIN)
    assert changes[0]['at']
    assert (changes[1]['feature'], changes[1]['action'], changes[1]['by']) == ('resume', 'clear', ADMIN)
    with app.app_context():
        row = KitSetting.query.one()
        assert row.kit == 'business' and row.updated_by == ADMIN and row.updated_at
    changes = admin.delete(URL).get_json()['recent_changes']
    assert (changes[0]['feature'], changes[0]['action'], changes[0]['by']) == ('kit:business', 'forget-kit', ADMIN)
    with app.app_context():
        assert KitSetting.query.count() == 0


# --- overrides --------------------------------------------------------------------------------

def test_switch_clears_every_override(app):
    from model.feature_override import FeatureOverride
    admin = login(app, ADMIN)
    _override(admin, {'kasm': False, 'hallpass': True, 'resume': False})
    info = _switch(admin, 'vanilla')
    assert set(info['features']) == _preset('vanilla') and info['customized'] is False
    assert all(d['override'] is None for d in info['feature_details'])
    with app.app_context():
        assert FeatureOverride.query.count() == 0


def test_applying_the_active_kit_again_resets_it(app):
    admin = login(app, ADMIN)
    _switch(admin, 'business')
    assert _override(admin, {'resume': False})['customized'] is True
    info = _switch(admin, 'business')
    assert set(info['features']) == _preset('business') and info['customized'] is False


def test_customizing_after_a_switch(app):
    admin, anon = login(app, ADMIN), login(app, None)
    _switch(admin, 'business')
    assert anon.get('/api/jokes').status_code == 404

    info = _override(admin, {'examples': True, 'social': False})
    assert info['kit'] == 'business' and info['kit_source'] == 'admin' and info['customized'] is True
    assert set(info['features']) == (_preset('business') | {'examples'}) - {'social'}
    assert set(info['base_features']) == _preset('business')
    assert _detail(info, 'examples')['source'] == 'admin' and _detail(info, 'examples')['override'] is True
    assert _detail(info, 'social')['source'] == 'admin' and _detail(info, 'social')['override'] is False
    assert _detail(info, 'resume')['source'] == 'kit'
    assert anon.get('/api/jokes').status_code == 200
    assert anon.get('/api/microblog').status_code == 404

    admin.delete('/api/kit/admin/features/examples')
    info = admin.delete('/api/kit/admin/features/social').get_json()
    assert set(info['features']) == _preset('business') and info['customized'] is False
    assert _detail(info, 'examples')['source'] == 'kit' and not _detail(info, 'examples')['enabled']


def test_override_that_agrees_with_the_preset_is_not_customized(app):
    admin = login(app, ADMIN)
    _switch(admin, 'business')
    info = _override(admin, {'social': True})
    assert info['customized'] is False and _detail(info, 'social')['source'] == 'admin'


def test_core_stays_on_under_a_stored_kit(app):
    admin = login(app, ADMIN)
    _switch(admin, 'vanilla')
    assert admin.put('/api/kit/admin/features', json={'features': {'core': False}}).status_code == 400
    assert 'core' in _public(app)['features']


# --- DELETE and precedence --------------------------------------------------------------------

def test_delete_returns_to_env(app):
    admin = login(app, ADMIN)
    env_before = _public(app)
    _switch(admin, 'vanilla')
    _override(admin, {'analytics': True})
    info = admin.delete(URL).get_json()
    assert info['kit'] == 'education' and info['kit_source'] == 'env' and info['customized'] is True
    assert info['features'] == env_before['features'] and info['roles'] == env_before['roles']
    assert all(d['override'] is None for d in info['feature_details'])
    assert _detail(info, 'examples')['source'] == 'env' and _detail(info, 'hallpass')['source'] == 'env'
    assert _detail(info, 'lessons')['source'] == 'kit'


def test_delete_with_nothing_stored_clears_overrides(app):
    admin = login(app, ADMIN)
    _override(admin, {'resume': False})
    info = admin.delete(URL).get_json()
    assert info['kit_source'] == 'env' and 'resume' in info['features']
    assert admin.delete(URL).status_code == 200


def test_stored_kit_ignores_env_kit_and_features(app, monkeypatch):
    admin = login(app, ADMIN)
    _switch(admin, 'business')
    _env(monkeypatch, 'vanilla', '+kasm,-resume')
    info = admin.get('/api/kit/admin').get_json()
    assert info['kit'] == 'business' and set(info['features']) == _preset('business')
    assert info['customized'] is False and info['roles']['staff'] == {'label': 'Manager'}
    assert all(d['source'] == 'kit' for d in info['feature_details'])


def test_stored_kit_ignores_an_explicit_features_list(app, monkeypatch):
    _env(monkeypatch, '', 'calendar')
    assert _public(app)['kit'] == 'custom'
    info = _switch(login(app, ADMIN), 'vanilla')
    assert info['kit'] == 'vanilla' and set(info['features']) == _preset('vanilla')


def test_without_a_stored_kit_env_then_overrides_decide(app, monkeypatch):
    admin = login(app, ADMIN)
    _env(monkeypatch, 'business', '+hallpass,-resume')
    info = admin.get('/api/kit/admin').get_json()
    assert info['kit'] == 'business' and info['kit_source'] == 'env' and info['customized'] is True
    assert set(info['features']) == (_preset('business') | {'hallpass'}) - {'resume'}
    assert _detail(info, 'hallpass')['source'] == 'env' and _detail(info, 'social')['source'] == 'kit'
    info = _override(admin, {'hallpass': False, 'resume': True})
    assert set(info['features']) == _preset('business') and info['customized'] is False
    assert _detail(info, 'hallpass')['source'] == 'admin'


@pytest.mark.parametrize('kit,feature_list,expected_kit,source,customized', [
    ('', '', 'default', 'default', False),
    ('vanilla', '', 'vanilla', 'env', False),
    ('', '+kasm', 'default', 'env', False),  # every feature is already on
    ('', '-kasm', 'default', 'env', True),
    ('', 'calendar', 'custom', 'env', False),
])
def test_kit_source_without_a_stored_kit(app, monkeypatch, kit, feature_list, expected_kit, source, customized):
    _env(monkeypatch, kit, feature_list)
    k = _public(app)
    assert (k['kit'], k['kit_source'], k['customized']) == (expected_kit, source, customized)


def test_override_changes_an_explicit_list(app, monkeypatch):
    admin = login(app, ADMIN)
    _env(monkeypatch, '', 'calendar')
    assert _override(admin, {'resume': True})['customized'] is True


def test_stored_kit_missing_from_the_catalog_is_ignored(app):
    from __init__ import db
    from model.feature_override import KitSetting
    with app.app_context():
        db.session.add(KitSetting(id=1, kit='retired'))
        db.session.commit()
    k = _public(app)
    assert k['kit'] == 'education' and k['kit_source'] == 'env'


# --- roles and sign-ups -----------------------------------------------------------------------

@pytest.mark.parametrize('kit', KITS)
def test_role_labels_follow_the_kit_immediately(app, kit):
    info = _switch(login(app, ADMIN), kit)
    roles_in_catalog = CATALOG['kits'][kit]['roles']
    expected = {rid: {'label': r['label']} for rid, r in roles_in_catalog.items()}
    assert info['roles'] == expected and _public(app)['roles'] == expected
    assert info['signup_role'] == CATALOG['kits'][kit]['signup_role']

    # accounts seeded under another kit keep their uid and stored role, with this kit's label
    for uid, stored, rid in ((ADMIN, 'Admin', 'admin'), (STAFF, 'Teacher', 'staff'), (MEMBER, 'User', 'member')):
        me = login(app, uid).get('/api/id').get_json()
        assert (me['uid'], me['role'], me['role_label']) == (uid, stored, roles_in_catalog[rid]['label'])


@pytest.mark.parametrize('kit', KITS)
def test_pages_show_this_kits_labels_and_staff_stays_staff(app, kit):
    _switch(login(app, ADMIN), kit)
    labels = CATALOG['kits'][kit]['roles']
    staff = login(app, STAFF)
    r = staff.get('/users/table2')  # a staff-only page
    assert r.status_code == 200
    page = r.get_data(as_text=True)
    assert f"<strong>ROLE:</strong> {labels['staff']['label']}" in page
    assert f"<td>{labels['staff']['label']}</td>" in page  # staff see only their own row
    assert f"<td>{labels['member']['label']}</td>" in login(app, ADMIN).get('/users/table2').get_data(as_text=True)
    assert login(app, MEMBER).get('/users/table2').status_code == 403
    assert staff.get('/api/kit/admin').status_code == 403
    assert login(app, ADMIN).get('/api/kit/admin').status_code == 200


@pytest.mark.parametrize('kit', KITS)
def test_new_signup_gets_the_active_kits_role(app, kit):
    _switch(login(app, ADMIN), kit)
    r = login(app, None).post('/api/user', json={'name': 'New Person', 'uid': f'signup-{kit}', 'password': PASSWORD})
    assert r.status_code == 200, r.get_data(as_text=True)
    member = CATALOG['kits'][kit]['roles'][CATALOG['kits'][kit]['signup_role']]
    assert r.get_json()['role'] == 'User' and r.get_json()['role_label'] == member['label']


def test_signup_role_is_read_from_the_active_kit(app, monkeypatch):
    monkeypatch.setitem(CATALOG['kits']['business'], 'signup_role', 'staff')
    info = _switch(login(app, ADMIN), 'business')
    assert info['signup_role'] == 'staff'
    r = login(app, None).post('/api/user', json={'name': 'New Person', 'uid': 'signup-staff', 'password': PASSWORD})
    assert r.get_json()['role'] == 'Teacher' and r.get_json()['role_label'] == 'Manager'
    assert _switch(login(app, ADMIN), 'vanilla')['signup_role'] == 'member'


# --- seeding ----------------------------------------------------------------------------------

def _empty_social_tables(app):
    from __init__ import db
    from model.microblog import MicroBlog, Topic
    from model.persona import Persona, UserPersona
    from model.post import Post
    with app.app_context():
        for model in (UserPersona, Persona, MicroBlog, Topic, Post):
            model.query.delete()
        db.session.commit()


def _persona_count(app):
    from model.persona import Persona
    with app.app_context():
        return Persona.query.count()


def test_switch_seeds_a_newly_enabled_feature_with_empty_tables_once(app):
    admin = login(app, ADMIN)
    _empty_social_tables(app)
    _switch(admin, 'vanilla')
    assert _persona_count(app) == 0  # social is off: nothing is seeded
    _switch(admin, 'business')
    seeded = _persona_count(app)
    assert seeded > 0
    _switch(admin, 'vanilla')
    _switch(admin, 'education')
    assert _persona_count(app) == seeded


def test_switch_does_not_seed_when_the_tables_have_data(app):
    from __init__ import db
    from model.persona import Persona
    admin = login(app, ADMIN)
    _empty_social_tables(app)
    _switch(admin, 'vanilla')
    with app.app_context():
        db.session.add(Persona(_alias='mine', _category='student', _bio_map={'title': 'Mine'}, _empathy_map={}))
        db.session.commit()
    _switch(admin, 'business')
    assert _persona_count(app) == 1


def test_a_feature_that_stays_on_is_not_seeded_again(app):
    admin = login(app, ADMIN)
    _switch(admin, 'education')  # social on
    _empty_social_tables(app)
    _switch(admin, 'business')   # social still on: not newly enabled
    assert _persona_count(app) == 0


def test_delete_seeds_what_the_environment_newly_enables(app, monkeypatch):
    admin = login(app, ADMIN)
    _empty_social_tables(app)
    _switch(admin, 'vanilla')
    _env(monkeypatch, 'business', '')
    admin.delete(URL)
    assert _persona_count(app) > 0


def test_seeding_does_not_change_existing_accounts(app):
    from model.user import User
    admin = login(app, ADMIN)
    _empty_social_tables(app)
    _switch(admin, 'vanilla')
    with app.app_context():
        before = {u.uid: (u.id, u.role, u._password) for u in User.query.all()}
    _switch(admin, 'business')
    with app.app_context():
        after = {u.uid: (u.id, u.role, u._password) for u in User.query.all()}
    assert {uid: after.get(uid) for uid in before} == before


def _users(app):
    from model.user import User
    with app.app_context():
        return {u.uid: (u.id, u.role, u._password) for u in User.query.all()}


def test_no_runtime_path_creates_or_changes_accounts(app):
    admin = login(app, ADMIN)
    _empty_social_tables(app)  # so that every seed function really runs below
    _switch(admin, 'vanilla')
    before = _users(app)

    for fid in features.feature_ids():  # per-feature toggle, one at a time
        _override(admin, {fid: True})
    admin.delete('/api/kit/admin/features/social')
    _override(admin, {'social': False})
    _empty_social_tables(app)
    _override(admin, {'social': True})
    assert _persona_count(app) > 0  # the seed did run
    assert _users(app) == before

    _empty_social_tables(app)
    _switch(admin, 'vanilla')
    _switch(admin, 'education')
    assert _persona_count(app) > 0
    _empty_social_tables(app)
    _switch(admin, 'vanilla')
    _switch(admin, 'business')
    assert admin.delete(URL).status_code == 200
    assert _users(app) == before


def test_only_seed_accounts_hooks_create_accounts():
    hooks = {ref for fid in features.feature_ids() for ref in features.flask_spec(fid)['seed']}
    assert 'model.persona:initPersonas' in hooks
    assert not hooks & {'model.user:initUsers', 'model.persona:initPersonaUsers'}


def test_seed_data_creates_accounts_only_when_asked_and_only_on_an_empty_database(app):
    from main import seed_data
    before = _users(app)
    with app.app_context():
        seed_data()
        seed_data(accounts=True)  # there are users already
    assert _users(app) == before


def test_failing_seed_does_not_hide_a_committed_switch(app, monkeypatch):
    from model import feature_override
    admin = login(app, ADMIN)
    _switch(admin, 'vanilla')

    def boom(fid):
        raise RuntimeError('seed exploded')
    monkeypatch.setattr(feature_override, '_feature_tables_empty', boom)
    info = _switch(admin, 'business')  # still answers 200
    assert info['kit'] == 'business' and set(info['features']) == _preset('business')


# --- nothing is lost across switches ----------------------------------------------------------

def _posts(client):
    r = client.get('/api/microblog')
    return r.status_code, r.get_data(as_text=True)


def test_round_trip_preserves_data_accounts_and_sessions(app):
    from model.microblog import MicroBlog
    from model.study import Study
    from model.user import User
    admin, member, member_jwt = login(app, ADMIN), login(app, MEMBER), _jwt_client(app, MEMBER)
    post = 'round trip post a81f'
    study = {'topic': 'round-trip', 'subtopic': 'a81f', 'studied': True, 'timestamp': '2026-01-01T00:00:00'}

    def counts():
        with app.app_context():
            return MicroBlog.query.filter_by(_content=post).count(), Study.query.filter_by(topic='round-trip').count()

    def accounts():
        with app.app_context():
            return {u.uid: (u.id, u.role) for u in User.query.all()}

    # vanilla, plus social as an override
    assert set(_switch(admin, 'vanilla')['features']) == {'core'}
    assert _posts(member)[0] == 404
    _override(admin, {'social': True})
    seen = accounts()
    assert member.post('/api/microblog', json={'content': post}).status_code == 200
    assert post in _posts(member)[1]

    # education: social is in the preset, assignments comes on
    info = _switch(admin, 'education')
    assert all(d['override'] is None for d in info['feature_details'])
    assert post in _posts(member)[1]
    assert member.post('/api/study', json=study).status_code == 201
    assert 'round-trip' in member.get('/api/study').get_data(as_text=True)

    # business: social stays, assignments is gated
    _switch(admin, 'business')
    assert post in _posts(member)[1]
    assert member.get('/api/study').status_code == 404

    # vanilla: both gated, nothing removed
    _switch(admin, 'vanilla')
    assert _posts(member)[0] == 404 and member.get('/api/study').status_code == 404
    assert counts() == (1, 1)

    # education again: everything is back
    _switch(admin, 'education')
    assert post in _posts(member)[1]
    assert 'round-trip' in member.get('/api/study').get_data(as_text=True)
    assert counts() == (1, 1)

    # same accounts and the same logins throughout
    assert accounts() == seen
    for client in (member, member_jwt):
        r = client.get('/api/id')
        assert r.status_code == 200 and r.get_json()['uid'] == MEMBER
    assert admin.get('/api/kit/admin').status_code == 200


def test_switch_applies_on_the_next_request_of_existing_clients(app):
    admin, anon = login(app, ADMIN), login(app, None)
    resolved = features._state()
    _switch(admin, 'vanilla')
    assert anon.get('/api/kit').get_json()['kit'] == 'vanilla'
    assert anon.get('/api/jokes').status_code == 404
    _override(admin, {'examples': True})
    assert anon.get('/api/jokes').status_code == 200
    admin.delete(URL)
    assert anon.get('/api/kit').get_json()['kit'] == 'education'
    assert features._state() is resolved  # the environment was never re-read


def test_navbar_links_follow_the_kit(app):
    admin = login(app, ADMIN)
    _switch(admin, 'business')
    assert 'Personas' in admin.get('/users/table2').get_data(as_text=True)
    _switch(admin, 'vanilla')
    assert 'Personas' not in admin.get('/users/table2').get_data(as_text=True)


# --- separate processes: what a real restart and a second worker see --------------------------

def _run(tmp_path, kit, script):
    env = dict(os.environ, SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'restart.db'}", KIT=kit, FEATURES='')
    header = textwrap.dedent(f"""\
        import json, sys
        sys.path.insert(0, {ROOT!r})
        from main import app, db, seed_data
        def admin():
            c = app.test_client()
            assert c.post('/login', data={{'username': 'admin', 'password': {PASSWORD!r}}}).status_code == 302
            return c
    """)
    done = subprocess.run([sys.executable, '-c', header + textwrap.dedent(script)], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stdout + done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_kit_survives_a_restart_and_upgrades_an_older_database(app, tmp_path):
    # An existing vanilla site from before this table existed
    _run(tmp_path, 'vanilla', """
        from model.feature_override import KitSetting
        with app.app_context():
            db.create_all()
            seed_data(accounts=True)
            KitSetting.__table__.drop(db.engine)
        print('{}')
    """)
    # Next boot: the table is created, and an admin applies a kit
    applied = _run(tmp_path, 'vanilla', """
        print(json.dumps(admin().put('/api/kit/admin/kit', json={'kit': 'business'}).get_json()['kit_source']))
    """)
    assert applied == 'admin'
    # A later boot, with a different KIT in the environment: the stored kit still wins, and
    # the account seeded as 'editor' under vanilla is staff, labelled for business
    state = _run(tmp_path, 'education', """
        c = app.test_client()
        assert c.post('/login', data={'username': 'editor', 'password': '%s'}).status_code == 302
        print(json.dumps({'kit': c.get('/api/kit').get_json(), 'me': c.get('/api/id').get_json(),
                          'staff_page': c.get('/users/table2').status_code}))
    """ % PASSWORD)
    assert state['kit']['kit'] == 'business' and state['kit']['kit_source'] == 'admin'
    assert set(state['kit']['features']) == _preset('business')
    assert (state['me']['role'], state['me']['role_label']) == ('Teacher', 'Manager')
    assert state['staff_page'] == 200
    # DELETE hands the site back to the environment of that boot
    back = _run(tmp_path, 'education', """
        info = admin().delete('/api/kit/admin/kit').get_json()
        print(json.dumps({'kit': info['kit'], 'source': info['kit_source'], 'features': info['features']}))
    """)
    assert back['kit'] == 'education' and back['source'] == 'env' and set(back['features']) == _preset('education')
