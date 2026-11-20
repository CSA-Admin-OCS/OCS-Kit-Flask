"""Site events: public reads, admin-only writes, repeats, scheduled posts, photos, feature gating.

Kit under test (conftest.py): KIT=education, which now includes 'events'.
"""
import io
import os

import pytest

from conftest import ADMIN, MEMBER, STAFF, login

BASE = '/api/site-events'
NOW = '2030-06-15T12:00:00'
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
JPEG = b'\xff\xd8\xff\xe0' + b'\x00' * 32


@pytest.fixture(autouse=True)
def _clean_events(app):
    from __init__ import db
    from model.site_event import SiteEvent, SiteEventPhoto, SiteEventPost

    def clear():
        with app.app_context():
            SiteEventPhoto.query.delete()
            SiteEventPost.query.delete()
            SiteEvent.query.delete()
            db.session.commit()
    clear()
    yield
    clear()


def _make(app, **fields):
    body = {'title': 'Open house', 'start': '2030-06-20T18:00:00'}
    body.update(fields)
    r = login(app, ADMIN).post(BASE, json=body)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def _titles(client, **params):
    query = '&'.join('%s=%s' % kv for kv in params.items())
    return [e['title'] for e in client.get(BASE + '?' + query).get_json()['events']]


# --- permissions ---------------------------------------------------------------------------

def test_public_can_read_without_login(app):
    _make(app)
    r = login(app, None).get(BASE + '?now=' + NOW)
    assert r.status_code == 200 and len(r.get_json()['events']) == 1


@pytest.mark.parametrize('uid', [None, STAFF, MEMBER])
def test_only_admin_can_create(app, uid):
    r = login(app, uid).post(BASE, json={'title': 'x', 'start': '2030-01-01T10:00:00'})
    assert r.status_code == (401 if uid is None else 403)


@pytest.mark.parametrize('uid', [None, STAFF, MEMBER])
def test_only_admin_can_edit_delete_and_see_admin_list(app, uid):
    event = _make(app)
    client = login(app, uid)
    expected = 401 if uid is None else 403
    assert client.put('%s/%d' % (BASE, event['id']), json={'title': 'Hacked'}).status_code == expected
    assert client.delete('%s/%d' % (BASE, event['id'])).status_code == expected
    assert client.get(BASE + '/admin').status_code == expected
    assert login(app, None).get('%s/%d' % (BASE, event['id'])).get_json()['title'] == 'Open house'


# --- create / edit / validate --------------------------------------------------------------

def test_create_edit_delete(app):
    admin = login(app, ADMIN)
    event = admin.post(BASE, json={'title': ' Fair ', 'start': '2030-07-01T09:00:00',
                                   'location': 'Main hall'}).get_json()
    assert event['title'] == 'Fair' and event['status'] == 'published'
    r = admin.put('%s/%d' % (BASE, event['id']), json={'location': 'Gym', 'end': '2030-07-01T11:00:00'})
    assert r.get_json()['location'] == 'Gym' and r.get_json()['end'] == '2030-07-01T11:00:00'
    assert admin.delete('%s/%d' % (BASE, event['id'])).status_code == 200
    assert login(app, None).get('%s/%d' % (BASE, event['id'])).status_code == 404


@pytest.mark.parametrize('body', [
    {'start': '2030-01-01T10:00:00'},
    {'title': 'x'},
    {'title': 'x', 'start': 'next tuesday'},
    {'title': 'x', 'start': '2030-01-01T10:00:00', 'end': '2029-12-31T10:00:00'},
    {'title': 'x', 'start': '2030-01-01T10:00:00', 'status': 'secret'},
    {'title': 'x', 'start': '2030-01-01T10:00:00', 'repeat': 'hourly'},
    {'title': 'x' * 201, 'start': '2030-01-01T10:00:00'},
    {'title': 'x', 'start': '2030-01-01T10:00:00', 'end': '2030-01-03T10:00:00', 'repeat': 'weekly'},
    {'title': 'x', 'start': '2030-01-10T10:00:00', 'repeat': 'daily', 'repeat_until': '2030-01-01'},
])
def test_bad_input_is_rejected(app, body):
    assert login(app, ADMIN).post(BASE, json=body).status_code == 400
    assert login(app, ADMIN).get(BASE + '/admin').get_json()['events'] == []


def test_non_json_body_is_rejected(app):
    assert login(app, ADMIN).post(BASE, data='nope').status_code == 400


# --- upcoming / past ------------------------------------------------------------------------

def test_upcoming_is_in_time_order_and_past_is_separate(app):
    _make(app, title='Later', start='2030-08-01T10:00:00')
    _make(app, title='Soon', start='2030-06-16T10:00:00')
    _make(app, title='Done', start='2030-06-01T10:00:00', end='2030-06-01T12:00:00')
    client = login(app, None)
    assert _titles(client, now=NOW) == ['Soon', 'Later']
    assert _titles(client, now=NOW, when='past') == ['Done']
    assert _titles(client, now=NOW, when='all') == ['Done', 'Soon', 'Later']


def test_event_without_end_is_past_once_started(app):
    """An event with no end time must still show as past (a NULL end must not hide it)."""
    _make(app, title='Quick', start='2030-06-10T10:00:00')
    client = login(app, None)
    assert _titles(client, now=NOW, when='past') == ['Quick']
    assert _titles(client, now=NOW) == []


def test_event_in_progress_is_still_upcoming(app):
    _make(app, title='Now', start='2030-06-15T11:00:00', end='2030-06-15T13:00:00')
    assert _titles(login(app, None), now=NOW) == ['Now']


def test_drafts_and_cancelled_are_hidden_from_the_public(app):
    _make(app, title='Draft', status='draft')
    _make(app, title='Off', status='cancelled')
    _make(app, title='On')
    client = login(app, None)
    assert _titles(client, now=NOW) == ['On']
    draft = login(app, ADMIN).get(BASE + '/admin').get_json()['events']
    assert {e['title'] for e in draft} == {'Draft', 'Off', 'On'}
    draft_id = next(e['id'] for e in draft if e['title'] == 'Draft')
    assert client.get('%s/%d' % (BASE, draft_id)).status_code == 404


def test_limit_and_bad_params(app):
    for day in range(1, 6):
        _make(app, title='E%d' % day, start='2030-07-%02dT10:00:00' % day)
    assert len(_titles(login(app, None), now=NOW, limit=2)) == 2
    assert login(app, None).get(BASE + '?now=garbage').status_code == 400
    assert login(app, None).get(BASE + '?when=sometime').status_code == 400


# --- repeats --------------------------------------------------------------------------------

def test_weekly_repeat_expands_into_dated_occurrences(app):
    _make(app, title='Standup', start='2030-06-03T09:00:00', end='2030-06-03T09:30:00',
          repeat='weekly', repeat_until='2030-07-15')
    events = login(app, None).get(BASE + '?now=' + NOW).get_json()['events']
    assert [e['occurrence_start'] for e in events] == [
        '2030-06-17T09:00:00', '2030-06-24T09:00:00', '2030-07-01T09:00:00',
        '2030-07-08T09:00:00', '2030-07-15T09:00:00']
    assert events[0]['occurrence_end'] == '2030-06-17T09:30:00'


def test_past_occurrences_of_a_repeat(app):
    _make(app, title='Daily', start='2030-06-10T08:00:00', end='2030-06-10T09:00:00',
          repeat='daily', repeat_until='2030-06-20')
    past = login(app, None).get(BASE + '?when=past&now=' + NOW).get_json()['events']
    assert [e['occurrence_start'][:10] for e in past] == [
        '2030-06-15', '2030-06-14', '2030-06-13', '2030-06-12', '2030-06-11', '2030-06-10']


def test_monthly_repeat_clamps_to_month_end(app):
    _make(app, title='Month end', start='2030-01-31T10:00:00', repeat='monthly',
          repeat_until='2030-04-30')
    starts = [e['occurrence_start'] for e in
              login(app, None).get(BASE + '?when=all&now=2030-01-01T00:00:00').get_json()['events']]
    assert starts == ['2030-01-31T10:00:00', '2030-02-28T10:00:00', '2030-03-31T10:00:00',
                      '2030-04-30T10:00:00']


def test_skip_one_occurrence(app):
    event = _make(app, title='Class', start='2030-06-17T09:00:00', repeat='weekly',
                  repeat_until='2030-07-01')
    r = login(app, ADMIN).post('%s/%d/skip' % (BASE, event['id']), json={'start': '2030-06-24T09:00:00'})
    assert r.status_code == 200
    starts = [e['occurrence_start'] for e in login(app, None).get(BASE + '?now=' + NOW).get_json()['events']]
    assert starts == ['2030-06-17T09:00:00', '2030-07-01T09:00:00']
    assert login(app, MEMBER).post('%s/%d/skip' % (BASE, event['id']),
                                   json={'start': '2030-07-01T09:00:00'}).status_code == 403


def test_repeat_without_end_date_is_capped(app):
    _make(app, title='Forever', start='2030-06-01T09:00:00', repeat='daily')
    assert len(_titles(login(app, None), now=NOW, limit=200)) <= 200


# --- scheduled posts ------------------------------------------------------------------------

def test_posts_go_live_at_publish_time(app):
    event = _make(app)
    admin = login(app, ADMIN)
    url = '%s/%d/posts' % (BASE, event['id'])
    assert admin.post(url, json={'title': 'What to bring', 'body': 'Snacks', 'kind': 'before',
                                 'publish_at': '2030-06-10T08:00:00'}).status_code == 201
    assert admin.post(url, json={'title': 'Thanks', 'body': 'Great turnout', 'kind': 'after',
                                 'publish_at': '2030-06-21T08:00:00'}).status_code == 201
    assert admin.post(url, json={'title': 'Old promo', 'body': 'Gone', 'kind': 'before',
                                 'publish_at': '2030-06-01T08:00:00',
                                 'unpublish_at': '2030-06-12T08:00:00'}).status_code == 201
    public = login(app, None)

    def live(now):
        return [p['title'] for p in public.get('%s/%d?now=%s' % (BASE, event['id'], now)).get_json()['posts']]
    assert live('2030-06-05T00:00:00') == ['Old promo']
    assert live('2030-06-15T00:00:00') == ['What to bring']
    assert live('2030-06-22T00:00:00') == ['What to bring', 'Thanks']
    admin_view = admin.get(BASE + '/admin').get_json()['events'][0]
    assert len(admin_view['posts']) == 3


def test_post_validation_and_permissions(app):
    event = _make(app)
    url = '%s/%d/posts' % (BASE, event['id'])
    good = {'title': 'T', 'body': 'B', 'kind': 'before', 'publish_at': '2030-06-10T08:00:00'}
    for uid, code in ((None, 401), (STAFF, 403), (MEMBER, 403)):
        assert login(app, uid).post(url, json=good).status_code == code
    admin = login(app, ADMIN)
    for bad in ({**good, 'kind': 'during'}, {**good, 'title': ''}, {**good, 'body': ''},
                {**good, 'publish_at': 'soon'}, {**good, 'unpublish_at': '2030-06-01T00:00:00'}):
        assert admin.post(url, json=bad).status_code == 400
    assert admin.post(BASE + '/9999/posts', json=good).status_code == 404


def test_edit_and_delete_post(app):
    event = _make(app)
    admin = login(app, ADMIN)
    post = admin.post('%s/%d/posts' % (BASE, event['id']),
                      json={'title': 'T', 'body': 'B', 'publish_at': '2030-06-10T08:00:00'}).get_json()
    r = admin.put('%s/posts/%d' % (BASE, post['id']), json={'body': 'New'})
    assert r.get_json()['body'] == 'New'
    assert login(app, MEMBER).delete('%s/posts/%d' % (BASE, post['id'])).status_code == 403
    assert admin.delete('%s/posts/%d' % (BASE, post['id'])).status_code == 200
    assert admin.delete('%s/posts/%d' % (BASE, post['id'])).status_code == 404


# --- photos and gallery ---------------------------------------------------------------------

def _upload(client, event_id, data, name='pic.png', caption='A photo'):
    return client.post('%s/%d/photos' % (BASE, event_id),
                       data={'file': (io.BytesIO(data), name), 'caption': caption},
                       content_type='multipart/form-data')


def test_upload_checks_content_not_filename(app):
    event = _make(app, start='2030-06-01T10:00:00')
    admin = login(app, ADMIN)
    assert _upload(admin, event['id'], b'<?php echo 1;', 'shell.png').status_code == 400
    assert _upload(admin, event['id'], b'GIF89a<script>', 'x.html').status_code == 201  # real GIF header
    assert _upload(admin, event['id'], b'', 'empty.png').status_code == 400
    assert _upload(admin, event['id'], PNG + b'0' * (5 * 1024 * 1024), 'big.png').status_code in (400, 413)
    assert admin.post('%s/%d/photos' % (BASE, event['id']), data={}).status_code == 400


def test_upload_uses_random_names_and_serves_the_file(app):
    event = _make(app, start='2030-06-01T10:00:00')
    admin = login(app, ADMIN)
    photo = _upload(admin, event['id'], PNG, '../../evil.png').get_json()
    assert 'evil' not in photo['url'] and photo['url'].endswith('.png')
    r = login(app, None).get(photo['url'])
    assert r.status_code == 200 and r.data == PNG
    assert r.headers['X-Content-Type-Options'] == 'nosniff'
    assert login(app, None).get(BASE + '/photos/not-a-photo.png').status_code == 404
    assert login(app, None).get(BASE + '/photos/..%2f..%2fmain.py').status_code == 404


def test_only_admin_uploads_and_deletes_photos(app):
    event = _make(app, start='2030-06-01T10:00:00')
    for uid, code in ((None, 401), (STAFF, 403), (MEMBER, 403)):
        assert _upload(login(app, uid), event['id'], PNG).status_code == code
    admin = login(app, ADMIN)
    photo = _upload(admin, event['id'], JPEG, 'a.jpg').get_json()
    assert login(app, MEMBER).delete('%s/photos/%d' % (BASE, photo['id'])).status_code == 403
    assert admin.delete('%s/photos/%d' % (BASE, photo['id'])).status_code == 200
    assert login(app, None).get(photo['url']).status_code == 404


def test_gallery_shows_started_published_events_newest_first(app):
    admin = login(app, ADMIN)
    old = _make(app, title='Old', start='2030-05-01T10:00:00')
    new = _make(app, title='New', start='2030-06-10T10:00:00')
    future = _make(app, title='Future', start='2030-09-01T10:00:00')
    draft = _make(app, title='Draft', start='2030-05-20T10:00:00', status='draft')
    for e in (old, new, future, draft):
        _upload(admin, e['id'], PNG)
    photos = login(app, None).get(BASE + '/gallery?now=' + NOW).get_json()['photos']
    assert [p['event_title'] for p in photos] == ['New', 'Old']
    assert login(app, None).get(photos[0]['url']).status_code == 200


def test_deleting_an_event_removes_its_files(app):
    event = _make(app, start='2030-06-01T10:00:00')
    admin = login(app, ADMIN)
    photo = _upload(admin, event['id'], PNG).get_json()
    path = os.path.join(app.config['UPLOAD_FOLDER'], 'events', photo['url'].rsplit('/', 1)[1])
    assert os.path.exists(path)
    admin.delete('%s/%d' % (BASE, event['id']))
    assert not os.path.exists(path)


# --- feature gating -------------------------------------------------------------------------

def test_disabled_feature_returns_404(app):
    admin = login(app, ADMIN)
    assert admin.put('/api/kit/admin/features', json={'features': {'events': False}}).status_code == 200
    assert login(app, None).get(BASE).status_code == 404
    assert admin.post(BASE, json={'title': 'x', 'start': '2030-01-01T10:00:00'}).status_code == 404
    assert admin.put('/api/kit/admin/features', json={'features': {'events': True}}).status_code == 200
    assert login(app, None).get(BASE + '?now=' + NOW).status_code == 200


# --- migration export / import --------------------------------------------------------------

def test_export_import_round_trip_keeps_events_posts_and_photos(app):
    admin = login(app, ADMIN)
    event = _make(app, title='Fair', start='2030-06-01T10:00:00', end='2030-06-01T12:00:00',
                  repeat='weekly', repeat_until='2030-07-01')
    admin.post('%s/%d/skip' % (BASE, event['id']), json={'start': '2030-06-08T10:00:00'})
    admin.post('%s/%d/posts' % (BASE, event['id']),
               json={'title': 'Recap', 'body': 'Thanks', 'kind': 'after', 'publish_at': '2030-06-02T08:00:00'})
    photo = _upload(admin, event['id'], PNG, 'a.png', 'Crowd').get_json()
    counts = admin.get('/api/export/counts').get_json()['counts']
    assert (counts['site_events'], counts['site_event_posts'], counts['site_event_photos']) == (1, 1, 1)
    dump = admin.get('/api/export/all').get_json()
    assert dump['site_event_photos'][0]['data']

    assert admin.delete('%s/%d' % (BASE, event['id'])).status_code == 200
    assert admin.get('/api/export/counts').get_json()['counts']['site_events'] == 0

    r = admin.post('/api/export/import', json={k: dump[k] for k in
                                               ('site_events', 'site_event_posts', 'site_event_photos')})
    results = r.get_json()['results']
    assert [results[k]['imported'] for k in ('site_events', 'site_event_posts', 'site_event_photos')] == [1, 1, 1]
    assert all(results[k]['failed'] == 0 for k in ('site_events', 'site_event_posts', 'site_event_photos'))

    back = login(app, None).get('%s/%d?now=2030-06-03T00:00:00' % (BASE, event['id'])).get_json()
    assert back['title'] == 'Fair' and back['repeat'] == 'weekly' and back['posts'][0]['title'] == 'Recap'
    starts = [e['occurrence_start'] for e in
              login(app, None).get(BASE + '?when=all&now=2030-05-01T00:00:00').get_json()['events']]
    assert '2030-06-08T10:00:00' not in starts and '2030-06-15T10:00:00' in starts  # the skip survived
    new_url = back['photos'][0]['url']
    assert new_url != photo['url'] and login(app, None).get(new_url).data == PNG

    again = admin.post('/api/export/import', json={'site_events': dump['site_events']}).get_json()['results']
    assert again['site_events']['imported'] == 0  # importing twice never duplicates


def test_import_rejects_bad_photo_data_and_orphans(app):
    admin = login(app, ADMIN)
    event = _make(app, start='2030-06-01T10:00:00')
    bad = [{'id': 5, 'event_id': event['id'], 'data': 'bm90IGFuIGltYWdl'},   # "not an image"
           {'id': 6, 'event_id': 9999, 'data': ''}]
    res = admin.post('/api/export/import/site_event_photos', json={'site_event_photos': bad}).get_json()
    assert res['site_event_photos']['failed'] == 2 and res['site_event_photos']['imported'] == 0
    assert login(app, MEMBER).post('/api/export/import/site_events', json={}).status_code == 403


def test_missing_tables_are_created_on_startup(app):
    """A database from before this feature gets its tables when the app starts, with no data loss."""
    from __init__ import db
    from model import site_event
    from model.site_event import SiteEvent, SiteEventPhoto, SiteEventPost
    _make(app, title='Survives')
    with app.app_context():
        site_event.ensure_tables()                      # nothing to do: the data stays
        assert SiteEvent.query.count() == 1
        for model in (SiteEventPhoto, SiteEventPost, SiteEvent):
            model.__table__.drop(db.engine)
        site_event.ensure_tables()
    r = login(app, None).get(BASE + '?now=' + NOW)
    assert r.status_code == 200 and r.get_json()['events'] == []
