"""permissions.json: the file is valid, it lists every route, and the check before each request refuses exactly
the callers below a request's level (with the right answer for APIs and for admin pages)."""
import json
import re
from datetime import datetime, timedelta

import jwt
import pytest
from flask_login import login_user
from werkzeug.exceptions import HTTPException

import permissions
from conftest import ADMIN, MEMBER, STAFF, login

CALLERS = [None, MEMBER, STAFF, ADMIN]  # anonymous, then rising trust
RANK_OF = {None: 0, MEMBER: 1, STAFF: 2, ADMIN: 3}


# --- the file ---------------------------------------------------------------------------------------------------

def test_file_is_valid_and_every_entry_is_in_one_list():
    with open(permissions.FILE) as fh:
        data = json.load(fh)
    listed = [entry for name in permissions.LISTS for entry in data[name]]
    assert len(listed) == len(set(listed)), 'a request is in two lists'
    parsed, api_paths, pinned = permissions.parse(data)
    assert set(parsed) == set(listed)
    assert api_paths == tuple(data['api_paths'])
    assert pinned == frozenset(data['pinned'])


def test_file_matches_the_routes(app):
    """Every route is listed (a new one is closed until someone decides) and no entry names a missing route."""
    assert permissions.problems(app) == []


@pytest.mark.parametrize('data,message', [
    ([], 'expected an object'),
    ({'owner': []}, '"owner" is not a level'),
    ({'admin': 'GET /x'}, 'must be a list'),
    ({'admin': ['/api/x']}, 'is not written "METHOD /route"'),
    ({'admin': ['FETCH /api/x']}, 'is not written "METHOD /route"'),
    ({'admin': ['GET /api/x'], 'member': ['GET /api/x']}, 'in only one'),
    ({'admin': ['GET /api/x', 'GET /api/x']}, 'in only one'),
    ({'api_paths': 'api'}, 'must be a list of path prefixes'),
    ({'api_paths': ['api/']}, 'must be a list of path prefixes'),
    ({'pinned': 'GET /x'}, '"pinned" must be a list'),
    ({'pinned': ['GET /api/x']}, 'is not in any level list'),
])
def test_unclear_file_is_refused(data, message):
    with pytest.raises(ValueError, match=message):
        permissions.parse(data)


def test_a_missing_list_is_empty():
    assert permissions.parse({'admin': ['GET /api/x']}) == ({'GET /api/x': 'admin'}, (), frozenset())


def test_unreviewed_is_open_but_listed_apart():
    assert permissions.RANK[permissions.UNREVIEWED] == permissions.RANK[permissions.PUBLIC] == 0


def test_role_levels_come_from_roles_py_in_rising_order():
    import roles
    assert permissions.ROLE_LEVELS == tuple(reversed(roles.ROLE_IDS))
    assert [permissions.RANK[level] for level in permissions.ROLE_LEVELS] == [1, 2, 3]


# --- the check, request by request ------------------------------------------------------------------------------

def _path(rule):
    rule = re.sub(r'<int:[^>]+>', '999999', rule)
    rule = re.sub(r'<path:[^>]+>', 'x', rule)
    return re.sub(r'<[^>]+>', 'nobody', rule)


def _answer(app, method, rule, uid):
    """What check_access answers a caller for a request, without running the route: None means 'let it go on',
    otherwise the status it refuses with."""
    from model.user import User
    with app.test_request_context(_path(rule), method=method):
        from flask import request
        assert request.url_rule is not None and request.url_rule.rule == rule, f'{_path(rule)} did not match {rule}'
        if uid:
            login_user(User.query.filter_by(_uid=uid).first())
        try:
            result = permissions.check_access()
        except HTTPException as refused:
            return refused.code
    if result is None:
        return None
    return result[1] if isinstance(result, tuple) else result.status_code


def _requests():
    return sorted(permissions.policy().items())


@pytest.mark.parametrize('uid', CALLERS, ids=lambda u: u or 'anonymous')
def test_each_caller_gets_as_far_as_its_level_and_no_further(app, uid):
    wrong = []
    for request_line, level in _requests():
        method, rule = request_line.split(' ', 1)
        answer = _answer(app, method, rule, uid)
        may_make = RANK_OF[uid] >= permissions.RANK[level]
        reached_route = answer is None
        if may_make != reached_route:
            wrong.append(f'{request_line} is {level}: {uid or "anonymous"} got {answer}')
    assert wrong == []


def test_refusals_use_the_right_status(app):
    assert _answer(app, 'GET', '/api/export/counts', None) == 401        # API: no login
    assert _answer(app, 'GET', '/api/export/counts', MEMBER) == 403      # API: not enough
    assert _answer(app, 'GET', '/users/table2', None) == 302             # admin page: sent to log in
    assert _answer(app, 'GET', '/users/table2', MEMBER) == 403           # admin page: not enough
    assert _answer(app, 'GET', '/users/table2', STAFF) is None


def test_options_and_static_are_never_refused(app):
    assert _answer(app, 'OPTIONS', '/api/export/counts', None) is None
    with app.test_request_context('/static/x.css'):
        assert permissions.check_access() is None


def test_head_follows_get(app):
    from flask import request
    with app.test_request_context('/api/export/counts', method='HEAD'):
        assert request.url_rule is not None
        assert permissions.level_of('HEAD', request.url_rule.rule) == permissions.level_of('GET', request.url_rule.rule)


def test_unlisted_request_is_refused_for_everyone_with_the_fix_in_the_message(app, monkeypatch):
    monkeypatch.delitem(permissions.policy(), 'GET /api/kit')
    for uid in CALLERS:
        client = login(app, uid)
        r = client.get('/api/kit')
        assert r.status_code == 403
        assert 'GET /api/kit is not in permissions.json' in r.get_json()['message']
    assert 'GET /api/kit is a route but is in no list' in permissions.problems(app)


def test_stale_entry_is_reported(app, monkeypatch):
    monkeypatch.setitem(permissions.policy(), 'GET /api/nothing-here', 'admin')
    assert 'GET /api/nothing-here is in the file but the app has no such route' in permissions.problems(app)


def test_disabled_feature_still_answers_404_first(app):
    """The test kit has social off. Its admin-level route is 404 to everyone, not 401/403."""
    assert permissions.level_of('POST', '/api/microblog/topics') == 'admin'
    for uid in CALLERS:
        assert login(app, uid).post('/api/microblog/topics', json={}).status_code == 404


def test_api_paths_come_from_the_file(app, monkeypatch):
    """Change what counts as an API and a request with no login is answered differently, with no code change."""
    assert _answer(app, 'GET', '/api/export/counts', None) == 401
    monkeypatch.setattr(permissions, '_loaded', (permissions.policy(), ('/somewhere-else/',), permissions.pinned()))
    assert _answer(app, 'GET', '/api/export/counts', None) == 302


def test_stored_role_outside_the_three_counts_as_member():
    class Other:
        role = 'Visitor'
    assert permissions.caller_rank(Other()) == 1
    assert permissions.caller_rank(None) == 0


# --- the same answers for a caller with a JWT instead of a session ------------------------------------------------

def _token(app, uid, **claims):
    from model.user import User
    user = User.query.filter_by(_uid=uid).first()
    payload = {'_uid': uid, 'token_version': user.token_version, 'exp': datetime.utcnow() + timedelta(minutes=5)}
    payload.update(claims)
    return jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')


def _with_token(app, token):
    client = app.test_client()
    if token:
        client.set_cookie(app.config['JWT_TOKEN_NAME'], token)
    return client


def test_jwt_callers_get_the_same_levels(app):
    with app.app_context():
        tokens = {ADMIN: _token(app, ADMIN), STAFF: _token(app, STAFF), MEMBER: _token(app, MEMBER)}
    url = '/api/export/counts'  # admin
    assert _with_token(app, None).get(url).status_code == 401
    assert _with_token(app, tokens[MEMBER]).get(url).status_code == 403
    assert _with_token(app, tokens[STAFF]).get(url).status_code == 403
    assert _with_token(app, tokens[ADMIN]).get(url).status_code not in (401, 403)
    assert _with_token(app, tokens[MEMBER]).get('/api/id').status_code not in (401, 403)  # member level


def test_bad_tokens_are_refused_401(app):
    url = '/api/id'
    with app.app_context():
        expired = _token(app, ADMIN, exp=datetime.utcnow() - timedelta(minutes=1))
        old_version = _token(app, ADMIN, token_version=-1)
    wrong_key = jwt.encode({'_uid': ADMIN}, 'not-the-key', algorithm='HS256')
    for token in ('garbage', expired, old_version, wrong_key):
        assert _with_token(app, token).get(url).status_code == 401
    unknown = jwt.encode({'_uid': 'nobody-here', 'exp': datetime.utcnow() + timedelta(minutes=5)},
                         app.config['SECRET_KEY'], algorithm='HS256')
    assert _with_token(app, unknown).get(url).status_code == 401


def test_a_jwt_does_not_open_admin_pages(app):
    """Server-rendered pages use the Flask session only, as before."""
    with app.app_context():
        token = _token(app, ADMIN)
    r = _with_token(app, token).get('/users/table2')
    assert r.status_code == 302 and '/login' in r.headers['Location']
