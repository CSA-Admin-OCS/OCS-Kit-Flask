"""Roles and tiers: every role has a tier from L1 (strongest) to L4 (weakest) that says how far up the permission
levels it reaches. Admins add roles and choose tiers on the Roles page, and everything that decides by role (the
check before each request, the decorators, is_admin() and is_staff()) follows the tier."""
import pytest

import roles
from conftest import ADMIN, MEMBER, PASSWORD, STAFF, login

PAGE, API = '/roles/', '/api/roles'
STAFF_NAME, MEMBER_NAME, ADMIN_NAME = roles.staff_role(), roles.member_role(), roles.admin_role()   # Teacher, User, Admin


@pytest.fixture
def people(app):
    """make(uid, role): a signed-in-able account with that role. The accounts are removed afterwards."""
    from __init__ import db
    from model.user import User
    made = []

    def make(uid, role=None):
        with app.app_context():
            User(name=uid, uid=uid, password=PASSWORD, role=role or MEMBER_NAME).create()
        made.append(uid)
        return uid
    yield make
    with app.app_context():
        for uid in made:
            user = User.query.filter_by(_uid=uid).first()
            if user:
                db.session.delete(user)
        db.session.commit()


def _add(admin, name, tier, label=None):
    return admin.post(API, json={'name': name, 'tier': tier, **({'label': label} if label else {})})


def _role(payload, name):
    return next(r for r in payload['roles'] if r['name'] == name)


# --- the model -----------------------------------------------------------------------------------------------------

def test_built_in_roles_start_at_l1_l2_l3_and_an_unknown_role_counts_as_a_member(app):
    with app.app_context():
        assert [roles.tier_of(n) for n in (ADMIN_NAME, STAFF_NAME, MEMBER_NAME)] == [1, 2, 3]
        assert roles.tier_of('Nobody Knows') == 3
        assert [roles.rank(n) for n in (ADMIN_NAME, STAFF_NAME, MEMBER_NAME)] == [3, 2, 1]
        assert roles.TIER_COUNT == roles.LOWEST_TIER == 4


def test_a_decorators_role_names_mean_their_level_or_stronger(app):
    with app.app_context():
        staff_or_stronger = (STAFF_NAME, ADMIN_NAME)
        assert roles.meets(ADMIN_NAME, staff_or_stronger) and roles.meets(STAFF_NAME, staff_or_stronger)
        assert not roles.meets(MEMBER_NAME, staff_or_stronger)
        assert roles.meets(ADMIN_NAME, (ADMIN_NAME,)) and not roles.meets(STAFF_NAME, (ADMIN_NAME,))
        assert not roles.meets(ADMIN_NAME, ())


def test_when_the_saved_roles_cannot_be_read_only_admin_keeps_its_power(app, monkeypatch):
    def broken():
        raise RuntimeError('database is down')
    monkeypatch.setattr(roles, '_saved', broken)
    with app.app_context():
        assert roles.tier_of(ADMIN_NAME) == 1
        assert roles.tier_of(STAFF_NAME) == roles.tier_of(MEMBER_NAME) == 4      # fails closed
        assert roles.label(STAFF_NAME) == 'Teacher'                              # a label just falls back to the kit's
    assert login(app, STAFF).post('/api/classrooms/', json={}).status_code == 403
    assert login(app, ADMIN).get('/api/export/counts').status_code not in (401, 403)


# --- the page and the API ---------------------------------------------------------------------------------------------

def test_only_admins_open_the_page_and_use_the_api(app):
    assert login(app, None).get(PAGE).status_code == 302
    assert login(app, None).get(API).status_code == 401
    for uid in (MEMBER, STAFF):
        client = login(app, uid)
        assert client.get(PAGE).status_code == 403 and client.get(API).status_code == 403
        assert _add(client, 'Sneaky', 1).status_code == 403
        assert client.put(f'{API}/{STAFF_NAME}', json={'tier': 1}).status_code == 403
        assert client.delete(f'{API}/{STAFF_NAME}').status_code == 403
        assert client.put('/api/user/role', json={'uid': MEMBER, 'role': ADMIN_NAME}).status_code == 403
    assert login(app, ADMIN).get(PAGE).status_code == 200


def test_the_payload_lists_the_roles_and_the_four_tiers(app):
    body = login(app, ADMIN).get(API).get_json()
    assert [(r['name'], r['tier'], r['locked'], r['custom']) for r in body['roles']] == [
        (ADMIN_NAME, 1, True, False), (STAFF_NAME, 2, False, False), (MEMBER_NAME, 3, False, False)]
    assert [t['tier'] for t in body['tiers']] == [1, 2, 3, 4]
    assert [t['level'] for t in body['tiers']] == ['admin', 'staff', 'member', 'public']
    counts = [t['may_make'] for t in body['tiers']]
    assert counts == sorted(counts, reverse=True) and counts[0] == body['tiers'][0]['of'] and counts[-1] > 0
    assert body['signup_role'] == MEMBER_NAME


def test_a_role_is_added_with_a_tier_and_listed(app):
    body = _add(login(app, ADMIN), 'Mentor', 3, 'Mentor (volunteer)').get_json()
    mentor = _role(body, 'Mentor')
    assert (mentor['tier'], mentor['label'], mentor['custom'], mentor['accounts']) == (3, 'Mentor (volunteer)', True, 0)
    assert body['recent_changes'][0]['action'] == 'create' and 'Mentor at L3' in body['recent_changes'][0]['detail']
    kit = login(app, None).get('/api/kit').get_json()
    assert kit['custom_roles'] == [{'name': 'Mentor', 'label': 'Mentor (volunteer)', 'tier': 3}]
    assert kit['role_tiers'] == {'admin': 1, 'staff': 2, 'member': 3}


@pytest.mark.parametrize('body,message', [
    ({'name': 'M', 'tier': 3}, '2 to 20 characters'),
    ({'name': 'x' * 21, 'tier': 3}, '2 to 20 characters'),
    ({'name': '1Mentor', 'tier': 3}, '2 to 20 characters'),
    ({'name': 'Men<script>', 'tier': 3}, '2 to 20 characters'),
    ({'name': 5, 'tier': 3}, '2 to 20 characters'),
    ({'name': 'admin', 'tier': 3}, 'already exists'),
    ({'name': 'TEACHER', 'tier': 3}, 'already exists'),
    ({'name': 'Mentor', 'tier': 0}, 'tier must be'),
    ({'name': 'Mentor', 'tier': 5}, 'tier must be'),
    ({'name': 'Mentor', 'tier': '3'}, 'tier must be'),
    ({'name': 'Mentor', 'tier': True}, 'tier must be'),
    ({'name': 'Mentor'}, 'tier must be'),
    ({'name': 'Mentor', 'tier': 3, 'label': 'x' * 41}, 'label must be'),
])
def test_a_bad_role_is_refused_and_nothing_is_saved(app, body, message):
    admin = login(app, ADMIN)
    r = admin.post(API, json=body)
    assert r.status_code == 400 and message in r.get_json()['message']
    assert [x['name'] for x in admin.get(API).get_json()['roles']] == [ADMIN_NAME, STAFF_NAME, MEMBER_NAME]


def test_a_role_name_cannot_be_used_twice_whatever_its_case(app):
    admin = login(app, ADMIN)
    assert _add(admin, 'Mentor', 3).status_code == 201
    assert _add(admin, 'mentor', 2).status_code == 400


# --- a tier really is the role's default permissions ------------------------------------------------------------------

def test_a_role_added_at_l2_has_staff_powers_everywhere(app, people):
    """In the permission check, in a decorator, in a page decorator and in an in-route is_staff() check."""
    _add(login(app, ADMIN), 'Coach', 2)
    uid = people('coach-l2', 'Coach')
    coach = login(app, uid)
    assert coach.get('/users/table2').status_code == 200                                    # staff page (decorator)
    assert coach.post('/api/classrooms/', json={}).status_code == 400                       # past is_staff(): the name is missing
    assert coach.get('/api/id').status_code == 200                                          # member level
    assert coach.get('/api/export/counts').status_code == 403                               # admin level: still no


def test_a_role_added_at_l3_has_member_powers_only(app, people):
    _add(login(app, ADMIN), 'Helper', 3)
    helper = login(app, people('helper-l3', 'Helper'))
    assert helper.get('/api/id').status_code == 200
    assert helper.get('/users/table2').status_code == 403
    assert helper.post('/api/classrooms/', json={}).status_code == 403


def test_a_role_added_at_l4_reaches_only_what_the_public_may(app, people):
    _add(login(app, ADMIN), 'Observer', 4)
    observer = login(app, people('observer-l4', 'Observer'))
    assert observer.get('/api/id').status_code == 403                    # member level
    assert observer.get('/api/jokes').status_code == 200                 # public
    assert observer.get('/').status_code == 200


def test_a_role_added_at_l1_can_do_what_admin_can(app, people):
    _add(login(app, ADMIN), 'Co-admin', 1)
    coadmin = login(app, people('coadmin-l1', 'Co-admin'))
    assert coadmin.get('/api/export/counts').status_code not in (401, 403)       # admin level, and is_admin() in the route
    assert coadmin.get(API).status_code == 200 and coadmin.get('/permissions/').status_code == 200


def test_changing_the_tier_of_a_built_in_role_changes_what_its_accounts_may_do(app):
    admin = login(app, ADMIN)
    assert login(app, STAFF).get('/users/table2').status_code == 200
    body = admin.put(f'{API}/{STAFF_NAME}', json={'tier': 4}).get_json()
    assert _role(body, STAFF_NAME)['tier'] == 4 and _role(body, STAFF_NAME)['changed']
    teacher = login(app, STAFF)
    assert teacher.get('/users/table2').status_code == 403
    assert teacher.post('/api/classrooms/', json={}).status_code == 403
    assert teacher.get('/api/id').status_code == 403                                   # L4: member-level requests too
    body = admin.delete(f'{API}/{STAFF_NAME}').get_json()                              # reset
    assert _role(body, STAFF_NAME)['tier'] == 2 and not _role(body, STAFF_NAME)['changed']
    assert login(app, STAFF).get('/users/table2').status_code == 200


def test_the_permissions_page_still_customizes_a_tiers_default(app, people):
    """The tier is the default; one request can still be made stricter for everyone."""
    _add(login(app, ADMIN), 'Helper', 3)
    helper = login(app, people('helper-custom', 'Helper'))
    assert helper.get('/api/id').status_code == 200
    login(app, ADMIN).put('/api/permissions', json={'requests': {'GET /api/id': 'staff'}})
    assert helper.get('/api/id').status_code == 403


def test_the_tier_counts_follow_what_the_permissions_page_changed(app):
    admin = login(app, ADMIN)
    before = {t['tier']: t['may_make'] for t in admin.get(API).get_json()['tiers']}
    admin.put('/api/permissions', json={'requests': {'GET /api/id': 'admin'}})
    after = {t['tier']: t['may_make'] for t in admin.get(API).get_json()['tiers']}
    assert after[1] == before[1] and after[2] == before[2] - 1 and after[3] == before[3] - 1


# --- labels and the admin role ----------------------------------------------------------------------------------------

def test_a_label_changes_what_people_see_and_clearing_it_restores_the_kits(app):
    admin = login(app, ADMIN)
    admin.put(f'{API}/{STAFF_NAME}', json={'label': 'Coach'})
    assert login(app, STAFF).get('/api/id').get_json()['role_label'] == 'Coach'
    assert 'Coach' in login(app, ADMIN).get('/users/table2').get_data(as_text=True)
    body = admin.put(f'{API}/{STAFF_NAME}', json={'label': ''}).get_json()
    assert _role(body, STAFF_NAME)['label'] == 'Teacher' and not _role(body, STAFF_NAME)['changed']
    assert login(app, STAFF).get('/api/id').get_json()['role_label'] == 'Teacher'


def test_setting_a_built_in_role_back_to_its_defaults_stores_nothing(app):
    admin = login(app, ADMIN)
    admin.put(f'{API}/{MEMBER_NAME}', json={'tier': 4})
    body = admin.put(f'{API}/{MEMBER_NAME}', json={'tier': 3}).get_json()
    assert not _role(body, MEMBER_NAME)['changed']


def test_the_admin_role_is_always_l1_and_cannot_be_removed(app):
    admin = login(app, ADMIN)
    r = admin.put(f'{API}/{ADMIN_NAME}', json={'tier': 3})
    assert r.status_code == 400 and 'always L1' in r.get_json()['message']
    assert admin.put(f'{API}/{ADMIN_NAME}', json={'label': 'Owner'}).status_code == 200      # a label is fine
    body = admin.delete(f'{API}/{ADMIN_NAME}').get_json()                                    # resets, never removes
    assert _role(body, ADMIN_NAME)['tier'] == 1 and _role(body, ADMIN_NAME)['label'] == 'Admin'


@pytest.mark.parametrize('body', [None, {}, {'colour': 'red'}, {'tier': 9}, {'tier': 'x'}, {'label': 'x' * 41}])
def test_a_bad_change_is_refused(app, body):
    admin = login(app, ADMIN)
    r = admin.put(f'{API}/{STAFF_NAME}', json=body) if body is not None else admin.put(f'{API}/{STAFF_NAME}', data='no')
    assert r.status_code == 400


def test_an_unknown_role_is_404(app):
    admin = login(app, ADMIN)
    assert admin.put(f'{API}/Ghost', json={'tier': 2}).status_code == 404
    assert admin.delete(f'{API}/Ghost').status_code == 404


# --- deleting a role ------------------------------------------------------------------------------------------------

def test_a_role_that_accounts_hold_cannot_be_deleted_until_they_have_another(app, people):
    admin = login(app, ADMIN)
    _add(admin, 'Mentor', 3)
    uid = people('mentor-holder', 'Mentor')
    r = admin.delete(f'{API}/Mentor')
    assert r.status_code == 409 and '1 account still has the role' in r.get_json()['message']
    assert _role(admin.get(API).get_json(), 'Mentor')['accounts'] == 1
    assert admin.put('/api/user/role', json={'uid': uid, 'role': MEMBER_NAME}).status_code == 200
    body = admin.delete(f'{API}/Mentor').get_json()
    assert 'Mentor' not in [r['name'] for r in body['roles']] and body['recent_changes'][0]['action'] == 'delete'


# --- giving an account a role ----------------------------------------------------------------------------------------

def test_an_admin_gives_an_account_a_role_and_it_is_logged(app, people):
    admin = login(app, ADMIN)
    _add(admin, 'Coach', 2)
    uid = people('assign-me')
    assert login(app, uid).get('/users/table2').status_code == 403
    r = admin.put('/api/user/role', json={'uid': uid, 'role': 'Coach'})
    assert r.status_code == 200 and r.get_json() == {'uid': uid, 'role': 'Coach', 'role_label': 'Coach'}
    assert login(app, uid).get('/users/table2').status_code == 200
    log = admin.get(API).get_json()['recent_changes']
    assert log[0]['action'] == 'assign' and f'{uid}: {MEMBER_NAME} to Coach' in log[0]['detail']
    admin.put('/api/user/role', json={'uid': uid, 'role': 'Coach'})                 # the same again
    assert admin.get(API).get_json()['recent_changes'][0] == log[0]                 # nothing new logged


def test_assigning_a_role_is_checked(app, people):
    admin = login(app, ADMIN)
    uid = people('assign-checks')
    assert admin.put('/api/user/role', json={'uid': 'no-such', 'role': MEMBER_NAME}).status_code == 404
    assert admin.put('/api/user/role', json={'uid': uid, 'role': 'Ghost'}).status_code == 400
    for body in (None, {}, {'uid': uid}, {'role': MEMBER_NAME}, {'uid': 5, 'role': 'x'}):
        r = admin.put('/api/user/role', json=body) if body is not None else admin.put('/api/user/role', data='no')
        assert r.status_code == 400
    r = admin.put('/api/user/role', json={'uid': ADMIN, 'role': MEMBER_NAME})
    assert r.status_code == 400 and 'your own role' in r.get_json()['message']
    assert login(app, ADMIN).get(API).status_code == 200                              # still an admin


def test_the_help_guide_and_menu_know_about_roles(app):
    page = login(app, ADMIN).get('/users/table2').get_data(as_text=True)
    assert 'href="/roles/"' in page
    assert 'Roles</a>' in page.split('dropdown-submenu')[1]
