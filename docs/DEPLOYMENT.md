# Deploying InteriorIQ

InteriorIQ runs out of the box on one computer with SQLite and no other services. This guide covers the next steps: a real Postgres
database, moving existing data there, several API servers with Celery workers, running behind a domain, and backups.

All commands are run from `apps/api` unless stated otherwise, with settings in `apps/api/.env` (copy `.env.example`).

---

## 1. Before anything: production settings

In `apps/api/.env`:

```ini
SECRET_KEY=<a long random string>          # signs logins; never keep the development default
PUBLIC_URL=https://iq.example.com          # used in client emails (portal links)
```

Generate a key with: `python -c "import secrets; print(secrets.token_urlsafe(48))"`

Change the passwords of the seeded `@interioriq.com` users (Settings → Users), or create your own admin and deactivate them.

---

## 2. Postgres

1. Install PostgreSQL (any recent version; tested with 18) and the driver:

   ```bash
   pip install "psycopg[binary]"
   ```

2. Create a database and a user:

   ```sql
   CREATE USER interioriq WITH PASSWORD 'choose-a-password';
   CREATE DATABASE interioriq OWNER interioriq;
   ```

3. Point the app at it in `.env`:

   ```ini
   DATABASE_URL=postgresql+psycopg://interioriq:choose-a-password@localhost:5432/interioriq
   ```

4. Create the tables:

   ```bash
   alembic upgrade head
   ```

   (The API also does this on start while `AUTO_MIGRATE=true`.) Check with `alembic current`; Settings → System shows the database
   revision next to the revision the code expects.

---

## 3. Moving existing SQLite data to Postgres

A backup restores into either database, so the move is: back up from SQLite, restore into Postgres.

```bash
# 1. with the OLD setting (SQLite) still in .env — stop the API first so nothing changes meanwhile
python -m app.backup create --out ../../move
#    → prints the path of the zip, e.g. ../../move/manual-20261119-101500.zip

# 2. switch DATABASE_URL in .env to Postgres (section 2), then:
python -m app.backup restore ../../move/manual-20261119-101500.zip --yes

# 3. start the API and check a few projects, quotations and documents
```

The restore checks every checksum first, builds the schema at the backup's revision, loads all rows and migrates to the current
revision — in one transaction, so a failure leaves the target database unchanged. Uploaded files come along if `STORAGE_PATH` is the
same folder (or add `--no-files` and copy the folder yourself).

---

## 4. Several API servers + Celery workers

With the default `TASK_BACKEND=thread`, document reading (OCR) and email sending run inside the API process. That is right for one
server. For more:

1. In `.env` on every server and worker:

   ```ini
   TASK_BACKEND=celery
   CELERY_BROKER_URL=sqla+postgresql+psycopg://interioriq:choose-a-password@localhost:5432/interioriq_broker
   AUTO_MIGRATE=false
   ```

   The broker can be a separate Postgres database (free, no extra service — create `interioriq_broker` like in section 2),
   `sqla+sqlite:///./celery-broker.db` for a single machine, or Redis (`redis://localhost:6379/0`) for heavy use.

2. Run migrations once per deploy (not from every server): `alembic upgrade head`

3. Start the API servers, e.g. `uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4`

4. Start one or more workers (same `.env`, same `STORAGE_PATH`):

   ```bash
   celery -A app.worker worker --loglevel=info            # Linux / macOS
   celery -A app.worker worker --pool=solo --loglevel=info   # Windows
   ```

5. `STORAGE_PATH` (uploads) and `BACKUP_DIR` must be the same shared folder for all servers and workers (network share / mounted volume).

Every email and every document is claimed with a single conditional database update, so two servers or workers never send the same email
or read the same document twice. Stuck jobs are recovered by time (`EMAIL_STALE_MINUTES`, `OCR_STALE_MINUTES`). The daily backup is also
claimed, so only one server takes it.

---

## 5. Behind a domain (one address for the app and the API)

Build the web app with the public address and run it:

```bash
cd apps/web
NEXT_PUBLIC_API_URL=https://iq.example.com npm run build      # PowerShell: $env:NEXT_PUBLIC_API_URL="https://iq.example.com"; npm run build
npm start                                                      # serves on port 3000
```

Then send `/api/…` to the API and everything else to the web app. Example with Caddy (automatic HTTPS):

```caddy
iq.example.com {
    handle /api/* {
        reverse_proxy 127.0.0.1:8000
    }
    handle {
        reverse_proxy 127.0.0.1:3000
    }
}
```

or nginx:

```nginx
server {
    server_name iq.example.com;
    client_max_body_size 30m;                 # drawing uploads
    location /api/ { proxy_pass http://127.0.0.1:8000; proxy_read_timeout 600s; }
    location /     { proxy_pass http://127.0.0.1:3000; }
}
```

Because the browser talks to one address, no CORS settings are needed. (If the API lives on a different address, list the site in
`ALLOWED_ORIGINS=["https://iq.example.com"]`.)

---

## 6. Backups

- **Automatic:** one backup per day after `BACKUP_HOUR` (company local time), the last `BACKUP_KEEP` kept, in `BACKUP_DIR`
  (default `../../backups`, i.e. `D:\interioriq\backups` next to the project). Turn off with `BACKUP_DAILY=false`.
- **By hand:** Settings → Backups → *Back up now*, or `python -m app.backup create`.
- **What's inside:** every table as JSON, the uploads folder, and a manifest with a SHA-256 for each table and file.
  *Verify* (or `python -m app.backup verify FILE`) re-checks them all.
- **Restore:** Settings → Backups → *Restore* (type RESTORE), or `python -m app.backup restore FILE --yes`. A safety backup of the current
  data is taken first; the database part is all-or-nothing; the current uploads folder is kept beside the restored one as
  `storage.before-restore-<time>`.
- **Keep copies elsewhere:** a backup on the same disk doesn't survive that disk. Copy `BACKUP_DIR` to another drive or a cloud folder
  regularly (e.g. a scheduled `robocopy` / `rsync`).
- **Confidential:** backups contain client details and password hashes. Never commit them or share them publicly.

### Restore drill (do it once, then a few times a year)

1. Create a scratch database (`CREATE DATABASE interioriq_drill;`).
2. `DATABASE_URL=postgresql+psycopg://…/interioriq_drill python -m app.backup restore <latest backup> --yes --no-files`
3. Start an API against it on another port and sign in. If that works, your backups work. Drop the scratch database afterwards.

---

## 7. Checklist

- [ ] `SECRET_KEY` set, seeded passwords changed
- [ ] Postgres, `alembic current` = head (Settings → System says *Up to date*)
- [ ] `TASK_BACKEND=celery` + workers running, if more than one server
- [ ] HTTPS in front, `/api` proxied, `PUBLIC_URL` set
- [ ] Daily backups on, copied off the machine, one restore drill done
- [ ] SMTP set (optional) — Settings → Notifications → *Send test email*
