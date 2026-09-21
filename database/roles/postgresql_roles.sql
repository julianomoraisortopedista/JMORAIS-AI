-- ST-22 least-privilege role provisioning. Run as the database owner after migrations.
-- Login membership and passwords are deployment responsibilities; never store them here.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='jmorais_migration_admin') THEN
    CREATE ROLE jmorais_migration_admin NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='jmorais_application_writer') THEN
    CREATE ROLE jmorais_application_writer NOLOGIN NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='jmorais_application_reader') THEN
    CREATE ROLE jmorais_application_reader NOLOGIN NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='jmorais_audit_verifier') THEN
    CREATE ROLE jmorais_audit_verifier NOLOGIN;
  END IF;
END $$;

ALTER ROLE jmorais_application_writer NOBYPASSRLS;
ALTER ROLE jmorais_application_reader NOBYPASSRLS;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC;

GRANT USAGE ON SCHEMA public TO jmorais_application_writer, jmorais_application_reader, jmorais_audit_verifier;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA public TO jmorais_application_writer;
REVOKE INSERT ON cryptographic_stream_checkpoints FROM jmorais_application_writer;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO jmorais_application_writer;
GRANT UPDATE (role, status, active, organization_id, tenant_id, updated_at,
              authorization_policy_version)
  ON reviewer_identities TO jmorais_application_writer;
GRANT UPDATE (status, last_seen_at)
  ON external_identity_links TO jmorais_application_writer;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO jmorais_application_reader, jmorais_audit_verifier;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT ON TABLES TO jmorais_application_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO jmorais_application_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT ON TABLES TO jmorais_application_reader, jmorais_audit_verifier;

-- Test/bootstrap owner may SET ROLE. Production login membership must be granted separately.
DO $$ BEGIN
  EXECUTE format('GRANT jmorais_application_writer, jmorais_application_reader, '
                 'jmorais_audit_verifier TO %I', current_user);
END $$;
