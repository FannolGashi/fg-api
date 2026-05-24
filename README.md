# FG API

Self-hosted platform that turns Python scripts into HTTP endpoints, each running in its own isolated virtual environment.

---

## Quick start

```bash
# 1. Copy and configure environment
cp .env.example .env
#    → edit .env: set ADMIN_PASSWORD and SECRET_KEY

# 2. Build and launch
docker-compose up -d

# 3. Open the web UI
open http://localhost:8000
```

Login with the credentials from `.env` (default: `admin` / `changeme`).

---

## How it works

1. **Create an endpoint** at `/ui/endpoints` — e.g. `check_dsl_connection`
2. **Upload a `script.py`** (+ optional `requirements.txt`)
3. FG API creates an isolated venv and installs dependencies in the background
4. **Call it**: `GET /check_dsl_connection` → stdout is returned as the HTTP response

---

## Project structure

```
.
├── app/
│   ├── main.py              # FastAPI app, startup/shutdown
│   ├── config.py            # Settings from env vars
│   ├── database.py          # SQLAlchemy async + SQLite
│   ├── models.py            # ORM models
│   ├── schemas.py           # Pydantic request/response schemas
│   ├── auth.py              # JWT, bcrypt, API token helpers
│   ├── dependencies.py      # FastAPI dependency injection
│   ├── routers/
│   │   ├── auth.py          # POST /api/auth/login|logout
│   │   ├── endpoints.py     # CRUD /api/endpoints/*
│   │   ├── execute.py       # GET /{name}  POST /webhook/{name}
│   │   ├── logs.py          # GET /api/logs
│   │   ├── tokens.py        # /api/tokens/*
│   │   └── ui.py            # Jinja2 HTML pages
│   ├── services/
│   │   ├── executor.py      # Subprocess execution, semaphore, timeout
│   │   ├── venv_manager.py  # venv create/rebuild/delete
│   │   └── scheduler.py     # APScheduler cron integration
│   └── templates/           # Jinja2 HTML templates (Tailwind CSS)
├── examples/
│   ├── check_health/        # System stats (psutil)
│   └── check_dsl/           # FritzBox WAN/DSL status (stdlib only)
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh            # Privilege-drop then uvicorn
└── requirements.txt
```

---

## Persistence

All data lives in `./data/` (bind-mounted into the container):

```
data/
├── db/app.db          SQLite — endpoints, logs, tokens, schedules
├── scripts/{name}/    Uploaded script.py + requirements.txt
├── venvs/{name}/      Isolated Python venv per endpoint
└── logs/              Reserved for future file-based logging
```

Killing and recreating the container **does not lose** any data.

---

## Configuration

All settings are environment variables:

| Variable | Default | Notes |
|---|---|---|
| `ADMIN_USERNAME` | `admin` | Login username |
| `ADMIN_PASSWORD` | `changeme` | **Change this** |
| `SECRET_KEY` | — | JWT signing key — random 32+ chars |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `480` | 8-hour sessions |
| `DEFAULT_TIMEOUT` | `30` | Script execution timeout (seconds) |
| `DEFAULT_MAX_CONCURRENT` | `3` | Max parallel runs per endpoint |
| `MAX_TIMEOUT` | `300` | Hard ceiling on timeout setting |

---

## API reference

Interactive docs: **http://localhost:8000/api/docs**

### Public (no auth)

```
GET  /{endpoint_name}          Execute endpoint, return stdout
POST /webhook/{endpoint_name}  Webhook trigger
GET  /api/endpoints            List all endpoints
GET  /api/logs                 List execution logs
GET  /health                   Health check
```

### Protected (Bearer JWT or API token)

```
POST   /api/auth/login
POST   /api/auth/logout

POST   /api/endpoints                     Create endpoint
PATCH  /api/endpoints/{id}                Edit settings
POST   /api/endpoints/{id}/toggle         Enable / disable
DELETE /api/endpoints/{id}                Delete + wipe files
POST   /api/endpoints/{id}/script         Upload script [+ requirements]
POST   /api/endpoints/{id}/rebuild-venv   Rebuild venv from scratch
PUT    /api/endpoints/{id}/schedule       Set cron schedule
DELETE /api/endpoints/{id}/schedule       Remove schedule

GET    /api/tokens                        List API tokens
POST   /api/tokens                        Create long-lived token
DELETE /api/tokens/{id}                   Revoke token
```

### Authentication

```bash
# Session token (8-hour JWT, stored in httponly cookie)
curl -c cookies.txt -X POST http://localhost:8000/api/auth/login \
  -d "username=admin&password=changeme"

# Long-lived API token
curl -X POST http://localhost:8000/api/tokens \
  -H "Authorization: Bearer <jwt>" \
  -H "Content-Type: application/json" \
  -d '{"name":"my-monitor"}'
# → save the raw_token field; shown only once

curl http://localhost:8000/check_health \
  -H "Authorization: Bearer <raw_token>"
```

---

## Loading example scripts

```bash
# 1. Get a JWT
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -d "username=admin&password=changeme" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2. Create endpoints
curl -X POST http://localhost:8000/api/endpoints \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"check_health","description":"System stats","response_type":"application/json"}'

curl -X POST http://localhost:8000/api/endpoints \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"check_dsl_connection","description":"FritzBox WAN status","response_type":"application/json"}'

# 3. Upload scripts (use the IDs returned above)
curl -X POST http://localhost:8000/api/endpoints/1/script \
  -H "Authorization: Bearer $TOKEN" \
  -F "script_file=@examples/check_health/script.py" \
  -F "requirements_file=@examples/check_health/requirements.txt"

curl -X POST http://localhost:8000/api/endpoints/2/script \
  -H "Authorization: Bearer $TOKEN" \
  -F "script_file=@examples/check_dsl/script.py"

# 4. Wait a few seconds for venv build, then call
curl http://localhost:8000/check_health
curl http://localhost:8000/check_dsl_connection
```

---

## Security summary

| Control | Implementation |
|---|---|
| Non-root execution | `appuser` (UID 1000) via `gosu` in entrypoint |
| Isolated environments | Per-endpoint Python venv, clean env vars |
| Execution timeout | `asyncio.wait_for` + `proc.kill()` |
| Concurrency cap | Per-endpoint `asyncio.Semaphore` |
| Path traversal | Endpoint names validated: `^[a-zA-Z0-9_-]{1,64}$` |
| Password storage | bcrypt (passlib) |
| Session tokens | JWT (HS256), 8-hour expiry, httponly cookie |
| API tokens | SHA-256 hash stored; raw token shown once |
| Parameterised queries | SQLAlchemy ORM throughout |

### Production checklist

- [ ] Set a strong `ADMIN_PASSWORD`
- [ ] Set a random 32+ char `SECRET_KEY`
- [ ] Put nginx/Caddy in front with TLS
- [ ] Bind to `127.0.0.1:8000` if behind a reverse proxy
- [ ] Back up `./data/` regularly

---

## Author

**Fannol Gashi** — [fg0.net](https://fg0.net)

---

## License

MIT License — see [LICENSE](LICENSE) for details.
