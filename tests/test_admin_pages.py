"""Server-rendered admin pages: staff pages for staff and admins, admin pages for admins only."""
import pytest

from conftest import ADMIN, MEMBER, STAFF, login

STAFF_PAGES = [('GET', '/users/table2'), ('GET', '/sections/')]
ADMIN_PAGES = [('DELETE', '/users/delete/99999'), ('POST', '/users/reset_password/99999'),
               ('PUT', '/update_user/nobody'), ('GET', '/kasm_users'), ('DELETE', '/delete_user/123')]


@pytest.mark.parametrize('method,url', STAFF_PAGES + ADMIN_PAGES)
def test_anonymous_is_sent_to_login(app, method, url):
    r = login(app, None).open(url, method=method, json={})
    assert r.status_code == 302 and '/login' in r.headers['Location']


@pytest.mark.parametrize('method,url', STAFF_PAGES + ADMIN_PAGES)
def test_member_is_forbidden(app, method, url):
    assert login(app, MEMBER).open(url, method=method, json={}).status_code == 403


@pytest.mark.parametrize('method,url', ADMIN_PAGES)
def test_staff_is_forbidden_on_admin_pages(app, method, url):
    assert login(app, STAFF).open(url, method=method, json={}).status_code == 403


@pytest.mark.parametrize('uid', [STAFF, ADMIN])
@pytest.mark.parametrize('method,url', STAFF_PAGES)
def test_staff_and_admin_open_staff_pages(app, uid, method, url):
    assert login(app, uid).open(url, method=method).status_code == 200


def test_admin_passes_admin_checks(app):
    client = login(app, ADMIN)
    assert client.delete('/users/delete/99999').status_code == 404       # past auth: no such user
    assert client.get('/kasm_users').status_code == 400                  # past auth: no Kasm keys


def test_user_table_shows_kit_role_labels(app):
    page = login(app, ADMIN).get('/users/table2').get_data(as_text=True)
    assert 'Teacher' in page and 'Student' in page  # education labels for Teacher / User
