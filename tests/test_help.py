"""The Q&A guide (/help/), its links from the home page and navbar, and the Web Security group in the Data menu."""
import os
import re

import features
from conftest import ADMIN, MEMBER, STAFF, login

HELP_SOURCE = os.path.join(os.path.dirname(__file__), '..', 'templates', 'help.html')


def _page(app, url, uid=None):
    r = login(app, uid).get(url)
    assert r.status_code == 200
    return r.get_data(as_text=True)


# --- the guide ---------------------------------------------------------------------------------------------------

def test_the_guide_is_open_to_anyone_and_answers_in_the_kits_role_labels(app):
    page = _page(app, '/help/')
    assert 'How to use the backend' in page and 'id="search"' in page
    for label in ('Admin', 'Teacher', 'Student'):                        # the education kit under test
        assert f'<b>{label}</b>' in page
    assert 'curl -c jar -X POST http://localhost/api/authenticate' in page   # examples use this server's address


def test_every_feature_that_has_flask_code_has_a_section(app):
    """Adding a feature with a blueprint of its own without writing its Q&A fails here."""
    source = open(HELP_SOURCE).read()
    catalog = features.load_catalog()
    for fid in features.feature_ids(catalog):
        if fid != features.CORE and features.flask_spec(fid, catalog)['blueprints']:
            assert f'"{fid}")' in source, f"help.html has no section for feature '{fid}'"


def test_sections_of_features_that_are_off_say_so(app):
    page = _page(app, '/help/')
    social = page.split('id="social"')[1].split('qa-section')[0]
    examples = page.split('id="examples"')[1].split('qa-section')[0]
    assert 'off in this kit' in social            # social is off in the test kit
    assert 'off in this kit' not in examples      # examples is on


def test_every_question_in_the_guide_has_an_answer_that_names_a_real_route(app):
    """Each /api/... or /run/... path written in the guide is a route this backend serves (a typo would mislead)."""
    page = _page(app, '/help/')
    served = {re.sub(r'<[^>]+>', '<x>', rule.rule) for rule in app.url_map.iter_rules()}
    templates = [re.compile(re.escape(rule).replace(re.escape('<x>'), '[^/]+')) for rule in served]
    seen = set(re.findall(r'(?:/api|/run)/[A-Za-z0-9_/\-]+', re.sub(r'&lt;[^&]*&gt;', '<x>', page)))
    unknown = []
    for path in sorted(seen):
        path = path.rstrip('/')
        names_a_route = any(t.fullmatch(path) for t in templates) or any(rule.startswith(path + '/') for rule in served)
        if not names_a_route:
            unknown.append(path)
    assert unknown == [], f'paths in help.html that no route serves: {unknown}'


# --- the links ---------------------------------------------------------------------------------------------------

def test_home_page_and_navbar_link_to_the_guide(app):
    home = _page(app, '/')
    assert 'href="/help/"' in home and 'Learn how to use every feature' in home
    assert '>Q&amp;A</a>' in home


# --- Web Security group in the Data menu -------------------------------------------------------------------------

def test_group_links_puts_a_group_where_its_first_link_was():
    links = [{'label': 'A', 'endpoint': 'a'}, {'label': 'P', 'endpoint': 'p', 'group': 'G'},
             {'label': 'B', 'endpoint': 'b'}, {'label': 'C', 'endpoint': 'c', 'group': 'G'}]
    assert features.group_links(links) == [
        {'label': 'A', 'endpoint': 'a'},
        {'group': 'G', 'links': [links[1], links[3]]},
        {'label': 'B', 'endpoint': 'b'},
    ]
    assert features.group_links([]) == []


def test_permissions_and_cors_are_in_a_web_security_sub_menu(app):
    page = _page(app, '/users/table2', ADMIN)
    menu = page.split('dropdown-submenu')[1].split('</li>\n                            {% ')[0].split('</ul>')[0]
    assert 'Web Security' in menu and 'href="/permissions/"' in menu and 'href="/cors/"' in menu
    outside = page.replace(menu, '')
    assert 'href="/users/table2"' in outside and 'href="/sections/"' in outside       # still plain entries
    assert 'href="/permissions/"' not in outside and 'href="/cors/"' not in outside


def test_the_home_pages_tools_group_web_security_for_admins_only(app):
    def tools(uid):
        page = _page(app, '/', uid)
        return page.split('Your tools')[1].split('Try the API')[0] if 'Your tools' in page else ''
    admin = tools(ADMIN)
    assert 'Web Security' in admin and '>Permissions</a>' in admin and '>CORS</a>' in admin
    for uid in (STAFF, MEMBER):
        assert 'Web Security' not in tools(uid)
