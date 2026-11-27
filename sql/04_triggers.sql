-- =====================================================================
-- 04_triggers.sql : helper functions and the 11 triggers that enforce the
-- donor-selection rules and keep notifications / logs up to date.
-- =====================================================================

-- ---------- small helpers used by triggers and stored functions ----------
CREATE OR REPLACE FUNCTION fn_log(p_member INT, p_action VARCHAR, p_entity VARCHAR, p_entity_id INT, p_details TEXT)
RETURNS VOID AS $$
    INSERT INTO activity_log (member_id, action, entity, entity_id, details)
    VALUES (p_member, p_action, p_entity, p_entity_id, p_details);
$$ LANGUAGE sql;

CREATE OR REPLACE FUNCTION fn_notify(p_member INT, p_kind VARCHAR, p_message VARCHAR, p_link VARCHAR, p_ref INT)
RETURNS VOID AS $$
    INSERT INTO notification (member_id, kind, message, link, ref_id)
    VALUES (p_member, p_kind, p_message, p_link, p_ref);
$$ LANGUAGE sql;

-- notify every active member who has one of the given roles
CREATE OR REPLACE FUNCTION fn_notify_roles(p_kind VARCHAR, p_message VARCHAR, p_link VARCHAR, p_ref INT, VARIADIC p_roles TEXT[])
RETURNS INT AS $$
    WITH n AS (
        INSERT INTO notification (member_id, kind, message, link, ref_id)
        SELECT member_id, p_kind, p_message, p_link, p_ref FROM member
        WHERE is_active AND role = ANY (p_roles)
        RETURNING 1)
    SELECT COUNT(*)::INT FROM n;
$$ LANGUAGE sql;

-- raises an error unless the member is active and has one of the roles
CREATE OR REPLACE FUNCTION fn_assert_role(p_member INT, VARIADIC p_roles TEXT[]) RETURNS VOID AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM member WHERE member_id = p_member AND is_active AND role = ANY (p_roles)) THEN
        RAISE EXCEPTION 'Only % can do this', array_to_string(p_roles, ' or ');
    END IF;
END;
$$ LANGUAGE plpgsql;

-- NULL when the donor may donate on p_on, otherwise the reason in words
CREATE OR REPLACE FUNCTION fn_eligibility_check(p_donor INT, p_on DATE) RETURNS TEXT AS $$
DECLARE v v_donor_status%ROWTYPE;
BEGIN
    SELECT * INTO v FROM v_donor_status WHERE donor_id = p_donor;
    IF NOT FOUND THEN RETURN 'Donor ' || p_donor || ' does not exist'; END IF;
    IF NOT v.is_active THEN RETURN v.donor_name || ' is marked inactive'; END IF;
    IF fn_age(v.dob, p_on) NOT BETWEEN 18 AND 65 THEN
        RETURN v.donor_name || ' must be between 18 and 65 years old on ' || to_char(p_on, 'DD Mon YYYY');
    END IF;
    IF v.permanently_deferred THEN RETURN v.donor_name || ' is permanently deferred'; END IF;
    IF v.next_eligible_on IS NOT NULL AND v.next_eligible_on > p_on THEN
        RETURN v.donor_name || ' can donate again only from ' || to_char(v.next_eligible_on, 'DD Mon YYYY');
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

-- ---------- T1: only an event of type BLOOD_DRIVE can be a blood drive ----------
CREATE OR REPLACE FUNCTION fn_drive_check() RETURNS TRIGGER AS $$
DECLARE v_type VARCHAR(12);
BEGIN
    SELECT event_type INTO v_type FROM event WHERE event_id = NEW.event_id;
    IF v_type IS DISTINCT FROM 'BLOOD_DRIVE' THEN
        RAISE EXCEPTION 'Event % is of type %, so it cannot be a blood drive', NEW.event_id, v_type;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_drive_check ON blood_drive;
CREATE TRIGGER trg_drive_check BEFORE INSERT OR UPDATE ON blood_drive
FOR EACH ROW EXECUTE FUNCTION fn_drive_check();

-- ---------- T2: check a registration before it is stored ----------
CREATE OR REPLACE FUNCTION fn_registration_check() RETURNS TRIGGER AS $$
DECLARE
    v_status VARCHAR(10); v_open BOOLEAN; v_max INT; v_day DATE; v_taken INT; v_msg TEXT;
BEGIN
    SELECT e.status, bd.registration_open, bd.max_donors, e.starts_at::date
      INTO v_status, v_open, v_max, v_day
    FROM blood_drive bd JOIN event e ON e.event_id = bd.event_id
    WHERE bd.event_id = NEW.drive_id;

    IF v_status NOT IN ('PLANNED', 'ONGOING') THEN
        RAISE EXCEPTION 'Registration is closed: the drive is %', lower(v_status);
    END IF;
    IF NOT v_open THEN RAISE EXCEPTION 'Registration for this drive is closed'; END IF;

    SELECT COUNT(*) INTO v_taken FROM registration
    WHERE drive_id = NEW.drive_id AND status NOT IN ('CANCELLED', 'NO_SHOW') AND reg_id IS DISTINCT FROM NEW.reg_id;
    IF v_taken >= v_max THEN RAISE EXCEPTION 'The drive is full (% donors)', v_max; END IF;

    v_msg := fn_eligibility_check(NEW.donor_id, v_day);
    IF v_msg IS NOT NULL THEN RAISE EXCEPTION '%', v_msg; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_registration_check ON registration;
CREATE TRIGGER trg_registration_check BEFORE INSERT ON registration
FOR EACH ROW EXECUTE FUNCTION fn_registration_check();
DROP TRIGGER IF EXISTS trg_registration_reopen ON registration;
CREATE TRIGGER trg_registration_reopen BEFORE UPDATE OF status ON registration
FOR EACH ROW WHEN (OLD.status = 'CANCELLED' AND NEW.status = 'REGISTERED')
EXECUTE FUNCTION fn_registration_check();

-- ---------- T3: decide the screening outcome from the vitals ----------
-- If the screener gives no reason, the NBTC limits below decide; a reason given
-- by the screener (for example a recent tattoo) is always kept.
CREATE OR REPLACE FUNCTION fn_screening_evaluate() RETURNS TRIGGER AS $$
DECLARE
    v_status VARCHAR(10); v_ev_status VARCHAR(10); v_day DATE; v_dob DATE; v_code VARCHAR(20);
BEGIN
    SELECT r.status, e.status, e.starts_at::date, d.dob
      INTO v_status, v_ev_status, v_day, v_dob
    FROM registration r
    JOIN event e ON e.event_id = r.drive_id
    JOIN donor d ON d.donor_id = r.donor_id
    WHERE r.reg_id = NEW.reg_id;

    IF v_status IS NULL THEN RAISE EXCEPTION 'Registration % does not exist', NEW.reg_id; END IF;
    IF v_status <> 'REGISTERED' THEN
        RAISE EXCEPTION 'Cannot screen: registration % is already %', NEW.reg_id, v_status;
    END IF;
    IF v_ev_status NOT IN ('PLANNED', 'ONGOING') THEN
        RAISE EXCEPTION 'Cannot screen: the drive is %', lower(v_ev_status);
    END IF;

    IF NEW.reason_id IS NULL THEN
        v_code := CASE
            WHEN fn_age(v_dob, v_day) NOT BETWEEN 18 AND 65                          THEN 'AGE'
            WHEN NEW.hemoglobin < 12.5                                               THEN 'LOW_HB'
            WHEN NEW.weight_kg < 45                                                  THEN 'UNDERWEIGHT'
            WHEN NEW.temperature_c >= 37.5                                           THEN 'FEVER'
            WHEN NEW.bp_systolic NOT BETWEEN 100 AND 180
              OR NEW.bp_diastolic NOT BETWEEN 50 AND 100                             THEN 'BP'
            WHEN NEW.pulse NOT BETWEEN 50 AND 100                                    THEN 'PULSE'
        END;
        IF v_code IS NOT NULL THEN
            SELECT reason_id INTO NEW.reason_id FROM deferral_reason WHERE code = v_code;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_screening_evaluate ON screening;
CREATE TRIGGER trg_screening_evaluate BEFORE INSERT ON screening
FOR EACH ROW EXECUTE FUNCTION fn_screening_evaluate();

-- ---------- T4: after screening: update the registration, tell a deferred donor when to return ----------
CREATE OR REPLACE FUNCTION fn_screening_after() RETURNS TRIGGER AS $$
DECLARE
    v_donor INT; v_reason VARCHAR(100); v_days INT; v_perm BOOLEAN;
BEGIN
    UPDATE registration
       SET status = CASE WHEN NEW.reason_id IS NULL THEN 'SCREENED' ELSE 'DEFERRED' END
     WHERE reg_id = NEW.reg_id
    RETURNING donor_id INTO v_donor;

    IF NEW.reason_id IS NOT NULL THEN
        SELECT reason, defer_days, is_permanent INTO v_reason, v_days, v_perm
        FROM deferral_reason WHERE reason_id = NEW.reason_id;
        INSERT INTO donor_reminder (donor_id, kind, message)
        VALUES (v_donor, 'DEFERRAL_RETURN',
                CASE WHEN v_perm
                     THEN 'Thank you for coming. You cannot donate blood (' || v_reason || '). Please consult your doctor.'
                     ELSE 'Thank you for coming. You were deferred (' || v_reason || '). You can donate again from '
                          || to_char(NEW.screened_at::date + v_days, 'DD Mon YYYY') || '.' END);
        PERFORM fn_log(NEW.screened_by, 'SCREENING_DEFERRED', 'registration', NEW.reg_id, v_reason);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_screening_after ON screening;
CREATE TRIGGER trg_screening_after AFTER INSERT ON screening
FOR EACH ROW EXECUTE FUNCTION fn_screening_after();

-- ---------- T5: blood can be collected only from a donor who passed screening ----------
CREATE OR REPLACE FUNCTION fn_donation_check() RETURNS TRIGGER AS $$
DECLARE
    v_status VARCHAR(10); v_weight NUMERIC; v_reason INT;
BEGIN
    SELECT r.status, s.weight_kg, s.reason_id INTO v_status, v_weight, v_reason
    FROM registration r LEFT JOIN screening s ON s.reg_id = r.reg_id
    WHERE r.reg_id = NEW.reg_id;

    IF v_status IS NULL THEN RAISE EXCEPTION 'Registration % does not exist', NEW.reg_id; END IF;
    IF v_status <> 'SCREENED' THEN
        RAISE EXCEPTION 'Cannot collect blood: registration % is % (it must be SCREENED)', NEW.reg_id, v_status;
    END IF;
    IF v_reason IS NOT NULL THEN
        RAISE EXCEPTION 'Cannot collect blood: the donor was deferred at screening';
    END IF;
    IF NEW.volume_ml = 450 AND v_weight <= 55 THEN
        RAISE EXCEPTION '450 ml needs a donor above 55 kg (this donor weighs % kg); use 350 ml', v_weight;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_donation_check ON donation;
CREATE TRIGGER trg_donation_check BEFORE INSERT ON donation
FOR EACH ROW EXECUTE FUNCTION fn_donation_check();

-- ---------- T6: after a donation: close the registration, thank the donor, log it ----------
CREATE OR REPLACE FUNCTION fn_donation_after() RETURNS TRIGGER AS $$
DECLARE
    v_donor INT; v_title VARCHAR(150); v_gender CHAR(1);
BEGIN
    UPDATE registration SET status = 'DONATED' WHERE reg_id = NEW.reg_id RETURNING donor_id INTO v_donor;
    SELECT e.title, d.gender INTO v_title, v_gender
    FROM registration r JOIN event e ON e.event_id = r.drive_id JOIN donor d ON d.donor_id = r.donor_id
    WHERE r.reg_id = NEW.reg_id;

    INSERT INTO donor_reminder (donor_id, kind, message)
    VALUES (v_donor, 'THANK_YOU', 'Thank you for donating blood at ' || v_title || '. You can donate again from '
            || to_char(NEW.collected_at::date + fn_gap_days(v_gender), 'DD Mon YYYY') || '.');
    PERFORM fn_log(NEW.collected_by, 'DONATION', 'donation', NEW.donation_id, 'bag ' || NEW.bag_no || ', ' || NEW.volume_ml || ' ml');
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_donation_after ON donation;
CREATE TRIGGER trg_donation_after AFTER INSERT ON donation
FOR EACH ROW EXECUTE FUNCTION fn_donation_after();

-- ---------- T7: a new emergency request is announced to coordinators and the admin ----------
CREATE OR REPLACE FUNCTION fn_request_new() RETURNS TRIGGER AS $$
DECLARE v_hospital VARCHAR(100); v_group VARCHAR(3);
BEGIN
    SELECT hospital_name INTO v_hospital FROM hospital WHERE hospital_id = NEW.hospital_id;
    SELECT group_name   INTO v_group    FROM blood_group WHERE bg_id = NEW.bg_id;
    PERFORM fn_notify_roles('REQUEST_NEW',
            NEW.urgency || ': ' || NEW.units_needed || ' unit(s) of ' || v_group || ' needed at ' || v_hospital
            || ' by ' || to_char(NEW.required_by, 'DD Mon'), '/requests/' || NEW.request_id, NEW.request_id,
            'ADMIN', 'COORDINATOR');
    PERFORM fn_log(NEW.raised_by, 'REQUEST_RAISED', 'blood_request', NEW.request_id,
                   NEW.units_needed || ' x ' || v_group || ' at ' || v_hospital);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_request_new ON blood_request;
CREATE TRIGGER trg_request_new AFTER INSERT ON blood_request
FOR EACH ROW EXECUTE FUNCTION fn_request_new();

-- ---------- T8: a donor can be asked only for a request they can serve; status moves in order ----------
CREATE OR REPLACE FUNCTION fn_pledge_check() RETURNS TRIGGER AS $$
DECLARE
    v_req_status VARCHAR(10); v_req_bg INT; v_donor_bg INT; v_consent BOOLEAN; v_msg TEXT; v_gname VARCHAR(3); v_rname VARCHAR(3);
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT status, bg_id INTO v_req_status, v_req_bg FROM blood_request WHERE request_id = NEW.request_id;
        IF v_req_status IS DISTINCT FROM 'OPEN' THEN
            RAISE EXCEPTION 'Request % is not open (it is %)', NEW.request_id, COALESCE(v_req_status, 'missing');
        END IF;
        SELECT bg_id, consent_contact INTO v_donor_bg, v_consent FROM donor WHERE donor_id = NEW.donor_id;
        IF NOT EXISTS (SELECT 1 FROM blood_compatibility WHERE donor_bg = v_donor_bg AND recipient_bg = v_req_bg) THEN
            SELECT group_name INTO v_gname FROM blood_group WHERE bg_id = v_donor_bg;
            SELECT group_name INTO v_rname FROM blood_group WHERE bg_id = v_req_bg;
            RAISE EXCEPTION 'Blood group % cannot be given to a patient of group %', v_gname, v_rname;
        END IF;
        IF NOT v_consent THEN RAISE EXCEPTION 'This donor has asked not to be contacted'; END IF;
        v_msg := fn_eligibility_check(NEW.donor_id, CURRENT_DATE);
        IF v_msg IS NOT NULL THEN RAISE EXCEPTION '%', v_msg; END IF;
        RETURN NEW;
    END IF;

    -- UPDATE of status: CONTACTED -> PLEDGED | DECLINED, PLEDGED -> DONATED | DECLINED
    IF OLD.status IS DISTINCT FROM NEW.status THEN
        IF NOT ((OLD.status = 'CONTACTED' AND NEW.status IN ('PLEDGED', 'DECLINED'))
             OR (OLD.status = 'PLEDGED'   AND NEW.status IN ('DONATED', 'DECLINED'))) THEN
            RAISE EXCEPTION 'A response cannot change from % to %', OLD.status, NEW.status;
        END IF;
        IF NEW.status IN ('PLEDGED', 'DECLINED') AND NEW.responded_at IS NULL THEN NEW.responded_at := CURRENT_TIMESTAMP; END IF;
        IF NEW.status = 'DONATED' AND NEW.donated_at IS NULL THEN NEW.donated_at := CURRENT_TIMESTAMP; END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_pledge_check ON request_pledge;
CREATE TRIGGER trg_pledge_check BEFORE INSERT OR UPDATE OF status ON request_pledge
FOR EACH ROW EXECUTE FUNCTION fn_pledge_check();

-- ---------- T9: when enough donors have donated, the request is fulfilled ----------
CREATE OR REPLACE FUNCTION fn_pledge_after() RETURNS TRIGGER AS $$
DECLARE v_needed INT; v_done INT; v_status VARCHAR(10); v_by INT;
BEGIN
    SELECT units_needed, status, raised_by INTO v_needed, v_status, v_by FROM blood_request WHERE request_id = NEW.request_id;
    SELECT COUNT(*) INTO v_done FROM request_pledge WHERE request_id = NEW.request_id AND status = 'DONATED';
    INSERT INTO donor_reminder (donor_id, kind, message)
    VALUES (NEW.donor_id, 'THANK_YOU', 'Thank you for donating blood for request #' || NEW.request_id || '. You saved a life.');
    IF v_status = 'OPEN' AND v_done >= v_needed THEN
        UPDATE blood_request SET status = 'FULFILLED' WHERE request_id = NEW.request_id;
        PERFORM fn_notify(v_by, 'REQUEST_FULFILLED', 'Request #' || NEW.request_id || ' is fulfilled: ' || v_done || ' of '
                          || v_needed || ' unit(s) donated', '/requests/' || NEW.request_id, NEW.request_id);
        PERFORM fn_log(NULL, 'REQUEST_FULFILLED', 'blood_request', NEW.request_id, v_done || ' of ' || v_needed || ' units');
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_pledge_after ON request_pledge;
CREATE TRIGGER trg_pledge_after AFTER UPDATE OF status ON request_pledge
FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status AND NEW.status = 'DONATED')
EXECUTE FUNCTION fn_pledge_after();

-- ---------- T10: event status changes are logged; a cancelled drive cancels its registrations ----------
CREATE OR REPLACE FUNCTION fn_event_status() RETURNS TRIGGER AS $$
DECLARE v_units INT;
BEGIN
    PERFORM fn_log(NEW.coordinator_id, 'EVENT_' || NEW.status, 'event', NEW.event_id, NEW.title);
    IF NEW.status = 'CANCELLED' THEN
        WITH c AS (
            UPDATE registration SET status = 'CANCELLED'
            WHERE drive_id = NEW.event_id AND status = 'REGISTERED' RETURNING donor_id)
        INSERT INTO donor_reminder (donor_id, kind, message)
        SELECT donor_id, 'DRIVE_CANCELLED', 'The drive "' || NEW.title || '" on ' || to_char(NEW.starts_at, 'DD Mon')
               || ' has been cancelled. We will inform you about the next one.' FROM c;
        PERFORM fn_notify(NEW.coordinator_id, 'EVENT_CANCELLED', '"' || NEW.title || '" was cancelled', '/events/' || NEW.event_id, NEW.event_id);
    ELSIF NEW.status = 'COMPLETED' THEN
        SELECT COUNT(*) INTO v_units FROM donation dn JOIN registration r ON r.reg_id = dn.reg_id WHERE r.drive_id = NEW.event_id;
        PERFORM fn_notify(NEW.coordinator_id, 'EVENT_COMPLETED',
                          '"' || NEW.title || '" is closed' || CASE WHEN v_units > 0 THEN ': ' || v_units || ' unit(s) collected' ELSE '' END,
                          '/events/' || NEW.event_id, NEW.event_id);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_event_status ON event;
CREATE TRIGGER trg_event_status AFTER UPDATE OF status ON event
FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status)
EXECUTE FUNCTION fn_event_status();

-- ---------- T11: medical and audit records are never deleted ----------
CREATE OR REPLACE FUNCTION fn_no_delete() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Rows of % are never deleted (audit rule); change their status instead', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_no_delete_donation ON donation;
CREATE TRIGGER trg_no_delete_donation BEFORE DELETE ON donation FOR EACH ROW EXECUTE FUNCTION fn_no_delete();
DROP TRIGGER IF EXISTS trg_no_delete_screening ON screening;
CREATE TRIGGER trg_no_delete_screening BEFORE DELETE ON screening FOR EACH ROW EXECUTE FUNCTION fn_no_delete();
DROP TRIGGER IF EXISTS trg_no_delete_log ON activity_log;
CREATE TRIGGER trg_no_delete_log BEFORE DELETE ON activity_log FOR EACH ROW EXECUTE FUNCTION fn_no_delete();
