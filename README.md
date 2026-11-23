<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="static/assets/ocs_backend_logo_dark.png"><img src="static/assets/ocs_backend_logo.png" alt="OCS-in-a-Kit Backend" width="460"></picture></p>

# OCS Kit - Flask Backend

The Python/Flask backend of OCS-in-a-Kit. It provides:

- REST APIs for the frontend (`api/`): user accounts and JWT cookie login, sections and classrooms, microblogs and posts, leaderboards, AI chat proxies (Gemini, Groq), code runners, and more.
- A small admin UI (`templates/`, Jinja2) for managing users, sections and personas.
- SQLAlchemy models (`model/`). SQLite by default (`instance/volumes/user_management.db`), with MySQL supported for production.

All organization-specific settings, such as your domain, CORS origins, seeded accounts and API keys, come from environment variables. See [`.env.example`](.env.example) for the full list.

## Quick start (Docker)

You need Docker with the Compose plugin.

```bash
git clone <your-copy-of-this-repo> flask
cd flask
cp .env.example .env
# Edit .env: at minimum set ORG_NAME, SECRET_KEY, ADMIN_PASSWORD and DEFAULT_PASSWORD
docker compose up -d --build
```

On first boot, `entrypoint.sh` creates the SQLite database and one seeded account per role. The kit picks their default uids (see [Roles](#roles)), and `ADMIN_UID`, `TEACHER_UID` and `USER_UID` override them. The backend listens on <http://localhost:8587>. Its home page introduces the backend: your organization and kit, the three roles, the features that are on, the admin tools the signed-in person may open, and a short API example. The **Q&A** page at <http://localhost:8587/help/> answers how to use every feature, and anyone can open it. **OCS JumpStart** at <http://localhost:8587/jumpstart/> is the in-depth guide to how the backend works, in 18 chapters from the first run to deployment; anyone can open it, and tests check it against the code. The sun and moon switch in the top bar changes every page between light and dark mode; it follows your computer's setting until you choose, and your browser remembers the choice. Log in to the admin UI at <http://localhost:8587/login> with the admin account.

The compose file also starts:
- `socketio` on port 8500, used by the multiplayer features
- `code_runner`, a locked-down container for the Python/JavaScript code-execution APIs

Data lives in `./instance` on the host, which is mounted into the container. Back up that folder.

To wipe and re-create the database, set `DB_INIT=true` for one start. This is destructive and drops all tables.

## Choosing a kit

A kit is a preset list of features with its own names for the three roles. Pick one with `KIT` in `.env`:

| `KIT` | Features | Roles (admin / staff / member) and seeded uids |
|-------|----------|-----------------------------------------------|
| `vanilla` | Core only: accounts, login, sections, classrooms, profile pictures, data export/import, feedback, admin pages. Safe to give to students. | Admin / Editor / User: `admin`, `editor`, `user` |
| `education` | Core plus lessons, code runners, assignments, game engine, AI chatbot, AI grading, calendar, analytics, hall pass, social and resume. | Admin / Teacher / Student: `admin`, `teacher`, `student` |
| `business` | Core plus AI chatbot, social, calendar, analytics and resume. | Admin / Manager / Member: `admin`, `manager`, `member` |
| *(empty)* | Every feature, as before kits existed. `/api/kit` reports `"kit": "default"`. | Admin / Teacher / User: `admin`, `teacher`, `user` |

Each feature has a **category**: `core` is always on, `general` features are useful to any organization, and `education` features are for classrooms. Each feature also has **labels** that say what it needs and what data it handles, such as `needs-api-key`, `personal-data`, `student-safe` or `runs-code`. Check the labels before you turn a feature on. Each feature also has a **setup guide**: the settings it needs and which service reads them, the manual steps, and how to check that it works. It all lives in [`kits/catalog.json`](kits/catalog.json), and `python -m features --list` prints a summary.

| Feature | Category | Flask endpoints (prefix) |
|---------|----------|--------------------------|
| `core` | core | `/api/kit`, `/api/authenticate`, `/api/user`, `/api/section`, `/api/id` (pfp), `/api/classrooms`, `/api/export`, `/api/feedback`, admin pages |
| `code-runner` | general | `/run/python`, `/run/javascript` |
| `game-engine` | general | `/api/ainpc`, `/api/profile/game`, `/api/dynamic`, `/api/events` |
| `ai-chatbot` | general | `/api/gemini`, `/api/groq` |
| `ai-grading` | education | No endpoints of its own. It uses `/api/gemini`, including `/api/gemini/summarize-submissions`, so turning it on serves the Gemini proxy even when `ai-chatbot` is off. |
| `social` | general | `/api/microblog`, `/api/post`, `/api/persona`, `/persona/` admin page |
| `analytics` | general | `/api/analytics`, `/api/user/skill-passport`, `/api/user/skill-snapshot`, `/api/admin/skill-passport`, `/api/snapshot` |
| `assignments` | education | `/api/study` (`/api/grade` exists but is never served) |
| `examples` | general | `/api/jokes`, `/api/student/*`, `/api/students`, `/api/congrats` |
| `lessons`, `calendar`, `hallpass`, `finance-sim`, `resume`, `face-recognition`, `kasm` | | No Flask code. These are served by the Pages and Spring backends. |

This backend has no Kasm code any more: no Kasm admin page, no Kasm user sync, no `KASM_*` settings, and the `kasm_server_needed` field is gone from users. A request that still sends that field simply ignores it, and an existing database keeps its old column untouched. The `kasm` feature id stays in the catalog because the catalog is shared with Pages and Spring.

Endpoints of disabled features return 404, and their admin-page links are hidden.

### Roles

Every kit has the same three roles: **admin** runs the site and is the only role that can change features, **staff** does day-to-day work (content, groups, grading, approvals), and **member** is a regular user and the role every sign-up gets. On accounts they are stored as `Admin`, `Teacher` and `User` (`flask.roles` in the catalog), whatever the kit, so changing the kit never rewrites accounts. Only the labels shown on pages and in `/api/kit` change, plus the default uids of the three seeded accounts, which are picked once from `KIT` when the database is first created. `ADMIN_*`, `TEACHER_*` (staff) and `USER_*` (member) in `.env` still override those uids, names and passwords.

| Who | Can do |
|-----|--------|
| admin | Everything: turn features on and off, see each feature's setup status, manage users (delete, reset passwords) and the persona admin page |
| staff | Open the user list and sections admin pages; staff-only API actions (classrooms, grading summaries in production). Cannot change features. |
| member | Use the enabled features and edit their own profile. Can see which features are on (`/api/kit`) but cannot change them. |

Deleting a user (`DELETE /api/user` with `{"uid": ...}`, or the Delete button on the users page) is admin-only. An admin cannot delete their own account, and a user who still owns records such as posts or classrooms is kept and the answer is a 409 saying so, rather than a false "deleted".

### Roles and tiers

Every role has a **tier** from L1 (strongest) to L4 (weakest). A tier is the role's default permissions: how far up the permission levels it reaches.

| Tier | Reaches | The built-in role that starts there |
|------|---------|-------------------------------------|
| L1 | everything (the admin level) | admin |
| L2 | the staff level | staff |
| L3 | the member level | member |
| L4 | the public level only: no more than someone who is not signed in | none |

Admins manage roles on the **Roles** page (admin menu, Web Security, `/roles/`), with no restart:

- **Add a role** with a name (2 to 20 characters, stored on accounts), an optional label and a tier. Change any role's label, and the tier of staff and member. The admin role is always L1 and cannot be removed. **Reset** puts a built-in role back to its tier and label. A role that accounts still hold cannot be deleted.
- **Give an account a role** with `PUT /api/user/role` and `{"uid": "ada", "role": "Mentor"}`, or from the page. You cannot change your own role, so the admins can never be locked out.
- **Everything follows the tier.** The check before each request, the `@token_required(...)` decorators, the admin pages, and `is_admin()` / `is_staff()` all ask the role's tier, so a role added at L2 really has staff powers. A decorator's built-in role name means its level or stronger.
- **Customizing.** The tier is only the default. Change what a level may do for one request on the [Permissions](#permissions) page. The page shows how many requests each tier may make right now.
- **API.** `GET /api/roles`, `POST /api/roles` with `{"name": "Mentor", "label": "Mentor", "tier": 3}`, `PUT /api/roles/<name>` with a `label` and/or `tier`, and `DELETE /api/roles/<name>`. Admin only and pinned in `permissions.json`, and every change is logged with who made it. `GET /api/kit` also reports `role_tiers` (the built-in roles' tiers) and `custom_roles`.
- **If the saved roles cannot be read**, the admin role keeps its power and every other role counts as L4 until they can, rather than guess.

### Permissions

[`permissions.json`](permissions.json) is the one place that says who may make each request. It has one flat list per level, and each entry is `METHOD /route`, with the route written as Flask knows it:

```json
{
  "public":     ["POST /api/authenticate", "GET /login"],
  "member":     ["GET /api/id", "PUT /api/user"],
  "staff":      ["POST /api/classrooms/"],
  "admin":      ["GET /api/export/users", "DELETE /api/user"],
  "unreviewed": ["GET /api/study"]
}
```

| Level | Who may make the request |
|-------|--------------------------|
| `public` | Anyone, signed in or not, on purpose (home page, login, sign-up) |
| `member` | Any signed-in account |
| `staff` | Staff and admin |
| `admin` | Admin only |
| `unreviewed` | Anyone, because it always was open and nobody has decided it should be. It is a to-do list: move each entry to the level it belongs at. |

- **Levels add up.** Admin may make everything staff may, and staff everything a member may. The file uses the three role ids, never the stored names, so changing the kit never touches it.
- **A route in no list is closed.** It is refused for everyone with a 403 that names the entry to add, so a new route is never open by accident.
- **Same in development and production.** There is no mode switch.
- **Answers.** No login on an API path gets 401 JSON, and too low a level gets 403. An admin page without a login session is sent to `/login`. API requests may use the session or the JWT; pages use the session only. `api_paths` in the file lists which path prefixes are APIs (`/api/`, `/run/`).
- **Rules about one record stay in the route.** "You may only change your own profile" needs the record, so it is still written there. A route that reads `g.current_user` still needs `@token_required()`. For who may reach the route at all, you only edit the file. A decorator that asks for more than the file still applies.

**Changing a level from the website.** An admin opens **Permissions** in the admin menu (`/permissions/`), where requests are grouped by feature. Pick a level for a request and press Save: the change is stored in the database (`permission_override`, with a log of who changed what in `permission_audit`) and applies on the next request in every worker, with no restart. **Reset** goes back to the level in `permissions.json`. The same is available as `GET`/`PUT /api/permissions` (admin only; `PUT` takes `{"requests": {"GET /api/study": "member", "GET /api/jokes": null}}`, where `null` resets). Things to know:

- Requests under `pinned` in `permissions.json` (login and the Permissions page itself) cannot be changed, so nobody can lock themselves or everyone out. The page shows them in red as locked, requests an admin has decided in green, and unreviewed ones in yellow.
- The page can make any request stricter. It can make one more open only when the route does not check for itself: a route with its own `@token_required()` or role check keeps that check.
- If the stored changes cannot be read, requests answer 503 rather than guess.
- `scripts/db_init.py` wipes the changes along with the rest of the database.

To add a route, put it under the right level and run:

```bash
python -m permissions --check   # the file against the app's routes; exits 1 on a problem
python -m permissions           # entries per level, and the unreviewed list
```

`python -m pytest tests` runs the same check, so a route missing from the file fails the tests, and the app logs a warning at startup.

**Upgrading a copy that has its own routes.** Accounts, roles and logins are unchanged, but a route of your own is in no list, so it is refused until you add it. Run `python -m permissions --check`, put each route it names under `unreviewed` to keep it exactly as open as it is today, deploy, then move each one to its real level when you have decided. The Gemini endpoints now need a login in development too, as they already did in production.

### CORS

A browser only lets a website call this backend if the website's origin is allowed. An origin is the scheme, host and port the browser sends: `https://pages.example.org` or `http://localhost:4500`, with no path and no trailing slash. Admins manage the list on the **CORS** page (admin menu, `/cors/`), with no restart:

- **Where the list comes from.** The list an admin saved on the page, if there is one; otherwise `CORS_ORIGINS` in `.env`; otherwise the local development sites. **Reset** forgets the saved list, so `.env` decides again.
- **Applies at once.** The list is read on every cross-origin request, so a change reaches every worker on the next request. If the saved list cannot be read, no cross-origin request is allowed until it can.
- **Only exact origins can be saved.** A path, trailing slash, pattern or `*` is refused with a message saying what to fix. The page warns about `http://` origins that are not local. An entry in `.env` may still be a pattern (a regular expression, or `*` for every site), as before; the page flags it, and saving a list drops it.
- **API.** `GET /api/cors`, `PUT /api/cors` with `{"origins": ["https://pages.example.org"]}`, and `DELETE /api/cors` to reset. Admin only, and pinned in `permissions.json` so they cannot be changed from the Permissions page. Every change is logged with who made it.
- **Headers.** `cors.py` replaces the Flask-CORS library, which fixed its list when the app started, so a runtime change could not reach the other workers. The answers are the same as Flask-CORS gave (checked request by request), except that a request with no `Origin` header, which a browser sends only for same-site requests, no longer gets an `Access-Control-Allow-Origin` header.

### Customizing features

An admin can [apply a whole kit at runtime](#switching-kits-at-runtime), which replaces the first two layers below. Otherwise features are decided in three layers, and each later layer wins:

1. **`KIT`** picks the preset.
2. **`FEATURES`** in `.env` changes the preset. Restart after changing it.
   ```bash
   KIT=business
   FEATURES=+hallpass,-resume     # add or remove features relative to the kit
   FEATURES=+*                    # the kit plus every other feature
   FEATURES=ai-chatbot,social     # an explicit list replaces the kit (core is always added)
   FEATURES=*,-kasm               # every feature except Kasm
   ```
3. **Admin overrides** apply at runtime with no restart, and only the admin role can set them. They are stored in the `feature_override` table, and every change is logged with who made it and when in `feature_audit`. `scripts/db_init.py` drops both tables, and `kit_setting` too.

`core` is always on and cannot be removed. An unknown kit or feature id in `.env` stops the app at startup with an error that lists the valid ids.

Every feature's database tables are always created, whatever the kit, so turning a feature on never needs a migration. When an admin turns a feature on and its tables are empty, its reference data (the catalog's `seed` hooks) is created. A feature that was turned off and on again keeps its data. Accounts are never created at runtime: hooks that create accounts with known passwords are listed under `seed_accounts`, and only `scripts/db_init.py` runs them, on a database with no users.

### Switching kits at runtime

An admin can turn a Vanilla site into Education or Business and back, then keep customizing, with no restart or rebuild:

```bash
curl -b jar -X PUT http://localhost:8587/api/kit/admin/kit -H 'Content-Type: application/json' -d '{"kit": "education"}'
curl -b jar -X DELETE http://localhost:8587/api/kit/admin/kit   # back to KIT and FEATURES
```

- **Precedence.** With a stored kit: its preset, then admin overrides; `KIT` and `FEATURES` are ignored. Without one: `KIT`, then `FEATURES`, then admin overrides. `core` is always on.
- **What a switch does.** It stores the kit in `kit_setting`, clears all overrides, logs who did it in `feature_audit`, and seeds newly enabled features whose tables are empty.
- **What it never does.** Accounts and data are not deleted or changed: uids and stored roles stay, and logins stay valid. A disabled feature answers 404 and keeps its data, which is visible again when the feature comes back. Labels and the role of new sign-ups follow the active kit immediately.

If the stored kit or overrides cannot be read (a database failure, not an empty or missing table), the site fails closed rather than falling back to `KIT`/`FEATURES`, which would bring back features an admin disabled. Only always-on features stay on, every check tries again so the site recovers by itself, the error is logged once per outage, and changes answer 503. `/api/kit` reports `degraded: true`, and `/api/kit/admin` adds `degraded_reason`. While degraded, `kit`, `kit_name` and `roles` come from the environment, because the stored kit is unknown.

### Kit API

Pages, Spring and the installer share this contract.

| Request | Who | Returns |
|---------|-----|---------|
| `GET /api/kit` | anyone | `{kit, kit_name, kit_source: admin\|env\|default, customized, degraded, features: [ids], feature_details: [{id, name, category, labels, enabled}], roles: {admin\|staff\|member: {label}}, role_tiers: {admin\|staff\|member: 1..4}, custom_roles: [{name, label, tier}], signup_role}` |
| `GET /api/kit/admin` | admin | The same, plus `base_features` (before overrides), `presets` (`{vanilla\|education\|business: {name, description, features, roles}}`), `degraded_reason`, `recent_changes` (audit log), and for each feature: `source` (`kit` \| `env` \| `admin`), `override`, `always_on`, `setup` (`summary`, `steps`, `verify`, and the settings Flask reads, each with `configured: true/false`) and `ready` (all required Flask settings configured). Setting values are never returned. |
| `PUT /api/kit/admin/features` | admin | Body `{"features": {"social": true, "kasm": false}}`. Rejects unknown ids and disabling `core` with 400. Returns the admin payload. |
| `DELETE /api/kit/admin/features/<id>` | admin | Clears that override, so the kit decides again. Returns the admin payload. |
| `PUT /api/kit/admin/kit` | admin | Body `{"kit": "vanilla\|education\|business"}`. Applies the preset and clears all overrides. An unknown kit gets 400. Returns the admin payload. |
| `DELETE /api/kit/admin/kit` | admin | Forgets the stored kit and all overrides, returning to `KIT`/`FEATURES`. Returns the admin payload. |

`customized` is true when the result differs from the preset. Anonymous callers get 401, and staff and members get 403. A change that cannot be saved gets 503. Both a login session and the JWT cookie from `/api/authenticate` work.

```bash
curl -c jar -X POST http://localhost:8587/api/authenticate -H 'Content-Type: application/json' \
  -H 'X-Origin: client' -d '{"uid": "admin", "password": "123Qwerty!"}'
curl -b jar http://localhost:8587/api/kit/admin
curl -b jar -X PUT http://localhost:8587/api/kit/admin/features -H 'Content-Type: application/json' \
  -d '{"features": {"social": false}}'
```

### Organizations (formerly "schools")

OCS-in-a-Kit is for any organization, so what used to be called a school is now an organization everywhere:

| Where | Name now | Still accepted (old name) |
|-------|----------|---------------------------|
| `.env` | `ORG_NAME`, `ORG_LOGO_URL` | `SCHOOL_NAME`, `SCHOOL_LOGO_URL` |
| User JSON (`/api/id`, `/api/user`, ...) | `organization` | `school`, in requests, imports and exports |
| Classroom JSON | `organization_name` | `school_name` and `schoolName`, in requests and imports |
| Endpoint | `/api/organization` | `/api/school`, the same handler |

Responses use only the new names. Requests, imports and old exports that still use the old names keep working, so Pages, Spring and existing backups need no change to keep running; update them at your own pace. The database columns keep their stored names (`users._school`, `classrooms._school_name`), so an existing database needs no migration.

### Adding a new feature

All the wiring lives in [`kits/catalog.json`](kits/catalog.json). `main.py` and `scripts/db_init.py` read it and need no edits.

1. Add the feature to the canonical `OCS-Kit/kits/catalog.json`: id, name, category, labels, description and `setup` guide. Add it to the kit presets that should include it. Copy everything except the `flask` blocks verbatim into this repo's `kits/catalog.json`.
2. Write the code: a blueprint in `api/`, and any models in `model/`. Add each route to [`permissions.json`](#permissions) at the level that may use it (a route in no list is refused). If the feature has a blueprint of its own, add a section about it to `templates/help.html` (the Q&A guide); a test fails without one. For role checks inside a route, use `roles.py` or `user.is_admin()`/`is_staff()` instead of role names.
3. In this repo's catalog, under the feature's `"flask"` block, list:
   - `blueprints`: `"api.my_api:my_api"`. Requests return 404 while the feature is off. Each blueprint has exactly one owning feature.
   - `uses_blueprints` (optional): blueprints owned by another feature that this feature also needs. They are served when either feature is on.
   - `models`: `"model.my_model"`. These are always imported, so their tables always exist.
   - `seed`: `"model.my_model:initMyThings"`. These run from `db_init.py`, and when an admin turns the feature on while its tables are empty.
   - `startup` (optional): functions that run at app start and when the feature is turned on.
   - `admin_links` (optional): `{"label": "My Page", "endpoint": "my_api.my_page"}` adds a link to the admin navbar. Add `"group": "Web Security"` (any name) to put it in a sub-menu of that name; links that share a group share one sub-menu.
4. Run `python -m features --check`, `python -m permissions --check` and `python -m pytest tests`. The features check fails on:
   - unknown ids, categories or labels, and kit roles that don't match the canonical ones
   - references that don't import
   - a blueprint claimed by two features
   - any blueprint in `api/` or `hacks/` that no feature lists, so new code can't skip gating
   - drift from the canonical catalog

To add code to an existing feature, append to that feature's lists instead.

## Going to production

1. In `.env`, set `IS_PRODUCTION=true`. The app then refuses to start without `SECRET_KEY`, `ADMIN_PASSWORD` and `DEFAULT_PASSWORD`, and it sends secure, cross-site cookies.
2. Set `CORS_ORIGINS` to your frontend origin(s), e.g. `https://pages.example.org`, or add them later on the CORS page.
3. Set `COOKIE_DOMAIN` (e.g. `.example.org`) if the frontend and backend are on different subdomains.
4. Optionally, set `ALLOWED_EMAIL_DOMAINS` to limit signups to your organization's email domains.
5. Put nginx in front of the backend using [`deploy/nginx.conf.template`](deploy/nginx.conf.template). The instructions for filling it in with `envsubst` and getting a certificate with certbot are at the top of that file.
6. To use MySQL instead of SQLite, set `DB_ENDPOINT`, `DB_USERNAME` and `DB_PASSWORD`. Set `DB_INIT=true` for the first boot only.

Within the enabled kit features, integrations that need settings turn themselves off when those settings are empty:
- Gemini and Groq AI chat
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

In development, any unset seeded password defaults to `123Qwerty!`. Every password, including the ones you set in `.env`, must follow the password rule: 8 or more characters, with an uppercase letter, a lowercase letter, a number and one of `` ` ~ ! @ # $ % ^ & * ( ) ``. Spring and Pages use the same rule. A password that breaks it is refused with HTTP 400. If `SECRET_KEY` is unset, a random key is generated at startup, so logins reset on every restart.

For the local frontend, the default `CORS_ORIGINS` allows `http://localhost:4500`, `http://127.0.0.1:4500`, `http://localhost:4000` and `http://127.0.0.1:4000`.

Test the login API:

```bash
curl -i -X POST http://localhost:8587/api/authenticate \
  -H 'Content-Type: application/json' -H 'X-Origin: client' \
  -d '{"uid": "admin", "password": "123Qwerty!"}'
```

## Project layout

| Path | Purpose |
|------|---------|
| `main.py` | App entry point: registers enabled features' blueprints and core admin routes |
| `features.py`, `kits/catalog.json` | Kit feature registry (`python -m features --list` / `--check`) |
| `tests/` | `python -m pytest tests` (uses a throwaway database, never your `.env` or `instance/`) |
| `roles.py` | Role names and per-kit labels from the catalog |
| `branding/`, `scripts/make_logo_assets.py` | The two source logos (one for light pages, one for dark) and the one-off script that makes the transparent web logos in `static/assets/` from them (needs Pillow and numpy; the PNGs are committed) |
| `static/css/theme.css`, `templates/layouts/` | The light and dark colours, and the layout pieces: the navbar holds the sun/moon switch, and `base.html` sets the theme before the page paints and restarts the animated background with the theme's colours |
| `templates/help.html` | The Q&A guide at `/help/`; a feature with a blueprint of its own needs a section here (a test checks) |
| `api/jumpstart.py`, `templates/jumpstart/`, `static/css/jumpstart.css` | OCS JumpStart at `/jumpstart/`: `chapters.json` lists the chapters, each chapter is a template, and live tables come from the running app; `tests/test_jumpstart.py` ties every file, route, command, setting and quoted message in the chapters to the code |
| `permissions.json`, `permissions.py` | Who may make each request, and the check that runs before every request |
| `api/permissions_admin.py`, `templates/permissions.html`, `model/permission_override.py` | The admin Permissions page, its API, and the levels admins changed |
| `cors.py`, `api/cors_admin.py`, `templates/cors.html`, `model/cors_setting.py` | The CORS headers, the admin CORS page and API, and the origins admins saved |
| `api/roles_admin.py`, `templates/roles.html`, `model/role_setting.py` | The Roles page and API, and the roles and tiers admins saved (tiers are decided in `roles.py`) |
| `model/feature_override.py` | Admin feature overrides and their audit log |
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
