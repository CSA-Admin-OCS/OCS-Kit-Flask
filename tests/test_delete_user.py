"""Deleting a user: DELETE /api/user and the admin table's /users/delete/<id> follow the same rules.
Foreign keys are enforced here, as MySQL does in production, so a user who still owns records cannot be removed."""
import pytest
from sqlalchemy import event

from conftest import ADMIN, PASSWORD, STAFF, login


@pytest.fixture
def foreign_keys(app):
    from __init__ import db

    def on(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
    with app.app_context():
        event.listen(db.engine, 'connect', on)
        db.engine.dispose()
        yield
        event.remove(db.engine, 'connect', on)
        db.engine.dispose()


def _make_user(app, uid, owns_classroom=False):
    from model.classroom import Classroom
    from model.user import User
    with app.app_context():
        User(name=uid, uid=uid, password=PASSWORD).create()
        user = User.query.filter_by(_uid=uid).first()
        if owns_classroom:
            Classroom(name='Owned', organization_name='Organization', owner_teacher_id=user.id).create()
        return user.id


def _exists(app, uid):
    from model.user import User
    with app.app_context():
        return User.query.filter_by(_uid=uid).first() is not None


def _delete_by_api(client, uid, id_):
    return client.delete('/api/user', json={'uid': uid})


def _delete_by_page(client, uid, id_):
    return client.delete(f'/users/delete/{id_}')


BOTH = pytest.mark.parametrize('delete', [_delete_by_api, _delete_by_page], ids=['api', 'page'])


@BOTH
def test_admin_deletes_a_user(app, foreign_keys, delete):
    id_ = _make_user(app, 'doomed')
    r = delete(login(app, ADMIN), 'doomed', id_)
    assert r.status_code == 200 and 'doomed' in r.get_json()['message']
    assert not _exists(app, 'doomed')


@BOTH
def test_user_who_owns_records_is_kept_and_the_answer_says_so(app, foreign_keys, delete):
    id_ = _make_user(app, 'owner', owns_classroom=True)
    r = delete(login(app, ADMIN), 'owner', id_)
    assert r.status_code == 409 and 'still owns records' in r.get_json()['message']
    assert _exists(app, 'owner')


@BOTH
def test_admin_cannot_delete_their_own_account(app, foreign_keys, delete):
    from model.user import User
    with app.app_context():
        admin_id = User.query.filter_by(_uid=ADMIN).first().id
    r = delete(login(app, ADMIN), ADMIN, admin_id)
    assert r.status_code == 400 and 'your own account' in r.get_json()['message']
    assert _exists(app, ADMIN)


@BOTH
def test_unknown_user_is_404(app, delete):
    assert delete(login(app, ADMIN), 'nobody-here', 999999).status_code == 404


@pytest.mark.parametrize('kwargs', [{}, {'json': {}}, {'json': []}, {'json': {'uid': 5}}, {'data': 'not json'}])
def test_api_body_without_a_uid_is_400_not_500(app, kwargs):
    assert login(app, ADMIN).delete('/api/user', **kwargs).status_code == 400


def test_staff_cannot_delete_users(app):
    assert login(app, STAFF).delete('/api/user', json={'uid': 'doomed'}).status_code == 403
