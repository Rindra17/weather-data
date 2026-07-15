.PHONY: all build start stop restart logs logs-airflow-apiserver logs-airflow-scheduler logs-airflow-worker logs-postgres logs-redis clean ps secrets help

all: build start

build:
	docker compose build

start:
	docker compose up -d

stop:
	docker compose down

restart: stop start

logs:
	docker compose logs -f

logs-airflow-apiserver:
	docker compose logs -f airflow-apiserver

logs-airflow-scheduler:
	docker compose logs -f airflow-scheduler

logs-airflow-worker:
	docker compose logs -f airflow-worker

logs-postgres:
	docker compose logs -f postgres

logs-redis:
	docker compose logs -f redis

clean:
	docker compose down -v --rmi all

ps:
	docker compose ps

secrets:
	mkdir -pm 700 secrets
	[ -f secrets/postgres_password.txt ] || python3 -c "import secrets; print(secrets.token_urlsafe(32))" > secrets/postgres_password.txt
	[ -f secrets/redis_password.txt ] || python3 -c "import secrets; print(secrets.token_urlsafe(32))" > secrets/redis_password.txt
	[ -f secrets/fernet_key.txt ] || python3 scripts/generate_fernet_key.py > secrets/fernet_key.txt
	[ -f secrets/jwt_secret.txt ] || python3 -c "import secrets; print(secrets.token_urlsafe(64))" > secrets/jwt_secret.txt
	chmod 600 secrets/postgres_password.txt secrets/redis_password.txt secrets/fernet_key.txt secrets/jwt_secret.txt

help:
	@echo "Available commands:"
	@echo "  make build                    - Build all Docker images"
	@echo "  make start                    - Start all services"
	@echo "  make stop                     - Stop all services"
	@echo "  make restart                  - Restart all services"
	@echo "  make logs                     - Follow all logs"
	@echo "  make logs-airflow-apiserver   - Follow Airflow API server logs"
	@echo "  make logs-airflow-scheduler   - Follow Airflow scheduler logs"
	@echo "  make logs-airflow-worker      - Follow Airflow worker logs"
	@echo "  make logs-postgres            - Follow PostgreSQL logs"
	@echo "  make logs-redis               - Follow Redis logs"
	@echo "  make clean                    - Stop and remove all (including volumes)"
	@echo "  make ps                       - Show running containers"
	@echo "  make secrets                  - Generate secret files"
