#!/bin/bash
#
# Production entrypoint for Airflow containers.
# Reads Docker secrets from /run/secrets/ and exports them as environment
# variables before handing control to the official Airflow entrypoint.
#
# Secrets mounted by docker-compose.prod.yaml:
#   - postgres_password  → used to build DB connection strings
#   - fernet_key         → AIRFLOW__CORE__FERNET_KEY
#   - jwt_secret         → AIRFLOW__API_AUTH__JWT_SECRET
#
set -euo pipefail

# ------------------------------------------------------------------
# 1. Load every Docker secret as an environment variable.
#    Secret file name → env var name (lowercase, underscores).
# ------------------------------------------------------------------
if [ -d /run/secrets ]; then
  for secret_file in /run/secrets/*; do
    if [ -f "$secret_file" ]; then
      secret_name="$(basename "$secret_file")"
      secret_value="$(cat "$secret_file")"
      export "${secret_name}"="${secret_value}"
    fi
  done
fi

# ------------------------------------------------------------------
# 2. Build Airflow connection strings from the postgres_password
#    secret so the password never appears in docker-compose YAML or
#    in shell history.
# ------------------------------------------------------------------
if [ -n "${postgres_password:-}" ]; then
  export AIRFLOW__DATABASE__SQL_ALCHEMY_CONN="postgresql+psycopg2://airflow:${postgres_password}@postgres/airflow"
  export AIRFLOW__CELERY__RESULT_BACKEND="db+postgresql+psycopg2://airflow:${postgres_password}@postgres/airflow"
fi

if [ -n "${fernet_key:-}" ]; then
  export AIRFLOW__CORE__FERNET_KEY="${fernet_key}"
fi

if [ -n "${jwt_secret:-}" ]; then
  export AIRFLOW__API_AUTH__JWT_SECRET="${jwt_secret}"
fi

# ------------------------------------------------------------------
# 3. Hand off to the official Airflow entrypoint.
# ------------------------------------------------------------------
exec /entrypoint "$@"
