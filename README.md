# OCS Kit - Flask Backend

The Python/Flask backend of OCS-in-a-Kit. It provides:

- REST APIs for the frontend (`api/`): user accounts and JWT cookie login, sections and classrooms, microblogs and posts, leaderboards, AI chat proxies (Gemini, Groq), code runners, and more.
- A small admin UI (`templates/`, Jinja2) for managing users, sections and personas.
- SQLAlchemy models (`model/`). SQLite by default (`instance/volumes/user_management.db`), with MySQL supported for production.

All school-specific settings, such as your domain, CORS origins, seeded accounts and API keys, come from environment variables. See [`.env.example`](.env.example) for the full list.

## Quick start (Docker)

You need Docker with the Compose plugin.

```bash
git clone <your-copy-of-this-repo> flask
cd flask
cp .env.example .env
# Edit .env: at minimum set SCHOOL_NAME, SECRET_KEY, ADMIN_PASSWORD and DEFAULT_PASSWORD
docker compose up -d --build
```

On first boot, `entrypoint.sh` creates the SQLite database and the seeded accounts (`ADMIN_UID`, `TEACHER_UID`, `USER_UID`). The backend listens on <http://localhost:8587>. Log in to the admin UI at <http://localhost:8587/login> with the admin account.

The compose file also starts:
- `socketio` on port 8500, used by the multiplayer features
- `code_runner`, a locked-down container for the Python/JavaScript code-execution APIs

Data lives in `./instance` on the host, which is mounted into the container. Back up that folder.

To wipe and re-create the database, set `DB_INIT=true` for one start. This is destructive and drops all tables.

## Going to production

1. In `.env`, set `IS_PRODUCTION=true`. The app then refuses to start without `SECRET_KEY`, `ADMIN_PASSWORD` and `DEFAULT_PASSWORD`, and it sends secure, cross-site cookies.
2. Set `CORS_ORIGINS` to your frontend origin(s), e.g. `https://pages.example.org`.
3. Set `COOKIE_DOMAIN` (e.g. `.example.org`) if the frontend and backend are on different subdomains.
4. Optionally, set `ALLOWED_EMAIL_DOMAINS` to limit signups to your school's email domains.
5. Put nginx in front of the backend using [`deploy/nginx.conf.template`](deploy/nginx.conf.template). The instructions for filling it in with `envsubst` and getting a certificate with certbot are at the top of that file.
6. To use MySQL instead of SQLite, set `DB_ENDPOINT`, `DB_USERNAME` and `DB_PASSWORD`. Set `DB_INIT=true` for the first boot only.

Optional features turn themselves off when their settings are empty:
- Gemini and Groq AI chat
- Kasm virtual desktops
- GitHub feedback issues (`FEEDBACK_GITHUB_REPO`)
- The skill-snapshot automator

## Local development

Requires Python 3.10 or newer.

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # optional in development; defaults are used for empty values
python scripts/db_init.py     # create tables and seed accounts
python main.py                # http://localhost:8587
```

In development, any unset seeded password defaults to `password`. If `SECRET_KEY` is unset, a random key is generated at startup, so logins reset on every restart.

For the local frontend, the default `CORS_ORIGINS` allows `http://localhost:4500`, `http://127.0.0.1:4500`, `http://localhost:4000` and `http://127.0.0.1:4000`.

Test the login API:

```bash
curl -i -X POST http://localhost:8587/api/authenticate \
  -H 'Content-Type: application/json' -H 'X-Origin: client' \
  -d '{"uid": "admin", "password": "password"}'
```

## Project layout

| Path | Purpose |
|------|---------|
| `main.py` | App entry point: registers blueprints and admin routes |
| `__init__.py` | Flask app, configuration from environment, database setup |
| `api/` | REST API blueprints |
| `model/` | SQLAlchemy models and seed data |
| `templates/`, `static/` | Admin UI |
| `scripts/` | Database init, migration and restore scripts |
| `socket/` | Socket.IO service |
| `runner/` | Sandboxed code-runner service |
| `deploy/` | nginx config templates |
| `instance/` | Runtime data: database, uploads (not in git) |

## Database scripts

- `scripts/db_init.py` drops all tables, recreates them and seeds the default data. It asks for confirmation unless `FORCE_YES=true`. It backs up SQLite to `instance/volumes/user_management_bak.db`, or MySQL with `mysqldump` to `instance/backups/`.
- `scripts/db_migrate-prod2sqlite.py` pulls all data from a running server (`FLASK_BASE_URL`) into the local SQLite database through the admin-only `/api/export/*` endpoints.
- `scripts/db_restore-sqlite2prod.py` pushes local data back to that server.

To change the schema on a server that already has data:
1. Deploy the new code.
2. Pull the data locally with `db_migrate-prod2sqlite.py`.
3. Run `db_init.py` on the server.
4. Restore with `db_restore-sqlite2prod.py`.

Both transfer scripts reconcile row counts and exit non-zero if any table did not transfer completely. Do not continue past a failure.

If you add a model, also add it to `MIGRATED_MODELS` and the export/import endpoints in `api/data_export_import_api.py`, and to both transfer scripts. Otherwise its data is lost during a migration.

## License

See [LICENSE](LICENSE).
