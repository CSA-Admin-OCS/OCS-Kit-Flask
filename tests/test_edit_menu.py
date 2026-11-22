"""The Edit button in User Management is a menu of places to go. What a row offers depends on the row and on what the
person looking may open: Change role (the Roles page with that account filled in) and Sections for other accounts, the
website's profile page only on the person's own row (it edits whoever is signed in)."""
import html
import re
from urllib.parse import quote

import pytest

import permissions
from conftest import ADMIN, MEMBER, PASSWORD, STAFF, login


def _rows(app, uid):
    """{account uid: that row's html} of the user table as seen by `uid`."""
    page = login(app, uid).get('/users/table2').get_data(as_text=True)
    rows = {}
    for chunk in page.split('<tr id="user-')[1:]:
        row = chunk.split('</tr>')[0]
        rows[html.unescape(re.search(r'<td>(?:\d+)</td>\s*<td>([^<]*)</td>', f'<td>{row}').group(1))] = row
    return rows


def _menu(row):
    """[(label, href)] of the Edit menu in a row."""
    return [(re.sub(r'\s+', ' ', label).replace(' &#8599;', '').strip(), href)
            for href, label in re.findall(r'<a class="dropdown-item" href="([^"]*)"[^>]*>([^<]*(?:&#8599;)?)</a>', row)]


def test_another_account_can_be_sent_to_the_roles_page_with_its_uid_filled_in(app):
    menu = _menu(_rows(app, ADMIN)[STAFF])
    assert ('Change role', f'/roles/?uid={STAFF}') in menu
    assert ('Sections', '/sections/') in menu
    assert not any(label.startswith('Open my profile') for label, _ in menu)       # that page edits you, not them


def test_your_own_row_has_the_website_profile_but_no_change_role(app):
    menu = _menu(_rows(app, ADMIN)[ADMIN])
    assert [label for label, _ in menu] == ['Sections', 'Open my profile on the website']
    assert dict(menu)['Open my profile on the website'] == app.config['FRONTEND_URL'].rstrip('/') + '/profile'
    row = _rows(app, ADMIN)[ADMIN]
    assert 'target="_blank" rel="noopener"' in row.split('Open my profile')[0].rsplit('<a', 1)[1]   # leaves this site safely


def test_staff_see_only_their_own_row_and_only_what_they_may_open(app):
    rows = _rows(app, STAFF)
    assert list(rows) == [STAFF]
    assert [label for label, _ in _menu(rows[STAFF])] == ['Sections', 'Open my profile on the website']


def test_a_page_the_admin_tightened_leaves_the_staff_menu(app):
    assert 'Sections' in [label for label, _ in _menu(_rows(app, STAFF)[STAFF])]
    assert login(app, ADMIN).put('/api/permissions', json={'requests': {'GET /sections/': 'admin'}}).status_code == 200
    assert 'Sections' not in [label for label, _ in _menu(_rows(app, STAFF)[STAFF])]


def test_members_cannot_open_the_table_at_all(app):
    assert login(app, MEMBER).get('/users/table2').status_code == 403


def test_with_nowhere_to_go_the_button_is_disabled(app, monkeypatch):
    monkeypatch.setattr(permissions, 'may_make', lambda *args, **kwargs: False)
    monkeypatch.setitem(app.config, 'FRONTEND_URL', '')
    for row in _rows(app, ADMIN).values():
        assert _menu(row) == [] and re.search(r'<button[^>]*\bdisabled\b[^>]*>Edit</button>', row)


def test_an_awkward_username_is_encoded_in_the_link(app):
    from __init__ import db
    from model.user import User
    uid = 'a b&c=d'
    with app.app_context():
        User(name='Odd', uid=uid, password=PASSWORD).create()
    try:
        href = dict(_menu(_rows(app, ADMIN)[uid]))['Change role']
        assert href.startswith('/roles/?uid=') and ' ' not in href and '&c' not in href and '=d' not in href.split('uid=')[1]
        assert quote(uid, safe='') in href or '+' in href                      # the same text once decoded
    finally:
        with app.app_context():
            user = User.query.filter_by(_uid=uid).first()
            if user:
                db.session.delete(user)
                db.session.commit()


def test_the_roles_page_fills_the_form_from_the_uid_in_the_address(app):
    page = login(app, ADMIN).get(f'/roles/?uid={STAFF}').get_data(as_text=True)
    assert 'new URLSearchParams(window.location.search).get("uid")' in page
    assert '$("assignUid").value = wanted' in page
