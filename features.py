"""Kit feature registry.

kits/catalog.json is the single source of truth: it lists every feature, which Flask
blueprints / models / seed functions belong to it, and which features each kit enables.
main.py and scripts/db_init.py only iterate this registry; nothing here is per-feature.

Which features are enabled (resolved once per process from the environment):

    KIT       starting preset: vanilla | education | business (unset = business, everything on)
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
DEFAULT_KIT = 'business'
FLASK_KEYS = ('blueprints', 'inactive_blueprints', 'models', 'seed', 'startup', 'admin_links')


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

    explicit = [t for t in tokens if t[0] not in '+-']
    if explicit:
        enabled = set(_expand(explicit, all_ids, 'FEATURES'))
        kit_name = kit_name if set(explicit) == {'*'} and not kit else 'custom'
    else:
        enabled = set(_expand(kits[kit_name]['features'], all_ids, f"kit '{kit_name}'"))

    for t in tokens:
        if t[0] == '+':
            enabled.update(_expand([t[1:].strip()], all_ids, 'FEATURES'))
        elif t[0] == '-':
            removed = _expand([t[1:].strip()], all_ids, 'FEATURES')
            if CORE in removed and t[1:].strip() != '*':
                raise FeatureConfigError("'core' is always on and cannot be removed")
            enabled.difference_update(removed)

    enabled.add(CORE)
    customized = False
    if kit_name != 'custom':
        preset = set(_expand(kits[kit_name]['features'], all_ids, f"kit '{kit_name}'")) | {CORE}
        customized = enabled != preset
    return kit_name, customized, [f for f in all_ids if f in enabled]


def _state():
    global _resolved
    if _resolved is None:
        _resolved = resolve(os.environ.get('KIT'), os.environ.get('FEATURES'))
    return _resolved


def kit_name():
    return _state()[0]


def enabled_features():
    return list(_state()[2])


def is_enabled(fid):
    if fid not in feature_ids():
        raise FeatureConfigError(f"Unknown feature id '{fid}'")
    return fid in _state()[2]


def kit_info():
    """Public summary served by GET /api/kit."""
    name, customized, enabled = _state()
    kit = load_catalog()['kits'].get(name, {})
    return {
        'kit': name,
        'name': kit.get('name', 'Custom'),
        'customized': customized,
        'features': enabled,
    }


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


def register_blueprints(app):
    """Register blueprints of enabled features only; returns [(feature, blueprint name)]."""
    done = []
    for fid in enabled_features():
        for ref in flask_spec(fid)['blueprints']:
            bp = load_ref(ref)
            app.register_blueprint(bp)
            done.append((fid, bp.name))
    return done


def run_hooks(kind):
    """Run 'seed' or 'startup' functions of enabled features, in catalog order."""
    for fid in enabled_features():
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
    for fid, f in catalog['features'].items():
        extra = set(f.get('flask', {})) - set(FLASK_KEYS)
        if extra:
            problems.append(f"feature '{fid}': unknown flask keys {sorted(extra)}")
    for kid, kit in catalog['kits'].items():
        try:
            _expand(kit['features'], all_ids, f"kit '{kid}'")
        except FeatureConfigError as e:
            problems.append(str(e))

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
        if canon['kits'] != catalog['kits']:
            problems.append(f"kit presets differ from canonical {canonical_path}")
    elif require_canonical:
        problems.append(f"canonical catalog not found at {canonical_path}")
    else:
        print(f"note: canonical catalog not found at {canonical_path}; skipping id comparison")

    # 3. every referenced module/attribute exists; blueprints are Blueprints and claimed once
    owner = {}
    blueprint_owner = {}
    for fid in all_ids:
        spec = flask_spec(fid, catalog)
        for kind in ('blueprints', 'inactive_blueprints', 'models', 'seed', 'startup'):
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
    try:
        name, customized, enabled = _state()
    except FeatureConfigError as e:
        print(f"\nCurrent configuration is INVALID: {e}")
        enabled, name, customized = [], None, False
    print("\nFeatures:")
    for fid, f in catalog['features'].items():
        mark = 'on ' if fid in enabled else 'off'
        bps = [r.split(':')[1] for r in flask_spec(fid, catalog)['blueprints']]
        print(f"  [{mark}] {fid:<17} {f['name']}" + (f"  (blueprints: {', '.join(bps)})" if bps else ''))
    if name:
        print(f"\nKIT={os.environ.get('KIT') or '(unset)'} FEATURES={os.environ.get('FEATURES') or '(unset)'}"
              f" -> kit '{name}'{' (customized)' if customized else ''}, {len(enabled)} features enabled")


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
