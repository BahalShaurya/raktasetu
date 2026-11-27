-- =====================================================================
-- 07_security.sql : least-privilege role for the website.
-- The web application connects as rotaract_app. That role
--   * can SELECT from tables and views (but not member.password_hash),
--   * can NOT INSERT / UPDATE / DELETE any table directly,
--   * changes data only by calling the stored functions, which run as
--     their owner (SECURITY DEFINER) and check who is calling.
-- =====================================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rotaract_app') THEN
        CREATE ROLE rotaract_app LOGIN PASSWORD 'rotaract_app';
    END IF;
END $$;

-- business functions run with the owner's rights and a fixed search_path
DO $$
DECLARE f RECORD;
BEGIN
    FOR f IN SELECT p.oid::regprocedure AS sig, p.proname
             FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE n.nspname = 'public' AND p.proname LIKE 'fn\_%'
               AND p.prorettype <> 'trigger'::regtype
               AND p.proname NOT IN ('fn_gap_days', 'fn_age')
    LOOP
        EXECUTE format('ALTER FUNCTION %s SECURITY DEFINER SET search_path = public, pg_temp', f.sig);
    END LOOP;
END $$;

REVOKE ALL ON ALL TABLES    IN SCHEMA public FROM rotaract_app;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM rotaract_app;

GRANT USAGE ON SCHEMA public TO rotaract_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO rotaract_app;
REVOKE SELECT ON member FROM rotaract_app;
GRANT SELECT (member_id, usn, fname, lname, email, phone, role, dept_id, joined_on, is_active) ON member TO rotaract_app;

-- the app may call every business function (not the trigger functions)
DO $$
DECLARE f RECORD;
BEGIN
    FOR f IN SELECT p.oid::regprocedure AS sig
             FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE n.nspname = 'public' AND p.proname LIKE 'fn\_%' AND p.prorettype <> 'trigger'::regtype
    LOOP
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO rotaract_app', f.sig);
    END LOOP;
END $$;
