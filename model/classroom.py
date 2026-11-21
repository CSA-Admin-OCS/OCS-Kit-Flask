from datetime import datetime
from sqlalchemy.exc import IntegrityError
from __init__ import db

# Association table for many-to-many between classrooms and students
classroom_student = db.Table(
    'classroom_student',
    db.Column('classroom_id', db.Integer, db.ForeignKey('classrooms.id'), primary_key=True),
    db.Column('student_id', db.Integer, db.ForeignKey('users.id'), primary_key=True)
)

def pick_organization_name(data):
    """The classroom's organization in a request or an export: "organization_name", else the old names
    "school_name" and "schoolName" that Pages, Spring and older exports still send."""
    return data.get('organization_name') or data.get('school_name') or data.get('schoolName')


class Classroom(db.Model):
    __tablename__ = 'classrooms'

    id = db.Column(db.Integer, primary_key=True)
    _name = db.Column(db.String(255), nullable=False)
    _organization_name = db.Column('_school_name', db.String(255), nullable=False)  # column name kept for existing databases
    _owner_teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    _status = db.Column(db.String(50), default='active')
    _created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Many-to-many relationship with User (students)
    students = db.relationship(
        'User',
        secondary=classroom_student,
        backref=db.backref('classrooms', lazy='dynamic'),
        lazy='dynamic'
    )

    def __init__(self, name, organization_name, owner_teacher_id, status='active'):
        self._name = name
        self._organization_name = organization_name
        self._owner_teacher_id = owner_teacher_id
        self._status = status

    @property
    def name(self): return self._name
    @name.setter
    def name(self, val): self._name = val

    @property
    def organization_name(self): return self._organization_name
    @organization_name.setter
    def organization_name(self, val): self._organization_name = val

    @property
    def owner_teacher_id(self): return self._owner_teacher_id
    @owner_teacher_id.setter
    def owner_teacher_id(self, val): self._owner_teacher_id = val

    @property
    def status(self): return self._status
    @status.setter
    def status(self, val): self._status = val

    @property
    def created_at(self): return self._created_at

    def create(self):
        try:
            db.session.add(self)
            db.session.commit()
            return self
        except IntegrityError:
            db.session.rollback()
            return None

    def update(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self, key) and key != 'id':
                setattr(self, key, value)
        db.session.commit()
        return self

    def delete(self):
        db.session.delete(self)
        db.session.commit()

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'organization_name': self.organization_name,
            'owner_teacher_id': self.owner_teacher_id,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'students': [s.id for s in self.students]
        }
