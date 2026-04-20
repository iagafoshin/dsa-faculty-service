# DSA Faculty Service

**DSA Faculty Service** is the faculty-data microservice of the **Digital Student Assistant (DSA)** platform. It aggregates profiles of HSE University faculty (scraped from hse.ru), their publications, and courses, and exposes them over a REST API. A sibling service (core DSA backend) consumes this API for the student-facing frontend.

- **Source of truth:** [`openapi.yaml`](./openapi.yaml) in repo root
- **Live Swagger UI** (after `make up`): http://localhost:8000/docs
- **OpenAPI JSON:** http://localhost:8000/openapi.json

## Stack

Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2.0 (async) · Postgres 16 · Alembic · `httpx` + `lxml` scraper · Docker · pytest.

## Quickstart

```bash
cp .env.example .env
make up          # docker compose up -d
make migrate     # alembic upgrade head (pg_trgm + all tables + campus seed)
make seed        # loads data/sample_100_persons.json — 100 real HSE profiles
open http://localhost:8000/docs
```

Sanity checks:

```bash
curl -s http://localhost:8000/api/v1/persons/25477 | jq .publications_total
# → 181  (Абанкина Ирина Всеволодовна)

curl -s 'http://localhost:8000/api/v1/publications?author_person_id=25477' | jq .count
# → > 150

curl -s 'http://localhost:8000/api/v1/search?q=Абанкина' | jq '.total'
```

## Running the scraper live

The scraper is ported from `data/hse_persons.ipynb` into `app/scraper/` as regular Python modules. It's wired behind the admin endpoint:

```bash
# kick off a background scrape (returns 202 + job_id)
curl -X POST "http://localhost:8000/api/v1/admin/scrape?limit=5&campus_id=1125608"

# poll status
curl "http://localhost:8000/api/v1/admin/scrape/<job_id>"
```

Or locally from the CLI:

```bash
make scrape   # docker compose exec app python scripts/run_scraper_local.py --limit=5
```

## Status: v0.2 scope

**In MVP:** persons, publications, courses, lexical search (ILIKE + pg_trgm), health/ready, news feed (last publications), admin scrape endpoint.

**Deferred to v1.0+:**
- NER-enriched interest/topic tags
- Semantic search (OpenSearch + SciBERT)
- `hse_portal` news source (separate parser)
- Outbox events for downstream consumers

## Layout

```
openapi.yaml              # source of truth
app/
  api/v1/                 # 14 endpoints, mounted under /api/v1
  models/                 # SQLAlchemy ORM
  schemas/                # Pydantic v2 models (match openapi.yaml exactly)
  services/
    mapping.py            # raw JSON ↔ DB-column refactor
    ingest.py             # idempotent upserts
    pagination.py         # Paginated[T] helper
  scraper/                # ported from data/hse_persons.ipynb
    parser.py             # all parse_* functions
    publications.py       # publications.hse.ru/api/searchPubs client
    profile.py            # scrape_one_profile(url) → dict
    crawler.py            # crawl_and_ingest()
alembic/versions/         # initial migration (pg_trgm + all tables + campus seed)
scripts/
  seed_from_sample.py     # loads data/sample_100_persons.json
  run_scraper_local.py    # CLI wrapper around crawler
tests/                    # smoke tests against seeded DB
data/
  sample_100_persons.json # real HSE data — anchor for seed + demo
  hse_persons.ipynb       # original scraper prototype (reference only)
```

## Role in DSA

Sibling microservice to the core DSA backend (`Digital-Student-Assistant` repo). This service owns the faculty / publications / courses domain; the core DSA service owns projects / applications / users. Integration is via the REST contract in [`openapi.yaml`](./openapi.yaml).

## Tests

```bash
make test    # docker compose exec app pytest -v
```

Covers all GET endpoints, the `person_id=25477` anchor (Абанкина, 181 publications), ordering, filtering, and the error path for unknown IDs.
