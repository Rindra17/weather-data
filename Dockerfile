# =============================================================================
# Custom Apache Airflow 3.3.0 image
#
# Installs additional runtime tools and Python packages on top of the
# official apache/airflow:3.3.0 base.
#
# Build:
#   docker build -t your-registry/airflow-custom:latest .
#
# Then update .env.production:
#   AIRFLOW_IMAGE_NAME=your-registry/airflow-custom:latest
#
# =============================================================================

ARG AIRFLOW_BASE_IMAGE=apache/airflow:3.3.0
FROM ${AIRFLOW_BASE_IMAGE}

LABEL maintainer="Weather Data Team"
LABEL description="Custom Airflow 3.3.0 image with additional packages"

# -- Switch to root for system-level operations ------------------------------
USER root

# Install runtime system packages that are useful in production:
#   curl, jq          — health checks and debugging
#   postgresql-client  — manual DB inspection / backups
#   redis-tools        — Redis CLI for debugging Celery broker
#   procps, lsof, iproute2 — troubleshooting inside the container
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        jq \
        postgresql-client \
        redis-tools \
        procps \
        lsof \
        iproute2 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# -- Copy the production entrypoint script -----------------------------------
COPY scripts/entrypoint-prod.sh /opt/airflow/scripts/entrypoint-prod.sh
RUN chmod 755 /opt/airflow/scripts/entrypoint-prod.sh && \
    chown airflow:root /opt/airflow/scripts/entrypoint-prod.sh

# -- Install additional Python dependencies ----------------------------------
# Switch to the airflow user: the base image's pip wrapper refuses to run
# as root (for security), and the official virtualenv is active for this user.
USER airflow

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --requirement /tmp/requirements.txt

# -- Finalise ----------------------------------------------------------------
WORKDIR /opt/airflow
HEALTHCHECK NONE

# The compose file sets the entrypoint to /opt/airflow/scripts/entrypoint-prod.sh
# and the command to the specific Airflow sub-command.  Leave CMD empty.
CMD []
