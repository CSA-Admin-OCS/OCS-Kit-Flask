"""GET /api/kit - public: which kit and features this backend runs (see features.py)."""
from flask import Blueprint, jsonify

import features

kit_api = Blueprint('kit_api', __name__, url_prefix='/api')


@kit_api.route('/kit', methods=['GET'])
def get_kit():
    return jsonify(features.kit_info())
