"""The OCS-in-a-Kit Backend logo: the wordmark on the home and login pages (one logo for light pages and one for dark,
in a banner that takes its card's colour), the flask mark as the navbar logo until an organization sets its own, and the
favicon on every page."""
import os
import struct

import pytest

from conftest import ADMIN, ROOT, login

ASSETS = os.path.join(ROOT, 'static', 'assets')
LOGO, LOGO_DARK, MARK, FAVICON = 'ocs_backend_logo.png', 'ocs_backend_logo_dark.png', 'ocs_backend_mark.png', 'favicon.png'


def _png_size(name):
    with open(os.path.join(ASSETS, name), 'rb') as fh:
        head = fh.read(24)
    assert head[:8] == b'\x89PNG\r\n\x1a\n', f'{name} is not a PNG'
    return struct.unpack('>II', head[16:24])


def test_the_logo_files_are_pngs_of_a_web_friendly_size():
    width, height = _png_size(LOGO)
    assert width == 1100 and 300 < height < 600 and os.path.getsize(os.path.join(ASSETS, LOGO)) < 600_000
    assert _png_size(LOGO_DARK)[0] == 1100 and os.path.getsize(os.path.join(ASSETS, LOGO_DARK)) < 600_000
    assert _png_size(MARK) == (256, 256)
    assert _png_size(FAVICON) == (64, 64)


@pytest.mark.parametrize('name', [LOGO, LOGO_DARK, MARK, FAVICON])
def test_the_logo_files_have_a_transparent_background(name):
    """PNG color type 6 is RGBA: the black of the original is gone, so the logo sits on any page."""
    with open(os.path.join(ASSETS, name), 'rb') as fh:
        header = fh.read(26)
    assert header[25] == 6, f'{name} has no alpha channel'


@pytest.mark.parametrize('url', ['/', '/login'])
def test_the_banner_has_a_logo_for_each_theme_and_no_colour_of_its_own(app, url):
    """A fixed white or black banner clashes with the card in the other theme: the colour comes from theme.css."""
    page = login(app, None).get(url).get_data(as_text=True)
    banner = page.split('class="brand-banner')[1].split('</div>')[0]
    assert f'/static/assets/{LOGO}' in banner and 'brand-logo-light' in banner
    assert f'/static/assets/{LOGO_DARK}' in banner and 'brand-logo-dark' in banner
    assert 'background' not in banner and '#fff' not in banner and '#000' not in banner


def test_the_stylesheet_gives_the_banner_the_cards_colour_and_shows_one_logo_per_theme():
    css = open(os.path.join(ROOT, 'static', 'css', 'theme.css')).read()
    assert 'brand-banner { background-color: var(--surface)' in css
    assert '.brand-logo-dark { display: none; }' in css
    assert '[data-theme="dark"] .brand-logo-light { display: none; }' in css
    assert '[data-theme="dark"] .brand-logo-dark { display: inline-block; }' in css


@pytest.mark.parametrize('url', ['/', '/login'])
def test_the_home_and_login_pages_show_the_wordmark(app, url):
    page = login(app, None).get(url).get_data(as_text=True)
    assert f'/static/assets/{LOGO}' in page and f'/static/assets/{LOGO_DARK}' in page


def test_the_files_the_pages_point_at_are_served(app):
    client = login(app, None)
    for name in (LOGO, LOGO_DARK, MARK, FAVICON):
        r = client.get(f'/static/assets/{name}')
        assert r.status_code == 200 and r.mimetype == 'image/png'


def test_the_navbar_logo_is_the_flask_mark_until_an_organization_sets_its_own(app, monkeypatch):
    assert app.config['ORG_LOGO_URL'] == f'/static/assets/{MARK}'
    assert f'src="/static/assets/{MARK}"' in login(app, ADMIN).get('/').get_data(as_text=True)
    monkeypatch.setitem(app.config, 'ORG_LOGO_URL', '/static/assets/my-org.svg')
    page = login(app, ADMIN).get('/').get_data(as_text=True)
    assert 'src="/static/assets/my-org.svg"' in page and f'src="/static/assets/{MARK}"' not in page


def test_the_web_logos_can_be_remade_from_the_source_in_branding():
    for source in ('ocs-backend-logo.png', 'ocs-backend-logo-dark.png'):
        assert os.path.exists(os.path.join(ROOT, 'branding', source))
    script = open(os.path.join(ROOT, 'scripts', 'make_logo_assets.py')).read()
    for name in (LOGO, LOGO_DARK, MARK, FAVICON):
        assert name in script
    assert 'branding/' in open(os.path.join(ROOT, '.dockerignore')).read()    # the 1 MB source stays out of the image


def test_the_readme_shows_the_logo_and_the_file_exists():
    readme = open(os.path.join(ROOT, 'README.md')).read()
    assert f'static/assets/{LOGO}' in readme and os.path.exists(os.path.join(ASSETS, LOGO))
    assert f'static/assets/{LOGO_DARK}' in readme and 'prefers-color-scheme: dark' in readme   # GitHub's dark theme gets the dark logo
