# imports from flask
from urllib.parse import urljoin, urlparse
from flask import abort, redirect, render_template, request, send_from_directory, url_for, jsonify, current_app, g # import render_template from "public" flask libraries
from flask_login import current_user, login_user, logout_user
from flask.cli import AppGroup
from flask_login import current_user, login_required
from flask import current_app
from dotenv import load_dotenv

# import "objects" from "this" project
from __init__ import app, db, login_manager  # Key Flask objects 
import features  # kit feature registry; kits/catalog.json says what belongs to each feature
import roles  # role names and per-kit labels from kits/catalog.json
from api.authorize import admin_page_required, staff_page_required

# Models: every feature's models are imported whatever the kit, so all tables and
# foreign keys exist in every kit (the User model relates to personas, posts, etc.).
features.import_all_models()
from model.user import User, Section, initUsers  # initUsers: used by scripts/db_migrate-prod2sqlite.py

import os

# Effective features = KIT preset -> FEATURES env -> admin overrides in the database
# (PUT /api/kit/admin/features). Overrides are read per request, so no restart is needed.
from model import feature_override
features.set_override_provider(feature_override.read_overrides)

# API endpoints: every feature's blueprints are registered, and a request to a blueprint whose
# feature(s) are disabled right now gets 404 (see kits/catalog.json, features.py).
# Validate the mapping with: python -m features --check
_registered = features.register_blueprints(app)

with app.app_context():
    feature_override.ensure_tables()  # databases created before admin overrides existed
    print(f"** Kit: {features.kit_name()} | features: {', '.join(features.enabled_features())}")
    # Startup hooks of enabled features (e.g. the jokes file for 'examples')
    features.run_hooks('startup')

# Tell Flask-Login the view function name of your login route
login_manager.login_view = "login"

@login_manager.unauthorized_handler
def unauthorized_callback():
    return redirect(url_for('login', next=request.path))

# register URIs for server pages
@login_manager.user_loader
def load_user(user_id):
    # user_id is the composite "id:token_version" from User.get_id(). A mismatched
    # token_version means the session predates a password change on this account --
    # returning None here tells Flask-Login the session is invalid.
    #
    # A session issued before this field existed at all has no ":" -- treat that as
    # token_version "0" (matching a fresh/unchanged account) instead of invalidating
    # it outright. It still correctly fails below once the account's real
    # token_version has moved past 0 from an actual password change.
    if ":" in user_id:
        raw_id, token_version = user_id.split(":", 1)
    else:
        raw_id, token_version = user_id, "0"
    try:
        raw_id = int(raw_id)
    except ValueError:
        return None
    user = User.query.get(raw_id)
    if user is None or str(user.token_version) != token_version:
        return None
    return user

@app.context_processor
def inject_user():
    return dict(current_user=current_user)

@app.context_processor
def inject_kit_config():
    # School branding for server-rendered admin pages (see .env.example)
    return dict(
        school_name=app.config.get('SCHOOL_NAME'),
        school_logo=app.config.get('SCHOOL_LOGO_URL'),
        site_domain=app.config.get('SITE_DOMAIN'),
        frontend_url=app.config.get('FRONTEND_URL'),
        social_github=app.config.get('SOCIAL_GITHUB_URL'),
        social_twitter=app.config.get('SOCIAL_TWITTER_URL'),
        social_youtube=app.config.get('SOCIAL_YOUTUBE_URL'),
        # Kit features: templates hide links to disabled features
        kit_features=features.enabled_features(),
        # Role labels of this kit, e.g. {'Admin': 'Admin', 'Teacher': 'Manager', 'User': 'Member'}
        role_labels=roles.labels(),
        admin_links=features.admin_links(),
    )

# Helper function to check if the URL is safe for redirects
def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    next_page = request.args.get('next', '') or request.form.get('next', '')
    if request.method == 'POST':
        user = User.query.filter_by(_uid=request.form['username']).first()
        if user and user.is_password(request.form['password']):
            login_user(user)
            if not is_safe_url(next_page):
                return abort(400)
            return redirect(next_page or url_for('index'))
        else:
            error = 'Invalid username or password.'
    return render_template("login.html", error=error, next=next_page)

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.errorhandler(404)  # catch for URL not found
def page_not_found(e):
    # note that we set the 404 status explicitly
    return render_template('404.html'), 404

@app.route('/')  # connects default URL to index() function
def index():
    print("Home:", current_user)
    return render_template("index.html")



# Admin pages. Staff (e.g. Teacher / Manager / Editor) may view users and sections; changing
# or deleting accounts is admin-only. Anonymous visitors are sent to /login, others get 403.
@app.route('/users/table2')
@staff_page_required
def u2table():
    users = User.query.all()
    return render_template("u2table.html", user_data=users)

@app.route('/sections/')
@staff_page_required
def sections():
    sections = Section.query.all()
    return render_template("sections.html", sections=sections)

# Helper function to extract uploads for a user (ie PFP image)
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)
 
@app.route('/users/delete/<int:user_id>', methods=['DELETE'])
@admin_page_required
def delete_user(user_id):
    user = User.query.get(user_id)
    if user:
        user.delete()
        return jsonify({'message': 'User deleted successfully'}), 200
    return jsonify({'error': 'User not found'}), 404

@app.route('/users/reset_password/<int:user_id>', methods=['POST'])
@admin_page_required
def reset_password(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Set the new password
    if user.update({"password": app.config['DEFAULT_PASSWORD']}):
        return jsonify({'message': 'Password reset successfully'}), 200
    return jsonify({'error': 'Password reset failed'}), 500

@app.route('/update_user/<string:uid>', methods=['PUT'])
@admin_page_required
def update_user(uid):
    # Get the JSON data from the request
    data = request.get_json()
    print(f"Request Data: {data}")  # Log the incoming data

    # Find the user in the database
    user = User.query.filter_by(_uid=uid).first()
    if user:
        print(f"Found user: {user.uid}")  # Log the found user's UID
        
        # Update the user using the provided data
        user.update(data)  # Assuming `user.update(data)` is a method on your User model
        
        # Save changes to the database
        return jsonify({"message": "User updated successfully."}), 200
    else:
        print("User not found.")  # Log when user is not found
        return jsonify({"message": "User not found."}), 404



    
# Create an AppGroup for custom commands
custom_cli = AppGroup('custom', help='Custom commands')

# Define a command to run the data generation functions
@custom_cli.command('generate_data')
def generate_data():
    # Seed functions of enabled features, in catalog order (core's initUsers first)
    features.run_hooks('seed')

# Register the custom command group with the Flask application
app.cli.add_command(custom_cli)
        
# this runs the flask application on the development server
if __name__ == "__main__":
    host = "0.0.0.0"
    port = app.config['FLASK_PORT']
    print(f"** Server running: http://localhost:{port}")  # Pretty link
    app.run(debug=True, host=host, port=port, use_reloader=False)
