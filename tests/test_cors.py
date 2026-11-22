"""CORS: which websites may call this backend from a browser. The list comes from .env until an admin saves one
on the CORS page; the headers are what Flask-CORS used to send (compared with it request by request when this
module replaced it), and a change applies on the next request."""
import pytest

import cors
from conftest import ADMIN, MEMBER, STAFF, login

PAGE, API = '/cors/', '/api/cors'
DEFAULT = 'http://localhost:4500'       # in the default list: CORS_ORIGINS is empty under test
NEW = 'https://pages.example.org'
URL = '/api/kit'                        # public, so only the CORS headers differ


def _get(app, origin=None, method='GET', extra=None):
    headers = {'Origin': origin} if origin else {}
    headers.update(extra or {})
    return login(app, None).open(URL, method=method, headers=headers)


def _put(client, origins):
    return client.put(API, json={'origins': origins})


# --- what an origin may look like -------------------------------------------------------------------------------

@pytest.mark.parametrize('text,expected', [
    ('https://pages.example.org', 'https://pages.example.org'),
    ('  HTTPS://Pages.Example.ORG  ', 'https://pages.example.org'),
    ('http://localhost:4500', 'http://localhost:4500'),
    ('http://[::1]:4500', 'http://[::1]:4500'),
])
def test_origins_are_written_one_way(text, expected):
    assert cors.normalize_origin(text) == expected


@pytest.mark.parametrize('text,message', [
    ('https://pages.example.org/', 'remove the path, trailing slash or login'),
    ('https://pages.example.org/app', 'remove the path'),
    ('https://user@pages.example.org', 'remove the path'),
    ('https://pages.example.org?x=1', 'remove the path'),
    ('pages.example.org', 'start with http:// or https://'),
    ('ftp://pages.example.org', 'start with http:// or https://'),
    ('https://', 'start with http:// or https://'),
    ('*', r'patterns and \* cannot be saved'),
    ('https://.*\\.example\\.org', r'patterns and \* cannot be saved'),
    ('http://host:abc', 'the port must be a number'),
    ('', 'Each origin must be text'),
    (None, 'Each origin must be text'),
    (5, 'Each origin must be text'),
])
def test_unclear_origins_are_refused(text, message):
    with pytest.raises(ValueError, match=message):
        cors.normalize_origin(text)


def test_a_list_drops_repeats_and_must_be_a_list_of_modest_size():
    assert cors.normalize_origins([NEW, NEW.upper(), DEFAULT]) == [NEW, DEFAULT]
    for bad in ('https://a.example', {'a': 1}, None):
        with pytest.raises(ValueError, match='Body must be'):
            cors.normalize_origins(bad)
    with pytest.raises(ValueError, match='At most'):
        cors.normalize_origins([f'https://s{i}.example.org' for i in range(cors.MAX_ORIGINS + 1)])


def test_matching_is_exact_and_case_blind_for_origins_and_regex_for_env_patterns():
    assert cors.allows('HTTP://LOCALHOST:4500', [DEFAULT])
    assert not cors.allows('http://localhost:45001', [DEFAULT])
    assert not cors.allows('https://evil.example', [DEFAULT])
    pattern = ['https://.*\\.example\\.org']
    assert cors.allows('https://a.example.org', pattern) and cors.allows('HTTPS://A.EXAMPLE.ORG', pattern)
    assert not cors.allows('https://a.example.com', pattern)
    assert cors.allows('https://anything.test', ['*'])


def test_a_bad_pattern_in_env_stops_startup():
    with pytest.raises(ValueError, match='not a valid pattern'):
        cors.check_defaults(['https://(unclosed'])
    cors.check_defaults([DEFAULT, 'https://.*\\.example\\.org', '*'])


def test_warnings_for_the_page():
    assert cors.warning_for('http://pages.example.org') and 'not https' in cors.warning_for('http://pages.example.org')
    assert cors.warning_for('http://localhost:4500') is None and cors.warning_for('http://127.0.0.1:4500') is None
    assert cors.warning_for('https://pages.example.org') is None
    assert cors.warning_for('*') == 'every site' and 'pattern' in cors.warning_for('https://.*\\.example\\.org')


# --- the headers -----------------------------------------------------------------------------------------------------

def test_an_allowed_origin_gets_the_headers_with_cookies_allowed(app):
    h = _get(app, DEFAULT).headers
    assert h['Access-Control-Allow-Origin'] == DEFAULT and h['Access-Control-Allow-Credentials'] == 'true'
    assert 'Origin' in h['Vary']


def test_other_origins_and_same_site_requests_get_no_cors_headers(app):
    for origin in ('https://evil.example', 'http://localhost:4500/', 'null', None):
        assert 'Access-Control-Allow-Origin' not in _get(app, origin).headers


def test_the_preflight_answer_lists_methods_and_echoes_requested_headers(app):
    h = _get(app, DEFAULT, 'OPTIONS', {'Access-Control-Request-Method': 'PUT',
                                      'Access-Control-Request-Headers': 'content-type, X-Origin, authorization'}).headers
    assert h['Access-Control-Allow-Methods'] == 'DELETE, GET, OPTIONS, POST, PUT'
    assert h['Access-Control-Allow-Headers'] == 'X-Origin, authorization, content-type'
    plain = _get(app, DEFAULT, 'OPTIONS').headers   # an OPTIONS that is not a preflight
    assert 'Access-Control-Allow-Methods' not in plain and plain['Access-Control-Allow-Origin'] == DEFAULT


def test_error_answers_carry_the_headers_too(app):
    r = login(app, None).get('/api/nothing-here', headers={'Origin': DEFAULT})
    assert r.status_code == 404 and r.headers['Access-Control-Allow-Origin'] == DEFAULT


def test_env_patterns_still_work_and_are_flagged_on_the_page(app, monkeypatch):
    monkeypatch.setitem(app.config, 'CORS_ORIGINS', ['https://.*\\.example\\.org'])
    monkeypatch.setitem(app.config, 'CORS_ORIGINS_FROM_ENV', True)
    assert _get(app, 'https://a.example.org').headers['Access-Control-Allow-Origin'] == 'https://a.example.org'
    assert 'Access-Control-Allow-Origin' not in _get(app, DEFAULT).headers
    body = login(app, ADMIN).get(API).get_json()
    assert body['source'] == 'env'
    assert body['origins'][0]['kind'] == 'pattern' and 'pattern' in body['origins'][0]['warning']


# --- the page and the API ----------------------------------------------------------------------------------------

def test_only_admins_open_the_page_and_the_api(app):
    assert login(app, None).get(PAGE).status_code == 302
    assert login(app, None).get(API).status_code == 401
    for uid in (MEMBER, STAFF):
        assert login(app, uid).get(PAGE).status_code == 403
        assert login(app, uid).get(API).status_code == 403
        assert _put(login(app, uid), [NEW]).status_code == 403
        assert login(app, uid).delete(API).status_code == 403
    assert login(app, ADMIN).get(PAGE).status_code == 200


def test_the_payload_starts_with_the_default_list(app):
    body = login(app, ADMIN).get(API).get_json()
    assert body['source'] == 'default' and body['default_source'] == 'default'
    assert body['origins'] == body['default_origins'] and DEFAULT in [o['origin'] for o in body['origins']]
    assert all(o['kind'] == 'exact' for o in body['origins']) and body['recent_changes'] == []


def test_a_saved_list_replaces_the_default_at_once_and_is_logged(app):
    admin = login(app, ADMIN)
    assert _get(app, DEFAULT).headers.get('Access-Control-Allow-Origin') == DEFAULT
    body = _put(admin, [NEW, 'http://localhost:4000']).get_json()
    assert body['source'] == 'admin' and [o['origin'] for o in body['origins']] == [NEW, 'http://localhost:4000']
    assert _get(app, NEW).headers['Access-Control-Allow-Origin'] == NEW                   # new: allowed now
    assert 'Access-Control-Allow-Origin' not in _get(app, DEFAULT).headers                # old default: no longer
    change = body['recent_changes'][0]
    assert change['action'] == 'set' and change['by'] == ADMIN
    assert f'added {NEW}' in change['detail'] and f'removed {DEFAULT}' in change['detail']


def test_saved_origins_are_normalized_and_repeats_dropped(app):
    body = _put(login(app, ADMIN), ['  HTTPS://Pages.Example.org ', NEW]).get_json()
    assert [o['origin'] for o in body['origins']] == [NEW]


def test_an_empty_saved_list_allows_no_website(app):
    body = _put(login(app, ADMIN), []).get_json()
    assert body['source'] == 'admin' and body['origins'] == []
    assert 'Access-Control-Allow-Origin' not in _get(app, DEFAULT).headers


@pytest.mark.parametrize('body', [None, {}, {'origins': 'https://a.example'}, {'origins': ['*']},
                                  {'origins': [NEW, 'https://a.example/']}, {'origins': [5]}])
def test_a_bad_list_is_refused_and_nothing_is_saved(app, body):
    admin = login(app, ADMIN)
    r = admin.put(API, json=body) if body is not None else admin.put(API, data='nope')
    assert r.status_code == 400 and r.get_json()['message']
    after = admin.get(API).get_json()
    assert after['source'] == 'default' and after['recent_changes'] == []


def test_reset_returns_to_the_default_and_a_second_reset_changes_nothing(app):
    admin = login(app, ADMIN)
    _put(admin, [NEW])
    body = admin.delete(API).get_json()
    assert body['source'] == 'default' and body['recent_changes'][0]['action'] == 'reset'
    assert _get(app, DEFAULT).headers['Access-Control-Allow-Origin'] == DEFAULT
    assert len(admin.delete(API).get_json()['recent_changes']) == len(body['recent_changes'])   # nothing new logged


def test_when_the_saved_list_cannot_be_read_no_website_is_allowed(app, monkeypatch):
    def broken():
        raise RuntimeError('database is down')
    monkeypatch.setattr(cors, 'stored_entries', broken)
    r = _get(app, DEFAULT)
    assert r.status_code == 200 and 'Access-Control-Allow-Origin' not in r.headers


def test_the_page_is_linked_from_the_admin_menu(app):
    assert 'href="/cors/"' in login(app, ADMIN).get('/users/table2').get_data(as_text=True)
