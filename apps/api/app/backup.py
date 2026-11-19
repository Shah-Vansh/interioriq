"""Backup command line (uses DATABASE_URL / STORAGE_PATH / BACKUP_DIR from apps/api/.env, like the API).

    cd apps/api
    python -m app.backup create [--no-files] [--out DIR]     # a backup zip (prints its path)
    python -m app.backup list                                # backups in BACKUP_DIR
    python -m app.backup verify FILE                         # re-check every checksum
    python -m app.backup restore FILE --yes [--no-files]     # REPLACES the database (+ uploads); takes a safety backup first

Moving from SQLite to Postgres:
    python -m app.backup create --out ..\\..\\move                                   (with the old SQLite DATABASE_URL)
    set DATABASE_URL=postgresql+psycopg://user:pass@host/db  (PowerShell: $env:DATABASE_URL="…")
    python -m app.backup restore ..\\..\\move\\manual-….zip --yes                     (into the new, empty Postgres database)
Schedule `create` with cron / Windows Task Scheduler if you turn the built-in daily backup off (BACKUP_DAILY=false)."""
import argparse, json, sys
from pathlib import Path

from app.services import backup as bk


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.backup", description="InteriorIQ backups")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create"); c.add_argument("--no-files", action="store_true"); c.add_argument("--out")
    sub.add_parser("list")
    v = sub.add_parser("verify"); v.add_argument("file")
    r = sub.add_parser("restore"); r.add_argument("file"); r.add_argument("--yes", action="store_true"); r.add_argument("--no-files", action="store_true")
    r.add_argument("--no-safety-backup", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "create":
            out = Path(a.out).resolve() if a.out else None
            if out: out.mkdir(parents=True, exist_ok=True)
            made = bk.create(kind="manual", include_files=not a.no_files, by="command line", out_dir=out)
            print(json.dumps(made, indent=1)); print((out or bk.backup_dir()) / made["name"])
        elif a.cmd == "list":
            for b in bk.list_backups(): print(f"{b['name']:40} {b.get('size_bytes', 0):>12} bytes  rows={b.get('rows')} files={b.get('files')} rev={b.get('schema_revision')}")
        elif a.cmd == "verify":
            res = bk.verify(Path(a.file)); print(json.dumps(res, indent=1)); return 0 if res["ok"] else 2
        elif a.cmd == "restore":
            if not a.yes:
                print("Restoring REPLACES the current database (and the uploads folder unless --no-files). Re-run with --yes to confirm."); return 1
            res = bk.restore(Path(a.file), safety_backup=not a.no_safety_backup, restore_files=not a.no_files, by="command line")
            print(json.dumps(res, indent=1))
    except bk.BackupError as e:
        print(f"Error: {e.message}", file=sys.stderr); return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
