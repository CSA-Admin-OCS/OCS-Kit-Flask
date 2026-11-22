"""Roles, read from kits/catalog.json so no Flask code names a role.

Every kit has the same three canonical roles, which the other OCS-Kit backends share:
    admin   runs the site; the only role that can change features
    staff   day-to-day work: content, groups, grading, approvals
    member  regular user; the role new sign-ups get (the kit's signup_role)
Each one is stored in users._role under a fixed Flask name (catalog 'flask.roles', e.g.
staff -> 'Teacher'), so changing the kit never rewrites existing accounts, whether through KIT
or an admin applying a kit at runtime. Only the labels shown to people ('Teacher' / 'Manager' /
'Editor') and the default seed account uids differ per kit.

Tiers. Every role also has a tier from L1 (strongest) to L4 (weakest). A tier is how far up the permission levels
in permissions.json the role reaches: L1 may make everything (the admin level), L2 the staff level, L3 the member
level, and L4 only what someone who is not signed in may make. The built-in roles start at L1, L2 and L3 (their
place in ROLE_IDS). Admins can add roles on the Roles page (GET /roles/), give each a tier, and change the tier
and label of staff and member; the admin role is always L1. Everything that decides by role (the check before each
request, the decorators, is_admin() and is_staff()) asks tier_of(), so a role added at L2 really has staff powers.
The permissions themselves are still customized request by request on the Permissions page.
"""
import os

import features

ROLE_IDS = ('admin', 'staff', 'member')
SEAT_TIER = {role: number for number, role in enumerate(ROLE_IDS, start=1)}   # where each built-in role starts
TIER_COUNT = len(ROLE_IDS) + 1                                                # L1 .. L4
LOWEST_TIER = TIER_COUNT                                                      # L4: no more than someone not signed in


def _catalog():
    return features.load_catalog()


def kit_config():
    """The active kit's roles/signup_role: the kit an admin applied, else KIT, else
    flask.default_kit. Read on every call, so labels follow a kit switch immediately."""
    kit = features.stored_kit() or (os.environ.get('KIT') or '').strip().lower()
    if kit:
        return _catalog()['kits'][kit]  # an unknown KIT already failed in features.resolve()
    return _catalog()['flask']['default_kit']


def flask_role(role_id):
    """Canonical role id ('admin' | 'staff' | 'member') -> the role name stored on users."""
    return _catalog()['flask']['roles'][role_id]


def role_id(stored_role):
    """Stored Flask role -> canonical id, or None for a role outside the three."""
    for rid, name in _catalog()['flask']['roles'].items():
        if name == stored_role:
            return rid
    return None


def admin_role():
    return flask_role('admin')


def staff_role():
    return flask_role('staff')


def member_role():
    return flask_role('member')


def staff_roles():
    """Roles that do staff work: staff and admin (a tuple, usable with token_required)."""
    return (staff_role(), admin_role())


def signup_role():
    """Stored role for a new sign-up in this kit."""
    return flask_role(kit_config()['signup_role'])


def _saved():
    """{name: {label, tier, custom}} that admins saved on the Roles page. Cached for the request; {} when there is
    no database to ask yet (while modules load). Raises if it cannot be read."""
    from flask import has_app_context
    if not has_app_context():
        return {}
    from model import feature_override, role_setting  # imported late: they need the database
    return feature_override._per_request('_role_settings', role_setting.read_settings)


def forget_saved():
    """Drop this request's copy of the saved roles, after a change has been committed."""
    from flask import g, has_request_context
    if has_request_context():
        g.pop('_role_settings', None)
        g.pop('_roles_unreadable_logged', None)


def _saved_or_nothing():
    """The saved roles, or {} when they cannot be read: a label falls back to the kit's, and a tier is never
    guessed from this (tier_of fails closed on its own)."""
    try:
        return _saved()
    except Exception:
        return {}


def tier_of(stored_role):
    """The tier (1 = L1 strongest .. 4 = L4 weakest) of a stored role. The admin role is always L1. If the saved
    roles cannot be read, any other role counts as L4 until they can, rather than guess. A stored role that is no
    role any more (nothing holds one) counts as a member, as it always did."""
    rid = role_id(stored_role)
    if rid == 'admin':
        return SEAT_TIER['admin']
    try:
        saved = _saved().get(stored_role)
    except Exception:
        from flask import current_app, g, has_request_context
        if not has_request_context() or not g.get('_roles_unreadable_logged'):  # once per request, not per check
            current_app.logger.exception('roles: the saved roles cannot be read, so every role but admin counts as L%s', LOWEST_TIER)
            if has_request_context():
                g._roles_unreadable_logged = True
        return LOWEST_TIER
    if saved:
        return saved['tier']
    return SEAT_TIER[rid or 'member']


def rank(stored_role):
    """How much a stored role may do on the permission levels: 3 for L1 down to 0 for L4 (public, member, staff and
    admin in permissions.json are 0..3)."""
    return TIER_COUNT - tier_of(stored_role)


def at_least(stored_role, seat):
    """Whether the role is as strong as a built-in one ('admin', 'staff' or 'member'): its tier is that or stronger."""
    return tier_of(stored_role) <= SEAT_TIER[seat]


def meets(stored_role, required):
    """Whether a role satisfies a decorator's list of stored role names. Each built-in name stands for its level,
    so ('Teacher', 'Admin') means "staff level or stronger": any role at L2 or L1. A name that is no built-in
    role (a custom one) must match exactly."""
    thresholds = []
    for name in required:
        rid = role_id(name)
        if rid:
            thresholds.append(SEAT_TIER[rid])
        elif name == stored_role:
            return True
    return bool(thresholds) and tier_of(stored_role) <= max(thresholds)


def label(stored_role):
    """What people see for a stored role: the label an admin gave it, else the kit's ('Teacher', 'Manager', 'Editor')
    for a built-in role, else its name."""
    saved = _saved_or_nothing().get(stored_role)
    if saved and saved['label']:
        return saved['label']
    rid = role_id(stored_role)
    return kit_config()['roles'][rid]['label'] if rid else stored_role


def labels():
    """Stored role -> label, for templates: the built-in roles and the ones admins added."""
    names = [flask_role(rid) for rid in ROLE_IDS] + [name for name in custom_names()]
    return {name: label(name) for name in names}


def custom_names():
    """Names of the roles admins added, sorted."""
    return sorted(name for name, row in _saved_or_nothing().items() if row['custom'])


def all_roles():
    """Every role, strongest first: [{name, label, tier, builtin (admin|staff|member or None)}]."""
    roles = [{'name': name, 'label': label(name), 'tier': tier_of(name), 'builtin': role_id(name)}
             for name in [flask_role(rid) for rid in ROLE_IDS] + custom_names()]
    return sorted(roles, key=lambda role: (role['tier'], role['builtin'] is None, role['name']))


def seed_uid(rid):
    """Default uid of the kit's seeded account for a canonical role (env ADMIN_UID etc. win)."""
    return kit_config()['roles'][rid]['seed_uid']


def public_roles():
    """{admin: {label}, staff: {label}, member: {label}} for GET /api/kit."""
    return {rid: {'label': label(flask_role(rid))} for rid in ROLE_IDS}
