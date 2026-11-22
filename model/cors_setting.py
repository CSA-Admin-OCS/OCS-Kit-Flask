"""The allowed origins an admin saved from the CORS page, and the log of who changed them.

cors.py explains the whole picture. Here: at most one row holds the saved list (as JSON text). While that row
exists it replaces the CORS_ORIGINS list from .env; deleting it ("Reset") returns to .env. Only the admin role
may change it (GET/PUT/DELETE /api/cors), and a change applies on the next request in every worker.
"""
import json
from datetime import datetime, timezone

from __init__ import db
from model.feature_override import _read_rows

ROW_ID = 1  # cors_setting holds at most this one row


class CorsSetting(db.Model):
    __tablename__ = 'cors_setting'

    id = db.Column(db.Integer, primary_key=True)
    origins = db.Column(db.Text, nullable=False)  # JSON list of origins
    updated_by = db.Column(db.String(255), nullable=True)  # uid of the admin
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class CorsAudit(db.Model):
    """Who changed the list, when. action: 'set' or 'reset'; detail says what was added and removed."""
    __tablename__ = 'cors_audit'

    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(16), nullable=False)
    detail = db.Column(db.Text, nullable=False, default='')
    actor = db.Column(db.String(255), nullable=True)
    at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def read(self):
        return {'action': self.action, 'detail': self.detail, 'by': self.actor,
                'at': self.at.isoformat() if self.at else None}


def ensure_tables():
    """Create the tables on a database that predates them (no-op otherwise)."""
    for model in (CorsSetting, CorsAudit):
        try:
            model.__table__.create(db.engine, checkfirst=True)
        except Exception as e:  # another worker may have created it a moment ago
            print(f"cors_setting: {model.__tablename__}: {e}")


def read_origins():
    """The list an admin saved, or None when there is none. Raises if it cannot be read."""
    rows = _read_rows(CorsSetting.__tablename__, db.select(CorsSetting.origins).where(CorsSetting.id == ROW_ID))
    return json.loads(rows[0][0]) if rows else None


def recent_changes(limit=20):
    return [a.read() for a in CorsAudit.query.order_by(CorsAudit.id.desc()).limit(limit)]


def save_origins(origins, actor, detail):
    """Save the list (already validated) and log it, in one transaction."""
    now = datetime.now(timezone.utc)
    row = db.session.get(CorsSetting, ROW_ID)
    if row is None:
        row = CorsSetting(id=ROW_ID)
        db.session.add(row)
    row.origins, row.updated_by, row.updated_at = json.dumps(origins), actor, now
    db.session.add(CorsAudit(action='set', detail=detail, actor=actor, at=now))
    db.session.commit()


def reset(actor, detail):
    """Forget the saved list so .env decides again. Returns False when there was none."""
    row = db.session.get(CorsSetting, ROW_ID)
    if row is None:
        return False
    db.session.delete(row)
    db.session.add(CorsAudit(action='reset', detail=detail, actor=actor))
    db.session.commit()
    return True
