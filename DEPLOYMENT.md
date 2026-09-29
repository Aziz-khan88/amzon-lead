# 🚀 Production Deployment & Operations Guide

This guide covers deploying the **Book Trailer Lead Finder** application in a production environment using **Ubuntu Linux**, **PostgreSQL**, **Gunicorn**, **Nginx**, and **systemd**.

---

## 🏗️ Production Architecture Overview

```mermaid
graph TD
    Client[Browser / API Client] -->|HTTPS :443| Nginx[Nginx Web Server]
    
    subgraph AppServer ["Application Server (Ubuntu Linux)"]
        Nginx -->|Static Assets| StaticFiles["/var/www/leadfinder/static"]
        Nginx -->|Proxy Pass Unix Socket| Gunicorn["Gunicorn WSGI Workers (4 Workers)"]
        Gunicorn --> DjangoApp["Django Lead Finder Application"]
        
        Systemd[systemd Daemon] -->|Manages Process| Gunicorn
        Systemd -->|Manages Worker| Scheduler["Scheduler Loop Worker (python manage.py run_scheduler_loop --daemon)"]
        
        DjangoApp --> Postgres[(PostgreSQL 14+ Database)]
        Scheduler --> Postgres
    end
```

---

## 1. Server Preparation & Package Installation

On a fresh Ubuntu 22.04 or 24.04 LTS server:

```bash
# Update repository packages
sudo apt update && sudo apt upgrade -y

# Install system dependencies
sudo apt install -y python3-venv python3-pip python3-dev postgresql postgresql-contrib nginx curl git
```

---

## 2. PostgreSQL Database Setup

```bash
# Switch to postgres user
sudo -u postgres psql

# Execute SQL commands:
CREATE DATABASE leadfinder_prod;
CREATE USER leadfinder_user WITH ENCRYPTED PASSWORD 'StrongProductionPasswordHere!';
GRANT ALL PRIVILEGES ON DATABASE leadfinder_prod TO leadfinder_user;
ALTER DATABASE leadfinder_prod OWNER TO leadfinder_user;
\q
```

---

## 3. Application Setup & Virtual Environment

```bash
# Create dedicated application directory
sudo mkdir -p /var/www/leadfinder
sudo chown -R $USER:$USER /var/www/leadfinder

# Clone repository
git clone git@github.com:Aziz-khan88/amzon-lead.git /var/www/leadfinder
cd /var/www/leadfinder

# Create and activate Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install production dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn psycopg[binary]
```

---

## 4. Production Environment Configuration (`.env`)

Create `/var/www/leadfinder/.env`:

```env
# Core Production Settings
DEBUG=False
SECRET_KEY=generate-a-strong-random-50-character-secret-key-here
ALLOWED_HOSTS=leads.yourdomain.com,www.leads.yourdomain.com,127.0.0.1

# Database URL
DATABASE_URL=postgres://leadfinder_user:StrongProductionPasswordHere!@127.0.0.1:5432/leadfinder_prod

# SSL & Security Headers
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
CSRF_TRUSTED_ORIGINS=https://leads.yourdomain.com

# API Keys
GROQ_API_KEY=your_production_groq_key
TAVILY_API_KEY=your_production_tavily_key
YOUTUBE_API_KEY=your_production_youtube_key

# Scheduler Settings
APP_MAX_SOCIAL_CONTACT_PAGES=5
APP_SCHEDULED_TASK_LEASE_SECONDS=21600
```

---

## 5. Database Migrations & Static Asset Collection

```bash
# Run migrations on production PostgreSQL
python manage.py migrate

# Create initial superadmin
python manage.py createsuperuser

# Collect static files into STATIC_ROOT
python manage.py collectstatic --noinput
```

---

## 6. Process Management with systemd

### 6.1 Gunicorn WSGI Service
Create `/etc/systemd/system/leadfinder-gunicorn.service`:

```ini
[Unit]
Description=Gunicorn daemon for Book Trailer Lead Finder
After=network.target postgresql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/leadfinder
ExecStart=/var/www/leadfinder/.venv/bin/gunicorn \
          --workers 4 \
          --bind unix:/run/leadfinder.sock \
          --access-logfile /var/log/leadfinder/gunicorn-access.log \
          --error-logfile /var/log/leadfinder/gunicorn-error.log \
          --timeout 120 \
          booktrailer_leads.wsgi:application
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 6.2 Scheduler Worker Service
Create `/etc/systemd/system/leadfinder-scheduler.service`:

```ini
[Unit]
Description=Background Scheduler Worker for Lead Hunts
After=network.target postgresql.service leadfinder-gunicorn.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/leadfinder
ExecStart=/var/www/leadfinder/.venv/bin/python manage.py run_scheduler_loop --daemon --check-interval 60
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 6.3 Enable & Start Services
```bash
# Create log directory with proper permissions
sudo mkdir -p /var/log/leadfinder
sudo chown -R www-data:www-data /var/log/leadfinder

# Reload systemd and start services
sudo systemctl daemon-reload
sudo systemctl enable --now leadfinder-gunicorn
sudo systemctl enable --now leadfinder-scheduler

# Verify status
sudo systemctl status leadfinder-gunicorn
sudo systemctl status leadfinder-scheduler
```

---

## 7. Nginx Configuration & SSL Setup

Create `/etc/nginx/sites-available/leadfinder`:

```nginx
server {
    server_name leads.yourdomain.com;

    client_max_body_size 25M;

    # Static file serving with long-lived cache
    location /static/ {
        alias /var/www/leadfinder/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, max-age=2592000, immutable";
    }

    # Pass all dynamic requests to Gunicorn socket
    location / {
        include proxy_params;
        proxy_pass http://unix:/run/leadfinder.sock;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 90s;
        proxy_read_timeout 90s;
    }
}
```

Enable site and configure SSL with Let's Encrypt:
```bash
sudo ln -s /etc/nginx/sites-available/leadfinder /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Install free SSL certificate
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d leads.yourdomain.com
```

---

## 8. Backup & Maintenance

### Automated Daily Database Backup
Add a daily cron job (`/etc/cron.daily/leadfinder-backup`):

```bash
#!/bin/bash
BACKUP_DIR="/var/backups/leadfinder"
mkdir -p "$BACKUP_DIR"
DATE=$(date +\%Y\%m\%d_\%H\%M\%S)
sudo -u postgres pg_dump leadfinder_prod | gzip > "$BACKUP_DIR/db_$DATE.sql.gz"
find "$BACKUP_DIR" -type f -name "*.sql.gz" -mtime +14 -delete
```
Make executable: `sudo chmod +x /etc/cron.daily/leadfinder-backup`.

---

## 9. Deployment Verification Checklist

- [ ] `DEBUG=False` verified in production `.env`.
- [ ] HTTPS redirect verified via browser inspection.
- [ ] Database migrations up to date (`python manage.py showmigrations`).
- [ ] Static files load with HTTP 200 / 304 without 404 errors.
- [ ] `leadfinder-scheduler` service active and executing due tasks.
- [ ] Full automated test suite passes on target production runtime (`pytest leadfinder/tests`).
