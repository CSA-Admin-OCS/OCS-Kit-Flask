"""Cross-origin requests (CORS): which websites may call this backend from a browser, and with cookies.

The allowed origins are one list, and an admin can change it from the CORS page (GET /cors/) with no restart:
    the list an admin saved there, if there is one (model/cors_setting.py), else
    CORS_ORIGINS in .env, else the local development frontends.
"Reset" on the page forgets the saved list, so .env decides again.

An origin is written as the browser sends it: scheme, host and optional port, with no path or trailing slash
("https://pages.example.org", "http://localhost:4500"). The page only saves origins of that exact form. A
CORS_ORIGINS entry in .env may still be a pattern (a regular expression, or "*" for every site), as it always
could be; that is checked the same way it was, and the page shows it flagged.

The answers are what Flask-CORS sent before this module replaced it, with one change: a request with no Origin
header, which a browser sends only for same-site requests, no longer gets an Access-Control-Allow-Origin header.
The list is read on every cross-origin request, so a change applies at once in every worker. If the saved list
cannot be read, no cross-origin request is allowed until it can.
"""
import re
from urllib.parse import urlsplit

from flask import current_app, request

ALLOWED_METHODS = ('GET', 'POST', 'PUT', 'DELETE', 'OPTIONS')
MAX_ORIGINS = 100
_PATTERN_HINTS = frozenset(']^*)[\\(?$')   # a CORS_ORIGINS entry with one of these is a pattern, not a literal origin
_LOCAL_HOSTS = ('localhost', '127.0.0.1', '[::1]', '::1')


# --- what an origin may look like ----------------------------------------------------------------

def normalize_origin(value):
    """The origin in its one written form (lower case), or ValueError with a message for the admin."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Each origin must be text like https://pages.example.org')
    text = value.strip()
    parts = urlsplit(text)
    if parts.scheme not in ('http', 'https') or not parts.netloc:
        if any(char in text for char in _PATTERN_HINTS):
            raise ValueError(f"'{text}': write the exact origin; patterns and * cannot be saved here")
        raise ValueError(f"'{text}': start with http:// or https://, then the host, like https://pages.example.org")
    if parts.path or parts.query or parts.fragment or '@' in parts.netloc:
        raise ValueError(f"'{text}': an origin is only scheme, host and port; remove the path, trailing slash or login")
    host = parts.netloc[1:parts.netloc.index(']')] if parts.netloc.startswith('[') and ']' in parts.netloc else parts.netloc
    if any(char in host for char in _PATTERN_HINTS):  # the brackets of an IPv6 host are not pattern characters
        raise ValueError(f"'{text}': write the exact origin; patterns and * cannot be saved here")
    try:
        parts.port  # raises for a port that is not a number in range
    except ValueError:
        raise ValueError(f"'{text}': the port must be a number") from None
    return f'{parts.scheme}://{parts.netloc}'.lower()


def normalize_origins(values):
    """A list of origins, each normalized, without repeats. ValueError names the first problem."""
    if not isinstance(values, list):
        raise ValueError('Body must be {"origins": ["https://pages.example.org", ...]}')
    origins = []
    for value in values:
        origin = normalize_origin(value)
        if origin not in origins:
            origins.append(origin)
    if len(origins) > MAX_ORIGINS:
        raise ValueError(f'At most {MAX_ORIGINS} origins')
    return origins


def is_pattern(entry):
    return not _PATTERN_HINTS.isdisjoint(entry)


def check_defaults(entries):
    """The .env list: a pattern that is not a valid regular expression stops the app at startup."""
    for entry in entries:
        if is_pattern(entry):
            try:
                re.compile('.*' if entry == '*' else entry)
            except re.error as error:
                raise ValueError(f'CORS_ORIGINS: {entry!r} is not a valid pattern: {error}') from None


def warning_for(entry):
    """A short caution for the page about an entry, or None."""
    if is_pattern(entry):
        return 'every site' if entry == '*' else 'pattern: matches by regular expression'
    parts = urlsplit(entry)
    if parts.scheme == 'http' and (parts.hostname or '') not in _LOCAL_HOSTS:
        return 'not https: cookies and passwords cross this connection unencrypted'
    return None


# --- the list in force -----------------------------------------------------------------------------

def default_entries():
    """The .env list (CORS_ORIGINS), or the local development frontends."""
    return list(current_app.config['CORS_ORIGINS'])


def default_source():
    return 'env' if current_app.config['CORS_ORIGINS_FROM_ENV'] else 'default'


def stored_entries():
    """The list an admin saved, or None. Raises if it cannot be read."""
    from model import cors_setting  # imported late: it needs the database
    return cors_setting.read_origins()


def effective_entries():
    """The origins allowed now: the saved list if there is one, else the default. Raises if unreadable."""
    stored = stored_entries()
    return default_entries() if stored is None else stored


def source():
    """Where the list in force comes from: 'admin', 'env' or 'default'."""
    return 'admin' if stored_entries() is not None else default_source()


def _matches(origin, entry):
    if is_pattern(entry):
        return re.match('.*' if entry == '*' else entry, origin, re.IGNORECASE) is not None
    return origin.casefold() == entry.casefold()


def allows(origin, entries):
    return any(_matches(origin, entry) for entry in entries)


# --- the headers -------------------------------------------------------------------------------------

def install(app, get_entries):
    """Add the CORS headers to every response whose request came from an allowed origin.
    get_entries() is called per cross-origin request and returns the origins in force."""

    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get('Origin')
        if not origin:
            return response  # not a cross-origin request
        try:
            allowed = allows(origin, get_entries())
        except Exception:
            current_app.logger.exception('cors: the allowed origins cannot be read, so no origin is allowed')
            return response
        if not allowed:
            return response
        headers = response.headers
        headers['Access-Control-Allow-Origin'] = origin
        headers['Access-Control-Allow-Credentials'] = 'true'
        response.vary.add('Origin')
        if request.method == 'OPTIONS' and 'Access-Control-Request-Method' in request.headers:  # a preflight
            headers['Access-Control-Allow-Methods'] = ', '.join(sorted(ALLOWED_METHODS))
            requested = request.headers.get('Access-Control-Request-Headers', '')
            names = sorted(name.strip() for name in requested.split(',') if name.strip())
            if names:
                headers['Access-Control-Allow-Headers'] = ', '.join(names)
        return response


def init_app(app):
    """Serve CORS from the list in force. Call it once the app and its database settings exist."""
    check_defaults(app.config['CORS_ORIGINS'])
    install(app, effective_entries)
