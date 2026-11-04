#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

usage() {
  printf '%s\n' 'Usage: [ENV_FILE=...] [BACKUP_DIR=...] [COMPOSE_PROJECT_NAME=...] bash deploy/restore.sh /absolute/backup-directory --confirm-restore'
}
if [[ "${1:-}" == "--help" ]]; then usage; exit 0; fi
if [[ $# -ne 2 || "$2" != '--confirm-restore' ]]; then usage >&2; exit 2; fi
PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env.production}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups}"
[[ "$ENV_FILE" = /* ]] || ENV_FILE="$PROJECT_DIR/$ENV_FILE"
[[ "$BACKUP_DIR" = /* ]] || BACKUP_DIR="$PROJECT_DIR/$BACKUP_DIR"
compose=(docker compose --project-directory "$PROJECT_DIR" --env-file "$ENV_FILE" -f "$PROJECT_DIR/compose.production.yaml")
fail() { printf '%s\n' "$1" >&2; exit 1; }
[[ -r "$ENV_FILE" && -f "$PROJECT_DIR/compose.production.yaml" ]] || fail 'Production configuration is missing.'
for command in docker sha256sum flock; do command -v "$command" >/dev/null || fail "Required command missing: $command"; done
[[ -d "$1" && ! -L "$1" ]] || fail 'The backup argument must be a real directory.'
snapshot="$(CDPATH= cd -- "$1" && pwd)"
expected=(database.dump avatars.tar.gz schema-version.txt backup-info.txt)
for name in "${expected[@]}" SHA256SUMS; do
  [[ -f "$snapshot/$name" && ! -L "$snapshot/$name" && -s "$snapshot/$name" ]] || fail "Missing or unsafe snapshot file: $name"
done
# Only these four exact names can enter checksum verification; never accept
# arbitrary paths/filenames or directives from an untrusted checksum manifest.
mapfile -t sums <"$snapshot/SHA256SUMS"
[[ ${#sums[@]} -eq ${#expected[@]} ]] || fail 'The checksum manifest has an unexpected format.'
for index in "${!expected[@]}"; do
  digest="${sums[index]%% *}"
  [[ "$digest" =~ ^[a-f0-9]{64}$ && "${sums[index]}" == "$digest  ${expected[index]}" ]] || fail 'The checksum manifest has an unexpected filename or digest.'
done
(
  cd -- "$snapshot"
  sha256sum --status --check --strict SHA256SUMS
) || fail 'Snapshot checksum verification failed. Nothing has been stopped or restored.'
grep -qx 'format=amergination-backup-v1' "$snapshot/backup-info.txt" || fail 'Unsupported snapshot format.'
grep -qx 'postgres_major=17' "$snapshot/backup-info.txt" || fail 'This restore script expects a PostgreSQL 17 snapshot.'
mkdir -p -- "$BACKUP_DIR"
exec 9>"$BACKUP_DIR/.operation.lock"
flock -n 9 || fail 'Another backup/restore operation holds this backup directory lock.'
running() { [[ -n "$("${compose[@]}" ps --status running -q "$1")" ]]; }
running postgres || fail 'Start only the production postgres/redis services before restoring.'
if running migrate; then fail 'Wait until the migration service finishes before restoring.'; fi
# Read-only checks precede any pause or database change.
"${compose[@]}" exec -T postgres pg_restore --list <"$snapshot/database.dump" >/dev/null
"${compose[@]}" run --rm -T --no-deps --entrypoint python maintenance /app/deploy/avatar_archive.py validate <"$snapshot/avatars.tar.gz"
"${compose[@]}" run --rm -T --no-deps --entrypoint python maintenance -c '
import re, sys
from alembic.config import Config
from alembic.script import ScriptDirectory
value = sys.stdin.read(4097)
versions = value.splitlines()
if not versions or len(value) > 4096 or any(not re.fullmatch(r"[A-Za-z0-9_]{1,100}", item) for item in versions):
    raise SystemExit("Invalid schema-version metadata.")
script = ScriptDirectory.from_config(Config("/app/alembic.ini"))
try:
    if any(script.get_revision(item) is None for item in versions):
        raise ValueError()
except Exception:
    raise SystemExit("The app image does not support this snapshot schema revision.")
' <"$snapshot/schema-version.txt"

started=0
staging_database=''
previous_database=''
finish() {
  local status=$?
  trap - EXIT
  if [[ $status -ne 0 && $started -eq 1 ]]; then
    "${compose[@]}" stop --timeout 30 proxy app >/dev/null 2>&1 || true
    printf '%s\n' 'Restore did not finish. app/proxy remain stopped; inspect the failure and repeat a verified restore before starting them.' >&2
    if [[ -n "$staging_database" ]]; then
      printf 'Staging/previous database names for inspection: %s / %s\n' "$staging_database" "$previous_database" >&2
      printf '%s\n' 'No database was automatically dropped. Check which database holds the configured application name before any manual rollback.' >&2
    fi
  fi
  exit "$status"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
printf '%s\n' 'Restoring this production Compose project into a fresh staging database. app/proxy will stop; the previous database will be retained.'
started=1
"${compose[@]}" stop --timeout 30 proxy app
prepared="$("${compose[@]}" run --rm -T --no-deps --entrypoint python maintenance /app/deploy/restore_database.py prepare)"
read -r staging_database previous_database <<<"$prepared"
[[ "$staging_database" =~ ^amergination_restore_[a-f0-9]{32}$ && "$previous_database" =~ ^amergination_previous_[a-f0-9]{32}$ \
   && "$prepared" == "$staging_database $previous_database" ]] || fail 'Invalid staging database metadata.'
"${compose[@]}" exec -T postgres sh -eu -c 'exec pg_restore --single-transaction --exit-on-error --clean --if-exists --no-owner --no-acl --username="$POSTGRES_USER" --dbname="$1"' sh "$staging_database" <"$snapshot/database.dump"
# Upgrade the isolated restored schema before changing the application DB name.
# Tables created after the snapshot cannot interfere with this pristine target.
"${compose[@]}" run --rm -T --no-deps -e "POSTGRES_DB=$staging_database" migrate
"${compose[@]}" run --rm -T --no-deps --entrypoint python maintenance /app/deploy/avatar_archive.py restore <"$snapshot/avatars.tar.gz"
"${compose[@]}" run --rm -T --no-deps --entrypoint python maintenance /app/deploy/restore_database.py switch "$staging_database" "$previous_database"
printf 'Previous database retained with connections disabled: %s\n' "$previous_database"
# Recreate with current configuration (including a rotated SECRET_KEY), rather
# than starting a container that still contains its previous environment.
"${compose[@]}" up -d --wait --wait-timeout 120 app proxy
printf '%s\n' 'Restore completed. Check /health/ready, sign-in and a restored avatar before reopening access.'
