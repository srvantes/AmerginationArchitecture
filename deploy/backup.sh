#!/usr/bin/env bash
# Run on the Linux deployment host, never against the development compose file.
set -Eeuo pipefail
umask 077

if [[ "${1:-}" == "--help" ]]; then
  printf '%s\n' 'Usage: [ENV_FILE=...] [BACKUP_DIR=...] [COMPOSE_PROJECT_NAME=...] bash deploy/backup.sh'
  exit 0
fi
[[ $# -eq 0 ]] || { printf '%s\n' 'Unexpected argument. Use --help.' >&2; exit 2; }
PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env.production}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups}"
[[ "$ENV_FILE" = /* ]] || ENV_FILE="$PROJECT_DIR/$ENV_FILE"
[[ "$BACKUP_DIR" = /* ]] || BACKUP_DIR="$PROJECT_DIR/$BACKUP_DIR"
compose=(docker compose --project-directory "$PROJECT_DIR" --env-file "$ENV_FILE" -f "$PROJECT_DIR/compose.production.yaml")
fail() { printf '%s\n' "$1" >&2; exit 1; }
[[ -r "$ENV_FILE" && -f "$PROJECT_DIR/compose.production.yaml" ]] || fail 'Production configuration is missing.'
for command in docker date mktemp sha256sum flock; do command -v "$command" >/dev/null || fail "Required command missing: $command"; done
mkdir -p -- "$BACKUP_DIR"
BACKUP_DIR="$(CDPATH= cd -- "$BACKUP_DIR" && pwd)"
exec 9>"$BACKUP_DIR/.operation.lock"
flock -n 9 || fail 'Another backup/restore operation holds this backup directory lock.'
running() { [[ -n "$("${compose[@]}" ps --status running -q "$1")" ]]; }
running postgres || fail 'The production PostgreSQL service must already be running.'
if running migrate; then fail 'Wait until the migration service finishes before backing up.'; fi

resume=()
running app && resume+=(app)
running proxy && resume+=(proxy)
staging=''
finish() {
  local status=$?
  trap - EXIT
  if [[ ${#resume[@]} -gt 0 ]]; then
    if ! "${compose[@]}" start "${resume[@]}"; then
      printf '%s\n' 'Could not restart a previously running service; inspect app/proxy before continuing.' >&2
      status=1
    fi
  fi
  if [[ $status -ne 0 && -n "$staging" ]]; then
    printf 'Backup failed. The private incomplete directory remains at: %s\n' "$staging" >&2
  fi
  exit "$status"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
staging="$(mktemp -d "$BACKUP_DIR/.partial-$stamp-XXXXXXXX")"
final="$BACKUP_DIR/${staging##*/.partial-}"
printf '%s\n' 'Pausing app/proxy briefly to capture matching database and avatar snapshots.'
# A graceful app stop waits for in-flight uploads/transactions to finish.
if [[ ${#resume[@]} -gt 0 ]]; then "${compose[@]}" stop --timeout 30 proxy app; fi
"${compose[@]}" exec -T postgres sh -eu -c 'exec pg_dump -Fc --no-owner --no-acl --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' >"$staging/database.dump"
"${compose[@]}" run --rm -T --no-deps --entrypoint python maintenance /app/deploy/avatar_archive.py backup >"$staging/avatars.tar.gz"
"${compose[@]}" exec -T postgres sh -eu -c 'exec psql --no-psqlrc --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" -At -c "SELECT version_num FROM alembic_version ORDER BY version_num"' >"$staging/schema-version.txt"
[[ -s "$staging/database.dump" && -s "$staging/avatars.tar.gz" && -s "$staging/schema-version.txt" ]] || fail 'A required snapshot file is empty.'
printf 'format=amergination-backup-v1\ncreated_utc=%s\npostgres_major=17\n' "$stamp" >"$staging/backup-info.txt"
(
  cd -- "$staging"
  sha256sum database.dump avatars.tar.gz schema-version.txt backup-info.txt >SHA256SUMS
)
[[ ! -e "$final" ]] || fail 'The final backup directory already exists.'
mv -T -- "$staging" "$final"
staging=''
printf 'Backup completed: %s\n' "$final"
