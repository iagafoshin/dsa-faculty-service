# Dev-команды. В Docker крутится только Postgres; FastAPI и
# NLP-команды запускаются локально из venv (с MPS-ускорением на macOS).
#
# Установка venv — см. README.md.

.PHONY: db db-down db-logs psql migrate revision serve scrape

# === Postgres в Docker ===

db:
	docker compose up -d db

db-down:
	docker compose down

db-logs:
	docker compose logs -f db

psql:
	docker compose exec db psql -U postgres -d hse_faculty

# === Локальные команды (требуют активного venv с [nlp] extras) ===

migrate:
	alembic upgrade head

revision:
	alembic revision --autogenerate -m "$(m)"

serve:
	uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

scrape:
	python -m app.scraper --limit=5
