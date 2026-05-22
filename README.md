# DSA Faculty Service

Сервис семантического поиска научных руководителей и экспертов по теме
исследования среди преподавателей НИУ ВШЭ.

**Демо:** https://faculty.agafoshin.ru

## Что умеет

- **Семантический поиск экспертов по теме** — запрос свободным текстом
  на русском или английском («применение машинного обучения в медицине»,
  «computer vision», «теория игр») возвращает топ преподавателей с их
  релевантными публикациями.
- **Семантический поиск публикаций** для подбора литературы.
- **Скрейпинг и обновление** профилей преподавателей с hse.ru
  (биографии, должности, публикации, курсы).
- **Лексический поиск** по ФИО, названиям публикаций и курсов.
- **HTML-интерфейс** и **REST API** (Swagger UI на `/docs`).

База: **11 879 преподавателей**, **71 116 публикаций**, **4 851 курс**
по 4 кампусам ВШЭ.

## Стек

Python 3.12 · FastAPI · Postgres 16 + `pg_trgm` + `pgvector` · spaCy +
KeyBERT + sentence-transformers (multilingual MiniLM-L12-v2) · Docker.

## Локальный запуск

В Docker — только Postgres. Сервис и NLP-команды запускаются локально
из venv.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[nlp]"
python -m spacy download ru_core_news_lg
python -m spacy download en_core_web_sm

cp .env.example .env
make db          # docker compose up -d db
make migrate     # alembic upgrade head
make serve       # uvicorn app.main:app --reload
```

Открыть: `http://localhost:8000/` (UI), `http://localhost:8000/docs` (API).

## Скрейпинг и обогащение

```bash
make scrape                                  # python -m app.scraper --limit=5
python -m app.nlp enrich-persons --only-empty
python -m app.nlp enrich-publications --only-empty
```

Полный цикл (~12k преподавателей + ~71k публикаций) — около 4 часов
на M3 Max с MPS.

## Production

```bash
docker compose up -d --build
docker compose exec app alembic upgrade head
```

Прод-Dockerfile собирает образ с полным NLP-стеком и предзагруженными
моделями (~2 GB образ, ~700 MB RAM). TLS терминируется host-nginx.
CI/CD — GitHub Actions при push в `main`.
