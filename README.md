# DSA Faculty Service

**DSA Faculty Service** — микросервис данных о НПР платформы **Digital Student Assistant (DSA)**. Агрегирует профили преподавателей НИУ ВШЭ (скрейпинг с hse.ru), их публикации и учебные курсы, и отдаёт их через REST API. Основной сервис (ядро DSA-бэкенда) использует этот API для фронтенда студентов.

- **Источник истины:** [`openapi.yaml`](./openapi.yaml) в корне репозитория
- **Swagger UI** (после `make up`): http://localhost:8000/docs
- **OpenAPI JSON:** http://localhost:8000/openapi.json

## Стек

Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2.0 (async) · Postgres 16 · Alembic · `httpx` + `lxml` для парсера · Docker.

## Быстрый старт

```bash
cp .env.example .env
make up          # docker compose up -d
make migrate     # alembic upgrade head (pg_trgm + все таблицы + сид кампусов)
make scrape      # docker compose exec app python -m app.scraper --limit=5
open http://localhost:8000/docs
```

## Запуск парсера

Через админ-эндпоинт:

```bash
# запустить фоновый скрейп (возвращает 202 + job_id)
curl -X POST "http://localhost:8000/api/v1/admin/scrape?limit=5&campus_id=1125608"

# опрос статуса
curl "http://localhost:8000/api/v1/admin/scrape/<job_id>"

# остановить
curl -X POST "http://localhost:8000/api/v1/admin/scrape/<job_id>/cancel"
```

Или локально через CLI:

```bash
make scrape   # docker compose exec app python -m app.scraper --limit=5
```

## Статус: объём v0.2

**В MVP:** профили, публикации, курсы, лексический поиск (ILIKE + pg_trgm), health/ready, лента новостей (последние публикации), админ-эндпоинт для парсера.

**Отложено до v1.0+:**
- NER-теги для интересов/тематик
- Семантический поиск (OpenSearch + SciBERT)
- Источник новостей `hse_portal` (отдельный парсер)
- Outbox-события для внешних потребителей

## Структура проекта

```
openapi.yaml                # источник истины
app/
  main.py                   # FastAPI app
  routes.py                 # все публичные эндпоинты (health, persons, publications, ...)
  admin.py                  # админ-эндпоинты для скрейпинга
  config.py, database.py
  models.py                 # SQLAlchemy ORM
  schemas.py                # Pydantic v2 модели ответов
  publication_enrichment.py # доп. поля из raw JSONB
  scraper/
    __main__.py             # CLI: python -m app.scraper --limit=5
    parser.py               # HTML → dict (со всеми normalize_*)
    publications.py         # клиент publications.hse.ru/api/searchPubs
    profile.py              # scrape_one_profile(url) → dict
    crawler.py              # crawl_and_ingest()
    ingest.py               # upsert person/publications/courses
    client.py               # HTTP-клиент к hse.ru
alembic/versions/           # начальная миграция (pg_trgm + таблицы + сид кампусов)
```

## Место в DSA

Соседний микросервис ядра DSA-бэкенда (репозиторий `Digital-Student-Assistant`). Этот сервис отвечает за домен «преподаватели / публикации / курсы»; ядро DSA — за проекты / заявки / пользователей. Интеграция — через REST-контракт в [`openapi.yaml`](./openapi.yaml).

Production: https://faculty.agafoshin.ru/docs

tested ci/cd