# /opt/ytt/app/__init__.py
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

# your existing config loader and limiter
from .config import load_config
from .extensions import limiter

# new imports for auth/db/login
from flask_login import LoginManager
from .models import db, User  # requires you to create app/models.py
# Note: importing User here only to register user_loader; it's safe if models.py exists.

from flask_migrate import Migrate

migrate = Migrate()

login_manager = LoginManager()
login_manager.login_view = "auth.login"  # best-effort default; adjust if you use a different route name


def create_app(config_object=None):
    """
    Create and configure the Flask application.

    - Preserves your prior behavior (load_config, ProxyFix, limiter).
    - Initializes SQLAlchemy (db) and Flask-Login (login_manager).
    - Registers blueprints: main (required), and optional auth/api if present.
    """

    app = Flask(__name__, static_folder="static", template_folder="templates")

    # Load app config from your existing loader first (this mirrors your previous flow)
    load_config(app)

    # Allow optional programmatic overrides (keeps compatibility with earlier create_app signature)
    if config_object:
        app.config.from_object(config_object)

    # Ensure some sensible defaults if not set by load_config (won't override loaded config)
    app.config.setdefault("SECRET_KEY", "replace-this-with-a-secure-random-value")
    app.config.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///ytt.db")
    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")

    # Apply ProxyFix exactly as before
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    # --- Initialize extensions that require app context ---

    # SQLAlchemy init
    db.init_app(app)

    # ✅ 初始化 Flask-Migrate（之後才能 flask db migrate / upgrade）
    migrate.init_app(app, db)

    # Flask-Login init
    login_manager.init_app(app)

    # Limiter (preserve your existing code)
    storage = app.config.get("REDIS_URL") or "memory://"
    app.config.setdefault("RATELIMIT_STORAGE_URI", storage)
    limiter.init_app(app)

    # Register blueprints
    # - main_bp was previously imported from .routes as `bp` -> keep that behavior
    # - Try to register auth and api blueprints if available (non-fatal if missing)
    from .routes import bp as main_bp
    app.register_blueprint(main_bp)

    # optional: auth and api blueprints (if you created them)
    try:
        from .auth import auth_bp
    except Exception:
        auth_bp = None

    try:
        from .api import api_bp
    except Exception:
        api_bp = None

    if auth_bp:
        app.register_blueprint(auth_bp)
    if api_bp:
        app.register_blueprint(api_bp)

    try:
        from .payments import payments_bp
        app.register_blueprint(payments_bp)
    except Exception:
        app.logger.exception("payments blueprint not loaded")

    # Health endpoint identical to before
    @app.get("/healthz")
    def health():
        return {"status": "ok", "storage": storage}

    # Make GA_MEASUREMENT_ID available in all templates as {{ GA_MEASUREMENT_ID }}
    @app.context_processor
    def inject_ga():
        return {
            "GA_MEASUREMENT_ID": app.config.get("GA_MEASUREMENT_ID")
        }

    # User loader for Flask-Login (uses models.User)
    @login_manager.user_loader
    def load_user(user_id):
        try:
            return User.query.get(int(user_id))
        except Exception:
            return None

    return app
