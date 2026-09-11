.PHONY: up down build logs ps test

up:
	docker compose up -d --build

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

ps:
	docker compose ps

test:
	cd backend && uv run pytest
	cd frontend && npm run build
