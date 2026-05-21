# Прод-деплой DSA Faculty Service

Конфигурация:

```
       internet :443
          │  (TLS — host-nginx с certbot)
          ▼
   ┌──────────────┐
   │ host nginx   │  proxy_pass → 127.0.0.1:8000
   └──────┬───────┘
          │
          ▼
   ┌──────────┐       ┌────────┐
   │   app    │  SQL→ │   db   │   127.0.0.1:5433 на хосте
   │ (uvicorn)│       │ pgvect │   (для SSH-туннеля)
   └──────────┘       └────────┘
       docker network
```

- TLS терминируется **host-nginx**'ом (уже стоит на сервере, нужен certbot).
- App слушает только `127.0.0.1:8000` — снаружи недоступен напрямую.
- Postgres снаружи **не доступен** — только через docker-network для app
  и через SSH-туннель к `127.0.0.1:5433`.

---

## 0. Что должно быть

- **VPS** на Ubuntu/Debian (≥ 2 vCPU + 4GB RAM — нужен torch + model)
- **nginx** на хосте, с TLS (certbot)
- **Домен** с A-записью на IP сервера
- **SSH-ключ** для GitHub Actions
- **Локальная БД** обогащена через `python -m app.nlp enrich-*`

---

## 1. Подготовка VPS (если ещё не делал)

```bash
# Создать deploy-пользователя
adduser dsa && usermod -aG sudo dsa
mkdir -p /home/dsa/.ssh
# положи свой публичный ssh-ключ
chmod 700 /home/dsa/.ssh
chmod 600 /home/dsa/.ssh/authorized_keys
chown -R dsa:dsa /home/dsa/.ssh

# SSH hardening
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart ssh

# Firewall
apt install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp     # для certbot + redirect 80→443
ufw allow 443/tcp
ufw --force enable

# Brute-force защита SSH
apt install -y fail2ban
systemctl enable --now fail2ban

# Docker
curl -fsSL https://get.docker.com | sh
usermod -aG docker dsa

# Auto-updates безопасности
apt install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades
```

Postgres-порт **НЕ открываем** — он биндится только на `127.0.0.1`.

---

## 2. host-nginx

Если уже стоит и работает на твоём домене с certbot — пропусти. Иначе
типовой конфиг (`/etc/nginx/sites-available/faculty`):

```nginx
server {
    listen 80;
    server_name faculty.example.ru;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name faculty.example.ru;

    ssl_certificate     /etc/letsencrypt/live/faculty.example.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/faculty.example.ru/privkey.pem;

    # Защита админ-путей basic-auth'ом
    location ~ ^/(admin|api/v1/admin|docs|redoc|openapi\.json) {
        auth_basic           "Restricted";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Security headers
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
}
```

```bash
# Создать htpasswd для basic-auth на /admin
apt install -y apache2-utils
htpasswd -c /etc/nginx/.htpasswd admin

# Получить TLS-сертификат
apt install -y certbot python3-certbot-nginx
certbot --nginx -d faculty.example.ru

ln -s /etc/nginx/sites-available/faculty /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

---

## 3. Клонирование репо

```bash
sudo mkdir -p /opt/dsa-faculty-service
sudo chown dsa:dsa /opt/dsa-faculty-service
cd /opt
git clone https://github.com/<you>/dsa-faculty-service.git
cd dsa-faculty-service
```

---

## 4. Секреты — `.env`

```bash
cp .env.example .env

# Сгенерировать random:
openssl rand -hex 24    # для ADMIN_TOKEN
openssl rand -hex 24    # для POSTGRES_PASSWORD

nano .env
chmod 600 .env
```

Минимально:

```env
POSTGRES_PASSWORD=<длинный-random>
DATABASE_URL=postgresql+asyncpg://postgres:<тот-же>@db:5432/hse_faculty
ADMIN_TOKEN=<длинный-random>
CORS_ORIGINS=https://faculty.example.ru
APP_NAME=dsa-faculty-service
APP_VERSION=0.4.0
LOG_LEVEL=INFO
POSTGRES_USER=postgres
POSTGRES_DB=hse_faculty
```

---

## 5. Первый деплой

```bash
cd /opt/dsa-faculty-service

# Прод-сборка с NLP-extras (Dockerfile.prod). ~5-7 минут на холодную.
docker compose -f docker-compose.prod.yml up -d --build

sleep 10
docker compose -f docker-compose.prod.yml exec -T app alembic upgrade head

# Проверка (через host-nginx с TLS)
curl https://faculty.example.ru/api/v1/health
# {"status": "ok", ...}
```

---

## 6. Перенос NLP-обогащения с локалки на прод

NLP-batch (enrich-persons / enrich-publications) на сервере **НЕ запускаем**.
Считаем локально (MPS/GPU), потом синкаем embeddings.

```bash
# Локально: открой SSH-туннель в отдельном терминале
ssh -L 5434:127.0.0.1:5433 dsa@faculty.example.ru

# В другом терминале (тоже локально):
DATABASE_URL_LOCAL='postgresql+asyncpg://postgres:LOCAL_PWD@localhost:5433/hse_faculty' \
DATABASE_URL_PROD='postgresql+asyncpg://postgres:PROD_PWD@localhost:5434/hse_faculty' \
.venv/bin/python scripts/sync_embeddings_to_prod.py
```

Перенесёт:
- `persons.embedding` + `persons.interests_extracted`
- `publications.embedding` + `publications.topics`

Время: ~5-10 минут. Идемпотентно (запустишь снова — обновятся только
новые/изменённые).

---

## 7. CI/CD

`.github/workflows/deploy.yml` уже настроен. В **Settings → Secrets** репы:

| Secret | Значение |
|---|---|
| `VPS_HOST` | IP сервера или DNS |
| `VPS_USER` | `dsa` |
| `SSH_PRIVATE_KEY` | приватный ключ той пары, чей публичный лежит на сервере |

Дальше push в `main` → автодеплой.

---

## 8. Чек-лист безопасности

- [ ] Postgres-порт `5432/5433` закрыт в UFW (только `127.0.0.1`)
- [ ] SSH: ключи only, no root, no password
- [ ] `.env` chmod 600, не в git
- [ ] `ADMIN_TOKEN`, `POSTGRES_PASSWORD` — длинный random (≥32 симв)
- [ ] Fail2ban активен (`fail2ban-client status`)
- [ ] UFW: `22, 80, 443` (БД не торчит)
- [ ] unattended-upgrades включены
- [ ] TLS работает (certbot выдал серт)
- [ ] `/admin/*`, `/docs` закрыты basic-auth на nginx
- [ ] `CORS_ORIGINS` НЕ `*` (укажи свой домен)
- [ ] Docker app запускается под `uid=1000` (см. `Dockerfile.prod`)

---

## 9. Бэкапы Postgres

```bash
# /etc/cron.daily/dsa-db-backup
#!/bin/bash
mkdir -p /var/backups/dsa
docker exec dsa-faculty-service-db-1 \
  pg_dump -U postgres hse_faculty | gzip \
  > /var/backups/dsa/db-$(date +%F).sql.gz
find /var/backups/dsa -name 'db-*.sql.gz' -mtime +14 -delete
```

```bash
chmod +x /etc/cron.daily/dsa-db-backup
```

**Восстановление:**
```bash
gunzip < /var/backups/dsa/db-2026-05-22.sql.gz | \
  docker exec -i dsa-faculty-service-db-1 psql -U postgres -d hse_faculty
```
