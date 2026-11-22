"""The Permissions page and API for admins: see who may make each request, and change one request's level.

GET /permissions/       admin page
GET /api/permissions    admin: every request with its level, grouped by feature, and the recent changes
PUT /api/permissions    admin: {"requests": {"GET /api/study": "member", "POST /api/jokes/create/<string:joke>": null}}
                        sets a level, or null to go back to permissions.json

A change is stored in the database and applies on the next request, with no restart (model/permission_override.py).
Requests under "pinned" in permissions.json cannot be changed. Only admins reach any of this, and the page's own
requests are pinned, so a change cannot lock the admins out. A change that cannot be saved answers 503.
"""
from flask import Blueprint, current_app, g, jsonify, render_template, request
from sqlalchemy.exc import SQLAlchemyError

import features
import permissions
import roles
from __init__ import db
from api.authorize import admin_page_required, token_required
from model import permission_override

permissions_admin = Blueprint('permissions_admin', __name__)


@permissions_admin.errorhandler(SQLAlchemyError)
def _not_saved(e):
    db.session.rollback()
    current_app.logger.error(f"permissions: a change could not be saved or read: {e!r}")
    return jsonify({'message': 'Permissions could not be saved or read. Try again when the database recovers.'}), 503


def _feature_of(endpoint):
    """The feature that owns a route's blueprint; app-level pages (login, user table) belong to core."""
    owners = features.features_of_blueprint(endpoint.rpartition('.')[0])
    return next((fid for fid in features.feature_ids() if fid in owners), features.CORE)


def _payload():
    stored = permission_override.read_overrides()
    enabled = features.enabled_features()
    catalog = features.load_catalog()['features']
    rows = []
    for rule in current_app.url_map.iter_rules():
        if rule.endpoint == 'static':
            continue
        for method in sorted(rule.methods - {'HEAD', 'OPTIONS'}):
            line = permissions.request_line(method, rule.rule)
            file_level = permissions.policy().get(line)
            rows.append({'request': line, 'method': method, 'route': rule.rule, 'feature': _feature_of(rule.endpoint),
                         'file_level': file_level, 'level': stored.get(line, file_level),
                         'overridden': line in stored, 'pinned': line in permissions.pinned()})
    order = features.feature_ids()
    rows.sort(key=lambda row: (order.index(row['feature']), row['route'], row['method']))
    return {
        'levels': list(permissions.LEVELS),
        # what people call each level in this kit: the kit's role labels, which the file never names
        'level_labels': {permissions.PUBLIC: f'Public (L{roles.LOWEST_TIER})',
                         **{role: f"{roles.public_roles()[role]['label']} (L{roles.SEAT_TIER[role]})"
                            for role in permissions.ROLE_LEVELS}},
        'features': [{'id': fid, 'name': catalog[fid]['name'], 'enabled': fid in enabled} for fid in order],
        'requests': rows,
        'recent_changes': permission_override.recent_changes(),
    }


def _checked_changes(body):
    """{request: level or None} from the body, or ValueError with a message for the client."""
    changes = body.get('requests') if isinstance(body, dict) else None
    if not isinstance(changes, dict) or not changes:
        raise ValueError('Body must be {"requests": {"METHOD /route": "<level>" or null, ...}}')
    known = permissions.routes(current_app)
    for line, level in changes.items():
        if line not in known or line not in permissions.policy():
            raise ValueError(f"'{line}' is not a request this app answers")
        if line in permissions.pinned():
            raise ValueError(f"'{line}' is pinned and cannot be changed here")
        if level is not None and level not in permissions.LEVELS:
            raise ValueError(f"'{line}': level must be one of {', '.join(permissions.LEVELS)}, or null")
    # choosing the level the file already gives is the same as clearing the change
    return {line: (None if level == permissions.policy()[line] else level) for line, level in changes.items()}


@permissions_admin.route('/permissions/')
@admin_page_required
def page():
    return render_template('permissions.html')


@permissions_admin.route('/api/permissions', methods=['GET'])
@token_required(roles.admin_role())
def get_permissions():
    return jsonify(_payload())


@permissions_admin.route('/api/permissions', methods=['PUT'])
@token_required(roles.admin_role())
def put_permissions():
    try:
        changes = _checked_changes(request.get_json(silent=True))
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    permission_override.set_levels(changes, g.current_user.uid)
    current_app.logger.warning(f"permissions: {g.current_user.uid} set {changes}")
    return jsonify(_payload())
