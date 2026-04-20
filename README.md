# DSA Faculty Service

**DSA Faculty Service** — микросервис данных о НПР платформы **Digital Student Assistant (DSA)**. Агрегирует профили преподавателей НИУ ВШЭ (скрейпинг с hse.ru), их публикации и учебные курсы, и отдаёт их через REST API. Соседний сервис (ядро DSA-бэкенда) использует этот API для фронтенда студентов.

- **Источник истины:** [`openapi.yaml`](./openapi.yaml) в корне репозитория
- **Swagger UI** (после `make up`): http://localhost:8000/docs
- **OpenAPI JSON:** http://localhost:8000/openapi.json

## Стек

Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2.0 (async) · Postgres 16 · Alembic · `httpx` + `lxml` для парсера · Docker · pytest.

## Быстрый старт

```bash
cp .env.example .env
make up          # docker compose up -d
make migrate     # alembic upgrade head (pg_trgm + все таблицы + сид кампусов)
make seed        # грузит data/sample_100_persons.json — 100 реальных профилей ВШЭ
open http://localhost:8000/docs
```

Проверочные запросы:

```bash
curl -s http://localhost:8000/api/v1/persons/25477 | jq .publications_total
# → 181  (Абанкина Ирина Всеволодовна)

curl -s 'http://localhost:8000/api/v1/publications?author_person_id=25477' | jq .count
# → > 150

curl -s 'http://localhost:8000/api/v1/search?q=Абанкина' | jq '.total'
```

## Запуск парсера «вживую»

Парсер перенесён из `data/hse_persons.ipynb` в `app/scraper/` как обычные Python-модули. Запускается через админ-эндпоинт:

```bash
# запустить фоновый скрейп (возвращает 202 + job_id)
curl -X POST "http://localhost:8000/api/v1/admin/scrape?limit=5&campus_id=1125608"

# опрос статуса
curl "http://localhost:8000/api/v1/admin/scrape/<job_id>"
```

Или локально через CLI:

```bash
make scrape   # docker compose exec app python scripts/run_scraper_local.py --limit=5
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
openapi.yaml              # источник истины
app/
  api/v1/                 # 14 эндпоинтов, смонтированы под /api/v1
  models/                 # SQLAlchemy ORM
  schemas/                # Pydantic v2 модели (строго по openapi.yaml)
  services/
    mapping.py            # сырой JSON ↔ колонки БД
    ingest.py             # идемпотентные upsert'ы
    pagination.py         # хелпер Paginated[T]
  scraper/                # порт data/hse_persons.ipynb
    parser.py             # все функции parse_*
    publications.py       # клиент publications.hse.ru/api/searchPubs
    profile.py            # scrape_one_profile(url) → dict
    crawler.py            # crawl_and_ingest()
alembic/versions/         # начальная миграция (pg_trgm + таблицы + сид кампусов)
scripts/
  seed_from_sample.py     # грузит data/sample_100_persons.json
  run_scraper_local.py    # CLI-обёртка над краулером
tests/                    # smoke-тесты по засиженной БД
data/
  sample_100_persons.json # реальные данные ВШЭ — опора для сида и демо
  hse_persons.ipynb       # исходный прототип парсера (для справки)
```

## Место в DSA

Соседний микросервис ядра DSA-бэкенда (репозиторий `Digital-Student-Assistant`). Этот сервис отвечает за домен «преподаватели / публикации / курсы»; ядро DSA — за проекты / заявки / пользователей. Интеграция — через REST-контракт в [`openapi.yaml`](./openapi.yaml).

## Тесты

```bash
make test    # docker compose exec app pytest -v
```

Покрывают все GET-эндпоинты, «якорь» `person_id=25477` (Абанкина, 181 публикация), сортировку, фильтрацию и ветки ошибок на несуществующих id.
