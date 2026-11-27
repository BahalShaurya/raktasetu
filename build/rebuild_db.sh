#!/bin/bash
# Rebuilds the raktasetu database from the numbered scripts. Usage: build/rebuild_db.sh [host] [user]
H=${1:-127.0.0.1}; U=${2:-postgres}; ROOT="$(cd "$(dirname "$0")/.." && pwd)"
psql -h $H -U $U -qc "DROP DATABASE IF EXISTS raktasetu" -c "CREATE DATABASE raktasetu" || exit 1
for f in 01_create_tables 02_insert_data 03_views 04_triggers 05_functions 06_admin 07_security; do
  psql -h $H -U $U -d raktasetu -v ON_ERROR_STOP=1 -q -f "$ROOT/sql/$f.sql" 2>&1 | grep -v "does not exist, skipping" || true
done
python3 "$ROOT/app/setup_passwords.py" $H $U
echo "raktasetu rebuilt"
