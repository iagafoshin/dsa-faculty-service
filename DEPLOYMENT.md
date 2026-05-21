# Прод-деплой DSA Faculty Service

Целевая конфигурация:

```
       internet
          │ :443 (https) / :80 (redirect)
          ▼
       ┌──────────┐
       │  Caddy   │  auto-TLS (Let's Encrypt) + basic-auth для /admin/*
       └────┬─────┘
            │ docker-network
            ▼
       ┌──────────┐        ┌────────┐
       │   app    │ ─SQL→ │   db   │  ← порт 5433 только на 127.0.0.1
       │ (uvicorn)│        │ pgvect │     (для SSH-туннеля при sync)
       └──────────┘        └────────┘
```

- Postgres снаружи **не доступен** — только через docker-network для app
  и через SSH-туннель к `127.0.0.1:5433` для разовых задач.
- App снаружи **не доступен напрямую** — только через Caddy.
- `/admin/*`, `/api/v1/admin/*`, `/docs` закрыты basic-auth на уровне Caddy.

---

## 0. Что должно быть до старта

- **VPS** на Ubuntu/Debian (минимум **2 vCPU + 4GB RAM** — нужно для torch
  + model in memory; **2GB SSD** под Docker-образ + ~1GB под Postgres-данные)
- **Домен** с A-записью на IP сервера (для Let's Encrypt)
- **SSH-ключ** для GitHub Actions (deploy без пароля)
- **Локальная БД** уже обогащена через `python -m app.nlp enrich-*`

---

## 1. Подготовка VPS

```bash
# Локально:
ssh root@your-vps-ip

# На сервере: создаём пользователя для деплоя
adduser dsa
usermod -aG sudo dsa
mkdir -p /home/dsa/.ssh
# Положи туда свой ssh-публичный ключ:
nano /home/dsa/.ssh/authorized_keys
chmod 700 /home/dsa/.ssh
chmod 600 /home/dsa/.ssh/authorized_keys
chown -R dsa:dsa /home/dsa/.ssh
```

### SSH hardening

```bash
# /etc/ssh/sshd_config — отключи парольный логин и root
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart ssh
```

### Firewall (UFW)

```bash
apt install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp     # SSH
ufw allow 80/tcp     # HTTP (Caddy redirects → 443)
ufw allow 443/tcp    # HTTPS
ufw --force enable
ufw status
```

**Postgres-порт 5432/5433 НЕ открываем** — он биндится только на
`127.0.0.1` внутри docker-compose.prod.yml. Доступ к БД снаружи —
ТОЛЬКО через SSH-туннель.

### Fail2ban (защита от brute-force SSH)

```bash
apt install -y fail2ban
systemctl enable --now fail2ban
```

### Docker + compose

```bash
curl -fsSL https://get.docker.com | sh
usermod -aG docker dsa
```

### Auto-updates безопасности

```bash
apt install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades
```

---

## 2. Клонирование репо

```bash
# На сервере под пользователем dsa:
sudo mkdir -p /opt/dsa-faculty-service
sudo chown dsa:dsa /opt/dsa-faculty-service
cd /opt
git clone https://github.com/<you>/dsa-faculty-service.git
cd dsa-faculty-service
```

---

## 3. Секреты — `.env`

```bash
cp .env.example .env
nano .env
```

Заполни **сильными значениями**:

```bash
# Сгенерировать random-токен:
openssl rand -hex 24    # для ADMIN_TOKEN
openssl rand -hex 24    # для POSTGRES_PASSWORD

# Bcrypt-хеш для basic-auth на /admin:
docker run --rm caddy:2-alpine caddy hash-password
# Введи пароль (он будет вводиться в браузере)
# Скопируй полученный хеш в CADDY_ADMIN_HASH
```

Минимально:

```env
DOMAIN=faculty.example.ru
POSTGRES_PASSWORD=<длинный-random-32-симв>
DATABASE_URL=postgresql+asyncpg://postgres:<тот-же-PASSWORD>@db:5432/hse_faculty
ADMIN_TOKEN=<длинный-random>
CADDY_ADMIN_USER=admin
CADDY_ADMIN_HASH=$2a$14$ABC...
CORS_ORIGINS=https://faculty.example.ru
```

**`chmod 600 .env`** — права только владельцу.

---

## 4. Первый деплой

```bash
cd /opt/dsa-faculty-service
docker compose -f docker-compose.prod.yml up -d --build
# Первый билд занимает 5–10 минут (NLP-extras + spaCy-модели).

# Миграции
sleep 10
docker compose -f docker-compose.prod.yml exec -T app alembic upgrade head

# Проверка
curl -k https://faculty.example.ru/api/v1/health
# {"status": "ok", "version": "0.4.0"}

curl -k https://faculty.example.ru/api/v1/meta/campuses
# [...4 campuses...]
```

Caddy сам получит TLS-сертификат от Let's Encrypt при первом запросе
(нужны открытые порты 80/443 + правильный DNS).

---

## 5. Перенос NLP-обогащения с локалки на прод

NLP-batch (enrich-persons / enrich-publications) на сервере **НЕ запускаем**
— это часовая операция, требующая много RAM. Считаем локально (где есть
MPS/GPU), потом синкаем embeddings.

```bash
# Локально: открой SSH-туннель в отдельном терминале
ssh -L 5434:127.0.0.1:5433 dsa@your-vps.example.ru
# Туннель: localhost:5434 (твоя машина) → 127.0.0.1:5433 (прод-db)

# В другом терминале (тоже локально):
DATABASE_URL_LOCAL='postgresql+asyncpg://postgres:LOCAL_PWD@localhost:5433/hse_faculty' \
DATABASE_URL_PROD='postgresql+asyncpg://postgres:PROD_PWD@localhost:5434/hse_faculty' \
.venv/bin/python scripts/sync_embeddings_to_prod.py
```

Скрипт перенесёт:
- `persons.embedding` + `persons.interests_extracted` (≈5984 строк)
- `publications.embedding` + `publications.topics` (≈71115 строк)

Время: ~5-10 минут (SQL UPDATE по сети).

Идемпотентно. Если локально сделал новый enrich — запусти снова, новое
попадёт в прод.

**Проверка:**
```bash
curl -u admin:PASSWORD -k 'https://faculty.example.ru/api/v1/experts/search?q=machine+learning&limit=3'
# должны быть results с score>0 и matched_topics
```

---

## 6. Скрейп новых данных на сервере

Скрейпер сам по себе **не** требует NLP, гонять можно прямо на проде:

```bash
# Через UI (basic-auth откроет popup):
open https://faculty.example.ru/admin

# Или через JSON API:
curl -u admin:PASSWORD -X POST \
  -H "X-Admin-Token: <ADMIN_TOKEN>" \
  "https://faculty.example.ru/api/v1/admin/scrape?limit=100"
```

После прихода новых данных — **прогон enrich локально + sync**.

---

## 7. Чек-лист безопасности

- [ ] Postgres-порт 5432/5433 закрыт в UFW (доступен только через docker-network)
- [ ] SSH: ключи only, no root, no password
- [ ] `.env` chmod 600, не в git
- [ ] `ADMIN_TOKEN`, `POSTGRES_PASSWORD`, `CADDY_ADMIN_HASH` — все длинный random
- [ ] Fail2ban активен (`fail2ban-client status`)
- [ ] UFW активен (`ufw status` — 22, 80, 443)
- [ ] unattended-upgrades включены
- [ ] TLS работает (Caddy сам подтянул сертификат)
- [ ] `/docs` и `/admin/*` закрыты basic-auth
- [ ] `CORS_ORIGINS` НЕ `*` в проде (укажи конкретный домен)
- [ ] Docker app запускается под uid=1000 (не root)

---

## 8. Бэкапы Postgres

Самый простой вариант — крон + `pg_dump`:

```bash
# /etc/cron.daily/dsa-db-backup
#!/bin/bash
mkdir -p /var/backups/dsa
docker exec dsa-faculty-service-db-1 \
  pg_dump -U postgres hse_faculty | gzip \
  > /var/backups/dsa/db-$(date +%F).sql.gz
# Хранить 14 дней
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

---

## 9. CI/CD через GitHub Actions

`.github/workflows/deploy.yml` уже настроен. Нужно положить в **Settings →
Secrets** репы:

| Secret | Значение |
|---|---|
| `VPS_HOST` | IP сервера или DNS |
| `VPS_USER` | `dsa` |
| `SSH_PRIVATE_KEY` | приватный ключ той пары, чей публичный лежит на сервере |

Дальше каждый `git push` в `main` → автодеплой.

---

## 10. Чего нет (но можно докрутить позже)

- Rate-limiting на API (Caddy умеет, можно прикрутить)
- Внешний health-check (UptimeRobot/Healthchecks.io пингует `/api/v1/health`)
- Метрики (Prometheus + Grafana — overkill для одного сервиса)
- Read-replica Postgres
