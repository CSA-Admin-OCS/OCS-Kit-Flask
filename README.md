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

## Choosing a kit

A kit is a preset list of features. Pick one with `KIT` in `.env`:

| `KIT` | What you get |
|-------|--------------|
| `vanilla` | Core only: accounts, login, sections, classrooms, profile pictures, data export/import, feedback, admin pages. Safe to give to students. |
| `education` | A CS classroom: core, lessons, code runners, assignments, game engine, AI chatbot, AI grading, calendar, analytics, hall pass and social. |
| `business` | Core plus every *general* feature: code runners, game engine, AI chatbot, social, calendar, analytics, finance sim, resume, Kasm, face recognition and examples. It leaves out the *education* features: lessons, assignments, AI grading and hall pass. |
| *(empty)* | Every feature, as before kits existed. `/api/kit` then reports `"kit": "default"`. |

Each feature has a **category**: `core` is always on, `general` features are useful to any organization, and `education` features are for classrooms. Each feature also has **labels** that say what it needs and what data it handles, such as `needs-api-key`, `personal-data`, `student-safe` or `runs-code`. Check the labels before you turn a feature on. The full list is in [`kits/catalog.json`](kits/catalog.json).

| Feature | Category | Flask endpoints (prefix) |
|---------|----------|--------------------------|
| `core` | core | `/api/kit`, `/api/authenticate`, `/api/user`, `/api/section`, `/api/id` (pfp), `/api/classrooms`, `/api/export`, `/api/feedback`, admin pages |
| `code-runner` | general | `/run/python`, `/run/javascript` |
| `game-engine` | general | `/api/ainpc`, `/api/profile/game`, `/api/dynamic`, `/api/events` |
| `ai-chatbot` | general | `/api/gemini`, `/api/groq` |
| `ai-grading` | education | No endpoints of its own. It uses `/api/gemini`, including `/api/gemini/summarize-submissions`, so turning it on registers the Gemini proxy even when `ai-chatbot` is off. |
| `social` | general | `/api/microblog`, `/api/post`, `/api/persona`, `/persona/` admin page |
| `analytics` | general | `/api/analytics`, `/api/user/skill-passport`, `/api/user/skill-snapshot`, `/api/admin/skill-passport`, `/api/snapshot` |
| `assignments` | education | `/api/study` (`/api/grade` exists but is not registered) |
| `kasm` | general | `/kasm_users` admin page; Kasm user sync in the User model |
| `examples` | general | `/api/jokes`, `/api/student/*`, `/api/students`, `/api/congrats` |
| `lessons`, `calendar`, `hallpass`, `finance-sim`, `resume`, `face-recognition` | | No Flask code. These are served by the Pages and Spring backends. |

Check what is running with `curl http://localhost:8587/api/kit`. It needs no login and returns e.g. `{"kit": "education", "name": "OCS Education", "customized": false, "features": ["core", ...], "feature_details": [{"id": "core", "name": "Core platform", "category": "core", "labels": [...]}, ...]}`. Endpoints of disabled features return 404, and their admin links are hidden. `python -m features --list` prints the kits, categories and features, and shows which are enabled.

### Customizing features

`FEATURES` changes the kit's list:

```bash
KIT=education
KIT=business
FEATURES=+hallpass,-kasm       # add or remove features relative to the kit
FEATURES=+*                    # the kit plus every other feature
FEATURES=ai-chatbot,social     # an explicit list replaces the kit (core is always added)
FEATURES=*,-kasm               # every feature except Kasm
```

`core` is always on and cannot be removed. An unknown kit or feature id stops the app at startup with an error that lists the valid ids. Restart the container after you change `.env`.

Every feature's database tables are always created, whatever the kit. Only the seed data and the API endpoints depend on the kit. So you can turn a feature on later without a migration: restart and its endpoints appear (re-run `scripts/db_init.py` only if you also want its sample data).

### Adding a new feature

All the wiring lives in [`kits/catalog.json`](kits/catalog.json). `main.py` and `scripts/db_init.py` read it and need no edits.

1. Add the feature (id, name, category, labels, description) to the canonical `OCS-Kit/kits/catalog.json`, and add it to the kit presets that should include it. Copy those entries, and the `categories`, `labels` and `kits` maps, verbatim into this repo's `kits/catalog.json`.
2. Write the code: a blueprint in `api/`, and any models in `model/`.
3. In this repo's catalog, under the feature's `"flask"` block, list:
   - `blueprints`: `"api.my_api:my_api"`. These are registered only when the feature is on. Each blueprint has exactly one owning feature.
   - `uses_blueprints` (optional): blueprints owned by another feature that this feature also needs. They are registered when either feature is on.
   - `models`: `"model.my_model"`. These are always imported, so their tables always exist.
   - `seed`: `"model.my_model:initMyThings"`. `db_init.py` runs these when the feature is on.
   - `startup` (optional): functions that run at app start when the feature is on.
   - `admin_links` (optional): `{"label": "My Page", "endpoint": "my_api.my_page"}` adds a link to the admin navbar.
4. Run `python -m features --check` and `python -m pytest tests`. The check fails on unknown ids, categories or labels, references that don't import, a blueprint claimed by two features, any blueprint in `api/` or `hacks/` that no feature lists (so new code can't skip gating), and drift from the canonical catalog.

To add a feature to an existing feature's code, append to that feature's lists instead.

## Going to production

1. In `.env`, set `IS_PRODUCTION=true`. The app then refuses to start without `SECRET_KEY`, `ADMIN_PASSWORD` and `DEFAULT_PASSWORD`, and it sends secure, cross-site cookies.
2. Set `CORS_ORIGINS` to your frontend origin(s), e.g. `https://pages.example.org`.
3. Set `COOKIE_DOMAIN` (e.g. `.example.org`) if the frontend and backend are on different subdomains.
4. Optionally, set `ALLOWED_EMAIL_DOMAINS` to limit signups to your school's email domains.
5. Put nginx in front of the backend using [`deploy/nginx.conf.template`](deploy/nginx.conf.template). The instructions for filling it in with `envsubst` and getting a certificate with certbot are at the top of that file.
6. To use MySQL instead of SQLite, set `DB_ENDPOINT`, `DB_USERNAME` and `DB_PASSWORD`. Set `DB_INIT=true` for the first boot only.

Within the enabled kit features, integrations that need settings turn themselves off when those settings are empty:
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
| `main.py` | App entry point: registers enabled features' blueprints and core admin routes |
| `features.py`, `kits/catalog.json` | Kit feature registry (`python -m features --list` / `--check`) |
| `tests/` | `python -m pytest tests` |
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

- `scripts/db_init.py` drops all tables, recreates every table (all features) and seeds the default data of the enabled features. It asks for confirmation unless `FORCE_YES=true`. It backs up SQLite to `instance/volumes/user_management_bak.db`, or MySQL with `mysqldump` to `instance/backups/`.
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
