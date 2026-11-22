"""Roles admins added or changed from the Roles page, and the log of who changed what.

roles.py explains the model. The three built-in roles (admin, staff, member) exist without a row here; a row for
one of them records only a change an admin made (its label, or for staff and member its tier). A row with
custom=True is a role an admin added. Every role has a tier from 1 (L1, strongest) to 4 (L4, weakest). The admin
role is always L1 and never has a row with another tier.
Only the admin role may change them (GET/POST/PUT/DELETE /api/roles), and a change applies on the next request.
"""
from datetime import datetime, timezone

from __init__ import db
from model.feature_override import _read_rows


class RoleSetting(db.Model):
    __tablename__ = 'role_setting'

    name = db.Column(db.String(20), primary_key=True)  # the role as stored on accounts (users._role is 20 characters)
    label = db.Column(db.String(64), nullable=True)    # what people see; None = the kit's label (built-in) or the name
    tier = db.Column(db.Integer, nullable=False)       # 1 (L1, strongest) to 4 (L4, weakest)
    custom = db.Column(db.Boolean, nullable=False, default=False)  # True for a role an admin added
    updated_by = db.Column(db.String(255), nullable=True)  # uid of the admin
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class RoleAudit(db.Model):
    """Who changed what, when. action: create, update, delete, reset or assign (a role given to an account)."""
    __tablename__ = 'role_audit'

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
    for model in (RoleSetting, RoleAudit):
        try:
            model.__table__.create(db.engine, checkfirst=True)
        except Exception as e:  # another worker may have created it a moment ago
            print(f"role_setting: {model.__tablename__}: {e}")


def read_settings():
    """{name: {'label', 'tier', 'custom'}} for every row. Raises if it cannot be read."""
    rows = _read_rows(RoleSetting.__tablename__,
                      db.select(RoleSetting.name, RoleSetting.label, RoleSetting.tier, RoleSetting.custom))
    return {name: {'label': label, 'tier': tier, 'custom': bool(custom)} for name, label, tier, custom in rows}


def recent_changes(limit=20):
    return [a.read() for a in RoleAudit.query.order_by(RoleAudit.id.desc()).limit(limit)]


def log(action, detail, actor):
    """Add a line to the log; the caller commits."""
    db.session.add(RoleAudit(action=action, detail=detail, actor=actor))


def save(name, label, tier, custom, actor):
    """Create or change the row for a role. The caller logs and commits."""
    row = db.session.get(RoleSetting, name)
    if row is None:
        row = RoleSetting(name=name)
        db.session.add(row)
    row.label, row.tier, row.custom = label, tier, custom
    row.updated_by, row.updated_at = actor, datetime.now(timezone.utc)
    return row


def remove(name):
    """Delete the row for a role. Returns False when there was none. The caller logs and commits."""
    row = db.session.get(RoleSetting, name)
    if row is None:
        return False
    db.session.delete(row)
    return True
