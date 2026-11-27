-- =====================================================================
-- 06_admin.sql : admin-only functions, login lookup and the overview view
-- =====================================================================
CREATE OR REPLACE FUNCTION fn_assert_admin(p_admin INT) RETURNS VOID AS $$
BEGIN
    PERFORM fn_assert_role(p_admin, 'ADMIN');
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_create_member(
    p_admin INT, p_usn VARCHAR, p_fname VARCHAR, p_lname VARCHAR, p_email VARCHAR, p_phone VARCHAR,
    p_role VARCHAR, p_dept INT, p_password_hash TEXT
) RETURNS INT AS $$
DECLARE v_id INT;
BEGIN
    PERFORM fn_assert_admin(p_admin);
    INSERT INTO member (usn, fname, lname, email, phone, role, dept_id, password_hash)
    VALUES (upper(p_usn), p_fname, NULLIF(p_lname, ''), lower(p_email), NULLIF(p_phone, ''), p_role, p_dept, p_password_hash)
    RETURNING member_id INTO v_id;
    PERFORM fn_log(p_admin, 'MEMBER_CREATED', 'member', v_id, upper(p_usn) || ' as ' || p_role);
    RETURN v_id;
EXCEPTION
    WHEN unique_violation THEN RAISE EXCEPTION 'A member with this USN or e-mail already exists';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_set_member_active(p_admin INT, p_member INT, p_active BOOLEAN) RETURNS VOID AS $$
BEGIN
    PERFORM fn_assert_admin(p_admin);
    IF p_member = p_admin AND NOT p_active THEN RAISE EXCEPTION 'You cannot block your own account'; END IF;
    UPDATE member SET is_active = p_active WHERE member_id = p_member;
    IF NOT FOUND THEN RAISE EXCEPTION 'Member % does not exist', p_member; END IF;
    PERFORM fn_log(p_admin, CASE WHEN p_active THEN 'MEMBER_UNBLOCKED' ELSE 'MEMBER_BLOCKED' END, 'member', p_member, NULL);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_set_member_role(p_admin INT, p_member INT, p_role VARCHAR) RETURNS VOID AS $$
BEGIN
    PERFORM fn_assert_admin(p_admin);
    IF p_member = p_admin AND p_role <> 'ADMIN' THEN RAISE EXCEPTION 'You cannot remove your own admin role'; END IF;
    UPDATE member SET role = p_role WHERE member_id = p_member;
    IF NOT FOUND THEN RAISE EXCEPTION 'Member % does not exist', p_member; END IF;
    PERFORM fn_log(p_admin, 'MEMBER_ROLE', 'member', p_member, p_role);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_set_password(p_admin INT, p_member INT, p_hash TEXT) RETURNS VOID AS $$
BEGIN
    PERFORM fn_assert_admin(p_admin);
    UPDATE member SET password_hash = p_hash WHERE member_id = p_member;
    IF NOT FOUND THEN RAISE EXCEPTION 'Member % does not exist', p_member; END IF;
    PERFORM fn_log(p_admin, 'PASSWORD_RESET', 'member', p_member, NULL);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_set_donor_active(p_admin INT, p_donor INT, p_active BOOLEAN) RETURNS VOID AS $$
BEGIN
    PERFORM fn_assert_admin(p_admin);
    UPDATE donor SET is_active = p_active WHERE donor_id = p_donor;
    IF NOT FOUND THEN RAISE EXCEPTION 'Donor % does not exist', p_donor; END IF;
    PERFORM fn_log(p_admin, CASE WHEN p_active THEN 'DONOR_RESTORED' ELSE 'DONOR_HIDDEN' END, 'donor', p_donor, NULL);
END;
$$ LANGUAGE plpgsql;

-- the only way the website reads a password hash (the table column is not readable by the app role)
CREATE OR REPLACE FUNCTION fn_login_info(p_usn VARCHAR)
RETURNS TABLE (member_id INT, fname VARCHAR, lname VARCHAR, role VARCHAR, password_hash TEXT, is_active BOOLEAN) AS $$
    SELECT m.member_id, m.fname, m.lname, m.role, m.password_hash, m.is_active
    FROM member m WHERE lower(m.usn) = lower(p_usn) OR (m.role = 'ADMIN' AND lower(p_usn) = 'admin');
$$ LANGUAGE sql STABLE;

-- the activity log, readable only by the admin
CREATE OR REPLACE FUNCTION fn_get_activity(p_admin INT, p_limit INT DEFAULT 100)
RETURNS TABLE (log_id INT, logged_at TIMESTAMP, member TEXT, action VARCHAR, entity VARCHAR, entity_id INT, details TEXT) AS $$
BEGIN
    PERFORM fn_assert_admin(p_admin);
    RETURN QUERY
    SELECT a.log_id, a.logged_at, COALESCE(m.fname || ' ' || COALESCE(m.lname, ''), 'system'), a.action, a.entity, a.entity_id, a.details
    FROM activity_log a LEFT JOIN member m ON m.member_id = a.member_id
    ORDER BY a.log_id DESC LIMIT p_limit;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE VIEW v_admin_overview AS
SELECT (SELECT COUNT(*) FROM member WHERE is_active)                                         AS members,
       (SELECT COUNT(*) FROM donor WHERE is_active)                                          AS donors,
       (SELECT COUNT(*) FROM v_donor_status WHERE eligible_now)                              AS donors_eligible_now,
       (SELECT COUNT(*) FROM event WHERE status = 'PLANNED' AND starts_at >= CURRENT_TIMESTAMP) AS upcoming_events,
       (SELECT COUNT(*) FROM donation WHERE status <> 'DISCARDED')                           AS units_collected,
       (SELECT COALESCE(SUM(volume_ml), 0) FROM donation WHERE status <> 'DISCARDED')        AS litres_ml,
       (SELECT COUNT(*) FROM blood_request WHERE status = 'OPEN')                            AS open_requests,
       (SELECT COUNT(*) FROM donor_reminder WHERE sent_at IS NULL)                           AS reminders_waiting;
