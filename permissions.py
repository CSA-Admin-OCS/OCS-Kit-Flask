"""Who may make each request, read from permissions.json.

permissions.json is one flat list per level. Every request the app answers is written "METHOD route" (the route
as Flask knows it, e.g. "GET /api/id" or "DELETE /api/classrooms/<int:id>") and sits in exactly one list:

    public       anyone, signed in or not, on purpose (home page, login, sign-up)
    member       any signed-in account
    staff        staff and admin
    admin        admin only
    unreviewed   open to anyone today, and nobody has decided it should be. It behaves like public. It is a
                 to-do list: move each entry to the level it belongs at. `python -m permissions` prints it.

The levels rise in trust, so a role may make everything at or below its own level. The three role levels are the
canonical role ids in roles.py; their stored names and labels differ per kit and never appear here.

A request in no list is refused for everyone, with a message that says what to add. So a new route is closed
until someone decides who may use it, never open by accident. `python -m permissions --check` and the tests fail
on a route that is missing from the file.

The file also says, under "api_paths", which paths are APIs. A caller with no login gets a 401 answer on those
and is sent to the login page everywhere else (the admin pages).

An admin can change the level of one request from the Permissions page (GET /permissions/). That change is stored
in the database (model/permission_override.py) and wins over the file until it is cleared. The requests listed under
"pinned" cannot be changed there, so nobody can lock the admins or everyone out.

This file decides who gets as far as the route. A rule about one record (an account may change only its own
profile) is still written in the route, where the record is known.

    python -m permissions            counts per level, and the unreviewed list
    python -m permissions --check    the file against the app's routes (exit 1 on a problem)
"""
import json
import os
import re
import sys

from flask import abort, current_app, request
from flask_login import current_user

import roles

PUBLIC = 'public'
UNREVIEWED = 'unreviewed'
ROLE_LEVELS = tuple(reversed(roles.ROLE_IDS))  # lowest trust first: member, staff, admin
LEVELS = (PUBLIC,) + ROLE_LEVELS
LISTS = LEVELS + (UNREVIEWED,)
SETTINGS = ('api_paths', 'pinned')
LOWEST_ROLE = ROLE_LEVELS[0]  # what a stored role outside the kit's three counts as
RANK = {PUBLIC: 0, UNREVIEWED: 0}
RANK.update({role: number for number, role in enumerate(ROLE_LEVELS, start=1)})

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'permissions.json')
_REQUEST = re.compile(r'(GET|POST|PUT|PATCH|DELETE) /\S*')
_loaded = None


def parse(data):
    """(policy, api_paths, pinned) from the file's data: {request: level}, the path prefixes that are APIs, and the
    requests an admin cannot change. Raises ValueError, naming the entry, for anything unclear."""
    if not isinstance(data, dict):
        raise ValueError('permissions.json: expected an object with one list per level')
    for name in data:
        if name not in LISTS + SETTINGS:
            raise ValueError(f'permissions.json: "{name}" is not a level; the lists are {", ".join(LISTS)}')
    api_paths = data.get('api_paths', [])
    if not isinstance(api_paths, list) or not all(isinstance(path, str) and path.startswith('/') for path in api_paths):
        raise ValueError('permissions.json: "api_paths" must be a list of path prefixes such as "/api/"')
    policy = {}
    for name in LISTS:
        entries = data.get(name, [])
        if not isinstance(entries, list):
            raise ValueError(f'permissions.json: "{name}" must be a list of "METHOD /route" entries')
        for entry in entries:
            if not (isinstance(entry, str) and _REQUEST.fullmatch(entry)):
                raise ValueError(f'permissions.json: {entry!r} in "{name}" is not written "METHOD /route"')
            if entry in policy:
                raise ValueError(f'permissions.json: {entry} is in "{policy[entry]}" and in "{name}"; it can be in only one')
            policy[entry] = name
    pinned = data.get('pinned', [])
    if not isinstance(pinned, list):
        raise ValueError('permissions.json: "pinned" must be a list of "METHOD /route" entries')
    for entry in pinned:
        if entry not in policy:
            raise ValueError(f'permissions.json: {entry!r} in "pinned" is not in any level list')
    return policy, tuple(api_paths), frozenset(pinned)


def _load():
    """Read the file once. A bad file stops the app at startup, not at the first request."""
    global _loaded
    if _loaded is None:
        with open(FILE) as fh:
            _loaded = parse(json.load(fh))
    return _loaded


def policy():
    """{request: level}"""
    return _load()[0]


def api_paths():
    """Path prefixes whose requests are APIs."""
    return _load()[1]


def pinned():
    """Requests an admin cannot change from the Permissions page."""
    return _load()[2]


def request_line(method, rule):
    """How a request is written in the file: "METHOD /route". HEAD is answered like GET."""
    return f'{"GET" if method == "HEAD" else method} {rule}'


def level_of(method, rule):
    """The level a request is listed at in the file, or None when it is in no list."""
    return policy().get(request_line(method, rule))


def effective_level(method, rule):
    """The level that applies now: the one an admin set, else the file's; None when the request is in no list.
    Raises when the admin's changes cannot be read, so the caller can refuse instead of guess."""
    line = request_line(method, rule)
    file_level = policy().get(line)
    if file_level is None or line in pinned():
        return file_level
    from model import permission_override  # imported late: it needs the database
    return permission_override.read_override(line) or file_level


def caller_rank(user):
    """How much a caller is trusted: 0 for no account, else 1 for a member up to the highest role. A stored role
    outside the kit's three counts as the lowest role, as it always did."""
    if user is None:
        return 0
    return RANK[roles.role_id(user.role) or LOWEST_ROLE]


ERROR_NAMES = {401: 'Unauthorized', 403: 'Forbidden', 503: 'Service Unavailable'}


def may_make(method, rule, user):
    """Whether a caller (a user, or None for no account) may make a request, by the level that applies now.
    False when the request is unlisted or the stored levels cannot be read."""
    try:
        level = effective_level(method, rule)
    except Exception:
        return False
    return level is not None and caller_rank(user) >= RANK[level]


def _refuse(message, status):
    return {'message': message, 'data': None, 'error': ERROR_NAMES[status]}, status


def _unlisted(rule):
    current_app.logger.warning('permissions: %s %s is not in permissions.json, so it is refused', request.method, rule.rule)
    return _refuse(f'{request.method} {rule.rule} is not in permissions.json, so nobody may make it. '
                   f'Add it under one of: {", ".join(LEVELS)}.', 403)


def _api_caller_answer(level):
    """For an API request: None when the caller may make it, else the answer to give. Session or JWT."""
    from api.authorize import identify  # imported late: it needs the User model
    user, refusal = identify()
    if refusal:
        return refusal
    may_make = caller_rank(user) >= RANK[level]
    if may_make:
        return None
    return _refuse(f'Insufficient permissions. This needs the {level} level or above.', 403)


def _page_caller_answer(level):
    """For a server-rendered page: None when the caller may make the request, else the answer. Session only."""
    user = current_user if current_user.is_authenticated else None
    if user is None:
        return current_app.login_manager.unauthorized()  # sent to the login page
    may_make = caller_rank(user) >= RANK[level]
    if may_make:
        return None
    abort(403)


def check_access():
    """Before every request: refuse it here unless the caller's level is enough. Returns None to let it go on."""
    rule = request.url_rule
    nothing_to_guard = request.method == 'OPTIONS' or rule is None or rule.endpoint == 'static'
    if nothing_to_guard:
        return None  # a CORS preflight carries no login; no route matched; static files are public
    try:
        level = effective_level(request.method, rule.rule)
    except Exception:
        current_app.logger.exception('permissions: the levels an admin set cannot be read')
        return _refuse('Permissions cannot be read right now. Try again shortly.', 503)
    if level is None:
        return _unlisted(rule)
    open_to_anyone = RANK[level] == 0
    if open_to_anyone:
        return None
    if rule.rule.startswith(api_paths()):
        return _api_caller_answer(level)
    return _page_caller_answer(level)


def routes(app):
    return {f'{method} {rule.rule}' for rule in app.url_map.iter_rules() if rule.endpoint != 'static'
            for method in rule.methods - {'HEAD', 'OPTIONS'}}


def unlisted(app):
    """Requests the app answers that are in no list."""
    return sorted(routes(app) - set(policy()))


def stale(app):
    """Entries in the file that name no route of the app."""
    return sorted(set(policy()) - routes(app))


def problems(app):
    """What is wrong between the file and the app's routes, as sentences. Empty when they agree."""
    found = [f'{r} is a route but is in no list' for r in unlisted(app)]
    return found + [f'{r} is in the file but the app has no such route' for r in stale(app)]


def init_app(app):
    """Put the check before every request. Call it after the routes and the feature gate are registered, so a
    disabled feature still answers 404 first."""
    _load()  # fail at startup on a bad file
    app.before_request(check_access)
    found = problems(app)
    if found:
        app.logger.warning('permissions.json does not match the routes (run: python -m permissions --check):\n  %s',
                           '\n  '.join(found))


def _cli(argv):
    from main import app  # the routes exist once the app is built
    if '--check' in argv:
        found = problems(app)
        for line in found:
            print(line)
        print(f'{len(policy())} requests listed, {len(routes(app))} routes: ' + ('OK' if not found else f'{len(found)} problem(s)'))
        return 1 if found else 0
    print('Requests per level:')
    for name in LISTS:
        print(f'  {name:<11}{sum(1 for level in policy().values() if level == name)}')
    unreviewed = sorted(r for r, level in policy().items() if level == UNREVIEWED)
    if unreviewed:
        print('\nUnreviewed: open to anyone today. Move each to the level it belongs at in permissions.json:')
        for r in unreviewed:
            print(f'  {r}')
    return 0


if __name__ == '__main__':
    sys.exit(_cli(sys.argv[1:]))
