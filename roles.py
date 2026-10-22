"""Roles, read from kits/catalog.json so no Flask code names a role.

Every kit has the same three canonical roles, which the other OCS-Kit backends share:
    admin   runs the site; the only role that can change features
    staff   day-to-day work: content, groups, grading, approvals
    member  regular user; the role new sign-ups get (the kit's signup_role)
Each one is stored in users._role under a fixed Flask name (catalog 'flask.roles', e.g.
staff -> 'Teacher'), so changing KIT never rewrites existing accounts. Only the labels shown
to people ('Teacher' / 'Manager' / 'Editor') and the default seed account uids differ per kit.
"""
import os

import features

ROLE_IDS = ('admin', 'staff', 'member')


def _catalog():
    return features.load_catalog()


def kit_config():
    """The KIT preset's roles/signup_role, or flask.default_kit when KIT is unset."""
    kit = (os.environ.get('KIT') or '').strip().lower()
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


def label(stored_role):
    """What people see for a stored role in this kit: 'Teacher', 'Manager', 'Editor'..."""
    rid = role_id(stored_role)
    return kit_config()['roles'][rid]['label'] if rid else stored_role


def labels():
    """Stored role -> label, for templates."""
    return {flask_role(rid): kit_config()['roles'][rid]['label'] for rid in ROLE_IDS}


def seed_uid(rid):
    """Default uid of the kit's seeded account for a canonical role (env ADMIN_UID etc. win)."""
    return kit_config()['roles'][rid]['seed_uid']


def public_roles():
    """{admin: {label}, staff: {label}, member: {label}} for GET /api/kit."""
    return {rid: {'label': kit_config()['roles'][rid]['label']} for rid in ROLE_IDS}
