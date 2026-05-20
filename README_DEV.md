# Локальная разработка NLP-части

NLP-зависимости (torch, sentence-transformers, spacy, keybert) тяжёлые и нужны
только для enrich-CLI, который запускается локально с воркстейшна разработчика.
Прод-Docker-образ их не ставит.

## Установка

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[nlp]"
python -m spacy download ru_core_news_lg
python -m spacy download en_core_web_sm
```

На macOS (M-series) torch автоматически подхватит MPS-ускорение.
На Linux x86 без GPU — CPU-режим, нормально для разовых прогонов.

## Запуск БД

```bash
docker compose up -d db   # только Postgres, без app
```

Контейнер биндит порт **5433** на `127.0.0.1` (5432 типично занят локальным
Postgres'ом). Локальные NLP-скрипты ходят туда напрямую:

```bash
export DATABASE_URL=postgresql+asyncpg://postgres:CHANGE_ME@localhost:5433/hse_faculty
```

(Внутри Docker `DATABASE_URL` остаётся `@db:5432` — это переменная окружения,
докер видит свою, host видит свою.)

## Smoke-тесты

```bash
# Тегер
python scripts/test_extractor.py

# Embedder (шаг 5)
python scripts/test_embedder.py
```

## Enrich-команды

См. шаг 6 (появятся позже).
