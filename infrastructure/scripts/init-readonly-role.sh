#!/bin/bash
# ============================================================================
# Postgres init script — provision the finguard_readonly role on a FRESH volume.
#
# Mounted into /docker-entrypoint-initdb.d/ by docker-compose.dev.yml so local
# `compose up` exercises the same read-only Text-to-SQL boundary that production
# enforces (gap #2b dev parity). Runs ONCE, on first DB init, connected as
# $POSTGRES_USER (the table-creating role) BEFORE migrations run — so the
# ALTER DEFAULT PRIVILEGES below automatically grants SELECT on every table the
# migrate service creates afterwards.
#
# Canonical/manual + production provisioning lives in infrastructure/db_security.sql.
# Password comes from POSTGRES_READONLY_PASSWORD (defaults to a dev value).
# ============================================================================
set -euo pipefail

RO_PW="${POSTGRES_READONLY_PASSWORD:-finguard_readonly}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'finguard_readonly') THEN
            CREATE ROLE finguard_readonly
                WITH LOGIN PASSWORD '${RO_PW}'
                     NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
                     CONNECTION LIMIT 10;
        END IF;
    END
    \$\$;

    GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO finguard_readonly;
    GRANT USAGE ON SCHEMA public TO finguard_readonly;
    GRANT USAGE ON SCHEMA "$POSTGRES_USER" TO finguard_readonly;

    -- Future tables (created later by the migrate service, which connects as
    -- this same role) are automatically SELECT-only for finguard_readonly. Both
    -- schemas are covered: Postgres's default search_path ("\$user", public)
    -- resolves unqualified DDL from the migrate/backend connection (which
    -- authenticates as \$POSTGRES_USER) to a same-named schema when one exists,
    -- which is where this app's tables actually land — "public" stays covered
    -- too for a deployment where that resolution doesn't apply.
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT SELECT ON TABLES TO finguard_readonly;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLES FROM finguard_readonly;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
        REVOKE USAGE, SELECT, UPDATE ON SEQUENCES FROM finguard_readonly;
    ALTER DEFAULT PRIVILEGES IN SCHEMA "$POSTGRES_USER"
        GRANT SELECT ON TABLES TO finguard_readonly;
    ALTER DEFAULT PRIVILEGES IN SCHEMA "$POSTGRES_USER"
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLES FROM finguard_readonly;
    ALTER DEFAULT PRIVILEGES IN SCHEMA "$POSTGRES_USER"
        REVOKE USAGE, SELECT, UPDATE ON SEQUENCES FROM finguard_readonly;

    -- The readonly role's own search_path ("\$user" → "finguard_readonly",
    -- then public) never resolves to "\$POSTGRES_USER"'s schema on its own, so
    -- point it there directly — otherwise every unqualified query 404s even
    -- with the grants above in place.
    ALTER ROLE finguard_readonly SET search_path = "$POSTGRES_USER", public;
EOSQL

echo "init-readonly-role: finguard_readonly provisioned (SELECT-only on public)."
