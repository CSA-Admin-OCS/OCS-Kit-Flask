"""
Site events API (feature 'events').

Public (no login):
  GET  /api/site-events                 upcoming, past or all published events as dated occurrences
                                        ?when=upcoming|past|all  &now=<ISO>  &limit=<n>
  GET  /api/site-events/<id>            one event with the posts that are live at `now`, and its photos
  GET  /api/site-events/gallery         photos from recent, already-started events (newest first)
  GET  /api/site-events/photos/<file>   a photo file (only for published events)

Admin only (the kit's admin role):
  GET    /api/site-events/admin                 every event, drafts and cancelled included, with all posts
  POST   /api/site-events                       create
  PUT    /api/site-events/<id>                  edit
  DELETE /api/site-events/<id>                  delete (photos and posts too)
  POST   /api/site-events/<id>/skip             leave one occurrence of a repeating event out
  POST   /api/site-events/<id>/posts            add a scheduled post
  PUT    /api/site-events/posts/<id>            edit a post
  DELETE /api/site-events/posts/<id>            delete a post
  POST   /api/site-events/<id>/photos           upload a photo (multipart: file, optional caption)
  DELETE /api/site-events/photos/<id>           delete a photo

The prefix is /api/site-events because /api/events already belongs to the game leaderboard.
Times are naive wall-clock ISO strings. `now` defaults to the server's local time.
"""
import os
import uuid
from datetime import datetime, timedelta

from flask import Blueprint, current_app, g, jsonify, request, send_from_directory
from flask_restful import Api, Resource

from __init__ import db
from api.authorize import token_required
from model.site_event import (SiteEvent, SiteEventPhoto, SiteEventPost, iso, parse_dt)

site_events_api = Blueprint('site_events_api', __name__, url_prefix='/api/site-events')
api = Api(site_events_api)

MAX_PHOTO_BYTES = 5 * 1024 * 1024
MAX_PHOTOS_PER_EVENT = 50
PAST_WINDOW = timedelta(days=365)
FUTURE_WINDOW = timedelta(days=365)
DEFAULT_LIMIT, MAX_LIMIT = 50, 200


def _image_type(head):
    """File extension for the image the bytes really are, or None. The upload's own name and
    content type are never trusted."""
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if head.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    if head[:6] in (b'GIF87a', b'GIF89a'):
        return '.gif'
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return '.webp'
    return None


def _photo_dir():
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'events')
    os.makedirs(path, exist_ok=True)
    return path


def _now():
    raw = request.args.get('now')
    if not raw:
        return datetime.now().replace(microsecond=0)
    return parse_dt(raw)


def _limit():
    try:
        return max(1, min(int(request.args.get('limit', DEFAULT_LIMIT)), MAX_LIMIT))
    except ValueError:
        return DEFAULT_LIMIT


def _admin_only():
    """None for an admin, else the (body, status) to return."""
    if not g.current_user.is_admin():
        return {'message': 'Admin privileges required'}, 403
    return None


def _json():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else None


def _bad(message):
    return {'message': message}, 400


class EventList(Resource):
    def get(self):
        try:
            now = _now()
        except ValueError as exc:
            return _bad(str(exc))
        when = request.args.get('when', 'upcoming')
        if when not in ('upcoming', 'past', 'all'):
            return _bad('when must be upcoming, past or all')
        limit = _limit()
        low, high = now - PAST_WINDOW, now + FUTURE_WINDOW
        rows = []
        for event in SiteEvent.query.filter_by(status='published').all():
            for occ_start, occ_end in event.occurrences(low, high):
                over = (occ_end or occ_start) < now if occ_end else occ_start < now
                if when == 'upcoming' and over:
                    continue
                if when == 'past' and not over:
                    continue
                rows.append(event.read_occurrence(occ_start, occ_end))
        rows.sort(key=lambda r: (r['occurrence_start'], r['id']), reverse=(when == 'past'))
        return jsonify({'now': iso(now), 'when': when, 'events': rows[:limit]})

    @token_required()
    def post(self):
        denied = _admin_only()
        if denied:
            return denied
        body = _json()
        if body is None:
            return _bad('JSON body required')
        fields, error = SiteEvent.clean(body)
        if error:
            return _bad(error)
        event = SiteEvent(**fields)
        error = event.check_times()
        if error:
            return _bad(error)
        event.create()
        return event.read(), 201


class EventDetail(Resource):
    def get(self, event_id):
        try:
            now = _now()
        except ValueError as exc:
            return _bad(str(exc))
        event = db.session.get(SiteEvent, event_id)
        if event is None or event.status == 'draft':
            return {'message': 'Event not found'}, 404
        out = event.read()
        out['posts'] = [p.read() for p in sorted(event.posts, key=lambda p: p.publish_at)
                        if p.is_live(now)]
        out['photos'] = [p.read() for p in event.photos]
        return out

    @token_required()
    def put(self, event_id):
        denied = _admin_only()
        if denied:
            return denied
        event = db.session.get(SiteEvent, event_id)
        if event is None:
            return {'message': 'Event not found'}, 404
        body = _json()
        if body is None:
            return _bad('JSON body required')
        fields, error = SiteEvent.clean(body, partial=True)
        if error:
            return _bad(error)
        error = event.update(fields)
        if error:
            return _bad(error)
        return event.read()

    @token_required()
    def delete(self, event_id):
        denied = _admin_only()
        if denied:
            return denied
        event = db.session.get(SiteEvent, event_id)
        if event is None:
            return {'message': 'Event not found'}, 404
        names = [p.filename for p in event.photos]
        event.delete()
        for name in names:
            _remove_file(name)
        return {'message': 'Deleted'}


class EventAdminList(Resource):
    @token_required()
    def get(self):
        denied = _admin_only()
        if denied:
            return denied
        out = []
        for event in SiteEvent.query.order_by(SiteEvent.start.desc()).all():
            row = event.read()
            row['posts'] = [p.read() for p in sorted(event.posts, key=lambda p: p.publish_at)]
            row['photos'] = [p.read() for p in event.photos]
            out.append(row)
        return jsonify({'events': out})


class EventSkip(Resource):
    @token_required()
    def post(self, event_id):
        denied = _admin_only()
        if denied:
            return denied
        event = db.session.get(SiteEvent, event_id)
        if event is None:
            return {'message': 'Event not found'}, 404
        body = _json() or {}
        try:
            start = parse_dt(body.get('start'))
        except ValueError as exc:
            return _bad(str(exc))
        if start is None:
            return _bad('start is required')
        event.skip(start)
        db.session.commit()
        return event.read()


class EventPosts(Resource):
    @token_required()
    def post(self, event_id):
        denied = _admin_only()
        if denied:
            return denied
        if db.session.get(SiteEvent, event_id) is None:
            return {'message': 'Event not found'}, 404
        body = _json()
        if body is None:
            return _bad('JSON body required')
        fields, error = SiteEventPost.clean(body)
        if error:
            return _bad(error)
        post = SiteEventPost(event_id=event_id, **fields)
        error = post.check_times()
        if error:
            return _bad(error)
        db.session.add(post)
        db.session.commit()
        return post.read(), 201


class EventPostDetail(Resource):
    @token_required()
    def put(self, post_id):
        denied = _admin_only()
        if denied:
            return denied
        post = db.session.get(SiteEventPost, post_id)
        if post is None:
            return {'message': 'Post not found'}, 404
        body = _json()
        if body is None:
            return _bad('JSON body required')
        fields, error = SiteEventPost.clean(body, partial=True)
        if error:
            return _bad(error)
        for key, value in fields.items():
            setattr(post, key, value)
        error = post.check_times()
        if error:
            db.session.rollback()
            return _bad(error)
        db.session.commit()
        return post.read()

    @token_required()
    def delete(self, post_id):
        denied = _admin_only()
        if denied:
            return denied
        post = db.session.get(SiteEventPost, post_id)
        if post is None:
            return {'message': 'Post not found'}, 404
        db.session.delete(post)
        db.session.commit()
        return {'message': 'Deleted'}


class EventPhotos(Resource):
    @token_required()
    def post(self, event_id):
        denied = _admin_only()
        if denied:
            return denied
        event = db.session.get(SiteEvent, event_id)
        if event is None:
            return {'message': 'Event not found'}, 404
        if len(event.photos) >= MAX_PHOTOS_PER_EVENT:
            return _bad('an event can have at most %d photos' % MAX_PHOTOS_PER_EVENT)
        upload = request.files.get('file')
        if upload is None:
            return _bad('file is required')
        data = upload.read(MAX_PHOTO_BYTES + 1)
        if not data:
            return _bad('the file is empty')
        if len(data) > MAX_PHOTO_BYTES:
            return _bad('the photo must be 5 MB or smaller')
        ext = _image_type(data[:16])
        if ext is None:
            return _bad('the file must be a PNG, JPEG, GIF or WebP image')
        caption = (request.form.get('caption') or '').strip()[:300] or None
        name = uuid.uuid4().hex + ext
        with open(os.path.join(_photo_dir(), name), 'wb') as fh:
            fh.write(data)
        photo = SiteEventPhoto(event_id, name, caption)
        try:
            db.session.add(photo)
            db.session.commit()
        except Exception:
            db.session.rollback()
            _remove_file(name)
            raise
        return photo.read(), 201


class PhotoDetail(Resource):
    def get(self, filename):
        photo = SiteEventPhoto.query.filter_by(filename=filename).first()
        if photo is None or photo.event.status == 'draft':
            return {'message': 'Photo not found'}, 404
        response = send_from_directory(_photo_dir(), filename)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response


class PhotoDelete(Resource):
    @token_required()
    def delete(self, photo_id):
        denied = _admin_only()
        if denied:
            return denied
        photo = db.session.get(SiteEventPhoto, photo_id)
        if photo is None:
            return {'message': 'Photo not found'}, 404
        name = photo.filename
        db.session.delete(photo)
        db.session.commit()
        _remove_file(name)
        return {'message': 'Deleted'}


class Gallery(Resource):
    def get(self):
        try:
            now = _now()
        except ValueError as exc:
            return _bad(str(exc))
        limit = _limit()
        rows = (db.session.query(SiteEventPhoto, SiteEvent)
                .join(SiteEvent, SiteEvent.id == SiteEventPhoto.event_id)
                .filter(SiteEvent.status == 'published', SiteEvent.start <= now)
                .order_by(SiteEvent.start.desc(), SiteEventPhoto.id.desc())
                .limit(limit).all())
        photos = []
        for photo, event in rows:
            item = photo.read()
            item['event_title'] = event.title
            item['event_start'] = iso(event.start)
            photos.append(item)
        return jsonify({'now': iso(now), 'photos': photos})


def _remove_file(name):
    try:
        os.remove(os.path.join(_photo_dir(), os.path.basename(name)))
    except OSError:
        pass


api.add_resource(EventAdminList, '/admin')
api.add_resource(Gallery, '/gallery')
api.add_resource(PhotoDetail, '/photos/<string:filename>')
api.add_resource(PhotoDelete, '/photos/<int:photo_id>')
api.add_resource(EventPostDetail, '/posts/<int:post_id>')
api.add_resource(EventList, '')
api.add_resource(EventDetail, '/<int:event_id>')
api.add_resource(EventSkip, '/<int:event_id>/skip')
api.add_resource(EventPosts, '/<int:event_id>/posts')
api.add_resource(EventPhotos, '/<int:event_id>/photos')
