"""The CORS page and API for admins: see which websites may call this backend, and change the list.

GET    /cors/       admin page
GET    /api/cors    admin: the origins in force, where they come from, the .env list, and recent changes
PUT    /api/cors    admin: {"origins": ["https://pages.example.org", ...]} saves the list
DELETE /api/cors    admin: forgets the saved list, so CORS_ORIGINS in .env decides again

A saved list replaces the .env list and applies on the next request, with no restart (see cors.py). Only exact
origins can be saved: https://pages.example.org, never a path, a trailing slash, a pattern or *. These requests are
pinned in permissions.json, so the page cannot be locked away from admins. A change that cannot be saved answers 503.
"""
from flask import Blueprint, current_app, g, jsonify, render_template, request
from sqlalchemy.exc import SQLAlchemyError

import cors
import roles
from __init__ import db
from api.authorize import admin_page_required, token_required
from model import cors_setting

cors_admin = Blueprint('cors_admin', __name__)


@cors_admin.errorhandler(SQLAlchemyError)
def _not_saved(e):
    db.session.rollback()
    current_app.logger.error(f"cors: the origins could not be saved or read: {e!r}")
    return jsonify({'message': 'The origins could not be saved or read. Try again when the database recovers.'}), 503


def _entry(origin):
    return {'origin': origin, 'kind': 'pattern' if cors.is_pattern(origin) else 'exact', 'warning': cors.warning_for(origin)}


def _payload():
    stored = cors.stored_entries()
    return {
        'source': 'admin' if stored is not None else cors.default_source(),
        'origins': [_entry(o) for o in (cors.default_entries() if stored is None else stored)],
        'default_origins': [_entry(o) for o in cors.default_entries()],
        'default_source': cors.default_source(),
        'recent_changes': cors_setting.recent_changes(),
    }


def _what_changed(before, after):
    """'added a, b; removed c' (or 'no change'), for the log."""
    added = [o for o in after if o.casefold() not in {b.casefold() for b in before}]
    removed = [o for o in before if o.casefold() not in {a.casefold() for a in after}]
    parts = ([f"added {', '.join(added)}"] if added else []) + ([f"removed {', '.join(removed)}"] if removed else [])
    return '; '.join(parts) or 'no change'


@cors_admin.route('/cors/')
@admin_page_required
def page():
    return render_template('cors.html')


@cors_admin.route('/api/cors', methods=['GET'])
@token_required(roles.admin_role())
def get_cors():
    return jsonify(_payload())


@cors_admin.route('/api/cors', methods=['PUT'])
@token_required(roles.admin_role())
def put_cors():
    body = request.get_json(silent=True)
    try:
        origins = cors.normalize_origins(body.get('origins') if isinstance(body, dict) else None)
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    before = cors.effective_entries()
    cors_setting.save_origins(origins, g.current_user.uid, _what_changed(before, origins))
    current_app.logger.warning(f"cors: {g.current_user.uid} saved {origins}")
    return jsonify(_payload())


@cors_admin.route('/api/cors', methods=['DELETE'])
@token_required(roles.admin_role())
def delete_cors():
    before = cors.effective_entries()
    after = cors.default_entries()
    if cors_setting.reset(g.current_user.uid, f"back to the .env list: {_what_changed(before, after)}"):
        current_app.logger.warning(f"cors: {g.current_user.uid} reset the origins to the .env list")
    return jsonify(_payload())
