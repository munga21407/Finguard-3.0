-- ============================================================================
-- Finguard 3.0 — Read-Only Database Role (Task 5)
--
-- Apply as a superuser (e.g. postgres) against the finguard database.
-- This role is used exclusively by the Text-to-SQL engine (Agent D CoVe)
-- to prevent LLM-generated queries from ever mutating data.
--
-- Usage (manual / production):
--   psql -U postgres -d finguard -f infrastructure/db_security.sql
--   (run AFTER `alembic upgrade head` so GRANT SELECT ON ALL TABLES sees them)
--
-- Local dev provisions this role automatically on first DB init via
-- infrastructure/scripts/init-readonly-role.sh (wired in docker-compose.dev.yml).
-- Keep the two in sync when editing grants.
-- ============================================================================

-- 1. Create the role (LOGIN so a connection string can use it directly).
--    Replace 'your_strong_password_here' with a value from your secrets manager.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'finguard_readonly') THEN
        CREATE ROLE finguard_readonly
            WITH LOGIN
                 PASSWORD 'your_strong_password_here'
                 NOSUPERUSER
                 NOCREATEDB
                 NOCREATEROLE
                 NOINHERIT
                 CONNECTION LIMIT 10;
    END IF;
END
$$;

-- 2. Allow the role to connect to the finguard database.
GRANT CONNECT ON DATABASE finguard TO finguard_readonly;

-- 3. Allow schema traversal (required to resolve table names).
GRANT USAGE ON SCHEMA public TO finguard_readonly;

-- 4. Grant SELECT on all existing tables.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO finguard_readonly;

-- 5. Ensure future tables are automatically readable by this role.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO finguard_readonly;

-- 6. Explicitly deny write operations (defence in depth against privilege escalation).
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON ALL TABLES IN SCHEMA public
    FROM finguard_readonly;

-- 7. Deny sequence access (prevents nextval() side-effects).
REVOKE USAGE, SELECT, UPDATE
    ON ALL SEQUENCES IN SCHEMA public
    FROM finguard_readonly;

-- 8. Deny function execution for any potentially mutating functions.
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM finguard_readonly;

-- ============================================================================
-- After running this script, set the following environment variable so that
-- Agent D's sql_executor uses this role for Text-to-SQL queries:
--
--   DATABASE_READONLY_URL=postgresql+asyncpg://finguard_readonly:<password>@<host>/<db>
--
-- If DATABASE_READONLY_URL is not set, sql_executor falls back to the main
-- database URL (safe because the string-level SELECT validator still rejects
-- any DML/DDL — the role boundary is an additional defence layer).
-- ============================================================================
