"""The Roles page and API for admins: which roles exist, how strong each is, and who has which.

GET    /roles/                       admin page
GET    /api/roles                    admin: every role with its tier, the four tiers, and recent changes
POST   /api/roles                    admin: {"name": "Mentor", "label": "Mentor", "tier": 3} adds a role
PUT    /api/roles/<name>             admin: {"label": "Coach", "tier": 2} changes a role's label and/or tier
DELETE /api/roles/<name>             admin: deletes a role no account holds; for a built-in role, resets it
PUT    /api/user/role                admin: {"uid": "ada", "role": "Mentor"} gives an account a role

A tier runs from L1 (strongest) to L4 (weakest) and says how far up the permission levels the role reaches: L1 the
admin level, L2 staff, L3 member, L4 only what someone who is not signed in may do (see roles.py). A tier is the
default; the Permissions page customizes it request by request. The admin role is always L1, cannot be deleted, and
an admin cannot change their own role, so a change here cannot lock the admins out. These requests are pinned in
permissions.json. A change that cannot be saved answers 503.
"""
import re

from flask import Blueprint, current_app, g, jsonify, render_template, request
from sqlalchemy.exc import SQLAlchemyError

import permissions
import roles
from __init__ import db
from api.authorize import admin_page_required, token_required
from model import permission_override, role_setting
from model.user import User

roles_admin = Blueprint('roles_admin', __name__)

_NAME = re.compile(r'[A-Za-z][A-Za-z0-9 _-]{1,19}')   # 2 to 20 characters: users._role holds 20
MAX_LABEL = 40
TIER_MEANING = {
    1: 'Everything, like the admin role: runs the site and can change every setting.',
    2: 'Staff level: the day-to-day work (sections, classrooms, grading, approvals).',
    3: 'Member level: what any signed-in account may do.',
    4: 'Public level only: no more than someone who is not signed in.',
}


@roles_admin.errorhandler(SQLAlchemyError)
def _not_saved(e):
    db.session.rollback()
    current_app.logger.error(f"roles: a change could not be saved or read: {e!r}")
    return jsonify({'message': 'Roles could not be saved or read. Try again when the database recovers.'}), 503


# --- what the page shows -----------------------------------------------------------------------------------------

def _requests_each_tier_may_make():
    """{tier: how many requests that tier may make}, by the permission levels in force now (the file, with the
    changes admins made on the Permissions page)."""
    changed = permission_override.read_overrides()
    ranks = [permissions.RANK[level if line in permissions.pinned() else changed.get(line, level)]
             for line, level in permissions.policy().items()]
    return {tier: sum(1 for rank in ranks if rank <= roles.TIER_COUNT - tier) for tier in range(1, roles.TIER_COUNT + 1)}


def _payload():
    holding = dict(db.session.query(User._role, db.func.count(User.id)).group_by(User._role).all())
    saved = role_setting.read_settings()
    may_make = _requests_each_tier_may_make()
    level_labels = {permissions.PUBLIC: 'Public', **{r: roles.public_roles()[r]['label'] for r in permissions.ROLE_LEVELS}}
    return {
        'tiers': [{'tier': tier, 'level': permissions.LEVELS[roles.TIER_COUNT - tier],
                   'level_label': level_labels[permissions.LEVELS[roles.TIER_COUNT - tier]],
                   'meaning': TIER_MEANING[tier], 'may_make': may_make[tier], 'of': len(permissions.policy())}
                  for tier in range(1, roles.TIER_COUNT + 1)],
        'roles': [{**role, 'custom': role['builtin'] is None, 'locked': role['builtin'] == 'admin',
                   'changed': role['name'] in saved, 'accounts': holding.get(role['name'], 0)}
                  for role in roles.all_roles()],
        'signup_role': roles.signup_role(),
        'recent_changes': role_setting.recent_changes(),
    }


# --- checking a request ------------------------------------------------------------------------------------------

def _role_named(name):
    return next((role for role in roles.all_roles() if role['name'] == name), None)


def _checked_tier(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= roles.TIER_COUNT:
        raise ValueError(f'tier must be a number from 1 (L1, strongest) to {roles.TIER_COUNT} (L{roles.TIER_COUNT}, weakest)')
    return value


def _checked_label(value):
    """The label, or None for 'use the default'."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str) or len(value.strip()) > MAX_LABEL:
        raise ValueError(f'label must be text of at most {MAX_LABEL} characters')
    return value.strip()


def _checked_new_name(value):
    if not isinstance(value, str) or not _NAME.fullmatch(value.strip()):
        raise ValueError('name must be 2 to 20 characters: a letter first, then letters, digits, spaces, - or _')
    name = value.strip()
    if name.casefold() in {role['name'].casefold() for role in roles.all_roles()}:
        raise ValueError(f"a role named '{name}' already exists")
    return name


def _describe(before, after):
    """'tier L2 to L4; label Manager to Coach' for the log."""
    parts = []
    if before['tier'] != after['tier']:
        parts.append(f"tier L{before['tier']} to L{after['tier']}")
    if before['label'] != after['label']:
        parts.append(f"label {before['label']} to {after['label']}")
    return '; '.join(parts) or 'no change'


# --- the page and the API ------------------------------------------------------------------------------------------

@roles_admin.route('/roles/')
@admin_page_required
def page():
    return render_template('roles.html')


@roles_admin.route('/api/roles', methods=['GET'])
@token_required(roles.admin_role())
def get_roles():
    return jsonify(_payload())


@roles_admin.route('/api/roles', methods=['POST'])
@token_required(roles.admin_role())
def post_role():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'message': 'Body must be {"name": "Mentor", "label": "Mentor", "tier": 3}'}), 400
    try:
        name = _checked_new_name(body.get('name'))
        label = _checked_label(body.get('label'))
        tier = _checked_tier(body.get('tier'))
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    actor = g.current_user.uid
    role_setting.save(name, label, tier, custom=True, actor=actor)
    role_setting.log('create', f"{name} at L{tier}", actor)
    db.session.commit()
    roles.forget_saved()
    current_app.logger.warning(f"roles: {actor} added {name} at L{tier}")
    return jsonify(_payload()), 201


@roles_admin.route('/api/roles/<string:role_name>', methods=['PUT'])
@token_required(roles.admin_role())
def put_role(role_name):
    role = _role_named(role_name)
    if role is None:
        return jsonify({'message': f"There is no role '{role_name}'"}), 404
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not ({'label', 'tier'} & set(body)):
        return jsonify({'message': 'Body must have a "label" and/or a "tier"'}), 400
    try:
        tier = _checked_tier(body['tier']) if 'tier' in body else role['tier']
        saved = role_setting.read_settings().get(role_name)
        stored_label = saved['label'] if saved else None
        label = _checked_label(body['label']) if 'label' in body else stored_label
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    if role['builtin'] == 'admin' and tier != roles.SEAT_TIER['admin']:
        return jsonify({'message': 'The admin role is always L1; give another role the tier you want instead'}), 400
    actor = g.current_user.uid
    before = {'tier': role['tier'], 'label': role['label']}
    default_tier = roles.SEAT_TIER[role['builtin']] if role['builtin'] else None
    if role['builtin'] and label is None and tier == default_tier:
        role_setting.remove(role_name)     # back to the built-in tier and the kit's label: nothing to store
    else:
        role_setting.save(role_name, label, tier, custom=role['builtin'] is None, actor=actor)
    after = {'tier': tier, 'label': label or (roles.kit_config()['roles'][role['builtin']]['label'] if role['builtin'] else role_name)}
    role_setting.log('update', f"{role_name}: {_describe(before, after)}", actor)
    db.session.commit()
    roles.forget_saved()
    current_app.logger.warning(f"roles: {actor} changed {role_name}: {_describe(before, after)}")
    return jsonify(_payload())


@roles_admin.route('/api/roles/<string:role_name>', methods=['DELETE'])
@token_required(roles.admin_role())
def delete_role(role_name):
    role = _role_named(role_name)
    if role is None:
        return jsonify({'message': f"There is no role '{role_name}'"}), 404
    actor = g.current_user.uid
    if role['builtin']:   # a built-in role cannot go away; this puts back its tier and label
        if role_setting.remove(role_name):
            role_setting.log('reset', f"{role_name}: back to the built-in tier and label", actor)
            db.session.commit()
            roles.forget_saved()
        return jsonify(_payload())
    holders = User.query.filter_by(_role=role_name).count()
    if holders:
        return jsonify({'message': f"{holders} account{'s' if holders > 1 else ''} still {'has' if holders == 1 else 'have'} "
                                   f"the role '{role_name}'. Give them another role first."}), 409
    role_setting.remove(role_name)
    role_setting.log('delete', role_name, actor)
    db.session.commit()
    roles.forget_saved()
    current_app.logger.warning(f"roles: {actor} deleted {role_name}")
    return jsonify(_payload())


@roles_admin.route('/api/user/role', methods=['PUT'])
@token_required(roles.admin_role())
def put_user_role():
    body = request.get_json(silent=True)
    uid, role_name = (body.get('uid'), body.get('role')) if isinstance(body, dict) else (None, None)
    if not isinstance(uid, str) or not isinstance(role_name, str):
        return jsonify({'message': 'Body must be {"uid": "ada", "role": "Mentor"}'}), 400
    user = User.query.filter_by(_uid=uid).first()
    if user is None:
        return jsonify({'message': f'User {uid} not found'}), 404
    if _role_named(role_name) is None:
        return jsonify({'message': f"There is no role '{role_name}'"}), 400
    if user.id == g.current_user.id:
        return jsonify({'message': 'You cannot change your own role; ask another admin.'}), 400
    before = user.role
    if before != role_name:
        user.role = role_name
        role_setting.log('assign', f"{uid}: {before} to {role_name}", g.current_user.uid)
        db.session.commit()
        current_app.logger.warning(f"roles: {g.current_user.uid} gave {uid} the role {role_name} (was {before})")
    return jsonify({'uid': uid, 'role': user.role, 'role_label': user.role_label})
