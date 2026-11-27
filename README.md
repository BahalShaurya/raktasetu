# RaktaSetu – Rotaract Blood Donation Data Management System
DBMS project. PostgreSQL 16 + Flask.

## Run it
1. Install PostgreSQL 16, Python 3.11+, then `pip install flask psycopg2-binary`.
2. Create the database and load everything (edit PG settings at the top of the script if needed):
   `bash build/rebuild_db.sh`   (runs sql/01 … 07, then sets the demo passwords)
   Or manually in psql/pgAdmin: create database `raktasetu`, run the files in `sql/` in order 01 → 07, then `python app/setup_passwords.py`.
3. Start the website: `cd app && python app.py` → http://127.0.0.1:5000

## Demo logins
| Role | USN / ID | Password |
|---|---|---|
| Admin | ROTADMIN01 | admin123 |
| Coordinator | 1RV23IS011 (also 1RV23CS027, 1RV23EC040) | rotaract@123 |
| Volunteer | 1RV24IS052 (and others) | rotaract@123 |
Public donor sign-up (no login): http://127.0.0.1:5000/donate

## Folders
- `sql/` – 01 tables, 02 sample data, 03 views, 04 triggers, 05 functions, 06 admin, 07 security, 08 data checks
- `app/` – Flask app (`app.py`, `reports.py`, templates, CSS)
- `tests/` – `db_tests.py` (29 database tests), `fe_tests.py` (39 front-end + system tests; run with the server running)
- `docs/` – ER diagram and relational schema
- `build/` – database rebuild script, seed generator and diagram scripts
