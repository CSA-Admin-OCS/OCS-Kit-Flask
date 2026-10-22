"""Server-rendered admin page for personas ('social' feature)."""
from flask import Blueprint, render_template

from api.authorize import admin_page_required as admin_required
from model.persona import Persona

persona_admin = Blueprint('persona_admin', __name__)


@persona_admin.route('/persona/')
@admin_required
def persona():
    personas = Persona.query.all()
    return render_template("persona.html", personas=personas)
