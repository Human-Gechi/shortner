# URL Shortener Service

A URL shortener with per-user link ownership, click analytics, and Redis-backed
caching, built on FastAPI, PostgreSQL, and Redis.

Create short links, protect them with an expiry date or a max-click limit,
and inspect click analytics (time series, top countries, device and browser
breakdown) for anything you own.

#### Note: The Frontend was built with AI(CLAUDE) 
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
- **Rate limiting** — per-IP, backed by Redis
- **Health check** — `/health` reports database and Redis status
- **Frontend** — a static dashboard (`static/index.html`) covering
  registration, login, link creation, the link list, and analytics

---

## Tech stack

| Layer          | Technology                               |
|----------------|------------------------------------------|
| API            | FastAPI (async), Uvicorn                 |
| Database       | PostgreSQL, SQLAlchemy (async)           |
| Cache / limits | Redis                                    |
| Auth           | JWT (`python-jose`), Argon2 password hashing |
| Frontend       | Static HTML/CSS/vanilla JS               |

---

## Project structure

```
├── static/
│   ├── index.html               # Dashboard frontend
│   └── link-error.html          # Shown when a short link can't be resolved
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
    │   └── analytics_service.py   # click aggregation queries
    └── utils/
        └── helpers.py             # URL normalization, password hashing, code generation
```

---

## Prerequisites

- Python 3.12+
- PostgreSQL (running instance + a database created for this app)
- Redis (running instance)
- (Optional) A GeoLite2 City `.mmdb` file if you want country/city data on
  clicks — without it, `country`/`city`/`region` on clicks will just be `null`

---

## Setup

### 1. Clone and create a virtual environment

```bash
git clone 
cd 
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
SALT=python -c "import secrets; print(secrets.token_hex(32))"
GEOIP_DB_PATH=your_GEO_DB_PATH
DATABASE_URL=postgresql+asyncpg://user:password@host:port/db
REDIS_URL=redis://redis-container:6379/0
SECRET_KEY=your_secret_key
DOMAIN=http://localhost:8000


POSTGRES_USER=db_username
POSTGRES_PASSWORD=db_password
POSTGRES_DB=your_db
POSTGRES_PORT=your_port
POSTGRES_HOST=your_host
```

> Generate a strong `SECRET_KEY` with:
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

Once running:

| URL | What it is |
|---|---|
| `http://localhost:8000/` | API root / basic info |
| `http://localhost:8000/ui` | Frontend dashboard |
| `http://localhost:8000/docs` | Interactive Swagger docs |
| `http://localhost:8000/health` | Health check (database + Redis) |

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

