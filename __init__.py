from flask import Flask
from flask_login import LoginManager
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from dotenv import load_dotenv
import os
import secrets
import warnings


# Load environment variables from .env file
load_dotenv()


# Setup of key Flask object (app)
app = Flask(__name__)

# Configure Flask Port, default to 8587 which is same as Docker setup
app.config['FLASK_PORT'] = int(os.environ.get('FLASK_PORT') or 8587)

# Configure Code Runner port, default 8591
app.config['RUNNER_PORT'] = int(os.environ.get('RUNNER_PORT') or 8591)

# Configure Flask to handle JSON with UTF-8 encoding versus default ASCII
app.config['JSON_AS_ASCII'] = False  # Allow emojis, non-ASCII characters in JSON responses


# Production mode flag (IS_PRODUCTION=true); enables secure cookies and fail-fast config checks
IS_PRODUCTION = (os.environ.get('IS_PRODUCTION') or 'false').lower() == 'true'
app.config['IS_PRODUCTION'] = IS_PRODUCTION


# Initialize Flask-Login object
login_manager = LoginManager()
login_manager.init_app(app)

# Kit / school identity settings
app.config['SCHOOL_NAME'] = os.environ.get('SCHOOL_NAME') or 'OCS Kit'
app.config['SITE_DOMAIN'] = os.environ.get('SITE_DOMAIN') or None
app.config['FRONTEND_URL'] = os.environ.get('FRONTEND_URL') or 'http://localhost:4500'
# Optional branding for the server-rendered admin pages
app.config['SCHOOL_LOGO_URL'] = os.environ.get('SCHOOL_LOGO_URL') or '/static/assets/kit_logo.svg'
app.config['SOCIAL_GITHUB_URL'] = os.environ.get('SOCIAL_GITHUB_URL') or None
app.config['SOCIAL_TWITTER_URL'] = os.environ.get('SOCIAL_TWITTER_URL') or None
app.config['SOCIAL_YOUTUBE_URL'] = os.environ.get('SOCIAL_YOUTUBE_URL') or None
# Cookie domain for the JWT cookie in production (e.g. '.example.org'); empty means host-only cookie
app.config['COOKIE_DOMAIN'] = os.environ.get('COOKIE_DOMAIN') or None
# Comma-separated list of email domains allowed at signup (e.g. 'example.org,students.example.org'); empty means any
app.config['ALLOWED_EMAIL_DOMAINS'] = [
    d.strip().lower().lstrip('@') for d in (os.environ.get('ALLOWED_EMAIL_DOMAINS') or '').split(',') if d.strip()
]

# Allowed servers for cross-origin resource sharing (CORS)
# Comma-separated list from CORS_ORIGINS; defaults to local development frontends
default_origins = 'http://localhost:4500,http://127.0.0.1:4500,http://localhost:4000,http://127.0.0.1:4000'
allowed_origins = [
    o.strip() for o in (os.environ.get('CORS_ORIGINS') or default_origins).split(',') if o.strip()
]
app.config['CORS_ORIGINS'] = allowed_origins

cors = CORS(
   app,
   supports_credentials=True,
   origins=allowed_origins,
   methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"]
)


# Seeded account defaults
# In development any unset password falls back to 'password'. In production (IS_PRODUCTION=true)
# there is no literal fallback: ADMIN_PASSWORD and DEFAULT_PASSWORD must be set, and the other
# seeded accounts fall back to DEFAULT_PASSWORD.
DEFAULT_PASSWORD = os.environ.get('DEFAULT_PASSWORD') or (None if IS_PRODUCTION else 'password')
if not DEFAULT_PASSWORD:
    raise RuntimeError('DEFAULT_PASSWORD must be set when IS_PRODUCTION=true')
# Admin Defaults
app.config['ADMIN_USER'] = os.environ.get('ADMIN_USER') or 'Admin Name'
app.config['ADMIN_UID'] = os.environ.get('ADMIN_UID') or 'admin'
app.config['ADMIN_PASSWORD'] = os.environ.get('ADMIN_PASSWORD') or (None if IS_PRODUCTION else DEFAULT_PASSWORD)
if not app.config['ADMIN_PASSWORD']:
    raise RuntimeError('ADMIN_PASSWORD must be set when IS_PRODUCTION=true')
app.config['ADMIN_PFP'] = os.environ.get('ADMIN_PFP') or 'default.png'
# Teacher Defaults
app.config['TEACHER_USER'] = os.environ.get('TEACHER_USER') or 'Teacher Name'
app.config['TEACHER_UID'] = os.environ.get('TEACHER_UID') or 'teacher'
app.config['TEACHER_PASSWORD'] = os.environ.get('TEACHER_PASSWORD') or DEFAULT_PASSWORD
app.config['TEACHER_PFP'] = os.environ.get('TEACHER_PFP') or 'default.png'
# Default User Defaults
app.config['USER_NAME'] = os.environ.get('USER_NAME') or 'User Name'
app.config['USER_UID'] = os.environ.get('USER_UID') or 'user'
app.config['USER_PASSWORD'] = os.environ.get('USER_PASSWORD') or DEFAULT_PASSWORD
app.config['USER_PFP'] = os.environ.get('USER_PFP') or 'default.png'
# Defaults
app.config['DEFAULT_PASSWORD'] = DEFAULT_PASSWORD
app.config['DEFAULT_PFP'] = os.environ.get('DEFAULT_PFP') or 'default.png'
# Signing secret for password-reset tokens issued by Spring's ResetCode.java.
# Must match RESET_TOKEN_SECRET in the spring repo's .env -- Flask verifies these
# tokens locally (no call back to Spring). No default -- unset means the
# frontend-driven reset-password endpoint is closed.
app.config['RESET_TOKEN_SECRET'] = os.environ.get('RESET_TOKEN_SECRET')
# Convenience user
app.config['MY_NAME'] = os.environ.get('MY_NAME') or 'convenience'
app.config['MY_UID'] = os.environ.get('MY_UID') or 'convenience'
app.config['MY_PASSWORD'] = os.environ.get('MY_PASSWORD') or DEFAULT_PASSWORD
app.config['MY_PFP'] = os.environ.get('MY_PFP') or 'default.png'
app.config['MY_ROLE'] = os.environ.get('MY_ROLE') or 'User'


# Browser settings
SECRET_KEY = os.environ.get('SECRET_KEY') # secret key for session management and JWT signing
if not SECRET_KEY:
    if IS_PRODUCTION:
        raise RuntimeError('SECRET_KEY must be set when IS_PRODUCTION=true')
    SECRET_KEY = secrets.token_hex(32)
    warnings.warn('SECRET_KEY not set; using a random key for this process (sessions/JWTs reset on restart)')
SESSION_COOKIE_NAME = os.environ.get('SESSION_COOKIE_NAME') or 'sess_python_flask'
JWT_TOKEN_NAME = os.environ.get('JWT_TOKEN_NAME') or 'jwt_python_flask'
JWT_TOKEN_MAX_AGE = int(os.environ.get('JWT_TOKEN_MAX_AGE') or 604800)  # Default: 1 week (604800 seconds)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SESSION_COOKIE_NAME'] = SESSION_COOKIE_NAME
app.config['JWT_TOKEN_NAME'] = JWT_TOKEN_NAME
app.config['JWT_TOKEN_MAX_AGE'] = JWT_TOKEN_MAX_AGE


# Database settings
dbName = 'user_management'
DB_ENDPOINT = os.environ.get('DB_ENDPOINT') or None
DB_USERNAME = os.environ.get('DB_USERNAME') or None
DB_PASSWORD = os.environ.get('DB_PASSWORD') or None
if DB_ENDPOINT and DB_USERNAME and DB_PASSWORD:
   # Production - Use MySQL
   DB_PORT = '3306'
   DB_NAME = dbName
   dbString = f'mysql+pymysql://{DB_USERNAME}:{DB_PASSWORD}@{DB_ENDPOINT}:{DB_PORT}'
   dbURI =  dbString + '/' + dbName
   backupURI = None  # MySQL backup would require a different approach
else:
   # Development - Use SQLite
   dbString = 'sqlite:///volumes/'
   dbURI = dbString + dbName + '.db'
   backupURI = dbString + dbName + '_bak.db'
# Set database configuration in Flask app
app.config['DB_ENDPOINT'] = DB_ENDPOINT
app.config['DB_USERNAME'] = DB_USERNAME
app.config['DB_PASSWORD'] = DB_PASSWORD
app.config['SQLALCHEMY_DATABASE_NAME'] = dbName
app.config['SQLALCHEMY_DATABASE_STRING'] = dbString
app.config['SQLALCHEMY_DATABASE_URI'] = dbURI
app.config['SQLALCHEMY_BACKUP_URI'] = backupURI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)


# Image upload settings
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # maximum size of uploaded content
app.config['UPLOAD_EXTENSIONS'] = ['.jpg', '.png', '.gif']  # supported file types
app.config['UPLOAD_FOLDER'] = os.path.join(app.instance_path, 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Data folder for shared file-based storage
app.config['DATA_FOLDER'] = os.path.join(app.instance_path, 'data')
os.makedirs(app.config['DATA_FOLDER'], exist_ok=True)


# GITHUB settings
app.config['GITHUB_API_URL'] = 'https://api.github.com'
app.config['GITHUB_TOKEN'] = os.environ.get('GITHUB_TOKEN') or None
app.config['GITHUB_TARGET_TYPE'] = os.environ.get('GITHUB_TARGET_TYPE') or 'user'
app.config['GITHUB_TARGET_NAME'] = os.environ.get('GITHUB_TARGET_NAME') or None  # GitHub org/user for analytics; unset disables
# Repo ('owner/name') that receives user feedback as GitHub issues; unset disables issue creation
app.config['FEEDBACK_GITHUB_REPO'] = os.environ.get('FEEDBACK_GITHUB_REPO') or None


# Gemini API settings
app.config['GEMINI_SERVER'] = os.environ.get('GEMINI_SERVER') or 'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent'
app.config['GEMINI_API_KEY'] = os.environ.get('GEMINI_API_KEY') or None


# KASM settings
app.config['KASM_SERVER'] = os.environ.get('KASM_SERVER') or None  # unset disables KASM features
app.config['KASM_API_KEY'] = os.environ.get('KASM_API_KEY') or None
app.config['KASM_API_KEY_SECRET'] = os.environ.get('KASM_API_KEY_SECRET') or None


# GROQ API settings
app.config['GROQ_SERVER'] = os.environ.get('GROQ_SERVER') or 'https://api.groq.com/openai/v1/chat/completions'
app.config['GROQ_API_KEY'] = os.environ.get('GROQ_API_KEY') or None