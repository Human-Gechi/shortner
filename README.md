# URL Shortener Service

A URL shortener with per-user link ownership, click analytics, and Redis-backed
caching, built on FastAPI, PostgreSQL, and Redis. Deployed on
[Render](https://render.com).

Create short links, protect them with an expiry date or a max-click limit,
and inspect click analytics (time series, top countries, device and browser
breakdown) for anything you own.

#### Note: The Frontend was built with AI (Claude)

**Live app:** https://shortner-5ztd.onrender.com

---

## Features

- **Auth** — JWT-based registration and login (`/auth/register`, `/auth/login`)
- **Link creation** — single or bulk (up to 100 at a time), with optional
  custom alias, expiry date, and max-click limit
- **Ownership** — every link belongs to the user who created it; only the
  owner can deactivate it or view its analytics
- **Redirects** — public, cache-first (Redis) with a PostgreSQL fallback
- **Click limits & expiry** — enforced consistently across cache and
  database paths
- **Analytics** — clicks over time, top countries, device breakdown, browser
  breakdown, per link
- **Geolocation** — click IPs are resolved to country/city/region via the
  [ip-api.com](http://ip-api.com) HTTP API (async `httpx` client), no local
  GeoLite2 database required
- **Rate limiting** — per-IP, backed by Redis
- **Health check** — `/health` reports database and Redis status
- **Frontend** — a static dashboard (`static/index.html`) covering
  registration, login, link creation, the link list, and analytics

---

## Tech stack

| Layer          | Technology                               |
|----------------|-------------------------------------------|
| API            | FastAPI (async), Uvicorn                 |
| Database       | PostgreSQL(hosted on Aiven), SQLAlchemy (async)           |
| Cache / limits | Redis                                    |
| Auth           | JWT (`python-jose`), Argon2 password hashing |
| Geolocation    | `httpx` → `ip-api.com`                   |
| Frontend       | Static HTML/CSS/vanilla JS               |
| Hosting        | Render                                   |

---

## Project structure

```
├── static/
│   ├── index.html               # Dashboard frontend
│   └── link-error.html          # Shown when a short
|   └── redirect.html            # redirection
|   └── home.html                # Home page
|   └── bot-preview.html         # mask page webelements  
|   └── link-error.html          # Shortner svg
└── src/
    ├── config.py                 # Settings (env-driven)
    ├── log.py                    # Logger setup
    ├── api/
    │   ├── auth.py                # /auth/register, /auth/login
    │   └── schemas.py             # Pydantic request/response models
    |   └── main.py                # FastAPI app
    ├── app_models/
    │   ├── database.py            # Async engine, session factory, Base
    │   └── models.py              # User, Link, Click (SQLAlchemy models)
    ├── cache/
    │   └── redis_client.py        # LinkCache, ClickCounter, RateLimiter, UniqueVisitorTracker
    ├── dependencies/
    │   └── database.py            # get_db() session dependency
    ├── services/
    │   ├── url_service.py         # link creation, resolution, click recording, bulk create
    │   ├── analytics_service.py   # click aggregation queries
    │   └── geo_service.py         # IP → country/city/region via ip-api.com (httpx)
    └── utils/
        └── helpers.py             # URL normalization, password hashing, code generation
```

---

## Prerequisites

- Python 3.12+
- PostgreSQL (running instance + a database created for this app)
- Redis (running instance)

No local geolocation database is needed — click IPs are resolved at request
time via an outbound call to `http://ip-api.com/json/{ip}`. If that call
fails or the free-tier rate limit is hit, `country`/`city`/`region` on
clicks will just be `null`.

---

## Setup

### 1. Clone and create a virtual environment

```bash
git clone <repo-url>
cd <repo-dir>
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```dotenv
SALT=your_generated_salt
DATABASE_URL=postgresql+asyncpg://user:password@host:port/db
REDIS_URL=redis://redis-host:6379/0
SECRET_KEY=your_secret_key
DOMAIN=http://localhost:8000

POSTGRES_USER=db_username
POSTGRES_PASSWORD=db_password
POSTGRES_DB=your_db
POSTGRES_PORT=your_port
POSTGRES_HOST=your_host
```

> Generate `SALT`:
> ```bash
> python -c "import secrets; print(secrets.token_hex(32))"
> ```
>
> Generate a strong `SECRET_KEY`:
> ```bash
> python -c "import secrets; print(secrets.token_urlsafe(48))"
> ```

---

## Running the app

### Development

```bash
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

### Production

```bash
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Deployment (Render)

The app is deployed on Render as a web service:

1. Push the repo to GitHub.
2. Create a new **Web Service** on Render and connect the repo.
3. Set the build command:
   ```bash
   pip install -r requirements.txt
   ```
4. Set the start command:
   ```bash
   uvicorn src.api.main:app --host 0.0.0.0 --port $PORT
   ```
5. Add all the environment variables from the `.env` section above in the
   Render dashboard (Environment tab). Point `DATABASE_URL` and `REDIS_URL`
   at your managed Postgres/Redis instances (Render's own or external, e.g.
   Upstash for Redis).
6. Set `DOMAIN` to your Render service URL, e.g.
   `https://<your-render-app>.onrender.com`, so generated short links resolve
   correctly.
7. Deploy — Render will build and start the service automatically on every
   push to the connected branch.

Once running:

| URL | What it is |
|---|---|
| `/` | API root / basic info |
| `/docs` | Interactive Swagger docs |
| `/health` | Health check (database + Redis) |

---

## API overview

All endpoints are also documented interactively at `/docs`.

### Auth

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/register` | — | Create an account, returns a JWT |
| POST | `/auth/login` | — | Log in (OAuth2 form: `username`=email, `password`), returns a JWT |

### Links

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/links` | ✅ | Create a short link |
| GET | `/links/me` | ✅ | List your active links |
| POST | `/links/bulk` | ✅ | Create up to `MAX_BULK_ITEMS` links at once |
| DELETE | `/links/{code}` | ✅ | Deactivate a link you own |
| GET | `/links/{code}/analytics` | ✅ | Click analytics for a link you own |
| GET | `/{code}` | — | Public redirect to the link's destination |

### System

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | — | Database + Redis health check |

Authenticated requests need an `Authorization: Bearer <token>` header, using
the `access_token` returned from register/login.

---
Trade-offs to be aware of:

- **No extra file/download** — nothing to bundle or keep updated.
- **Network dependency** — each unresolved click makes an outbound HTTP
  call, adding latency and a possible point of failure.
- **Rate limits** — ip-api.com's free tier is limited (45 requests/minute
  per IP at time of writing); consider caching results per IP in Redis or
  upgrading to a paid tier for high-traffic deployments.
- Local/private IPs (e.g. `127.0.0.1`, `10.x.x.x`) won't resolve to a real
  location — expect `null` geo fields in local testing.