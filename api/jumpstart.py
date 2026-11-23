"""OCS JumpStart: a guide to how the system works, from the first run to deployment.

GET /jumpstart/            the contents: every chapter with a line about it
GET /jumpstart/<chapter>/  one chapter: a summary box, then the subject under topic headings

It is open to anyone, like the Q&A guide (/help/): it teaches how the system works and holds no secrets. The chapters
are templates in templates/jumpstart/, listed in order in templates/jumpstart/chapters.json (each chapter's slug is the
name of its template). Some chapters show live facts about this backend (which features exist and are on, how many
requests each serves, how the permission levels split them), so the tables cannot go stale. tests/test_jumpstart.py
checks that every file, route, setting and command the chapters name really exists.
"""
import json
import os
from collections import Counter

from flask import Blueprint, abort, render_template

import features
import permissions
import roles
from __init__ import app

jumpstart = Blueprint('jumpstart', __name__)

_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'templates', 'jumpstart')


def _registry():
    with open(os.path.join(_FOLDER, 'chapters.json'), encoding='utf-8') as fh:
        data = json.load(fh)
    chapters = [{**chapter, 'number': number} for number, chapter in enumerate(data['chapters'], start=1)]
    return data['groups'], chapters


def _facts():
    """Live facts about this backend, for the tables in the chapters."""
    catalog = features.load_catalog()
    order = features.feature_ids(catalog)
    enabled = set(features.enabled_features())
    requests = {fid: 0 for fid in order}
    prefixes = Counter()
    for rule in app.url_map.iter_rules():
        if rule.endpoint == 'static':
            continue
        parts = rule.rule.strip('/').split('/')
        prefixes['/' + '/'.join(parts[:2] if parts[0] == 'api' else parts[:1])] += len(rule.methods - {'HEAD', 'OPTIONS'})
        owners = features.features_of_blueprint(rule.endpoint.rpartition('.')[0])
        owner = next((fid for fid in order if fid in owners), features.CORE)   # app-level pages belong to core
        requests[owner] += len(rule.methods - {'HEAD', 'OPTIONS'})
    return {
        'features': [{'id': fid, 'name': f['name'], 'category': f['category'], 'labels': f.get('labels', []),
                      'enabled': fid in enabled, 'requests': requests[fid],
                      'modules': sorted({ref.partition(':')[0] for ref in features.flask_spec(fid, catalog)['blueprints']})}
                     for fid, f in catalog['features'].items()],
        'kits': [{'id': kid, 'name': kit['name'], 'description': kit.get('description', ''), 'features': kit['features'],
                  'accounts': {rid: (kit['roles'][rid]['label'], kit['roles'][rid]['seed_uid']) for rid in roles.ROLE_IDS}}
                 for kid, kit in catalog['kits'].items()],
        'default_kit': {rid: (v['label'], v['seed_uid']) for rid, v in catalog['flask']['default_kit']['roles'].items()},
        'pinned': sorted(permissions.pinned()),
        'api_paths': list(permissions.api_paths()),
        'categories': {cid: c['description'] for cid, c in catalog['categories'].items()},
        'labels': catalog['labels'],
        'prefixes': sorted(prefixes.items()),
        'requests_total': sum(requests.values()),
        'by_level': {level: Counter(permissions.policy().values()).get(level, 0) for level in permissions.LISTS},
        'levels': list(permissions.LEVELS),
        'tiers': roles.TIER_COUNT,
    }


def _render(template, chapter=None):
    groups, chapters = _registry()
    index = next((i for i, c in enumerate(chapters) if chapter and c['slug'] == chapter), None)
    return render_template(template, groups=groups, chapters=chapters, facts=_facts(),
                           chapters_by_slug={c['slug']: c for c in chapters},
                           current=chapters[index] if index is not None else None,
                           previous=chapters[index - 1] if index else None,
                           following=chapters[index + 1] if index is not None and index + 1 < len(chapters) else None)


@jumpstart.route('/jumpstart/')
def index():
    return _render('jumpstart/index.html')


@jumpstart.route('/jumpstart/<string:chapter>/')
def chapter(chapter):
    _, chapters = _registry()
    if chapter not in {c['slug'] for c in chapters}:   # only registered chapters: a name is never turned into a path
        abort(404)
    return _render(f'jumpstart/{chapter}.html', chapter)
