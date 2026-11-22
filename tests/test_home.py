"""The home page introduces this backend: the organization and kit, the roles, what is running, and the admin
tools the signed-in person may open (by the permission levels in force)."""
import pytest

from conftest import ADMIN, MEMBER, STAFF, login


def _home(app, uid=None):
    r = login(app, uid).get('/')
    assert r.status_code == 200
    return r.get_data(as_text=True)


def test_anonymous_visitor_sees_the_intro_and_a_sign_in_button(app):
    page = _home(app)
    assert 'OCS-in-a-Kit Backend' in page and app.config['ORG_NAME'] in page
    assert '>Education</span>' in page                   # the kit under test
    assert 'Sign in</a>' in page and 'Signed in as' not in page
    assert 'Python Home Page' not in page                # the old teaching page is gone
    assert 'Your tools' not in page


def test_roles_are_shown_with_the_kits_labels(app):
    page = _home(app)
    for label in ('Admin', 'Teacher', 'Student'):
        assert f'<strong>{label}</strong>' in page


def test_only_features_that_are_on_are_listed(app):
    page = _home(app)
    assert 'Teaching examples' in page                   # +examples in the test kit
    assert 'Social' not in page.split('Running in this kit')[1].split('Try the API')[0]   # -social


def test_signed_in_person_sees_who_they_are(app):
    page = _home(app, MEMBER)
    assert 'Signed in as' in page and 'Sign in</a>' not in page


def _tools(page):
    """The 'Your tools' section of the home page ('' when there is none). The navbar menu is not part of it."""
    return page.split('Your tools')[1].split('Try the API')[0] if 'Your tools' in page else ''


@pytest.mark.parametrize('uid,sees,does_not_see', [
    (MEMBER, [], ['User Management', 'Sections', 'Permissions']),
    (STAFF, ['User Management', 'Sections'], ['Permissions']),
    (ADMIN, ['User Management', 'Sections', 'Permissions'], []),
])
def test_tools_follow_the_callers_level(app, uid, sees, does_not_see):
    tools = _tools(_home(app, uid))
    for text in sees:
        assert f'{text}</a>' in tools
    for text in does_not_see:
        assert f'{text}</a>' not in tools


def test_a_tool_the_admin_tightened_disappears_for_staff(app):
    assert 'Sections</a>' in _tools(_home(app, STAFF))
    assert login(app, ADMIN).put('/api/permissions', json={'requests': {'GET /sections/': 'admin'}}).status_code == 200
    tools = _tools(_home(app, STAFF))
    assert 'Sections</a>' not in tools and 'User Management</a>' in tools


def test_degraded_state_is_explained(app, monkeypatch):
    import features
    monkeypatch.setattr(features, 'degraded', lambda: True)
    assert 'cannot read its saved kit settings' in _home(app)


def test_api_examples_use_this_servers_address(app):
    assert 'curl http://localhost/api/kit' in _home(app)
