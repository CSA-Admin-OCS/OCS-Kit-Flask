"""Kit feature registry tests. Run from the repo root: python -m pytest tests"""
import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import features  # noqa: E402
from features import FeatureConfigError, resolve  # noqa: E402

ALL = features.feature_ids()


def test_catalog_matches_code():
    """python -m features --check: every mapped module loads, every api/ blueprint is mapped,
    no blueprint is claimed twice, ids/kits match the canonical catalog when it is present."""
    assert features.check() == []


def test_default_is_everything():
    assert resolve(None, None) == ('default', False, ALL)


def test_business_excludes_education_features():
    kit, customized, enabled = resolve('business', None)
    cat = features.load_catalog()['features']
    assert kit == 'business' and not customized
    assert all(cat[f]['category'] != 'education' for f in enabled)
    assert set(enabled) == set(features.load_catalog()['kits']['business']['features'])


def test_star_override_means_every_feature():
    kit, customized, enabled = resolve('business', '+*')
    assert enabled == ALL and customized


def test_vanilla_is_core_only():
    assert resolve('vanilla', '') == ('vanilla', False, ['core'])


def test_education_preset():
    kit, customized, enabled = resolve('education', None)
    assert kit == 'education' and not customized
    assert set(enabled) == set(features.load_catalog()['kits']['education']['features'])


def test_relative_overrides():
    kit, customized, enabled = resolve('education', '+finance-sim, -hallpass')
    assert kit == 'education' and customized
    assert 'finance-sim' in enabled and 'hallpass' not in enabled and 'ai-chatbot' in enabled


def test_explicit_list_ignores_kit():
    assert resolve('education', 'ai-chatbot,social') == ('custom', False, ['core', 'ai-chatbot', 'social'])


def test_star_minus():
    kit, customized, enabled = resolve(None, '*,-kasm')
    assert 'kasm' not in enabled and len(enabled) == len(ALL) - 1 and customized


@pytest.mark.parametrize('kit,feat', [('nope', None), (None, 'bogus'), ('vanilla', '+bogus'), (None, '-core')])
def test_bad_config_raises(kit, feat):
    with pytest.raises(FeatureConfigError):
        resolve(kit, feat)


@pytest.fixture
def patched_catalog(monkeypatch):
    cat = copy.deepcopy(features.load_catalog())
    monkeypatch.setattr(features, '_catalog', cat)
    return cat


def test_check_flags_unmapped_blueprint(patched_catalog):
    patched_catalog['features']['examples']['flask']['blueprints'].remove('hacks.joke:joke_api')
    assert any('hacks.joke:joke_api' in p and 'not mapped' in p for p in features.check())


def test_check_flags_double_claim(patched_catalog):
    patched_catalog['features']['ai-chatbot']['flask']['blueprints'].append('hacks.joke:joke_api')
    assert any('claimed by both' in p for p in features.check())


def test_check_flags_missing_module(patched_catalog):
    patched_catalog['features']['ai-chatbot']['flask']['blueprints'].append('api.does_not_exist:bp')
    assert any('does_not_exist' in p for p in features.check())


def test_check_flags_label_and_category(patched_catalog):
    patched_catalog['features']['kasm']['labels'].append('no-such-label')
    patched_catalog['features']['kasm']['category'] = 'nope'
    probs = features.check()
    assert any('no-such-label' in p for p in probs) and any("category 'nope'" in p for p in probs)


def test_check_flags_unowned_uses_blueprint(patched_catalog):
    patched_catalog['features']['ai-grading']['flask']['uses_blueprints'] = ['api.kit_api:kit_api', 'api.nope:x']
    probs = features.check()
    assert any('api.nope:x' in p for p in probs)
