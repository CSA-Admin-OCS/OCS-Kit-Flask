"""Server-rendered admin page for personas ('social' feature)."""
from flask import Blueprint, render_template
from flask_login import login_required

from model.persona import Persona

persona_admin = Blueprint('persona_admin', __name__)


@persona_admin.route('/persona/')
@login_required
def persona():
    personas = Persona.query.all()
    return render_template("persona.html", personas=personas)
