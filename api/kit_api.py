"""Kit and feature management API (same contract as the Spring backend).

GET    /api/kit                         public: kit, enabled features, role labels, signup role
GET    /api/kit/admin                   admin: + per-feature source, setup guide, readiness
PUT    /api/kit/admin/features          admin: {"features": {"<id>": true|false}} sets overrides
DELETE /api/kit/admin/features/<id>     admin: clears an override (the kit decides again)
PUT    /api/kit/admin/kit               admin: {"kit": "<id>"} applies a preset, clears all overrides
DELETE /api/kit/admin/kit               admin: forgets the stored kit and overrides (back to env)

A kit switch never changes accounts or data: only labels and which features answer.
Only the admin role may change features (catalog 'feature_management'); staff and members
get 403, anonymous callers 401. Setting values are never returned, only whether each is set.
"""
from flask import Blueprint, current_app, g, jsonify, request

import features
import roles
from api.authorize import token_required
from model import feature_override

kit_api = Blueprint('kit_api', __name__, url_prefix='/api')


def _admin_payload():
    info = features.admin_info(current_app.config)
    info['recent_changes'] = feature_override.recent_changes()
    return info


@kit_api.route('/kit', methods=['GET'])
def get_kit():
    return jsonify(features.kit_info())


@kit_api.route('/kit/admin', methods=['GET'])
@token_required(roles.admin_role())
def get_kit_admin():
    return jsonify(_admin_payload())


@kit_api.route('/kit/admin/features', methods=['PUT'])
@token_required(roles.admin_role())
def put_kit_features():
    body = request.get_json(silent=True) or {}
    try:
        feature_override.set_overrides(body.get('features'), g.current_user.uid)
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    return jsonify(_admin_payload())


@kit_api.route('/kit/admin/features/<feature_id>', methods=['DELETE'])
@token_required(roles.admin_role())
def delete_kit_feature_override(feature_id):
    try:
        feature_override.clear_override(feature_id, g.current_user.uid)
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    return jsonify(_admin_payload())


@kit_api.route('/kit/admin/kit', methods=['PUT'])
@token_required(roles.admin_role())
def put_kit():
    body = request.get_json(silent=True)
    try:
        feature_override.apply_kit(body.get('kit') if isinstance(body, dict) else None, g.current_user.uid)
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    return jsonify(_admin_payload())


@kit_api.route('/kit/admin/kit', methods=['DELETE'])
@token_required(roles.admin_role())
def delete_kit():
    feature_override.forget_kit(g.current_user.uid)
    return jsonify(_admin_payload())
