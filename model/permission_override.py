"""Levels an admin changed at runtime, and their audit log.

permissions.json is the default for who may make each request. An admin can change the level of one
request from the Permissions page (GET /permissions/); the change is stored here and wins over the
file, on the next request in every worker, with no restart. Clearing it returns to the file.
Only the admin role may change them, and requests listed under "pinned" in permissions.json never can.
While the stored levels cannot be read, permissions.py refuses requests (503) rather than guess.
"""
from datetime import datetime, timezone

from sqlalchemy import inspect

from __init__ import db


class PermissionOverride(db.Model):
    __tablename__ = 'permission_override'

    request = db.Column(db.String(255), primary_key=True)  # "METHOD /route", as in permissions.json
    level = db.Column(db.String(16), nullable=False)
    updated_by = db.Column(db.String(255), nullable=True)  # uid of the admin
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class PermissionAudit(db.Model):
    """Who changed what, when. old_level and new_level are None for 'the level in permissions.json'."""
    __tablename__ = 'permission_audit'

    id = db.Column(db.Integer, primary_key=True)
    request = db.Column(db.String(255), nullable=False)
    old_level = db.Column(db.String(16), nullable=True)
    new_level = db.Column(db.String(16), nullable=True)
    actor = db.Column(db.String(255), nullable=True)
    at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def read(self):
        return {'request': self.request, 'from': self.old_level, 'to': self.new_level, 'by': self.actor,
                'at': self.at.isoformat() if self.at else None}


def ensure_tables():
    """Create the tables on a database that predates them (no-op otherwise)."""
    for model in (PermissionOverride, PermissionAudit):
        try:
            model.__table__.create(db.engine, checkfirst=True)
        except Exception as e:  # another worker may have created it a moment ago
            print(f"permission_override: {model.__tablename__}: {e}")


def _read_rows(stmt):
    """Rows of a stored-state table, on a connection of its own so a failure cannot poison the caller's session.
    A table that does not exist holds nothing (a first boot, or a database from before it); any other failure
    means the answer is unknown, so it is raised."""
    try:
        with db.engine.connect() as conn:
            return conn.execute(stmt).all()
    except Exception:
        if not inspect(db.engine).has_table(PermissionOverride.__tablename__):
            return []
        raise


def read_override(request_line):
    """The level an admin set for one request, or None when there is none. Raises if it cannot be read."""
    rows = _read_rows(db.select(PermissionOverride.level).where(PermissionOverride.request == request_line))
    return rows[0][0] if rows else None


def read_overrides():
    """{request: level} for every change an admin made. Raises if it cannot be read."""
    return dict(_read_rows(db.select(PermissionOverride.request, PermissionOverride.level)))


def recent_changes(limit=20):
    return [a.read() for a in PermissionAudit.query.order_by(PermissionAudit.id.desc()).limit(limit)]


def set_levels(changes, actor):
    """changes: {request: level, or None to go back to permissions.json}. Everything is validated by the caller;
    this writes the rows and the audit log in one transaction."""
    now = datetime.now(timezone.utc)
    for request_line, level in changes.items():
        row = db.session.get(PermissionOverride, request_line)
        old = row.level if row else None
        if level == old:
            continue
        if level is None:
            db.session.delete(row)
        elif row is None:
            db.session.add(PermissionOverride(request=request_line, level=level, updated_by=actor, updated_at=now))
        else:
            row.level, row.updated_by, row.updated_at = level, actor, now
        db.session.add(PermissionAudit(request=request_line, old_level=old, new_level=level, actor=actor, at=now))
    db.session.commit()
