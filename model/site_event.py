"""Site events: admin-managed upcoming events, scheduled posts about them, and photos.

Times are naive wall-clock values (no time zones): "6pm" means 6pm wherever the site is run.
The table names are prefixed site_ because the game leaderboard already owns "events".
"""
import calendar
import json
from datetime import date, datetime, timedelta

from __init__ import db

STATUSES = ('published', 'draft', 'cancelled')
REPEATS = ('none', 'daily', 'weekly', 'monthly')
POST_KINDS = ('before', 'after')
MAX_OCCURRENCES = 500  # safety cap per event and query


def parse_dt(value):
    """ISO date or date-time string to a naive datetime. Offsets are dropped, not converted."""
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip().replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        raise ValueError('not a valid date or date-time: %r' % (value,))


def parse_date(value):
    if value is None or value == '':
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return parse_dt(value).date()


def iso(dt):
    return dt.isoformat(timespec='seconds') if dt else None


def add_months(dt, months):
    """dt moved by whole months; a day past the end of the month becomes its last day."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


class SiteEvent(db.Model):
    __tablename__ = 'site_events'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    start = db.Column(db.DateTime, nullable=False)
    end = db.Column(db.DateTime, nullable=True)
    location = db.Column(db.String(200), nullable=True)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='published')
    repeat = db.Column(db.String(20), nullable=False, default='none')
    repeat_until = db.Column(db.Date, nullable=True)
    skipped = db.Column(db.Text, nullable=True)  # JSON list of occurrence start times left out
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    posts = db.relationship('SiteEventPost', backref='event', cascade='all, delete-orphan', lazy=True)
    photos = db.relationship('SiteEventPhoto', backref='event', cascade='all, delete-orphan', lazy=True)

    def __init__(self, title, start, end=None, location=None, description=None, status='published',
                 repeat='none', repeat_until=None):
        self.title = title
        self.start = start
        self.end = end
        self.location = location
        self.description = description
        self.status = status
        self.repeat = repeat
        self.repeat_until = repeat_until

    # -- validation ---------------------------------------------------------------------------

    @staticmethod
    def clean(data, partial=False):
        """Validate request data. Returns (fields, error); fields hold parsed values."""
        fields = {}
        try:
            if 'title' in data or not partial:
                title = (data.get('title') or '').strip()
                if not title:
                    return None, 'title is required'
                if len(title) > 200:
                    return None, 'title must be 200 characters or less'
                fields['title'] = title
            if 'start' in data or not partial:
                start = parse_dt(data.get('start'))
                if start is None:
                    return None, 'start is required'
                fields['start'] = start
            if 'end' in data:
                fields['end'] = parse_dt(data.get('end'))
            if 'repeat_until' in data:
                fields['repeat_until'] = parse_date(data.get('repeat_until'))
        except ValueError as exc:
            return None, str(exc)
        for key, limit in (('location', 200), ('description', 20000)):
            if key in data:
                value = data.get(key)
                value = value.strip() if isinstance(value, str) else None
                if value and len(value) > limit:
                    return None, '%s is too long' % key
                fields[key] = value or None
        if 'status' in data:
            if data['status'] not in STATUSES:
                return None, 'status must be one of: ' + ', '.join(STATUSES)
            fields['status'] = data['status']
        if 'repeat' in data:
            if data['repeat'] not in REPEATS:
                return None, 'repeat must be one of: ' + ', '.join(REPEATS)
            fields['repeat'] = data['repeat']
        return fields, None

    def check_times(self):
        """Error text if the stored times do not make sense together, else None."""
        if self.end is not None and self.end < self.start:
            return 'end must not be before start'
        if self.repeat != 'none' and self.end is not None and self.end - self.start >= timedelta(days=1):
            return 'a repeating event must be shorter than one day'
        if self.repeat_until is not None and self.repeat_until < self.start.date():
            return 'repeat_until must not be before the start date'
        return None

    # -- occurrences --------------------------------------------------------------------------

    def skipped_starts(self):
        try:
            return set(json.loads(self.skipped)) if self.skipped else set()
        except ValueError:
            return set()

    def skip(self, start):
        starts = self.skipped_starts()
        starts.add(iso(start))
        self.skipped = json.dumps(sorted(starts))

    def occurrences(self, window_start, window_end):
        """[(start, end)] of every occurrence that overlaps [window_start, window_end]."""
        length = (self.end - self.start) if self.end else timedelta(0)
        skipped = self.skipped_starts()
        found = []
        if self.repeat == 'none':
            candidates = iter([self.start])
        else:
            candidates = self._repeat_starts(window_start, length)
        for occ_start in candidates:
            if occ_start > window_end:
                break
            if self.repeat_until is not None and occ_start.date() > self.repeat_until:
                break
            if occ_start + length < window_start or iso(occ_start) in skipped:
                continue
            found.append((occ_start, occ_start + length if self.end else None))
            if len(found) >= MAX_OCCURRENCES:
                break
        return found

    def _repeat_starts(self, window_start, length):
        """Occurrence start times in order, jumping close to window_start for daily/weekly."""
        if self.repeat == 'monthly':
            for k in range(0, 24 * 12):
                yield add_months(self.start, k)
            return
        step = timedelta(days=1 if self.repeat == 'daily' else 7)
        first = 0
        gap = window_start - length - self.start
        if gap > timedelta(0):
            first = max(0, gap // step)
        for k in range(first, first + 5000):
            yield self.start + step * k

    # -- output -------------------------------------------------------------------------------

    def read(self):
        return {
            'id': self.id, 'title': self.title, 'start': iso(self.start), 'end': iso(self.end),
            'location': self.location, 'description': self.description, 'status': self.status,
            'repeat': self.repeat,
            'repeat_until': self.repeat_until.isoformat() if self.repeat_until else None,
            'photo_count': len(self.photos),
        }

    def read_occurrence(self, occ_start, occ_end):
        out = self.read()
        out['occurrence_start'] = iso(occ_start)
        out['occurrence_end'] = iso(occ_end)
        return out

    def create(self):
        try:
            db.session.add(self)
            db.session.commit()
            return self
        except Exception:
            db.session.rollback()
            raise

    def update(self, fields):
        for key, value in fields.items():
            setattr(self, key, value)
        error = self.check_times()
        if error:
            db.session.rollback()
            return error
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        return None

    def delete(self):
        try:
            db.session.delete(self)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise


class SiteEventPost(db.Model):
    """A post about an event that goes live at publish_at ('before' promo, 'after' recap)."""
    __tablename__ = 'site_event_posts'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('site_events.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    kind = db.Column(db.String(20), nullable=False, default='before')
    publish_at = db.Column(db.DateTime, nullable=False)
    unpublish_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, event_id, title, body, kind, publish_at, unpublish_at=None):
        self.event_id = event_id
        self.title = title
        self.body = body
        self.kind = kind
        self.publish_at = publish_at
        self.unpublish_at = unpublish_at

    @staticmethod
    def clean(data, partial=False):
        fields = {}
        try:
            if 'title' in data or not partial:
                title = (data.get('title') or '').strip()
                if not title or len(title) > 200:
                    return None, 'title is required (200 characters or less)'
                fields['title'] = title
            if 'body' in data or not partial:
                body = (data.get('body') or '').strip()
                if not body or len(body) > 20000:
                    return None, 'body is required (20000 characters or less)'
                fields['body'] = body
            if 'kind' in data or not partial:
                kind = data.get('kind', 'before')
                if kind not in POST_KINDS:
                    return None, 'kind must be one of: ' + ', '.join(POST_KINDS)
                fields['kind'] = kind
            if 'publish_at' in data or not partial:
                publish_at = parse_dt(data.get('publish_at'))
                if publish_at is None:
                    return None, 'publish_at is required'
                fields['publish_at'] = publish_at
            if 'unpublish_at' in data:
                fields['unpublish_at'] = parse_dt(data.get('unpublish_at'))
        except ValueError as exc:
            return None, str(exc)
        return fields, None

    def check_times(self):
        if self.unpublish_at is not None and self.unpublish_at <= self.publish_at:
            return 'unpublish_at must be after publish_at'
        return None

    def is_live(self, now):
        return self.publish_at <= now and (self.unpublish_at is None or now < self.unpublish_at)

    def read(self):
        return {'id': self.id, 'event_id': self.event_id, 'title': self.title, 'body': self.body,
                'kind': self.kind, 'publish_at': iso(self.publish_at),
                'unpublish_at': iso(self.unpublish_at)}


class SiteEventPhoto(db.Model):
    """A picture from an event. The file lives under instance/uploads/events/<filename>."""
    __tablename__ = 'site_event_photos'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('site_events.id'), nullable=False)
    filename = db.Column(db.String(100), nullable=False, unique=True)
    caption = db.Column(db.String(300), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, event_id, filename, caption=None):
        self.event_id = event_id
        self.filename = filename
        self.caption = caption

    def read(self):
        return {'id': self.id, 'event_id': self.event_id, 'caption': self.caption,
                'url': '/api/site-events/photos/' + self.filename,
                'uploaded_at': iso(self.uploaded_at)}


def ensure_tables():
    """Create the events tables on a database that predates them (no-op otherwise), so an existing
    install gets them when it is updated, without wiping its data."""
    for model in (SiteEvent, SiteEventPost, SiteEventPhoto):
        try:
            model.__table__.create(db.engine, checkfirst=True)
        except Exception as e:  # another worker may have created it a moment ago
            print(f"site_event: {model.__tablename__}: {e}")
