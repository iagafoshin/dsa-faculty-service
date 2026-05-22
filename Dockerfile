# Production-образ с полным NLP-стеком (torch CPU-only, sentence-transformers,
# spacy). Модели предзагружаются на build-time, в runtime HF выключен —
# первый запрос мгновенный, без сетевых обращений.
#
# Используется как для деплоя на VPS (docker compose up), так и для
# локальной проверки сборки. В dev FastAPI обычно запускается прямо
# с воркстейшна через `uvicorn --reload` из venv — в Docker только
# Postgres (см. README.md, `make db`).
#
# Размер образа ~2 GB, RAM-footprint ~700 MB после загрузки модели.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    HF_HOME=/code/.hf_cache

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code

COPY pyproject.toml README.md /code/

# CPU-only torch ставим ПЕРВЫМ из PyTorch-индекса — иначе [nlp]-extras
# подтянут CUDA-сборку и образ распухнет на ~3 GB nvidia-* мусора. На
# CPU-only VPS CUDA не нужен.
RUN pip install --upgrade pip \
 && pip install --index-url https://download.pytorch.org/whl/cpu torch \
 && pip install ".[nlp]"

# Pre-download spaCy-моделей в образ (~525 MB).
RUN python -m spacy download ru_core_news_lg \
 && python -m spacy download en_core_web_sm

# Pre-download sentence-transformer в HF_HOME → /code/.hf_cache.
RUN python -c "from sentence_transformers import SentenceTransformer; \
SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')"

# Все скачивания позади — фиксируем runtime в offline-mode, чтобы первый
# запрос в проде не уходил в HF за обновлениями.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

# Запускаем под не-root пользователем — снижает blast radius при компрометации.
RUN useradd --create-home --uid 1000 app \
 && chown -R app:app /code
USER app

COPY --chown=app:app app /code/app
COPY --chown=app:app alembic /code/alembic
COPY --chown=app:app alembic.ini /code/alembic.ini
COPY --chown=app:app templates /code/templates

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
