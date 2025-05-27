from flask import Blueprint
from flask_sqlalchemy import SQLAlchemy

subsys_bp = Blueprint(
    'subsys',
    __name__,
    template_folder='templates',
    static_folder='static'
)

db = SQLAlchemy()

def init_app(app):
    with app.app_context():
        db.init_app(app)
        db.create_all(bind=['subsys'])

from . import routes