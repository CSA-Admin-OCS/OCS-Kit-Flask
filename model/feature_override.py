"""The kit an admin applied at runtime, admin feature overrides, and their audit log.

Effective features = stored kit preset -> these overrides, or, with no stored kit,
KIT preset -> FEATURES env -> these overrides (see features.py).
Only the admin role may change them (GET/PUT/DELETE /api/kit/admin...). Changes apply on the
next request in every worker, without a restart: features.py reads these tables on each check.
A kit switch only changes this state: accounts and feature data are never touched.
"""
from datetime import datetime, timezone

from sqlalchemy import inspect

from __init__ import app, db
import features


KIT_ROW_ID = 1  # kit_setting holds at most this one row


class FeatureOverride(db.Model):
    __tablename__ = 'feature_override'

    feature_id = db.Column(db.String(64), primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False)
    updated_by = db.Column(db.String(255), nullable=True)  # uid of the admin
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class KitSetting(db.Model):
    """The kit applied through PUT /api/kit/admin/kit: one row, or none to follow KIT/FEATURES."""
    __tablename__ = 'kit_setting'

    id = db.Column(db.Integer, primary_key=True)
    kit = db.Column(db.String(64), nullable=False)
    updated_by = db.Column(db.String(255), nullable=True)  # uid of the admin
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class FeatureAudit(db.Model):
    """Who changed what, when. action: 'enable' | 'disable' | 'clear' for a feature id;
    'apply-kit' | 'forget-kit' with feature_id 'kit:<kit id>' for a kit."""
    __tablename__ = 'feature_audit'

    id = db.Column(db.Integer, primary_key=True)
    feature_id = db.Column(db.String(64), nullable=False)
    action = db.Column(db.String(16), nullable=False)
    actor = db.Column(db.String(255), nullable=True)
    at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def read(self):
        return {'feature': self.feature_id, 'action': self.action, 'by': self.actor,
                'at': self.at.isoformat() if self.at else None}


def ensure_tables():
    """Create the override tables on a database that predates them (no-op otherwise)."""
    for model in (FeatureOverride, FeatureAudit, KitSetting):
        try:
            model.__table__.create(db.engine, checkfirst=True)
        except Exception as e:  # another worker may have created it a moment ago
            print(f"feature_override: {model.__tablename__}: {e}")


def read_overrides():
    """{feature_id: enabled}; cached per request in flask.g."""
    from flask import g, has_request_context
    if has_request_context() and '_feature_overrides' in g:
        return g._feature_overrides
    found = {o.feature_id: o.enabled for o in FeatureOverride.query.all()}
    if has_request_context():
        g._feature_overrides = found
    return found


def read_stored_kit():
    """The stored kit id or None; cached per request in flask.g."""
    from flask import g, has_app_context, has_request_context
    if not has_app_context():  # e.g. while modules are imported; there is no database to ask yet
        return None
    if has_request_context() and '_stored_kit' in g:
        return g._stored_kit
    with db.session.no_autoflush:  # may run while the caller builds a new User
        found = db.session.execute(db.select(KitSetting.kit).where(KitSetting.id == KIT_ROW_ID)).scalar()
    if has_request_context():
        g._stored_kit = found
    return found


def _forget_cache():
    from flask import g, has_request_context
    if has_request_context():
        g.pop('_feature_overrides', None)
        g.pop('_stored_kit', None)


def recent_changes(limit=20):
    return [a.read() for a in FeatureAudit.query.order_by(FeatureAudit.id.desc()).limit(limit)]


def _feature_tables_empty(fid):
    """True when the feature has tables and every one of them is empty."""
    modules = {ref.partition(':')[0] for ref in features.flask_spec(fid)['models']}
    tables = [m.__table__ for m in db.Model.__subclasses__() if m.__module__ in modules]
    names = set(inspect(db.engine).get_table_names())
    tables = [t for t in tables if t.name in names]
    if not tables:
        return False
    return all(db.session.execute(db.select(db.func.count()).select_from(t)).scalar() == 0 for t in tables)


def _after_enable(fids):
    """Startup hooks always; seed data only when the feature's tables are still empty,
    so turning a feature off and on again never duplicates data. The change is already
    committed here, so a failing hook is logged and must not hide that or stop the others."""
    for fid in fids:
        try:
            features.run_hooks('startup', only=[fid])
            if features.flask_spec(fid)['seed'] and _feature_tables_empty(fid):
                print(f"feature_override: seeding '{fid}'")
                features.run_hooks('seed', only=[fid])
        except Exception:
            db.session.rollback()
            app.logger.exception(f"features: setting up '{fid}' failed")


def set_overrides(changes, actor):
    """changes: {feature_id: bool}. Validates everything before writing anything.
    Raises ValueError with a message for the client on a bad request."""
    if not isinstance(changes, dict) or not changes:
        raise ValueError('Body must be {"features": {"<id>": true|false, ...}}')
    ids = features.feature_ids()
    for fid, on in changes.items():
        if fid not in ids:
            raise ValueError(f"Unknown feature id '{fid}'. Valid ids: {', '.join(ids)}")
        if not isinstance(on, bool):
            raise ValueError(f"'{fid}' must be true or false")
        if fid == features.CORE and not on:
            raise ValueError("'core' is always on and cannot be disabled")
    before = set(features.enabled_features())
    now = datetime.now(timezone.utc)
    for fid, on in changes.items():
        row = db.session.get(FeatureOverride, fid)
        if row is None:
            row = FeatureOverride(feature_id=fid)
            db.session.add(row)
        row.enabled, row.updated_by, row.updated_at = on, actor, now
        db.session.add(FeatureAudit(feature_id=fid, action='enable' if on else 'disable', actor=actor, at=now))
    db.session.commit()
    _forget_cache()
    app.logger.warning(f"features: {actor} set {changes}")
    _after_enable([f for f in features.enabled_features() if f not in before])


def clear_override(fid, actor):
    """Drop the admin override so the kit decides again. Returns False if there was none."""
    if fid not in features.feature_ids():
        raise ValueError(f"Unknown feature id '{fid}'")
    row = db.session.get(FeatureOverride, fid)
    if row is None:
        return False
    before = set(features.enabled_features())
    db.session.delete(row)
    db.session.add(FeatureAudit(feature_id=fid, action='clear', actor=actor))
    db.session.commit()
    _forget_cache()
    app.logger.warning(f"features: {actor} cleared the override for {fid}")
    _after_enable([f for f in features.enabled_features() if f not in before])
    return True


def _clear_all_overrides(actor, now):
    for row in FeatureOverride.query.all():
        db.session.add(FeatureAudit(feature_id=row.feature_id, action='clear', actor=actor, at=now))
        db.session.delete(row)


def apply_kit(kit, actor):
    """Make kit the active preset and drop every override, in one transaction. Raises ValueError
    with a message for the client on an unknown kit. Applying the active kit again resets it."""
    kits = features.load_catalog()['kits']
    if not isinstance(kit, str) or kit not in kits:
        raise ValueError(f"Unknown kit {kit!r}. Valid kits: {', '.join(kits)}")
    before = set(features.enabled_features())
    now = datetime.now(timezone.utc)
    _clear_all_overrides(actor, now)
    row = db.session.get(KitSetting, KIT_ROW_ID)
    if row is None:
        row = KitSetting(id=KIT_ROW_ID)
        db.session.add(row)
    row.kit, row.updated_by, row.updated_at = kit, actor, now
    db.session.add(FeatureAudit(feature_id=f'kit:{kit}', action='apply-kit', actor=actor, at=now))
    db.session.commit()
    _forget_cache()
    app.logger.warning(f"features: {actor} applied kit {kit}")
    _after_enable([f for f in features.enabled_features() if f not in before])


def forget_kit(actor):
    """Forget the stored kit and every override: KIT/FEATURES decide again."""
    before = set(features.enabled_features())
    now = datetime.now(timezone.utc)
    _clear_all_overrides(actor, now)
    row = db.session.get(KitSetting, KIT_ROW_ID)
    if row is not None:
        db.session.add(FeatureAudit(feature_id=f'kit:{row.kit}', action='forget-kit', actor=actor, at=now))
        db.session.delete(row)
    db.session.commit()
    _forget_cache()
    app.logger.warning(f"features: {actor} returned to the KIT/FEATURES configuration")
    _after_enable([f for f in features.enabled_features() if f not in before])
