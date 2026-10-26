"""Kit feature registry.

kits/catalog.json is the single source of truth: it lists every feature, which Flask
blueprints / models / seed functions belong to it, and which features each kit enables.
main.py and scripts/db_init.py only iterate this registry; nothing here is per-feature.

Which features are enabled (resolved once per process from the environment):

    KIT       starting preset: vanilla | education | business
              (unset = 'default': every feature on, as before kits existed)
    FEATURES  customizes the preset:
                "+finance-sim,-hallpass"  add/remove relative to KIT
                "core,ai,social"          explicit full list (ignores KIT)
                "*" or "*,-kasm"          everything (minus kasm)
    'core' is always enabled. Unknown kit or feature ids raise FeatureConfigError at startup.

CLI (run from the repo root):
    python -m features --list    show kits, features and what is enabled right now
    python -m features --check   validate the catalog against the code; non-zero exit on problems
"""
import importlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
CATALOG_PATH = os.path.join(ROOT, 'kits', 'catalog.json')
# Canonical catalog shared by all OCS-Kit repos (only present in a dev checkout of the parent repo)
CANONICAL_PATH = os.environ.get('KIT_CANONICAL_CATALOG') or os.path.join(ROOT, '..', 'OCS-Kit', 'kits', 'catalog.json')
CORE = 'core'
DEFAULT_KIT = 'default'  # reported kit name when KIT is unset: every feature enabled
FLASK_KEYS = ('blueprints', 'uses_blueprints', 'inactive_blueprints', 'models', 'seed', 'startup', 'admin_links')


class FeatureConfigError(ValueError):
    """Bad KIT / FEATURES value or a malformed catalog."""


_catalog = None
_resolved = None


def load_catalog(path=CATALOG_PATH):
    global _catalog
    if _catalog is None or path != CATALOG_PATH:
        with open(path, encoding='utf-8') as f:
            cat = json.load(f)
        if path != CATALOG_PATH:
            return cat
        _catalog = cat
    return _catalog


def feature_ids(catalog=None):
    return list((catalog or load_catalog())['features'].keys())


def flask_spec(fid, catalog=None):
    """The feature's 'flask' block with every key present."""
    spec = (catalog or load_catalog())['features'][fid].get('flask', {})
    return {k: spec.get(k, []) for k in FLASK_KEYS}


def _expand(ids, all_ids, where):
    out = []
    for fid in ids:
        if fid == '*':
            out.extend(all_ids)
        elif fid in all_ids:
            out.append(fid)
        else:
            raise FeatureConfigError(
                f"Unknown feature id '{fid}' in {where}. Valid ids: {', '.join(all_ids)}")
    return out


def resolve(kit=None, features=None, catalog=None):
    """Return (kit_name, customized, ordered list of enabled feature ids).

    kit_name is the KIT preset in effect, 'custom' when FEATURES is an explicit list.
    """
    catalog = catalog or load_catalog()
    all_ids = feature_ids(catalog)
    kits = catalog['kits']
    kit = (kit or '').strip().lower()
    tokens = [t.strip() for t in (features or '').split(',') if t.strip()]

    if kit and kit not in kits:
        raise FeatureConfigError(f"Unknown KIT '{kit}'. Valid kits: {', '.join(kits)}")
    kit_name = kit or DEFAULT_KIT
    preset_ids = kits[kit]['features'] if kit else ['*']
    preset = set(_expand(preset_ids, all_ids, f"kit '{kit_name}'")) | {CORE}

    explicit = [t for t in tokens if t[0] not in '+-']
    if explicit:
        enabled = set(_expand(explicit, all_ids, 'FEATURES'))
        kit_name = kit_name if set(explicit) == {'*'} and not kit else 'custom'
    else:
        enabled = set(preset)

    for t in tokens:
        if t[0] == '+':
            enabled.update(_expand([t[1:].strip()], all_ids, 'FEATURES'))
        elif t[0] == '-':
            removed = _expand([t[1:].strip()], all_ids, 'FEATURES')
            if CORE in removed and t[1:].strip() != '*':
                raise FeatureConfigError("'core' is always on and cannot be removed")
            enabled.difference_update(removed)

    enabled.add(CORE)
    customized = kit_name != 'custom' and enabled != preset
    return kit_name, customized, [f for f in all_ids if f in enabled]


def _state():
    global _resolved
    if _resolved is None:
        _resolved = resolve(os.environ.get('KIT'), os.environ.get('FEATURES'))
    return _resolved


def kit_name():
    return _state()[0]


# --- admin overrides (stored in the database, see model/feature_override.py) ----------------
# Effective features = KIT preset -> FEATURES env -> admin overrides. This module stays free of
# Flask/DB imports; main.py installs a provider that reads the feature_override table.

_override_provider = None


def set_override_provider(fn):
    """fn() -> {feature_id: bool}. Called on every check, so changes apply without a restart."""
    global _override_provider
    _override_provider = fn


def overrides():
    if _override_provider is None:
        return {}
    try:
        found = _override_provider() or {}
    except Exception as e:  # a missing table or DB outage must not take the site down
        print(f"features: cannot read admin overrides ({e}); using KIT/FEATURES only")
        return {}
    ids = feature_ids()
    return {fid: bool(on) for fid, on in found.items() if fid in ids}  # ids removed from the catalog are ignored


def apply_overrides(base_enabled, override_map):
    """Pure: base list + {id: bool} -> ordered effective list; core always on."""
    enabled = set(base_enabled)
    for fid, on in override_map.items():
        (enabled.add if on else enabled.discard)(fid)
    enabled.add(CORE)
    return [f for f in feature_ids() if f in enabled]


def base_features():
    """Enabled by KIT + FEATURES only (what the server operator configured)."""
    return list(_state()[2])


def enabled_features():
    """Effective enabled features, admin overrides included."""
    return apply_overrides(_state()[2], overrides())


def is_enabled(fid):
    if fid not in feature_ids():
        raise FeatureConfigError(f"Unknown feature id '{fid}'")
    return fid in enabled_features()


def source(fid, override_map=None):
    """Who decided this feature's state: 'admin' (override), 'env' (FEATURES) or 'kit'."""
    override_map = overrides() if override_map is None else override_map
    if fid in override_map:
        return 'admin'
    name, _, base = _state()
    if (os.environ.get('FEATURES') or '').strip():
        if name == 'custom':
            return 'env'
        kit = os.environ.get('KIT', '').strip().lower()
        preset = set(_expand(load_catalog()['kits'][kit]['features'], feature_ids(), 'kit')) | {CORE} \
            if kit else set(feature_ids())
        if (fid in preset) != (fid in base):
            return 'env'
    return 'kit'


def kit_info():
    """Public summary served by GET /api/kit (shared contract with the Spring backend)."""
    import roles  # roles imports this module
    name, customized, _ = _state()
    override_map = overrides()
    enabled = apply_overrides(_state()[2], override_map)
    catalog = load_catalog()
    kit = catalog['kits'].get(name, {})
    default_names = {DEFAULT_KIT: catalog['flask']['default_kit']['name'], 'custom': 'Custom'}
    kit_label = kit.get('name', default_names.get(name, name))
    return {
        'kit': name,
        'kit_name': kit_label,
        'name': kit_label,  # same as kit_name; kept for older clients
        'customized': customized or bool(override_map),
        'features': enabled,  # ids of enabled features
        'feature_details': [
            {'id': fid,
             'name': f['name'],
             'category': f.get('category'),
             'labels': f.get('labels', []),
             'enabled': fid in enabled}
            for fid, f in catalog['features'].items()
        ],
        'roles': roles.public_roles(),
        'signup_role': roles.kit_config()['signup_role'],
    }


def setting_configured(key, config=None):
    """True when a backend setting has a value (env or app config). Never returns the value."""
    value = os.environ.get(key)
    if not value and config is not None:
        value = config.get(key)
    return bool(value)


def admin_info(config=None):
    """kit_info() plus, per feature, where its state comes from and its Flask setup status.
    Setting values are never included, only whether each one is configured."""
    info = kit_info()
    override_map = overrides()
    catalog = load_catalog()
    for d in info['feature_details']:
        f = catalog['features'][d['id']]
        setup = f.get('setup', {})
        settings = [
            {'key': st['key'], 'service': st['service'], 'required': bool(st.get('required')),
             'secret': bool(st.get('secret')), 'help': st.get('help'), 'get_it': st.get('get_it'),
             'example': None if st.get('secret') else st.get('example'),
             'configured': setting_configured(st['key'], config)}
            for st in setup.get('settings', []) if st.get('service') == 'flask'
        ]
        d.update({
            'always_on': bool(f.get('always_on')),
            'source': source(d['id'], override_map),
            'override': override_map.get(d['id']),
            'setup': {'summary': setup.get('summary'), 'settings': settings,
                      'steps': setup.get('steps', []), 'verify': setup.get('verify')},
            'ready': all(st['configured'] for st in settings if st['required']),
        })
    info['base_features'] = base_features()
    info['feature_management'] = catalog.get('feature_management', {})
    return info


# --- loading code named in the catalog ---------------------------------------

def load_ref(ref):
    """'package.module:attribute' -> the attribute (module only when there is no ':')."""
    module, _, attr = ref.partition(':')
    mod = importlib.import_module(module)
    return getattr(mod, attr) if attr else mod


def import_all_models():
    """Import every feature's models, enabled or not, so all tables and FKs always exist."""
    for fid in feature_ids():
        for ref in flask_spec(fid)['models']:
            load_ref(ref)


_blueprint_features = {}


def register_blueprints(app):
    """Register every feature's blueprints ('blueprints' + 'uses_blueprints'; not
    'inactive_blueprints') and gate each request: a blueprint answers 404 unless one of the
    features that list it is enabled right now. Returns [(feature, blueprint name)]."""
    from flask import abort, request
    done, seen = [], {}
    for fid in feature_ids():
        spec = flask_spec(fid)
        for ref in spec['blueprints'] + spec['uses_blueprints']:
            if ref not in seen:
                bp = load_ref(ref)
                app.register_blueprint(bp)
                seen[ref] = bp.name
                done.append((fid, bp.name))
            _blueprint_features.setdefault(seen[ref], set()).add(fid)

    def _blueprint_of_request():
        if request.blueprint or request.url_rule is not None:
            return request.blueprint
        # Wrong HTTP method: no rule matched, but the path belongs to a blueprint. Find it,
        # so a disabled feature answers 404 rather than revealing itself with a 405.
        from werkzeug.exceptions import MethodNotAllowed
        exc = request.routing_exception
        if isinstance(exc, MethodNotAllowed):
            adapter = app.create_url_adapter(request)
            for method in exc.valid_methods or ():
                try:
                    endpoint, _ = adapter.match(method=method)
                    return endpoint.rpartition('.')[0] or None
                except Exception:
                    continue
        return None

    @app.before_request
    def _gate_disabled_features():
        owners = _blueprint_features.get(_blueprint_of_request())
        if owners and CORE not in owners and not owners.intersection(enabled_features()):
            abort(404)
    return done


def features_of_blueprint(name):
    return set(_blueprint_features.get(name, ()))


def run_hooks(kind, only=None):
    """Run 'seed' or 'startup' functions of enabled features (or of the ids in only),
    in catalog order."""
    targets = enabled_features() if only is None else [f for f in feature_ids() if f in only]
    for fid in targets:
        for ref in flask_spec(fid)[kind]:
            load_ref(ref)()


def admin_links():
    links = []
    for fid in enabled_features():
        links.extend(flask_spec(fid)['admin_links'])
    return links


# --- CLI ----------------------------------------------------------------------

def check(canonical_path=CANONICAL_PATH, require_canonical=False):
    """Validate the catalog against the code. Returns a list of problems (empty = OK)."""
    from flask import Blueprint
    problems = []
    catalog = load_catalog()
    all_ids = feature_ids(catalog)

    # 1. catalog shape and kit presets
    if CORE not in all_ids:
        problems.append("catalog has no 'core' feature")
    categories, labels = catalog.get('categories', {}), catalog.get('labels', {})
    for fid, f in catalog['features'].items():
        if f.get('category') not in categories:
            problems.append(f"feature '{fid}': category {f.get('category')!r} not in 'categories'")
        for lab in f.get('labels', []):
            if lab not in labels:
                problems.append(f"feature '{fid}': label '{lab}' not in 'labels'")
        extra = set(f.get('flask', {})) - set(FLASK_KEYS)
        if extra:
            problems.append(f"feature '{fid}': unknown flask keys {sorted(extra)}")
    role_ids = list(catalog.get('roles', {}))
    flask_roles = catalog.get('flask', {}).get('roles', {})
    if sorted(flask_roles) != sorted(role_ids) or not role_ids:
        problems.append(f"top-level flask.roles must map exactly the canonical roles {role_ids}")
    if len(set(flask_roles.values())) != len(flask_roles):
        problems.append("flask.roles: two canonical roles map to the same Flask role")
    default_kit = catalog.get('flask', {}).get('default_kit', {})
    for kid, kit in list(catalog['kits'].items()) + [('(KIT unset) flask.default_kit', default_kit)]:
        if kid in catalog['kits']:
            try:
                _expand(kit['features'], all_ids, f"kit '{kid}'")
            except FeatureConfigError as e:
                problems.append(str(e))
        if sorted(kit.get('roles', {})) != sorted(role_ids):
            problems.append(f"kit '{kid}': roles must cover exactly {role_ids}")
        if kit.get('signup_role') not in role_ids:
            problems.append(f"kit '{kid}': signup_role {kit.get('signup_role')!r} is not a canonical role")
    for fid, f in catalog['features'].items():
        for st in f.get('setup', {}).get('settings', []):
            if st.get('service') not in ('flask', 'spring', 'pages') or not st.get('key'):
                problems.append(f"feature '{fid}': setup setting {st.get('key')!r} needs a key and service flask|spring|pages")

    # 2. ids, names, descriptions and kits must match the canonical catalog verbatim
    if os.path.exists(canonical_path):
        canon = load_catalog(canonical_path)
        if list(canon['features']) != all_ids:
            problems.append(f"feature ids differ from canonical {canonical_path}: "
                            f"missing {sorted(set(canon['features']) - set(all_ids))}, "
                            f"extra {sorted(set(all_ids) - set(canon['features']))}")
        for fid, cf in canon['features'].items():
            mine = catalog['features'].get(fid, {})
            for key in set(cf) | (set(mine) - {'flask'}):
                if mine.get(key) != cf.get(key):
                    problems.append(f"feature '{fid}' field '{key}' differs from canonical catalog")
        for key in canon:
            if key in ('version', 'description', 'features'):
                continue
            if canon.get(key) != catalog.get(key):
                problems.append(f"top-level '{key}' differs from canonical {canonical_path}")
    elif require_canonical:
        problems.append(f"canonical catalog not found at {canonical_path}")
    else:
        print(f"note: canonical catalog not found at {canonical_path}; skipping id comparison")

    # 3. every referenced module/attribute exists; blueprints are Blueprints and claimed once
    owner = {}
    blueprint_owner = {}
    for fid in all_ids:
        spec = flask_spec(fid, catalog)
        for kind in ('blueprints', 'inactive_blueprints', 'models', 'seed', 'startup'):  # owned
            for ref in spec[kind]:
                try:
                    obj = load_ref(ref)
                except Exception as e:
                    problems.append(f"feature '{fid}' {kind}: cannot load '{ref}': {e!r}")
                    continue
                if kind.endswith('blueprints'):
                    if not isinstance(obj, Blueprint):
                        problems.append(f"feature '{fid}': '{ref}' is not a Blueprint")
                        continue
                    if id(obj) in owner:
                        problems.append(f"blueprint '{ref}' claimed by both '{owner[id(obj)]}' and '{fid}'")
                    owner[id(obj)] = fid
                    blueprint_owner[obj.name] = fid
                elif kind in ('seed', 'startup') and not callable(obj):
                    problems.append(f"feature '{fid}' {kind}: '{ref}' is not callable")

    # 3b. 'uses_blueprints' must point at a blueprint another feature owns
    owned_refs = {ref: fid for fid in all_ids for ref in flask_spec(fid, catalog)['blueprints']}
    for fid in all_ids:
        for ref in flask_spec(fid, catalog)['uses_blueprints']:
            if owned_refs.get(ref) in (None, fid):
                problems.append(f"feature '{fid}' uses_blueprints '{ref}': not owned by another feature's 'blueprints'")

    # 4. no blueprint in api/ or hacks/ may bypass gating
    for pkg in ('api', 'hacks'):
        for fn in sorted(os.listdir(os.path.join(ROOT, pkg))):
            if not fn.endswith('.py') or fn.startswith('__'):
                continue
            modname = f"{pkg}.{fn[:-3]}"
            try:
                mod = importlib.import_module(modname)
            except Exception as e:
                problems.append(f"cannot import {modname}: {e!r}")
                continue
            for attr, obj in vars(mod).items():
                if isinstance(obj, Blueprint) and getattr(obj, 'import_name', None) == modname \
                        and id(obj) not in owner:
                    problems.append(f"blueprint '{modname}:{attr}' is not mapped to any feature in kits/catalog.json")

    # 5. admin links that point into a blueprint must point into the feature's own blueprint
    for fid in all_ids:
        for link in flask_spec(fid, catalog)['admin_links']:
            if not {'label', 'endpoint'} <= set(link):
                problems.append(f"feature '{fid}': admin link {link} needs 'label' and 'endpoint'")
                continue
            bp_name = link['endpoint'].rpartition('.')[0]
            if bp_name and blueprint_owner.get(bp_name) != fid:
                problems.append(f"feature '{fid}': admin link endpoint '{link['endpoint']}' is not in one of its blueprints")
    return problems


def print_list():
    catalog = load_catalog()
    print("Kits:")
    for kid, kit in catalog['kits'].items():
        print(f"  {kid:<10} {kit['name']}: {', '.join(kit['features'])}")
    print("\nCategories:")
    for cid, cat in catalog.get('categories', {}).items():
        print(f"  {cid:<10} {cat['description']}")
    try:
        name, customized, enabled = _state()
    except FeatureConfigError as e:
        print(f"\nCurrent configuration is INVALID: {e}")
        enabled, name, customized = [], None, False
    print("\nFeatures:")
    for fid, f in catalog['features'].items():
        mark = 'on ' if fid in enabled else 'off'
        spec = flask_spec(fid, catalog)
        bps = [r.split(':')[1] for r in spec['blueprints']] + [r.split(':')[1] + ' (shared)' for r in spec['uses_blueprints']]
        print(f"  [{mark}] {fid:<17} {f.get('category', '?'):<10} {f['name']}  [{', '.join(f.get('labels', []))}]"
              + (f"\n{'':<36}blueprints: {', '.join(bps)}" if bps else ''))
    if name:
        print(f"\nKIT={os.environ.get('KIT') or '(unset)'} FEATURES={os.environ.get('FEATURES') or '(unset)'}"
              f" -> kit '{name}'{' (customized)' if customized else ''}, {len(enabled)} features enabled")
        print("Admins can change this at runtime (PUT /api/kit/admin/features); see GET /api/kit/admin.")


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog='python -m features', description='OCS-Kit feature registry')
    p.add_argument('--list', action='store_true', help='show kits, features and what is enabled')
    p.add_argument('--check', action='store_true', help='validate kits/catalog.json against the code')
    p.add_argument('--require-canonical', action='store_true',
                   help='fail --check when the canonical OCS-Kit catalog is not found')
    args = p.parse_args(argv)
    if not (args.list or args.check):
        args.list = True
    status = 0
    if args.list:
        print_list()
    if args.check:
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        try:
            resolve(os.environ.get('KIT'), os.environ.get('FEATURES'))
        except FeatureConfigError as e:
            print(f"FAIL: KIT/FEATURES: {e}")
            status = 1
        problems = check(require_canonical=args.require_canonical)
        for prob in problems:
            print(f"FAIL: {prob}")
        if problems:
            status = 1
        else:
            print("OK: kits/catalog.json matches the code")
    return status


if __name__ == '__main__':
    sys.exit(main())
