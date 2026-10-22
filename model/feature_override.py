"""Admin feature overrides and their audit log.

Effective features = KIT preset -> FEATURES env -> these overrides (see features.py).
Only the admin role may change them (GET/PUT/DELETE /api/kit/admin...). Changes apply on the
next request in every worker, without a restart: features.py reads this table on each check.
"""
from datetime import datetime, timezone

from sqlalchemy import inspect

from __init__ import app, db
import features


class FeatureOverride(db.Model):
    __tablename__ = 'feature_override'

    feature_id = db.Column(db.String(64), primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False)
    updated_by = db.Column(db.String(255), nullable=True)  # uid of the admin
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class FeatureAudit(db.Model):
    """Who changed which feature, when. action: 'enable' | 'disable' | 'clear'."""
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
    for model in (FeatureOverride, FeatureAudit):
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


def _forget_cache():
    from flask import g, has_request_context
    if has_request_context():
        g.pop('_feature_overrides', None)


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
    so turning a feature off and on again never duplicates data."""
    for fid in fids:
        features.run_hooks('startup', only=[fid])
        if features.flask_spec(fid)['seed'] and _feature_tables_empty(fid):
            print(f"feature_override: seeding '{fid}'")
            features.run_hooks('seed', only=[fid])


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
    """Drop the admin override so KIT/FEATURES decide again. Returns False if there was none."""
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
