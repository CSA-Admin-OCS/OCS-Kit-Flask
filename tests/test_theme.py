"""Light and dark mode: the sun/moon switch in the navbar, the theme chosen before the page paints, and a stylesheet
whose colours are readable in both themes. (The behaviour in a browser was checked by driving the pages.)"""
import os
import re

import pytest

from conftest import ADMIN, ROOT, login

CSS = os.path.join(ROOT, 'static', 'css', 'theme.css')
PAGES = ['/', '/login', '/help/', '/users/table2', '/sections/', '/permissions/', '/roles/', '/cors/']


def _css():
    return open(CSS).read()


# --- the switch and the early theme ------------------------------------------------------------------------------

@pytest.mark.parametrize('url', PAGES)
def test_every_page_has_the_switch_the_stylesheet_and_the_early_theme(app, url):
    page = login(app, ADMIN).get(url).get_data(as_text=True)
    assert 'id="themeSwitch"' in page and 'aria-label="Dark mode"' in page and 'role="switch"' in page
    assert 'fa-sun' in page and 'fa-moon' in page                                   # sun on the left, moon on the right
    assert 'href="/static/css/theme.css"' in page
    head = page.split('</head>')[0]
    assert 'data-theme' in head and "localStorage.getItem(\"theme\")" in head      # chosen before the body is painted
    assert 'prefers-color-scheme: dark' in head                                    # the system setting is the default
    assert head.index('setAttribute("data-theme"') < head.index('href="/static/css/theme.css"')   # set before the stylesheet loads


def test_the_old_do_nothing_toggle_is_gone(app):
    page = login(app, ADMIN).get('/').get_data(as_text=True)
    assert 'darkSwitch' not in page and 'darkFunction' not in page


def test_the_animated_background_is_started_again_with_the_themes_colours(app):
    page = login(app, ADMIN).get('/').get_data(as_text=True)
    assert 'window.startVanta' in page and 'light:' in page and 'dark:' in page
    assert 'window.startVanta(theme)' in page                                      # called by the switch


def test_pages_that_sit_straight_on_the_background_use_the_themes_text_colour(app):
    page = login(app, None).get('/login').get_data(as_text=True)
    assert 'page-text' in page and 'border-primary text-light' not in page


# --- the stylesheet --------------------------------------------------------------------------------------------------

def test_the_stylesheet_is_served(app):
    r = login(app, None).get('/static/css/theme.css')
    assert r.status_code == 200 and r.mimetype == 'text/css'
    assert '[data-theme="dark"]' in r.get_data(as_text=True)


def test_the_page_colour_is_on_html_so_the_animated_background_is_not_covered():
    """An opaque <body> hides the animation canvas that sits behind the page."""
    css = _css()
    assert re.search(r'html\s*\{[^}]*background-color:\s*var\(--page-bg\)', css)
    assert re.search(r'body\s*\{[^}]*background-color:\s*transparent', css)


def _variables(theme):
    css = _css()
    block = re.search(r':root\s*\{(.*?)\}' if theme == 'light' else r'\[data-theme="dark"\]\s*\{(.*?)\}', css, re.S).group(1)
    return dict(re.findall(r'--([a-z0-9-]+):\s*([^;]+);', block))


def _rgb(value, over=None):
    value = value.strip()
    if value.startswith('#'):
        digits = value[1:] if len(value) == 7 else ''.join(c * 2 for c in value[1:])    # #rrggbb or #rgb
        return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))
    channels = [float(x) for x in re.findall(r'[\d.]+', value)]
    r, g, b, a = (channels + [1])[:4]
    under = over or (255, 255, 255)
    return tuple(c * a + u * (1 - a) for c, u in zip((r, g, b), under))


def _contrast(foreground, background):
    def luminance(rgb):
        parts = [(c / 255) / 12.92 if c / 255 <= .03928 else (((c / 255) + .055) / 1.055) ** 2.4 for c in rgb]
        return .2126 * parts[0] + .7152 * parts[1] + .0722 * parts[2]
    high, low = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (high + .05) / (low + .05)


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_every_text_colour_is_readable_on_the_colours_it_sits_on(theme):
    """WCAG AA: 4.5 to 1 for body text."""
    v = _variables(theme)
    colour = {name: _rgb(value) for name, value in v.items()}
    colour['nav-text'] = _rgb(v['nav-text'], over=_rgb(v['nav-bg']))     # translucent: judge it on the navbar colour
    surfaces = ['page-bg', 'surface', 'surface-2', 'input-bg']
    checks = [('text', s) for s in surfaces] + [('muted', s) for s in ('page-bg', 'surface', 'surface-2')] \
        + [('link', s) for s in ('page-bg', 'surface')] + [('code', 'surface'), ('text', 'nav-bg'), ('nav-text', 'nav-bg'), ('nav-icon', 'nav-bg')]
    too_faint = [f'{fg} on {bg}: {_contrast(colour[fg], colour[bg]):.2f}' for fg, bg in checks if _contrast(colour[fg], colour[bg]) < 4.5]
    assert too_faint == []


def test_both_themes_define_the_same_variables():
    assert set(_variables('light')) == set(_variables('dark'))
