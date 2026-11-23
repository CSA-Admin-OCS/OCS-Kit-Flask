"""OCS JumpStart, the guide at /jumpstart/: every chapter renders for anyone, the links between them work, and everything
the chapters say about the code is checked against the code, so the guide fails the build the day it stops being true."""
import html
import json
import os
import re

import pytest

import permissions
from conftest import ADMIN, ROOT, login

FOLDER = os.path.join(ROOT, 'templates', 'jumpstart')
NOT_CHAPTERS = {'layout.html', 'macros.html', 'index.html'}


def _registry():
    with open(os.path.join(FOLDER, 'chapters.json'), encoding='utf-8') as fh:
        return json.load(fh)


SLUGS = [c['slug'] for c in _registry()['chapters']]


def _source(slug):
    with open(os.path.join(FOLDER, f'{slug}.html'), encoding='utf-8') as fh:
        return fh.read()


def _all_sources():
    return {slug: _source(slug) for slug in SLUGS}


def _marked(source, kind):
    """The text of every <code class="kind">...</code> in a template, HTML-unescaped."""
    return [html.unescape(text).strip() for text in re.findall(rf'<code class="{kind}">(.*?)</code>', source, re.S)]


def _page(app, url, uid=None):
    r = login(app, uid).get(url)
    assert r.status_code == 200, f'{url} answered {r.status_code}'
    return r.get_data(as_text=True)


# --- the chapters ------------------------------------------------------------------------------------------------

def test_the_contents_and_the_templates_agree():
    data = _registry()
    assert len(SLUGS) == len(set(SLUGS)), 'a chapter is listed twice'
    assert {c['group'] for c in data['chapters']} <= set(data['groups'])
    for slug in SLUGS:
        assert os.path.exists(os.path.join(FOLDER, f'{slug}.html')), f'chapter {slug} has no template'
    on_disk = {name for name in os.listdir(FOLDER) if name.endswith('.html')} - NOT_CHAPTERS
    assert on_disk == {f'{slug}.html' for slug in SLUGS}, 'a template is not listed in chapters.json, or the reverse'


@pytest.mark.parametrize('slug', SLUGS)
def test_every_chapter_renders_for_anyone_with_its_parts(app, slug):
    page = _page(app, f'/jumpstart/{slug}/')
    chapter = next(c for c in _registry()['chapters'] if c['slug'] == slug)
    assert html.escape(chapter['title'], quote=False) in page or chapter['title'] in page
    assert '<title>' in page and 'OCS JumpStart' in page.split('</title>')[0]
    assert 'class="js-short"' in page                                  # the summary box
    assert page.count('class="js-section"') >= 3                       # topic sections
    assert '<details' not in page                                      # topics are always open, not collapsed questions
    assert 'class="js-files"' in page                                  # the files to read


def test_the_contents_page_lists_every_chapter(app):
    page = _page(app, '/jumpstart/')
    for chapter in _registry()['chapters']:
        assert f'/jumpstart/{chapter["slug"]}/' in page


@pytest.mark.parametrize('slug', ['nope', 'index', 'layout', 'macros', '..%2Fmain', 'big-picture%2F..%2Fx', 'chapters.json'])
def test_only_listed_chapters_exist(app, slug):
    assert login(app, None).get(f'/jumpstart/{slug}/').status_code == 404


def test_the_guide_is_public_in_the_permission_file():
    assert permissions.level_of('GET', '/jumpstart/') == 'public'
    assert permissions.level_of('GET', '/jumpstart/<string:chapter>/') == 'public'


def test_first_and_last_chapters_have_one_neighbour_and_the_rest_two(app):
    def neighbours(slug):
        page = _page(app, f'/jumpstart/{slug}/')
        pager = page.split('class="js-pager"')[1].split('</main>')[0]
        return len(re.findall(r'class="btn btn-outline-(?:primary|secondary)"', pager))
    assert neighbours(SLUGS[0]) == 1 and neighbours(SLUGS[-1]) == 1 and neighbours(SLUGS[len(SLUGS) // 2]) == 2


def test_the_links_between_chapters_land_on_chapters(app):
    for slug in SLUGS:
        for target in re.findall(r'href="/jumpstart/([a-z-]+)/"', _page(app, f'/jumpstart/{slug}/')):
            assert target in SLUGS, f'{slug} links to a chapter that does not exist: {target}'


# --- everything it says about the code is true ------------------------------------------------------------------------

def test_every_file_a_chapter_names_exists():
    missing = []
    for slug, source in _all_sources().items():
        for name in _marked(source, 'file'):
            if not os.path.exists(os.path.join(ROOT, name)):
                missing.append(f'{slug}: {name}')
    assert missing == []


def _served(app):
    return {f'{method} {re.sub(r"<[^>]+>", "<x>", rule.rule)}' for rule in app.url_map.iter_rules() if rule.endpoint != 'static'
            for method in rule.methods - {'HEAD', 'OPTIONS'}}


def test_every_request_a_chapter_names_is_one_the_app_serves(app):
    served, wrong = _served(app), []
    for slug, source in _all_sources().items():
        for line in _marked(source, 'route'):
            if re.sub(r'<[^>]+>', '<x>', line) not in served:
                wrong.append(f'{slug}: {line}')
    assert wrong == []


def test_every_command_a_chapter_names_is_real():
    allowed_starts = ('python main.py', 'gunicorn main:app', 'docker compose', 'pip install', 'python -m pytest')
    wrong = []
    for slug, source in _all_sources().items():
        for command in _marked(source, 'cmd'):
            script = re.match(r'python (scripts/\S+\.py)', command)
            module = re.match(r'python -m (features|permissions)((?: --[a-z]+)*)$', command)
            if script:
                ok = os.path.exists(os.path.join(ROOT, script.group(1)))
            elif module:
                flags = set(module.group(2).split())
                ok = flags <= ({'--list', '--check'} if module.group(1) == 'features' else {'--check'})
            else:
                ok = command.startswith(allowed_starts)
            if not ok:
                wrong.append(f'{slug}: {command}')
    assert wrong == []


def _settings_the_system_knows():
    names = set()
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in ('venv', 'tests', '__pycache__', '.git', 'node_modules', 'instance')]
        for name in files:
            if name.endswith('.py'):
                text = open(os.path.join(base, name), encoding='utf-8', errors='ignore').read()
                names |= set(re.findall(r'''os\.(?:environ\.get|getenv)\(\s*['"]([A-Z][A-Z0-9_]+)['"]''', text))
                names |= set(re.findall(r'''os\.environ\[\s*['"]([A-Z][A-Z0-9_]+)['"]''', text))
    names |= set(re.findall(r'^([A-Z][A-Z0-9_]+)=', open(os.path.join(ROOT, '.env.example')).read(), re.M))
    entrypoint = open(os.path.join(ROOT, 'entrypoint.sh')).read()
    names |= {n for n in ('DB_INIT', 'DB_ENDPOINT', 'IS_PRODUCTION', 'SECRET_KEY') if f'${n}' in entrypoint or f'${{{n}' in entrypoint}
    return names


def test_the_settings_chapter_lists_exactly_the_settings_the_system_knows():
    known = _settings_the_system_knows()
    documented = set(_marked(_source('settings'), 'env'))
    assert known - documented == set(), f'settings the code reads but the chapter does not list: {sorted(known - documented)}'
    assert documented - known == set(), f'settings the chapter lists that nothing reads: {sorted(documented - known)}'


def test_no_chapter_invents_a_setting():
    known = _settings_the_system_knows()
    for slug, source in _all_sources().items():
        invented = set(_marked(source, 'env')) - known
        assert invented == set(), f'{slug} names settings that do not exist: {sorted(invented)}'


def test_the_errors_the_permissions_file_chapter_quotes_are_in_the_code():
    code = open(os.path.join(ROOT, 'permissions.py'), encoding='utf-8').read()
    for fragment in ('must be a list of "METHOD /route" entries', 'is not written "METHOD /route"', 'it can be in only one',
                     'is not a level; the lists are', '"api_paths" must be a list of path prefixes such as "/api/"',
                     'is not in any level list', 'is a route but is in no list', 'is in the file but the app has no such route'):
        assert fragment in code, f'permissions.py no longer says: {fragment}'
        assert html.unescape(fragment) in html.unescape(_source('permissions-file')), f'the chapter does not quote: {fragment}'


def test_every_test_file_is_described_in_the_testing_chapter():
    chapter = _source('testing')
    for name in sorted(os.listdir(os.path.join(ROOT, 'tests'))):
        if name.startswith('test_') and name.endswith('.py'):
            assert f'tests/{name}' in chapter, f'tests/{name} is not described in the testing chapter'


# --- the live tables are the app --------------------------------------------------------------------------------------

def test_every_feature_is_in_the_live_tables(app):
    import features
    page = _page(app, '/jumpstart/kits/')
    for fid in features.feature_ids():
        assert f'<code>{fid}</code>' in page, f'feature {fid} is missing from the kits chapter'


def test_the_live_counts_are_the_apps_own(app):
    from api import jumpstart
    with app.test_request_context('/'):
        facts = jumpstart._facts()
    assert facts['requests_total'] == len(permissions.policy()) == len(_served(app))
    assert sum(count for _, count in facts['prefixes']) == facts['requests_total']
    assert sum(f['requests'] for f in facts['features']) == facts['requests_total']
    page = _page(app, '/jumpstart/api/')
    assert f'<th>{facts["requests_total"]}</th>' in page and f'{facts["requests_total"]} requests' in page


def test_the_first_day_chapter_shows_the_real_seeded_usernames(app):
    page = _page(app, '/jumpstart/first-day/')
    for uid in ('admin', 'teacher', 'student', 'editor', 'manager', 'member'):
        assert f'<code>{uid}</code>' in page


# --- how people find it ------------------------------------------------------------------------------------------------

def test_the_navbar_home_page_and_qa_guide_link_to_it(app):
    for url in ('/', '/help/', '/login'):
        assert 'href="/jumpstart/"' in _page(app, url, ADMIN if url != '/login' else None)
    assert 'OCS JumpStart' in _page(app, '/')
    assert 'href="/help/"' in _page(app, '/jumpstart/')


def test_wide_tables_scroll_inside_their_card_and_the_on_badge_is_readable_in_dark_mode():
    css = open(os.path.join(ROOT, 'static', 'css', 'jumpstart.css')).read()
    assert re.search(r'\.js-main\s*\{[^}]*min-width:\s*0', css) and re.search(r'\.js-body\s*\{[^}]*overflow-x:\s*auto', css)
    assert '[data-theme="dark"] .js-badge-on' in css


def test_it_follows_the_theme_and_keeps_its_own_styles_out_of_the_way(app):
    page = _page(app, '/jumpstart/roles/')
    assert 'href="/static/css/jumpstart.css"' in page and 'href="/static/css/theme.css"' in page
    css = open(os.path.join(ROOT, 'static', 'css', 'jumpstart.css')).read()
    assert 'var(--surface)' in css and 'var(--text)' in css
    assert not re.search(r'#(?:fff|ffffff)\b', css.split('pre.js-code')[0], re.I)     # no fixed white to clash with dark mode
