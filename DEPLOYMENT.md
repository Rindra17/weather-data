# Deployment Guide — Weather Data Airflow on VPS

> **Target audience:** Operations / DevOps engineers  
> **Target stack:** Docker Compose · Apache Airflow 3.3.0 · PostgreSQL 16 · Redis 7  
> **OS:** Ubuntu 22.04 LTS or 24.04 LTS (other Debian-based distros similar)

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Server Setup](#2-server-setup)
3. [Secret Generation](#3-secret-generation)
4. [Environment Configuration](#4-environment-configuration)
5. [Deployment Steps](#5-deployment-steps)
6. [Backup and Restore](#6-backup-and-restore)
7. [Monitoring and Logging](#7-monitoring-and-logging)
8. [Troubleshooting](#8-troubleshooting)
9. [Upgrading](#9-upgrading)
10. [Production Hardening (Optional)](#10-production-hardening-optional)
11. [Reference](#11-reference)

---

## 1. Prerequisites

### 1.1 Hardware Minimums

| Component   | Minimum   | Recommended |
|-------------|-----------|-------------|
| CPU         | 2 vCPU    | 4 vCPU      |
| RAM         | 4 GB      | 8 GB        |
| Disk        | 20 GB SSD | 50 GB SSD   |
| Swap        | 2 GB      | 4 GB        |

### 1.2 Software

- **Docker Engine** ≥ 24.x ([install guide](https://docs.docker.com/engine/install/ubuntu/))
- **Docker Compose plugin** ≥ 2.20.x (included with Docker Engine)
- **Git** (to clone the repository)

A registered domain and SSL certificate are **optional** — see the [Production Hardening](#10-production-hardening-optional) section if you need HTTPS.

### 1.3 Required Directory Structure

```
weather-data/
├── config/              # airflow.cfg overrides (optional)
├── dags/                # DAG Python files
├── logs/                # Airflow task logs (auto-created)
├── plugins/             # Custom Airflow plugins (optional)
├── scripts/             # Entrypoint and utility scripts
│   └── entrypoint-prod.sh
├── secrets/             # Secret files (git-ignored; see §3)
├── docker-compose.yaml  # Production Compose file
├── Dockerfile           # Custom Airflow image (optional; see §5.2)
└── .env                 # Environment variables (see §4)
```

---

## 2. Server Setup

### 2.1 Connect and Update

```bash
ssh root@<your-vps-ip>

apt update && apt upgrade -y
apt autoremove -y
```

### 2.2 Create a Non-root User with Docker Access

```bash
adduser deploy
usermod -aG docker deploy

# Log out and back in as deploy
exit
ssh deploy@<your-vps-ip>
```

### 2.3 Configure Firewall (UFW)

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh                # port 22
sudo ufw allow 8080/tcp           # Airflow API server
sudo ufw --force enable
sudo ufw status verbose
```

If your VPS provider has a separate firewall panel (e.g. DigitalOcean Cloud
Firewall, AWS Security Group), also open port **22** and **8080** there.

If you later add a reverse proxy (see §10), also open ports **80** and **443**.

### 2.4 Configure Swap

```bash
# Check if swap is already active
sudo swapon --show

# Create a 4 GB swap file if none exists
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Make permanent
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Verify
free -h
```

### 2.5 Optimise Kernel Parameters (sysctl)

Create `/etc/sysctl.d/99-airflow.conf`:

```ini
# Airflow optimisation — apply with: sudo sysctl --system

# Network: increase connection backlog and buffer sizes
net.core.somaxconn = 4096
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = fq

# Connection tracking
net.netfilter.nf_conntrack_max = 1048576
net.netfilter.nf_conntrack_tcp_timeout_established = 86400

# Reduce TIME_WAIT sockets
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_tw_reuse = 1

# Increase max user watches (for inotify on DAGs)
fs.inotify.max_user_watches = 524288
```

Apply:

```bash
sudo sysctl --system
```

### 2.6 Install Docker (if not already installed)

```bash
# Official convenience script (review at https://get.docker.com)
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Log out and back in, then verify
docker --version
docker compose version
```

---

## 3. Secret Generation

All secrets are stored as plain-text files under `secrets/`. The directory is
git-ignored and must never be committed.  The Compose file mounts these as
[Docker secrets](https://docs.docker.com/compose/use-secrets/) at `/run/secrets/`.

```bash
cd /home/deploy/weather-data
mkdir -p secrets
chmod 700 secrets

# PostgreSQL password (used by both Airflow and the DB init)
python3 -c "import secrets; print(secrets.token_urlsafe(32))" \
  > secrets/postgres_password.txt

# Redis password
python3 -c "import secrets; print(secrets.token_urlsafe(32))" \
  > secrets/redis_password.txt

# Fernet key (Airflow encrypts connection passwords and variables with this)
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" \
  > secrets/fernet_key.txt

# JWT secret (Airflow API authentication)
python3 -c "import secrets; print(secrets.token_urlsafe(64))" \
  > secrets/jwt_secret.txt

# Secure the files
chmod 600 secrets/*.txt
```

> **⚠️  Warning:** Losing `fernet_key.txt` makes all previously stored Airflow
> connections and variables **undecryptable**.  Back up the `secrets/` directory
> to a secure location (e.g. a password manager or encrypted vault).

---

## 4. Environment Configuration

### 4.1 Create `.env`

```bash
# If a template exists, copy it:
cp .env.production.template .env

# Otherwise create .env manually (see §4.2)
chmod 600 .env
```

### 4.2 Edit `.env`

```bash
nano .env
```

The critical variables:

| Variable                         | Description                                | Example                        |
|----------------------------------|--------------------------------------------|--------------------------------|
| `AIRFLOW_IMAGE_NAME`             | Custom image (if using Dockerfile; §5.2)   | `airflow-custom:latest`        |
| `AIRFLOW_UID`                    | UID for file permissions (default `50000`) | `50000`                        |
| `ENV_FILE_PATH`                  | Path to this env file (default `.env`)     | `.env`                         |
| `REDIS_PASSWORD`                 | Redis password (must match secret)         |                               |
| `AIRFLOW__CELERY__BROKER_URL`    | Redis URL (password must match secret)     | `redis://:<pwd>@redis:6379/0` |
| `_AIRFLOW_WWW_USER_USERNAME`    | Admin UI username                          | `admin`                        |
| `_AIRFLOW_WWW_USER_PASSWORD`    | Admin UI password (use a strong one)       |                               |

The variables for database connection, Fernet key, and JWT secret are **not**
set in `.env`; they are injected at runtime by `scripts/entrypoint-prod.sh` from
the Docker secrets.

A minimal `.env` file looks like:

```ini
AIRFLOW_IMAGE_NAME=apache/airflow:3.3.0
AIRFLOW_UID=50000
ENV_FILE_PATH=.env
_AIRFLOW_WWW_USER_USERNAME=admin
_AIRFLOW_WWW_USER_PASSWORD=<strong-password>

REDIS_PASSWORD=<paste-from-redis_password.txt>
AIRFLOW__CELERY__BROKER_URL=redis://:<REDIS_PASSWORD>@redis:6379/0
```

> **Note:** The compose file references the env file via
> `env_file: - ${ENV_FILE_PATH:-.env}`.  If you prefer a different filename
> (e.g. `.env.production`), set `ENV_FILE_PATH` accordingly or export the
> variable before running `docker compose`.

### 4.3 Pull the Base Image (Optional)

If you are using the stock Airflow image (no custom Dockerfile), pull it now:

```bash
docker pull apache/airflow:3.3.0
```

---

## 5. Deployment Steps

### 5.1 Clone the Repository

```bash
git clone <repository-url> /home/deploy/weather-data
cd /home/deploy/weather-data
```

### 5.2 (Optional) Build a Custom Airflow Image

If you have additional Python dependencies listed in `requirements.txt`, build
a custom image using the provided `Dockerfile`:

```bash
# Create (or edit) requirements.txt with your extra packages
echo "apache-airflow-providers-http" > requirements.txt
echo "requests" >> requirements.txt

# Build the image
docker build -t airflow-custom:latest .

# Update .env:
#   AIRFLOW_IMAGE_NAME=airflow-custom:latest
```

> **Why multi-stage?** The builder stage installs Python packages with
> `--user`, keeping build tools (gcc, libc-dev, etc.) out of the runtime
> image.  This reduces the final image size and attack surface.

### 5.3 Deploy

```bash
cd /home/deploy/weather-data

# Pull images (if not already local)
docker compose pull

# Start all services in detached mode
docker compose up -d

# Verify
docker compose ps
docker compose logs --tail=50
```

The Airflow API server is now reachable at **http://\<your-vps-ip\>:8080**.
Log in with the admin credentials set in `.env`.

### 5.4 Post-deployment Checks

```bash
# Health check (direct to Airflow API server)
curl -s http://localhost:8080/healthz | jq .

# Airflow REST API health
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/api/v2/monitor/health

# From an external machine, replace localhost with the VPS IP:
# curl -s http://<VPS_IP>:8080/api/v2/monitor/health
```

Open `http://<your-vps-ip>:8080` in a browser and log in with the admin
credentials set in `.env`.

---

## 6. Backup and Restore

### 6.1 What to Back Up

| Item                    | Location                          | Criticality |
|-------------------------|-----------------------------------|-------------|
| Secrets                 | `./secrets/*.txt`                 | 🔴 Critical |
| Environment file        | `.env`                            | 🔴 Critical |
| PostgreSQL data         | Docker volume `postgres-db-volume`| 🔴 Critical |
| Redis data (if any)     | Docker volume `redis-data-volume` | 🟡 Optional |
| DAGs                    | `./dags/` (git-managed)           | 🟢 Git       |
| Custom image (optional) | Private registry or Dockerfile    | 🟡 Important |

### 6.2 Database Backup (PostgreSQL)

```bash
# One-shot backup
docker compose exec -T postgres \
  pg_dump -U airflow airflow \
  | gzip > "backups/airflow-db-$(date +%Y%m%d-%H%M%S).sql.gz"

# Automated: add a cron job
# 0 2 * * * cd /home/deploy/weather-data && docker compose exec -T postgres pg_dump -U airflow airflow | gzip > backups/daily/airflow-db-$(date +\%Y\%m\%d).sql.gz && find backups/daily -name "*.sql.gz" -mtime +30 -delete
```

### 6.3 Full Backup

```bash
BACKUP_DIR="/home/deploy/backups/weather-data-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

# 1. Database dump
docker compose exec -T postgres \
  pg_dump -U airflow airflow > "$BACKUP_DIR/airflow-db.sql"

# 2. Secrets and env
cp -r secrets "$BACKUP_DIR/"
cp .env "$BACKUP_DIR/"

# 3. Compress
tar czf "${BACKUP_DIR}.tar.gz" -C "$(dirname "$BACKUP_DIR")" "$(basename "$BACKUP_DIR")"
rm -rf "$BACKUP_DIR"

# 4. Upload to off-site storage (example: S3-compatible)
# rclone copy "${BACKUP_DIR}.tar.gz" myremote:weather-data-backups/
```

### 6.4 Restore Procedure

```bash
# 1. Stop all services
docker compose down

# 2. Restore secrets and env
cp /path/to/backup/secrets/*.txt ./secrets/
cp /path/to/backup/.env ./

# 3. Restore database (start only postgres)
docker compose up -d postgres
sleep 10  # wait for postgres to be healthy
docker compose exec -T postgres \
  psql -U airflow -d airflow < /path/to/backup/airflow-db.sql

# 4. Restart all services
docker compose up -d
```

> **Warning:** The PostgreSQL container must be fresh (empty volume) or you
> must drop the existing `airflow` schema before restoring.  To start fresh:
> `docker compose down -v` (⚠️ **this destroys all volumes**).

---

## 7. Monitoring and Logging

### 7.1 Built-in Health Endpoints

| Endpoint                                       | Purpose                        |
|------------------------------------------------|--------------------------------|
| `http://localhost:8080/api/v2/monitor/health`  | Airflow API health             |
| `http://localhost:8080/api/v2/monitor/dag_stats`| DAG execution stats           |

Replace `localhost` with the VPS IP when checking from an external machine.

### 7.2 Container Logs

```bash
# Tail logs for all services
docker compose logs --tail=100 -f

# Tail a single service
docker compose logs --tail=100 -f airflow-apiserver

# Search for errors
docker compose logs --tail=1000 airflow-scheduler | grep -i error

# Log to a file
docker compose logs --no-color > logs/deploy-$(date +%Y%m%d).log
```

### 7.3 Resource Monitoring

```bash
# Real-time container resource usage
docker stats

# Disk usage
docker system df
du -sh logs/ backups/
```

### 7.4 External Monitoring (Recommended)

- **Uptime Kuma** or **Healthchecks.io** — ping `/api/v2/monitor/health` every 5 minutes.
- **Prometheus + Grafana** — scrape `http://airflow-apiserver:8080/api/v2/monitor/health` and container metrics via `cAdvisor`.
- **Log aggregation** — ship logs to a central system (Loki, Elasticsearch, or
  Papertrail) using the `json-file` log driver.

### 7.5 Log Rotation

Docker is configured with json-file logging and rotation (10 MB × 3 files) in
`docker-compose.yaml`.  To prevent the host disk from filling up, also set up
system-wide logrotate for Docker:

```bash
sudo nano /etc/logrotate.d/docker
```

```
/var/lib/docker/containers/*/*.log {
    rotate 7
    daily
    compress
    missingok
    delaycompress
    copytruncate
}
```

---

## 8. Troubleshooting

### 8.1 Containers Keep Restarting

```bash
# Inspect logs
docker compose logs --tail=50 <service-name>

# Check if the init container completed
docker compose logs --tail=30 airflow-init

# Ensure secrets exist and are valid
ls -la secrets/
cat secrets/postgres_password.txt | wc -c   # should be > 20
```

### 8.2 Permission Errors (Volume Mounts)

Symptom: `PermissionError: [Errno 13] Permission denied: '/opt/airflow/logs'`

**Cause:** The `AIRFLOW_UID` in `.env` does not match the UID of the airflow
user inside the container (default 50000).

**Fix:**
```bash
# Check the UID used by the container
docker compose exec airflow-apiserver id -u airflow   # should be 50000

# Update .env
AIRFLOW_UID=50000

# Re-run the init container
docker compose up -d airflow-init
```

### 8.3 Port 8080 Already in Use

```bash
# Check what is listening on port 8080
sudo ss -tlnp | grep 8080

# If another service is bound to that port, either stop it or
# change the host port in docker-compose.yaml (e.g. "8081:8080").
```

### 8.4 Airflow Database Migration Failures

```bash
# Check the init container logs for SQL errors
docker compose logs --tail=100 airflow-init

# Common causes:
# - PostgreSQL not yet healthy when init started
# - Wrong postgres_password secret
# - Existing corrupt database in the volume

# To start from scratch (destroys all data):
docker compose down -v
docker compose up -d
```

### 8.5 429 Too Many Requests

If you have enabled rate limiting via a reverse proxy (see §10), and
legitimate traffic is being throttled, increase `burst` or `rate` in the
relevant `limit_req_zone` / `limit_req` directives.

### 8.6 WebSocket Errors in Airflow UI

Symptom: Task logs stream for a few seconds then disconnect.

**Check:**
```bash
# If using a reverse proxy, confirm WebSocket upgrades are forwarded:
# Look for 101 Switching Protocols in the proxy access logs.

# Increase proxy_read_timeout for the /ws/ location if tasks take
# longer than 3600s (1 hour).
```

### 8.7 Disk Space

```bash
# Check disk usage
df -h

# Prune unused Docker resources
docker system prune -af --volumes   # CAUTION: removes all unused containers, networks, images, and volumes
```

---

## 9. Upgrading

### 9.1 Upgrade Airflow (Patch within 3.3.x)

```bash
# 1. Pull the newer patch image
docker pull apache/airflow:3.3.1   # (example)

# 2. Update .env
sed -i 's/AIRFLOW_IMAGE_NAME=.*/AIRFLOW_IMAGE_NAME=apache\/airflow:3.3.1/' .env

# 3. Recreate the init container to run DB migrations
docker compose up -d airflow-init
docker compose logs --tail=30 -f airflow-init   # wait for completion

# 4. Recreate all Airflow services
docker compose up -d --remove-orphans

# 5. Verify
docker compose ps
```

### 9.2 Upgrade to a New Minor/Major Version (e.g. 3.4.0)

> **Always test in a staging environment first.**

```bash
# 1. Backup the database (see §6)
# 2. Check for breaking changes in the Airflow changelog
# 3. Update the image tag in .env
# 4. Run the init container (see §9.1 step 3)
# 5. If migration fails: restore backup and roll back the image tag
```

### 9.3 Upgrade Service Images (PostgreSQL / Redis)

```bash
# Upgrade base images without changing Airflow
docker compose pull postgres redis
docker compose up -d --remove-orphans
```

### 9.4 Rollback

```bash
# Revert .env to the previous image tag
# Re-run init and services:
docker compose up -d airflow-init
docker compose up -d --remove-orphans
```

If the rollback involves a database schema change that is not backward
compatible, you **must** restore from a database backup taken before the
upgrade.

---

## 10. Production Hardening (Optional)

This section describes how to add an **nginx reverse proxy** with **SSL/TLS
via Let's Encrypt** in front of the Airflow API server.  This is recommended
for production deployments that serve traffic over the internet.

### 10.1 Directory Structure Additions

```
weather-data/
├── nginx/                # nginx reverse-proxy configuration
│   └── nginx.conf
├── certbot/              # Let's Encrypt certificates (auto-created)
│   ├── conf/
│   └── www/
```

### 10.2 Configure the Reverse Proxy

Create `nginx/nginx.conf` with the following content (replace
`your-domain.com` with your actual domain):

```nginx
events {
    worker_connections 1024;
}

http {
    # ------------------------------------------------------------------
    # Upstream: Airflow API server (on the backend Docker network)
    # ------------------------------------------------------------------
    upstream airflow {
        server airflow-apiserver:8080;
    }

    # ------------------------------------------------------------------
    # Redirect HTTP → HTTPS
    # ------------------------------------------------------------------
    server {
        listen 80;
        server_name your-domain.com;

        location /.well-known/acme-challenge/ {
            root /var/www/certbot;
        }

        location / {
            return 301 https://$host$request_uri;
        }
    }

    # ------------------------------------------------------------------
    # HTTPS server
    # ------------------------------------------------------------------
    server {
        listen 443 ssl http2;
        server_name your-domain.com;

        ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

        # Modern SSL configuration (Mozilla Intermediate)
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
        ssl_prefer_server_ciphers off;
        ssl_session_cache shared:SSL:10m;
        ssl_session_timeout 1d;

        # HSTS (optional — uncomment after confirming HTTPS works)
        # add_header Strict-Transport-Security "max-age=63072000" always;

        # ------------------------------------------------------------------
        # Reverse proxy to Airflow API server
        # ------------------------------------------------------------------
        location / {
            proxy_pass http://airflow;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # WebSocket support (required for Airflow task log streaming)
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_read_timeout 3600s;
        }

        # Health check endpoint (no caching)
        location /healthz {
            proxy_pass http://airflow/healthz;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }
    }
}
```

### 10.3 Issue SSL Certificate with Certbot

Run certbot in standalone mode to obtain the initial certificate:

```bash
mkdir -p certbot/conf certbot/www

docker run --rm -it \
  -p 80:80 \
  -v /home/deploy/weather-data/certbot/conf:/etc/letsencrypt \
  certbot/certbot:v2.2.0 certonly --standalone \
  -d your-domain.com
```

> **Note:** Standalone mode requires port 80 to be free.  Stop any process
> listening on port 80 before running this command.

### 10.4 Add the nginx Service to docker-compose.yaml

Add the nginx service to `docker-compose.yaml` (or create a
`docker-compose.override.yaml`):

```yaml
services:
  nginx:
    image: nginx:1.27-bookworm
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./certbot/www:/var/www/certbot:ro
      - ./certbot/conf:/etc/letsencrypt:ro
    networks:
      - backend
    depends_on:
      airflow-apiserver:
        condition: service_healthy
```

Then restart:

```bash
docker compose up -d
```

### 10.5 Set Up Auto-renewal

Create a cron job to renew the certificate before it expires (Let's Encrypt
certificates are valid for 90 days).

```bash
sudo crontab -e
```

Add the following line (runs daily at 03:00):

```cron
0 3 * * * docker run --rm \
  -p 80:80 \
  -v /home/deploy/weather-data/certbot/conf:/etc/letsencrypt \
  certbot/certbot:v2.2.0 renew --quiet && \
  docker exec nginx nginx -s reload
```

### 10.6 Update Firewall

If you followed the minimal firewall setup in §2.3, add ports 80 and 443:

```bash
sudo ufw allow http
sudo ufw allow https
sudo ufw status verbose
```

### 10.7 Update Post-deployment Checks

After the reverse proxy is in place, use HTTPS URLs:

```bash
# Health check through nginx
curl -s https://your-domain.com/healthz | jq .

# Airflow REST API
curl -s -o /dev/null -w "%{http_code}" https://your-domain.com/api/v2/monitor/health
```

---

## 11. Reference

### Useful Commands

| Action                                           | Command                                                       |
|--------------------------------------------------|---------------------------------------------------------------|
| Start all services                               | `docker compose up -d`                                        |
| Stop all services                                | `docker compose down`                                         |
| Restart a service                                | `docker compose restart <service>`                            |
| View logs (follow)                               | `docker compose logs -f <service>`                            |
| Execute a command inside a running container     | `docker compose exec <service> <command>`                     |
| Enter a container shell                          | `docker compose exec <service> bash`                          |
| Inspect image layers                             | `docker history airflow-custom:latest`                        |
| List Docker networks                             | `docker network ls`                                           |
| Inspect network (find container IPs)             | `docker network inspect weather_data_backend`                 |

### Ports Reference

| Port | Service        | Bound on Host | Notes                    |
|------|----------------|---------------|--------------------------|
| 22   | SSH            | Yes           | Firewalled to your IP    |
| 8080 | Airflow API    | Yes           | Airflow UI + API         |
| 5432 | PostgreSQL     | No            | Internal (backend network) |
| 6379 | Redis          | No            | Internal                 |

> If you add the optional nginx reverse proxy (see §10), ports **80** and
> **443** will also be bound on the host.

### File Permissions Reference

```bash
# Secrets directory
chmod 700 secrets/
chmod 600 secrets/*.txt

# Env file
chmod 600 .env

# Entrypoint script
chmod 755 scripts/entrypoint-prod.sh
```

---

> **Maintainer note:** Keep this document up to date with every significant
> infrastructure change.  Review the Airflow release notes before upgrading
> the base image.  Test backup and restore procedures at least quarterly.
