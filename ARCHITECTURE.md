# DSA Faculty Service — детальное описание

Микросервис данных о научно-педагогических работниках (НПР) для платформы
**Digital Student Assistant (DSA)**. Собирает профили преподавателей с
hse.ru и `publications.hse.ru`, хранит в Postgres, отдаёт через REST API
и server-rendered HTML.

Над классическим поиском надстроены **два векторных слоя**:
- `/api/v1/experts/search` — поиск экспертов по теме над embeddings персон
- `/api/v1/publications/semantic-search` — семантический поиск над embeddings
  публикаций (для подбора лит-обзора курсача / диплома)

Embeddings — `paraphrase-multilingual-MiniLM-L12-v2`, 384-мерные, HNSW-индекс
поверх pgvector.

Поверх API — **HTML-UI на Jinja2 + Tailwind** (`/`, `/persons`, `/publications`,
`/persons/{id}`).

- **Источник истины контракта:** `openapi.yaml`
- **Прод:** https://faculty.agafoshin.ru/docs
- **Локально после `make up`:** http://localhost:8000/ (UI), `/docs` (Swagger)

---

## Содержание

1. [Стек](#стек)
2. [Поток данных](#поток-данных)
3. [Структура репозитория](#структура-репозитория)
4. [Модель данных](#модель-данных)
5. [API](#api)
6. [Скрейпер](#скрейпер)
7. [NLP-пайплайн](#nlp-пайплайн)
8. [Векторный поиск экспертов](#векторный-поиск-экспертов)
9. [Развёртывание](#развёртывание)
10. [Метрики и текущее состояние БД](#метрики-и-текущее-состояние-бд)
11. [Принятые архитектурные решения](#принятые-архитектурные-решения)

---

## Стек

| Слой | Технологии |
|---|---|
| Язык / рантайм | Python 3.12 |
| Web | FastAPI, uvicorn |
| ORM / БД | SQLAlchemy 2.0 async, asyncpg, Alembic |
| База данных | Postgres 16 + расширения `pg_trgm` (триграммный поиск) и `pgvector` (HNSW-индекс) |
| Скрейпинг | `requests` (HTML), `lxml` (XPath) |
| NLP | spaCy (`ru_core_news_lg`, `en_core_web_sm`), KeyBERT, sentence-transformers (`paraphrase-multilingual-MiniLM-L12-v2`), torch с MPS на macOS |
| Контейнеризация | Docker, docker-compose, `pgvector/pgvector:pg16` |
| CI/CD | GitHub Actions (deploy.yml) |

NLP-зависимости (`torch`, `sentence-transformers`, `spacy`, `keybert`) — в
optional-extras `[nlp]`. Прод-образ их **не ставит** — enrich запускается
с воркстейшна разработчика.

---

## Поток данных

```
                         hse.ru                  publications.hse.ru
                            │                            │
                            │   HTML профиля             │   JSON API
                            ▼                            ▼
                  ┌──────────────────────────────────────────┐
                  │            app/scraper/                  │
                  │  client → publications API клиент        │
                  │  parser → HTML → структурированный dict  │
                  │  profile.scrape_one_profile              │
                  │  crawler.crawl_and_ingest                │
                  │  ingest.upsert_person → Postgres         │
                  └──────────────────────────────────────────┘
                            │
                            ▼
                ┌────────────────────────┐
                │       Postgres 16      │
                │  persons, publications │
                │  authorships, courses  │
                │  scrape_jobs, campuses │
                └────────────────────────┘
                       │           │
                       │           └─── (offline, локально из venv)
                       │                ┌─────────────────────────┐
                       │                │      app/nlp/           │
                       │                │  build_person_context   │
                       │                │  extract_topics (NER)   │
                       │                │  embed (MiniLM)         │
                       │                │  → interests_extracted, │
                       │                │    embedding (Vector)   │
                       │                └─────────────────────────┘
                       │
                       ▼
                ┌────────────────────────┐
                │     FastAPI app        │
                │  routes  — публичный   │
                │  admin   — управление  │
                │  experts — векторный   │
                │             поиск      │
                └────────────────────────┘
                            │
                            ▼
                  REST: GET / POST   →   DSA-фронт / клиенты
```

Конкретные пути:

- **Скрейп-этап**: cron / админ-эндпоинт `POST /admin/scrape` запускает
  `crawler.crawl_and_ingest`, который перебирает страницы кампусов
  ВШЭ по букве алфавита, собирает URL'ы профилей и для каждого
  вызывает `scrape_one_profile`. Парсер выдаёт «плоский» dict под
  колонки `Person` + списки публикаций и курсов. `ingest.upsert_person`
  кладёт всё в одной транзакции на пачку.
- **Enrich-этап (offline)**: `python -m app.nlp enrich-{persons,publications}`
  читает из БД пачки записей, считает NER-теги и 384-мерные эмбеддинги,
  пишет назад в колонки `interests_extracted`, `embedding`, `topics`.
- **Read-этап (онлайн)**: API запросы читают данные **только из колонок**,
  без парсинга на лету. `/experts/search` использует pgvector HNSW для
  k-NN по `embedding`.

---

## Структура репозитория

```
.
├── alembic/                       # миграции БД
│   └── versions/
│       ├── 0001_initial.py        # схема + pg_trgm + сид кампусов
│       ├── 0002_add_patents_to_persons.py
│       ├── 0003_add_nlp_fields.py # pgvector + embedding + topics
│       └── 0004_publication_extras_columns.py
│                                  # абстракт/DOI/editors/translators в колонках
├── app/
│   ├── main.py                    # FastAPI-приложение, mounts роутеров
│   ├── config.py                  # pydantic-settings (env-based)
│   ├── database.py                # async engine + sessionmaker + get_session()
│   ├── routes.py                  # JSON API (health, meta, persons,
│   │                              #   publications, courses, search, news)
│   ├── admin.py                   # /admin/scrape{,/cancel,/{job_id}}
│   ├── experts.py                 # /experts/search + /publications/semantic-search
│   │                              #   (JSON, lazy-import NLP)
│   ├── ui.py                      # HTML-страницы (/, /persons, /publications,
│   │                              #   /persons/{id}); Jinja2 + Tailwind
│   ├── vector_search.py           # общие helper'ы vector_search_{persons,publications}
│   │                              #   и compute_matched_topics для experts.py + ui.py
│   ├── models.py                  # ВСЕ SQLAlchemy-таблицы в одном файле
│   ├── schemas.py                 # ВСЕ Pydantic-схемы ответов
│   ├── nlp/
│   │   ├── __main__.py            # CLI: python -m app.nlp enrich-*
│   │   ├── extractor.py           # spaCy NER + KeyBERT + 9 post-фильтров
│   │   ├── embedder.py            # MiniLM sentence-transformer
│   │   ├── person_context.py      # сборка текста для NER/embedding
│   │   └── stopwords.py           # ~110 стоп-слов + ORG_INDICATORS + JUNK_PHRASES
│   └── scraper/
│       ├── __main__.py            # CLI: python -m app.scraper --limit=...
│       ├── client.py              # HTTP-клиент к hse.ru и publications.hse.ru
│       ├── parser.py              # HTML → dict; ~980 строк, по одной parse_*
│       │                          #   функции на блок: positions, awards, conferences,
│       │                          #   grants, patents и т.д.
│       ├── profile.py             # _compose: оркестрация parser.* + fetch_publications
│       │                          #   → плоский dict под колонки Person
│       ├── crawler.py             # обход кампусов/букв, фоновая задача с ScrapeJob
│       └── ingest.py              # upsert_person: один батч → транзакция;
│                                  #   парсинг extras при insert (abstract,
│                                  #   DOI, editors, ...)
├── templates/                     # Jinja2 для app/ui.py
│   ├── base.html                  # layout: navbar + Tailwind CDN
│   ├── home.html                  # 🎯 Подбор научрука (поиск + 4 секции)
│   ├── persons.html               # 👥 список преподавателей
│   ├── publications.html          # 📚 список + checkbox семантического поиска
│   └── profile.html               # 👤 профиль с табами (профиль/публикации/курсы)
├── scripts/
│   ├── test_extractor.py          # smoke: 5 захардкоженных person_id, видим теги
│   ├── test_embedder.py           # smoke: cosine ru↔en blockchain ≈ 0.88
│   └── backfill_publication_extras.py
│                                  # one-shot: для миграции 0004 заполнить
│                                  # новые колонки из существующего raw JSONB
├── notes/                         # артефакты для ВКР (before/after сравнения)
│   ├── extractor_v1_sample.txt    # baseline NER без фильтров
│   ├── extractor_v2_sample.txt    # та же выборка после apply_filters v2
│   ├── extractor_iterations.md    # narrative проблем v1 и фиксов v2
│   ├── embedder_validation.txt    # cosine-матрица семантической близости
│   ├── score_distribution_sample30.txt   # 30 enriched persons (sample)
│   ├── score_distribution_full.txt       # 239 enriched (after first full run)
│   ├── score_distribution_with_courses.txt
│   └── score_distribution_5k.txt         # 2439 enriched (5k scrape)
├── openapi.yaml                   # источник истины API-контракта
├── Dockerfile                     # прод-образ (без nlp extras)
├── docker-compose.yml             # db (pgvector/pgvector:pg16) + app
├── Makefile                       # make up/migrate/scrape/...
├── pyproject.toml                 # deps + optional [nlp]
├── README.md                      # быстрый старт
├── README_DEV.md                  # локальная NLP-установка
├── IDEAS.md                       # каталог направлений на будущее
└── ARCHITECTURE.md                # этот файл
```

**Дизайн-принципы расположения**:
- Один файл на крупный домен (routes.py, models.py, schemas.py, ingest.py).
  «Плоско лучше, чем вложенно» (Zen of Python). Никаких 7-файловых
  пакетов с одним классом в каждом.
- `app/nlp/` и `app/scraper/` — папки только потому что у них реально
  4+ файла с разной ответственностью.
- `__main__.py` — идиоматичный Python CLI-entrypoint.

---

## Модель данных

Шесть таблиц + два индексных расширения:

```
                          ┌─────────┐
                          │ campuses│ (4 кампуса, сид в миграции)
                          │ id, name│
                          └────┬────┘
                               │
                               ▼
┌───────┐                ┌─────────┐                  ┌─────────────┐
│courses├───person_id───►│ persons │◄────person_id────┤ authorships │
│       │                │         │                  │             │
│ title │                │ profile │                  │ pub_id, pos │
│ year  │                │ name    │                  │ display_name│
└───────┘                │ avatar  │                  │ display_en  │
                         │ campus  │                  │ is_hse_pers │
                         │ ...     │                  │ href        │
                         │ interest│                  └──────┬──────┘
                         │ embed   │                         │
                         └─────────┘                         │
                                                            pub_id
                                                              │
                                                              ▼
                                                       ┌─────────────┐
                                                       │ publications│
                                                       │             │
                                                       │ id (str)    │
                                                       │ title, year │
                                                       │ raw (JSONB) │
                                                       │ abstract_ru │
                                                       │ doi_url     │
                                                       │ editors     │
                                                       │ embedding   │
                                                       └─────────────┘

           ┌──────────────┐
           │ scrape_jobs  │ статус фоновых задач скрейпа
           │ job_id       │
           │ status, err  │
           │ proc / total │
           └──────────────┘
```

**Person** (расширенный профиль НПР):

| Колонка | Тип | Назначение |
|---|---|---|
| `person_id` | BIGINT PK | ID из hse.ru |
| `full_name` | TEXT NOT NULL | ФИО |
| `avatar` | TEXT | URL аватара |
| `profile_url` | TEXT NOT NULL | каноническая ссылка `/org/persons/<id>` |
| `primary_unit` | TEXT | первое подразделение |
| `campus_id` | TEXT FK→campuses | кампус (Москва / СПб / НН / Пермь) |
| `publications_total` | INT | сколько публикаций (HSE-cчётчик, валидированный) |
| `languages` / `positions` / `relations` / `education` / ... | JSONB | гибкие nested-блоки из профиля |
| `interests` / `bio_notes` / `work_experience` / `awards` / `grants` / `editorial_staff` / `conferences` / `patents` | JSONB | детали профиля (списки) |
| `research_ids` | JSONB | ORCID, ResearcherID, Scopus AuthorID и т.д. |
| `parsed_at` | TIMESTAMPTZ | когда последний раз парсили |
| `interests_extracted` | JSONB | NER-теги от KeyBERT после фильтров (NEW) |
| `embedding` | Vector(384) | 384-мерный embedding профиля (NEW) |
| `created_at`, `updated_at` | TIMESTAMPTZ | служебные |

Индексы:
- `ix_persons_full_name_trgm` — GIN trigram для `ILIKE %q%`
- `ix_persons_languages_gin`, `ix_persons_interests_gin`
- `ix_persons_embedding_hnsw` — HNSW cosine для k-NN
- `ix_persons_interests_extracted_gin`
- стандартные B-tree на campus_id, primary_unit, publications_total

**Publication**:

| Колонка | Тип | Назначение |
|---|---|---|
| `id` | TEXT PK | ID из HSE publications API |
| `title`, `type`, `year`, `language` | — | базовое |
| `raw` | JSONB | полный исходный ответ HSE-API |
| `abstract_ru`, `abstract_en` | TEXT | абстракт (парсится при insert) |
| `venue`, `citation`, `publisher` | TEXT | библиографические поля |
| `doi_url`, `document_url`, `external_url`, `cover_url` | TEXT | абсолютные URL'ы |
| `editors`, `translators` | JSONB | списки AuthorRef-дикт'ов |
| `topics` | JSONB | NER-теги (NEW) |
| `embedding` | Vector(384) | embedding (NEW) |
| `ingested_at` | TIMESTAMPTZ | когда добавили |

Поля `abstract_*`, `doi_*`, `editors`, `translators` и т.д. раньше
вытаскивались из `raw` на каждый GET (модуль `publication_enrichment.py`).
С миграции 0004 они стали обычными колонками — парсинг происходит
один раз при scrape (`ingest._publication_payload`).

**Authorship** (M2M между Person и Publication, с позицией автора):

| Колонка | Тип |
|---|---|
| `publication_id` | TEXT PK FK |
| `position` | INT PK |
| `person_id` | BIGINT FK→persons (NULL если автор не в нашей БД) |
| `display_name`, `display_name_en` | TEXT |
| `href` | TEXT |
| `is_hse_person` | BOOL |

Upsert использует `ON CONFLICT DO UPDATE` с `COALESCE` на `person_id` —
backfill соавторов, добавленных позже (см. ingest.py).

**Course**: одна запись на (преподаватель × дисциплина × год обучения).
4851 курс в БД, до 365 у одного преподавателя (общеуниверситетские).

**ScrapeJob**: фоновая задача парсинга — статусы
`queued → running → done | failed | cancelled` (`cancelling` — промежуточный).

---

## API

Все эндпоинты под `/api/v1`. Контракт фиксирован в `openapi.yaml`,
Swagger UI на `/docs`.

| Метод + путь | Назначение |
|---|---|
| `GET /health` | живость |
| `GET /ready` | live + DB-ping |
| `GET /meta/campuses` | справочник кампусов |
| `GET /meta/publication-types` | enum типов с локализованными лейблами |
| `GET /persons` | список с пагинацией, фильтрами `q`, `campus_id`, `has_publications`, `language`, сортировкой |
| `GET /persons/{id}` | полный профиль |
| `GET /persons/{id}/publications` | публикации одного автора, фильтры по году и типу |
| `GET /persons/{id}/courses` | курсы |
| `GET /publications` | список с фильтрами `q`, `year_from/to`, `type`, `author_person_id` |
| `GET /publications/{id}` | одна публикация с авторами/редакторами |
| `GET /publications/semantic-search?q=...` | **vector-поиск** публикаций (см. ниже) — фильтры `year_from/to`, `type`, `language` |
| `GET /courses?q=...` | поиск курсов по названию, фильтры `academic_year`, `language` |
| `GET /search?q=...` | гибридный triagram + ILIKE поиск по persons и publications |
| `GET /news` | лента — последние публикации как «новости» |
| `GET /experts/search?q=...` | **vector-поиск** экспертов по теме — фильтры `campus_id`, `primary_unit`, `has_publications` (см. ниже) |
| `POST /admin/scrape` 🔒 | запуск фонового скрейпа, фильтры `campus_ids`, `letters`, `limit` |
| `GET /admin/scrape/{job_id}` 🔒 | статус задачи |
| `POST /admin/scrape/{job_id}/cancel` 🔒 | мягкая отмена |

🔒 — требует header `X-Admin-Token`. Если токен не настроен в env,
эндпоинт возвращает 500 (явный сигнал «admin не сконфигурирован»).

Пагинация повсюду — `?page=N&page_size=M` со схемой `Paginated[T]`,
которая отдаёт `{count, page, page_size, next, previous, results}`.
Helper `paginate()` инлайн в `routes.py`.

### HTML UI (root-paths)

Поверх JSON API — server-rendered HTML на Jinja2 + Tailwind через CDN.

| Метод + путь | Назначение |
|---|---|
| `GET /` | 🎯 Подбор научрука. Поисковая строка + 2 фильтра (кампус + факультет с datalist-автокомплитом). Результат: 4 секции — эксперты (vector, top-20), публикации (vector, top-5), курсы (ILIKE, top-5), преподаватели по фамилии (ILIKE, top-5) |
| `GET /persons` | Список преподавателей с пагинацией + фильтры (q, кампус, has_publications) + сортировка |
| `GET /persons/{id}` | Профиль: метрики, секции (интересы, должности, био, награды, гранты, конференции, патенты, research_ids), пагинированные публикации, курсы |
| `GET /publications` | Список публикаций с пагинацией + фильтры (q, год, тип) + сортировка. Checkbox **🧠 «Семантический поиск»** переключает на vector mode |

Шаблоны живут в `templates/`, роуты — в `app/ui.py`. Никаких CSS-билдов:
Tailwind через CDN.

---

## Скрейпер

### `client.py`
Тонкий wrapper над `requests.Session` с фиксированным User-Agent.
Две функции:
- `get(url)` — для HTML-страниц hse.ru
- `fetch_publications(person_id)` — для скрытого JSON-API
  `publications.hse.ru/api/searchPubs` с пагинацией

### `parser.py` (~980 строк)
Состоит из ~30 функций `parse_<section>(tree)`. Каждая:
- независима (можно тестировать изолированно)
- толерантна к отсутствующему DOM — возвращает `[]` или `{}`, не падает
- знает несколько вариантов вёрстки HSE (tab-node + heading-fallback)

Содержит нормализаторы строк/URL: `clean_text`, `normalize_phone`,
`normalize_conference_string` и т.д. — раньше были в отдельном файле,
влиты сюда после рефакторинга.

### `profile.py`
`scrape_one_profile(url)`:
1. `client.get(url)` — HTML
2. `parser.make_tree` + 15+ парс-функций
3. `client.fetch_publications(person_id)` — публикации
4. `_compose()` собирает «плоский» dict под колонки `Person`
   плюс ключи `_publications` и `_courses` для отдельных таблиц

### `crawler.py`
- `list_profile_urls(campus_ids, letters, limit)` — обходит индекс по
  буквам алфавита и (опционально) фильтру кампуса. Возвращает список
  `(url, source_campus_id)` пар.
- `crawl_and_ingest(...)` — async-обёртка, исполняет скрейп в фоне,
  обновляет `ScrapeJob` статусы, поллит `cancelling`-сигнал, делает
  commit каждые 10 профилей.

Фильтры из API: `campus_ids=[1125608, 1125609]`, `letters=["А","Б"]`,
`limit=N` — комбинируются.

### `ingest.py`
`upsert_person(session, data)`:
1. `INSERT ... ON CONFLICT DO UPDATE` для Person.
2. Для каждой публикации:
   - Парсит **все** extras (abstract, DOI, editors, ...) через
     `_publication_payload(item)`.
   - Upsert Publication со свежими extras (re-scrape обновляет данные).
3. Для каждой записи authorship:
   - Извлекает `display_name_en` и `is_hse_person` из raw.
   - Upsert с `ON CONFLICT DO UPDATE COALESCE(person_id, excluded.person_id)`
     — backfill ранее неизвестных соавторов.
4. Полная замена курсов: `DELETE WHERE person_id=X` + `INSERT`.

### CLI
- `python -m app.scraper --limit=5000 --campus-ids=1125608 --letters=А,Б`
- Под капотом: создаёт `ScrapeJob` запись, вызывает `crawl_and_ingest`,
  печатает итог.

---

## NLP-пайплайн

### Контекст
Прежде чем эмбеддить, для каждой персоны строится текст ~5000 символов:
`build_person_context(person, publications, courses)` склеивает:
- ФИО
- интересы (`person.interests`)
- bio_notes
- последние 5 записей опыта работы
- заголовки + абстракты последних 30 публикаций (DESC по году)
- уникальные названия преподаваемых курсов (один title — один сигнал)

Персоны с контекстом **<500 символов отсеиваются** (профили без
публикаций и без курсов — для них embedding будет шумом).

### Экстракция тегов

`extract_topics(text, person_name)`:

1. **Языковая эвристика** по соотношению кириллицы/латиницы → `ru | en | mixed`.
2. **spaCy NER + noun_chunks**:
   - `ru_core_news_lg` (или `en_core_web_sm`) парсит весь текст.
   - Кандидаты: сущности типов `PRODUCT, WORK_OF_ART, LAW, EVENT, NORP`.
   - `noun_chunks` 1-4 слов (только для английского — у русского
     spaCy не реализовано).
   - **Отдельно собираются** сущности типов `ORG, GPE, LOC, DATE` —
     это «reject-набор» для последующего отсева.
3. **KeyBERT** с моделью `paraphrase-multilingual-MiniLM-L12-v2`:
   - `keyphrase_ngram_range=(1, 3)`
   - `use_mmr=True, diversity=0.5` — разнообразные тeги
   - `top_n=max_tags*2`
4. **`apply_filters(tags, person_name, ner_rejects)`** — 9 правил:
   1. lowercase + strip punctuation
   2. **имя персоны** как подстрока → отсев
   3. **ORG_INDICATORS** (~30 корней: `университ`, `институт`,
      `школ`, `министерств`, `росстат`, `минобрнауки`, `банк рос`, ...) →
      отсев. Короткие токены — word-boundary, длинные — substring.
   4. **NER reject spans** (доменные ORG/GPE/LOC/DATE) → отсев
   5. **служебный префикс** (тег начинается с `в`, `по`, `гг`, ...) → отсев
   6. **numeric ratio ≥ 40%** (цифры + пробелы + `.,–-/` + `гг`) → отсев
   7. **JUNK_PHRASES** (`научно педагогический стаж`, `опыт работы`, ...) → отсев
   8. **substring-dedup** (длинная фраза поглощает короткую)
   9. min длина 4 символа + хотя бы одно слово ≥ 4 симв

### Эмбеддинг

`embed(text)` / `embed_batch(texts)`:
- `SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")`
- 384-мерный, L2-нормализованный (cosine = dot product)
- Кэш модели общий с KeyBERT — один экземпляр в памяти
- Device-detection: `mps` (macOS M-series) > `cuda` > `cpu`

Кросс-язычность подтверждена: «блокчейн и распределённые системы» ↔
«blockchain and distributed systems» дают cosine ≈ 0.88, при этом обе
далеко (~0.18) от «теория категорий в алгебре».

### CLI наполнения

```bash
python -m app.nlp enrich-persons      [--batch=100] [--only-empty] [--sample=N]
python -m app.nlp enrich-publications [--batch=200] [--only-empty] [--sample=N]
```

Реализация в `app/nlp/__main__.py`:
- **keyset-pagination** по `person_id` / `publication.id` (без offset-сдвигов)
- **JOIN-fetch** топ-30 публикаций + всех курсов **одним SQL** на батч
- **батчинг** spaCy через `nlp.pipe`, sentence-transformers через
  `model.encode(batch_size=64)`
- **одна транзакция** на батч
- `--only-empty` — пропускает уже enriched, безопасно для повторных запусков

Замеры на полной БД (см. `notes/`): persons ~14 мин, publications ~55 мин
на M3 Max c MPS.

---

## Векторный поиск

Общие helper'ы — в `app/vector_search.py`:
- `vector_search_persons(db, q, *, campus_id, primary_unit, has_publications, limit)`
- `vector_search_publications(db, q, *, year_from, year_to, pub_type, language, limit)`
- `compute_matched_topics(query, person_topics)` — substring-сопоставление

Их зовут и JSON-эндпоинты (`app/experts.py`), и HTML-страницы (`app/ui.py`) —
без дублирования SQL.

### Эксперты по теме

`GET /api/v1/experts/search?q=...&limit=10&campus_id=...`

1. Запрос `q` эмбеддится **online** через тот же sentence-transformer.
2. SQL по pgvector с HNSW-индексом:

   ```sql
   SELECT p.*, c.campus_name,
          1 - (p.embedding <=> :q_vec) AS score
   FROM persons p
   LEFT JOIN campuses c USING (campus_id)
   WHERE p.embedding IS NOT NULL
     [ AND p.campus_id = :campus_id ]
   ORDER BY p.embedding <=> :q_vec
   LIMIT :limit;
   ```

3. Для top-10 одной батч-выборкой подгружаются 3 свежих публикации
   каждого (через `ORDER BY year DESC` per person).
4. `extract_topics(q)` на запросе даёт `query_tags`; для `matched_topics`
   используется **substring-сопоставление** токенов запроса с
   `person.interests_extracted` (надёжно на запросах любой длины,
   в отличие от пересечения с KeyBERT-keyphrases).

### Публикации по теме (для лит-обзора курсача)

`GET /api/v1/publications/semantic-search?q=...&year_from=...&type=...`

SQL — тот же паттерн, но по `publications.embedding`:

```sql
SELECT p.*, 1 - (p.embedding <=> :q_vec) AS score
FROM publications p
WHERE p.embedding IS NOT NULL
  [ AND p.year >= :year_from ]
  [ AND p.year <= :year_to ]
  [ AND p.type = :type ]
  [ AND p.language = :language ]
ORDER BY p.embedding <=> :q_vec
LIMIT :limit;
```

Use case: студент пишет введение курсовой и ищет релевантные работы для
лит-обзора. ILIKE по «машинное обучение» даёт 635 публикаций с этими
словами в title, vector search — статьи по смыслу, даже если конкретных
слов нет (например, «AutoML в медицинской диагностике» для запроса
«применение машинного обучения в медицине»).

В UI семантический режим включается checkbox'ом «🧠 Семантический поиск»
на `/publications`; на главной странице `/` секция публикаций
**всегда** использует vector (там это основной use case).

### Прод-нюанс

NLP-зависимости тяжёлые (torch ~700MB). В прод-Docker они **не ставятся**.
`app/experts.py` импортирует `app.nlp.*` **лениво** внутри функции
эндпоинта: модуль грузится при первом вызове. Если в окружении нет
deps, прод-`app` стартует нормально, но `/experts/search` вернёт 500.
Решается выделением отдельного сервиса либо установкой extras в прод
(`pip install .[nlp]`).

### Качество (на полной БД)

Замер на 10 разнообразных запросах (см. `notes/score_distribution_*.txt`):
- top-1 score для **узких** тем (machine learning, теория игр,
  компьютерное зрение, квантовые компьютеры, городская инфраструктура)
  вырос с 0.31–0.45 (на 30-сэмпле) до **0.60–0.75** на 2439 enriched;
  ожидается дальнейший рост на full enrich.
- Эксперты содержательно правильные: запрос «компьютерное зрение» →
  ФКН-эксперт; «история России» → ФГН-историк; «квантовые компьютеры»
  → кафедра квантовой оптики; «городская инфраструктура» → ФГРР.
- Кросс-язычность держится: ru-запрос находит эксперта по en-публикациям.

---

## Развёртывание

### Локальная разработка

```bash
cp .env.example .env
make up       # docker compose up -d (db + app)
make migrate  # alembic upgrade head
make scrape   # python -m app.scraper --limit=5
```

Swagger: http://localhost:8000/docs

### NLP (только локально)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[nlp]"
python -m spacy download ru_core_news_lg
python -m spacy download en_core_web_sm

# Docker-DB пробрасывает 5433 на хост
export DATABASE_URL="postgresql+asyncpg://postgres:CHANGE_ME@localhost:5433/hse_faculty"
python -m app.nlp enrich-persons --batch=100 --only-empty
```

На M-series Macbook → MPS-ускорение автоматом.

### Прод

GitHub Actions деплоит `Dockerfile` (без NLP-extras). `.env` на сервере
содержит `ADMIN_TOKEN`, `DATABASE_URL` (внешний Postgres с pgvector).
Образ ставит только базовые deps + `pgvector` (Python-binding ~50KB).

Миграции применяются вручную при деплое:
`docker compose exec app alembic upgrade head`.

Для прод-`/experts/search` нужен NLP-инференс — варианты:
1. Поставить extras в прод-образ (+700MB).
2. Вынести embedder в отдельный сервис.
3. Эмбеддить запросы оффлайн (но запросы заранее неизвестны).

Сейчас выбран вариант «в проде эндпоинт 500, локально работает» —
решение отложено.

---

## Метрики и текущее состояние БД

После полного скрейпа ВШЭ:

| | значение |
|---|---|
| persons total | **11 879** |
| persons enriched | 2 439 (ожидается рост до ~7000 после полного enrich) |
| publications | **71 116** |
| publications enriched | 31 579 (ожидается рост до 71 116) |
| authorships | 89 055 |
| courses | 4 851 |
| campuses | 4 (Москва / СПб / НН / Пермь) |
| Размер БД | ~349 MB (после 5k scrape) / ~1.5GB (после full) |
| HNSW-индекс persons | ~5 MB |
| HNSW-индекс publications | ~61 MB |

Время полного цикла:
- **Скрейп** 12 248 URL → 1 ч 45 мин
- **Enrich-persons** 9 440 (после фильтра ~4600 настоящих) → ~25-40 мин
- **Enrich-publications** 39 537 новых → ~1 ч 50 мин

Скорости (M3 Max, MPS):
- Скрейп: ~115-140 профилей/мин
- Enrich persons: 3-10 p/s (рост к концу, когда профили мельче)
- Enrich pubs: 6-8 p/s

---

## Принятые архитектурные решения

| Решение | Почему так | Альтернатива и tradeoff |
|---|---|---|
| **Async SQLAlchemy** | FastAPI native, единый стек | Sync был бы проще читать, но при росте нагрузки async держит больше connections без блокировок |
| **Один файл на домен** (routes.py, models.py, schemas.py) | Плоско читается, нет «теряющихся» классов | Привычка из крупных проектов — разносить по файлам. Для микросервиса избыточно |
| **Pydantic-схемы `*Out`** (PersonOut, PublicationOut) | Явная развязка response-shape от ORM-модели; разные поля для read/write | Можно отдавать ORM напрямую через `from_attributes=True`, но теряется контроль над выдачей |
| **`raw` JSONB + извлечённые колонки** | `raw` — страховка на случай если HSE поменяет формат; колонки — быстрый read-path | Можно только колонки. Tradeoff: миграция при каждом новом поле |
| **Scrape-time извлечение vs read-time** | Извлечь один раз — все API-запросы быстрые. Альтернатива (read-time) была в коде до миграции 0004 — выкинута | Read-time гибче (новое поле = одна строка кода, без миграции). Но read-path замедляется |
| **NER + KeyBERT + post-фильтры**, а не fine-tuned NER на ВШЭ | Стандартный pre-trained pipeline + чистка стоп-словами достаточно качественен | Fine-tune SciBERT на ВШЭ-биографиях дал бы лучшее качество, но требует разметки и compute |
| **MiniLM-L12-v2 multilingual** | 384 dim — компактный embedding, multilingual, влезает в HNSW | Bigger BERT-like → лучше качество, больше RAM/диск, медленнее inference |
| **pgvector + HNSW** | В Postgres, не нужен отдельный vector-store (Qdrant/Weaviate). HNSW быстрый k-NN | Отдельный vector-store был бы быстрее на больших объёмах (миллионы), но у нас 12k персон — overkill |
| **Lazy import NLP в `/experts/search`** | Прод-Docker без torch стартует нормально | Можно поставить torch в прод; tradeoff — +700MB образ |
| **Trigram-similarity в order by + ILIKE в where** | ILIKE использует существующий GIN-index с `gin_trgm_ops`, similarity() — ранжирование | Полный fuzzy-match через `%` оператор; но он требует similarity_threshold и непредсказуем для коротких запросов |
| **`--only-empty` в enrich** | Делает прогоны идемпотентными — можно прервать и продолжить | Без флага — пере-обрабатывает уже сделанное, безопаснее но медленнее |
| **Контекст-фильтр <500 chars** | Профили без публикаций / курсов дают шумные embeddings («начал работать», «году») | Без фильтра качество search падает: такие персоны конкурируют с настоящими экспертами |
| **`__main__.py` вместо `scripts/...`** | Идиоматично для Python-пакетов (`python -m app.scraper`). `scripts/` — для smoke-тестов и one-shot backfill | Можно держать оба в `scripts/`, но тогда теряется чёткая граница «прод CLI vs утилиты» |

---

## Чего нет (намеренно)

- **Тестов**. Сознательно удалены ранее. Для учебного проекта smoke-скрипты
  (`scripts/test_*.py`) дают практический сигнал.
- **OpenSearch / семантический поиск по публикациям**. Был в roadmap v1.0+,
  не сделан (есть `publications.embedding` — основа есть).
- **Outbox-события для других сервисов DSA**. В roadmap.
- **Rate-limiting** в API. Не было запроса от потребителей.
- **Структурированный auth** (JWT / OAuth). Сейчас только static
  `ADMIN_TOKEN` для admin-роутов.

---

## История ключевых рефакторингов

| Коммит | Что изменено |
|---|---|
| `0d9a23a` | refactor: flatten layout — apps/api/v1/* → routes.py, models/ → models.py, schemas/ → schemas.py, удалены services/ |
| `72386de` | feat: NER pipeline foundation — admin auth, pgvector, базовый extractor |
| `6577b84` | feat: NER extractor + embedder с MPS-ускорением |
| `b1fc700` | feat: /experts/search с pgvector cosine |
| `b365e0b` | feat: курсы в person-контекст для embedding |
| `36bc490` | refactor: publication extras → scrape-time (drop publication_enrichment.py) |
| `a901ea7` | refactor: merge HTTP clients (scraper/publications.py → client.py) |
| `b230fd2` | refactor: merge nlp/cli.py → __main__.py |

Каждый шаг с before/after-сравнениями в `notes/`.
