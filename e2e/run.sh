#!/usr/bin/env bash
# One-command browser test. Prereqs (once):  pip install playwright httpx && python -m playwright install chromium
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Ports: WEB_PORT/API_PORT (default 3000/8000) — use e.g. WEB_PORT=3100 API_PORT=8100 when another app holds the defaults.
WEB_PORT=${WEB_PORT:-3000}; API_PORT=${API_PORT:-8000}
# Refuse to run if something else holds the ports: a stale server would silently serve OLD code and give false results.
for port in $WEB_PORT $API_PORT; do
  if curl -s -o /dev/null --max-time 2 "localhost:$port"; then echo "Port $port is already in use. Stop that server first, then re-run."; exit 1; fi
done

echo "Building the web app (so the test always runs the current code)..."
if [ "$API_PORT" != "8000" ]; then export NEXT_PUBLIC_API_URL="http://localhost:$API_PORT"; fi   # the browser must call the test API
(cd "$ROOT/apps/web" && npm run build >/tmp/iq_build.log 2>&1) || { echo "BUILD FAILED:"; tail -25 /tmp/iq_build.log; exit 1; }

# CELERY=1 bash e2e/run.sh: background jobs (OCR, email) go to a real Celery worker on a free database broker (sqla+sqlite), started here.
export TASK_BACKEND=thread IQ_TASK_BACKEND=thread
# uploads + backups of the test run go to throwaway folders, never the real storage/ or backups/
TMPD=$(mktemp -d); export STORAGE_PATH="$TMPD/storage" BACKUP_DIR="$TMPD/backups" BACKUP_DAILY=false
if [ "$CELERY" = "1" ]; then export TASK_BACKEND=celery IQ_TASK_BACKEND=celery CELERY_BROKER_URL=sqla+sqlite:///./e2e-broker.db; rm -f "$ROOT/apps/api/e2e-broker.db"; fi
cd "$ROOT/apps/api"
SMTP_HOST=127.0.0.1 SMTP_PORT=2525 SMTP_SECURITY=none SMTP_FROM="InteriorIQ Studio <studio@interioriq.test>" DATABASE_URL=sqlite:///./e2e.db python3 -m uvicorn app.main:app --port $API_PORT >/tmp/iq_api.log 2>&1 &  API=$!
WK=""
if [ "$CELERY" = "1" ]; then
  for i in $(seq 1 60); do curl -s localhost:$API_PORT/api/health >/dev/null && break; sleep 1; done   # the API migrates the database first
  POOL=""; case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) POOL="--pool=solo";; esac
  (cd "$ROOT/apps/api" && SMTP_HOST=127.0.0.1 SMTP_PORT=2525 SMTP_SECURITY=none SMTP_FROM="InteriorIQ Studio <studio@interioriq.test>" DATABASE_URL=sqlite:///./e2e.db exec python3 -m celery -A app.worker worker $POOL --loglevel=info >/tmp/iq_worker.log 2>&1) &  WK=$!
fi
cd "$ROOT/apps/web"
node node_modules/next/dist/bin/next start -p $WEB_PORT >/tmp/iq_web.log 2>&1 &  WEB=$!      # the real server process, not an npx wrapper, so cleanup really stops it
restore() { kill $API $WEB $WK 2>/dev/null; rm -f "$ROOT/apps/api/e2e.db" "$ROOT/apps/api/e2e-broker.db"; rm -rf "$TMPD"
  if [ -n "$NEXT_PUBLIC_API_URL" ]; then echo "Rebuilding the web app for the normal API address..."; (cd "$ROOT/apps/web" && unset NEXT_PUBLIC_API_URL && npm run build >/tmp/iq_build.log 2>&1); fi; }
trap restore EXIT

for i in $(seq 1 60); do curl -s localhost:$API_PORT/api/health >/dev/null && curl -s -o /dev/null localhost:$WEB_PORT/login && break; sleep 1; done
export IQ_API="http://localhost:$API_PORT/api" IQ_WEB="http://localhost:$WEB_PORT"
if [ "$CELERY" = "1" ]; then   # Celery mode: the suites whose work runs in the background
  python3 "$ROOT/e2e/jobs_smoke.py" && python3 "$ROOT/e2e/documents_smoke.py" && python3 "$ROOT/e2e/notifications_smoke.py"; exit $?
fi
python3 "$ROOT/e2e/login_smoke.py" && python3 "$ROOT/e2e/jobs_smoke.py" && python3 "$ROOT/e2e/editor_smoke.py" && python3 "$ROOT/e2e/editor_rotation_smoke.py" && python3 "$ROOT/e2e/documents_smoke.py" && python3 "$ROOT/e2e/estimation_smoke.py" && python3 "$ROOT/e2e/terms_smoke.py" && python3 "$ROOT/e2e/crm_smoke.py" && python3 "$ROOT/e2e/catalogue_smoke.py" && python3 "$ROOT/e2e/photos_smoke.py" && python3 "$ROOT/e2e/operations_smoke.py" && python3 "$ROOT/e2e/invoices_smoke.py" && python3 "$ROOT/e2e/credit_smoke.py" && python3 "$ROOT/e2e/notifications_smoke.py" && python3 "$ROOT/e2e/profit_smoke.py" && python3 "$ROOT/e2e/payables_smoke.py" && python3 "$ROOT/e2e/finance_smoke.py" && python3 "$ROOT/e2e/takeoff_smoke.py" && python3 "$ROOT/e2e/openings_smoke.py" && python3 "$ROOT/e2e/shape_smoke.py" && python3 "$ROOT/e2e/followups_smoke.py" && python3 "$ROOT/e2e/reminders_smoke.py" && python3 "$ROOT/e2e/layouts_smoke.py" && python3 "$ROOT/e2e/home_smoke.py" && python3 "$ROOT/e2e/team_smoke.py" && python3 "$ROOT/e2e/backups_smoke.py"
