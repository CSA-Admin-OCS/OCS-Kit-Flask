"""The Permissions page and API: admins see who may make each request and change one request's level."""
import pytest

from conftest import ADMIN, MEMBER, STAFF, login

PAGE = '/permissions/'
API = '/api/permissions'
OPEN_ROUTE = 'GET /api/study'   # unreviewed in permissions.json: open to anyone until someone decides
MEMBER_ROUTE = 'GET /api/id'    # member in permissions.json


def _put(client, requests):
    return client.put(API, json={'requests': requests})


def _row(payload, request_line):
    return next(row for row in payload['requests'] if row['request'] == request_line)


def test_only_admins_open_the_page_and_the_api(app):
    assert login(app, None).get(PAGE).status_code == 302
    assert login(app, None).get(API).status_code == 401
    for uid in (MEMBER, STAFF):
        assert login(app, uid).get(PAGE).status_code == 403
        assert login(app, uid).get(API).status_code == 403
        assert _put(login(app, uid), {OPEN_ROUTE: 'admin'}).status_code == 403
    assert login(app, ADMIN).get(PAGE).status_code == 200


def test_payload_lists_every_request_by_feature(app):
    payload = login(app, ADMIN).get(API).get_json()
    assert payload['levels'] == ['public', 'member', 'staff', 'admin']
    # the education kit under test calls the three roles Student, Teacher and Admin
    assert payload['level_labels'] == {'public': 'Public', 'member': 'Student', 'staff': 'Teacher', 'admin': 'Admin'}
    assert {f['id'] for f in payload['features']} >= {'core'}
    row = _row(payload, OPEN_ROUTE)
    assert row['file_level'] == row['level'] == 'unreviewed' and not row['overridden'] and not row['pinned']
    assert _row(payload, 'PUT /api/permissions')['pinned'] is True
    assert _row(payload, 'POST /api/microblog/topics')['feature'] == 'social'


def test_tightening_a_request_applies_at_once_and_is_logged(app):
    assert login(app, None).get('/api/study').status_code != 401           # open today
    payload = _put(login(app, ADMIN), {OPEN_ROUTE: 'member'}).get_json()
    assert _row(payload, OPEN_ROUTE)['overridden'] and _row(payload, OPEN_ROUTE)['level'] == 'member'
    assert payload['recent_changes'][0] == {**payload['recent_changes'][0], 'request': OPEN_ROUTE,
                                            'from': None, 'to': 'member', 'by': ADMIN}
    assert login(app, None).get('/api/study').status_code == 401           # now needs a login
    assert login(app, MEMBER).get('/api/study').status_code != 401


def test_reset_goes_back_to_the_file(app):
    admin = login(app, ADMIN)
    _put(admin, {MEMBER_ROUTE: 'admin'})
    assert login(app, MEMBER).get('/api/id').status_code == 403
    payload = _put(admin, {MEMBER_ROUTE: None}).get_json()
    assert not _row(payload, MEMBER_ROUTE)['overridden']
    assert login(app, MEMBER).get('/api/id').status_code != 403


def test_choosing_the_level_the_file_gives_is_a_reset(app):
    admin = login(app, ADMIN)
    _put(admin, {MEMBER_ROUTE: 'admin'})
    payload = _put(admin, {MEMBER_ROUTE: 'member'}).get_json()
    assert not _row(payload, MEMBER_ROUTE)['overridden']
    assert payload['recent_changes'][0]['to'] is None


@pytest.mark.parametrize('body,message', [
    (None, 'Body must be'),
    ({'requests': {}}, 'Body must be'),
    ({'requests': {'GET /api/nothing-here': 'admin'}}, 'is not a request this app answers'),
    ({'requests': {'PUT /api/permissions': 'public'}}, 'pinned'),
    ({'requests': {'POST /login': 'admin'}}, 'pinned'),
    ({'requests': {OPEN_ROUTE: 'unreviewed'}}, 'level must be one of'),
    ({'requests': {OPEN_ROUTE: 'owner'}}, 'level must be one of'),
])
def test_bad_changes_are_refused_and_nothing_is_saved(app, body, message):
    admin = login(app, ADMIN)
    r = admin.put(API, json=body) if body is not None else admin.put(API, data='nope')
    assert r.status_code == 400 and message in r.get_json()['message']
    assert all(not row['overridden'] for row in admin.get(API).get_json()['requests'])


def test_a_bad_entry_saves_none_of_the_batch(app):
    admin = login(app, ADMIN)
    assert _put(admin, {OPEN_ROUTE: 'member', 'POST /login': 'admin'}).status_code == 400
    assert not _row(admin.get(API).get_json(), OPEN_ROUTE)['overridden']


def test_an_override_cannot_loosen_a_pinned_request_even_if_a_row_exists(app):
    """Defence in depth: a stored row for a pinned request is ignored."""
    import permissions
    from __init__ import db
    from model.permission_override import PermissionOverride
    with app.app_context():
        db.session.add(PermissionOverride(request='PUT /api/permissions', level='public'))
        db.session.commit()
        assert permissions.effective_level('PUT', '/api/permissions') == 'admin'


def test_when_the_stored_levels_cannot_be_read_requests_are_refused_not_guessed(app, monkeypatch):
    from model import permission_override

    def broken(_):
        raise RuntimeError('database is down')
    monkeypatch.setattr(permission_override, 'read_override', broken)
    r = login(app, ADMIN).get('/api/id')
    assert r.status_code == 503 and 'cannot be read' in r.get_json()['message']
    assert login(app, None).get('/login').status_code == 200   # pinned login still works


def test_the_page_is_linked_from_the_admin_menu(app):
    page = login(app, ADMIN).get('/users/table2').get_data(as_text=True)
    assert 'href="/permissions/"' in page


def test_loosening_cannot_override_a_check_the_route_makes_itself(app):
    """Routes with their own sign-in or role decorator still apply it: the page can tighten any request, but only
    loosen one the route does not guard itself. The README says so."""
    admin = login(app, ADMIN)
    assert _put(admin, {MEMBER_ROUTE: 'public'}).status_code == 200
    assert login(app, None).get('/api/id').status_code == 401
