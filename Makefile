.PHONY: up down logs migrate revision scrape shell psql fmt build

up:
	docker compose up -d

build:
	docker compose build

down:
	docker compose down

logs:
	docker compose logs -f app

migrate:
	docker compose exec app alembic upgrade head

revision:
	docker compose exec app alembic revision --autogenerate -m "$(m)"

scrape:
	docker compose exec app python -m app.scraper --limit=5

shell:
	docker compose exec app python

psql:
	docker compose exec db psql -U postgres -d hse_faculty
