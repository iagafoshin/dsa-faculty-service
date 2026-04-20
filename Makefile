.PHONY: up down logs migrate revision seed scrape test shell psql fmt build

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

seed:
	docker compose exec app python scripts/seed_from_sample.py

scrape:
	docker compose exec app python scripts/run_scraper_local.py --limit=5

test:
	docker compose exec app pytest -v

shell:
	docker compose exec app python

psql:
	docker compose exec db psql -U postgres -d hse_faculty
