-- Local PostgreSQL setup for the School Management System.
--
-- Creates two least-privilege users and two databases. Run once, as the
-- postgres superuser, from the backend/ folder:
--
--   sudo -u postgres psql -v ON_ERROR_STOP=1 < scripts/create_local_database.sql
--
-- Users:
--   sms_migrator  owns the schema; used only to run migrations.
--   sms_app       reads and writes rows; used by the running API.
--
-- No passwords are set here. Set them with scripts/set_local_db_passwords.py.

\set ON_ERROR_STOP on

CREATE ROLE sms_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE sms_app      LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

CREATE DATABASE sms_dev  OWNER sms_migrator ENCODING 'UTF8' TEMPLATE template0;
CREATE DATABASE sms_test OWNER sms_migrator ENCODING 'UTF8' TEMPLATE template0;

-- Only our two users may connect. By default every user on the server could.
REVOKE ALL ON DATABASE sms_dev  FROM PUBLIC;
REVOKE ALL ON DATABASE sms_test FROM PUBLIC;
GRANT CONNECT ON DATABASE sms_dev  TO sms_app;
GRANT CONNECT ON DATABASE sms_test TO sms_app;

-- Schema permissions are per database, so apply them in each one.
\connect sms_dev
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO sms_app;
ALTER DEFAULT PRIVILEGES FOR ROLE sms_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sms_app;
ALTER DEFAULT PRIVILEGES FOR ROLE sms_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO sms_app;

\connect sms_test
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO sms_app;
ALTER DEFAULT PRIVILEGES FOR ROLE sms_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sms_app;
ALTER DEFAULT PRIVILEGES FOR ROLE sms_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO sms_app;
