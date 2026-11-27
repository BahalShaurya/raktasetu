-- =====================================================================
-- 05_functions.sql : stored functions. Every business action of the
-- website is one function = one transaction, with its own checks.
-- =====================================================================

-- ------------------------------------------------------------------ donors
CREATE OR REPLACE FUNCTION fn_add_donor(
    p_fname VARCHAR, p_lname VARCHAR, p_gender CHAR, p_dob DATE, p_bg INT, p_phone VARCHAR,
    p_email VARCHAR DEFAULT NULL, p_city VARCHAR DEFAULT 'Bengaluru', p_type VARCHAR DEFAULT 'STUDENT',
    p_usn VARCHAR DEFAULT NULL, p_dept INT DEFAULT NULL, p_by INT DEFAULT NULL
) RETURNS INT AS $$
DECLARE v_id INT;
BEGIN
    IF p_by IS NOT NULL THEN PERFORM fn_assert_role(p_by, 'ADMIN', 'COORDINATOR', 'VOLUNTEER'); END IF;
    IF fn_age(p_dob, CURRENT_DATE) NOT BETWEEN 18 AND 65 THEN
        RAISE EXCEPTION 'A donor must be between 18 and 65 years old';
    END IF;
    IF p_type = 'STUDENT' AND (p_usn IS NULL OR p_dept IS NULL) THEN
        RAISE EXCEPTION 'A student donor needs a USN and a department';
    END IF;
    INSERT INTO donor (fname, lname, gender, dob, bg_id, phone, email, city, donor_type, usn, dept_id)
    VALUES (p_fname, NULLIF(p_lname, ''), p_gender, p_dob, p_bg, p_phone, NULLIF(p_email, ''), p_city, p_type, NULLIF(p_usn, ''), p_dept)
    RETURNING donor_id INTO v_id;
    PERFORM fn_log(p_by, 'DONOR_ADDED', 'donor', v_id, p_fname || ' ' || COALESCE(p_lname, ''));
    RETURN v_id;
EXCEPTION
    WHEN unique_violation THEN
        RAISE EXCEPTION 'A donor with this phone number or USN already exists';
END;
$$ LANGUAGE plpgsql;

-- search with filters; every filter is optional
CREATE OR REPLACE FUNCTION fn_search_donors(
    p_group TEXT DEFAULT NULL, p_city TEXT DEFAULT NULL, p_only_eligible BOOLEAN DEFAULT false,
    p_type TEXT DEFAULT NULL, p_name TEXT DEFAULT NULL
) RETURNS TABLE (donor_id INT, donor_name TEXT, group_name VARCHAR, city VARCHAR, donor_type VARCHAR, phone VARCHAR,
                 donations INT, last_donated_on DATE, next_eligible_on DATE, eligible_now BOOLEAN) AS $$
    SELECT v.donor_id, v.donor_name, v.group_name, v.city, v.donor_type, v.phone,
           v.donations::INT, v.last_donated_on, v.next_eligible_on, v.eligible_now
    FROM v_donor_status v
    WHERE v.is_active
      AND (p_group IS NULL OR v.group_name = p_group)
      AND (p_city  IS NULL OR v.city ILIKE p_city)
      AND (p_type  IS NULL OR v.donor_type = p_type)
      AND (p_name  IS NULL OR v.donor_name ILIKE '%' || p_name || '%')
      AND (NOT p_only_eligible OR v.eligible_now)
    ORDER BY v.eligible_now DESC, v.donations DESC, v.donor_name;
$$ LANGUAGE sql STABLE;

-- the full history of one donor
CREATE OR REPLACE FUNCTION fn_donor_history(p_donor INT)
RETURNS TABLE (reg_id INT, drive TEXT, drive_date DATE, reg_status VARCHAR, hemoglobin NUMERIC, weight_kg NUMERIC,
               bag_no VARCHAR, volume_ml INT, deferral_reason VARCHAR) AS $$
    SELECT r.reg_id, e.title::TEXT, e.starts_at::date, r.status, s.hemoglobin, s.weight_kg,
           dn.bag_no, dn.volume_ml, dr.reason
    FROM registration r
    JOIN event e                 ON e.event_id = r.drive_id
    LEFT JOIN screening s        ON s.reg_id = r.reg_id
    LEFT JOIN deferral_reason dr ON dr.reason_id = s.reason_id
    LEFT JOIN donation dn        ON dn.reg_id = r.reg_id
    WHERE r.donor_id = p_donor
    ORDER BY e.starts_at DESC;
$$ LANGUAGE sql STABLE;

-- ------------------------------------------------------- registration flow
CREATE OR REPLACE FUNCTION fn_register_for_drive(p_donor INT, p_drive INT, p_slot TIME DEFAULT NULL, p_by INT DEFAULT NULL)
RETURNS INT AS $$
DECLARE v_id INT; v_status VARCHAR(10);
BEGIN
    IF p_by IS NOT NULL THEN PERFORM fn_assert_role(p_by, 'ADMIN', 'COORDINATOR', 'VOLUNTEER'); END IF;
    SELECT reg_id, status INTO v_id, v_status FROM registration WHERE drive_id = p_drive AND donor_id = p_donor;
    IF FOUND THEN
        IF v_status <> 'CANCELLED' THEN
            RAISE EXCEPTION 'This donor is already registered for this drive (%)', lower(v_status);
        END IF;
        UPDATE registration SET status = 'REGISTERED', slot_time = COALESCE(p_slot, slot_time),
               registered_at = CURRENT_TIMESTAMP, registered_by = p_by WHERE reg_id = v_id;
    ELSE
        INSERT INTO registration (drive_id, donor_id, slot_time, registered_by)
        VALUES (p_drive, p_donor, p_slot, p_by) RETURNING reg_id INTO v_id;
    END IF;
    PERFORM fn_log(p_by, 'REGISTERED', 'registration', v_id, 'donor ' || p_donor || ' for drive ' || p_drive);
    RETURN v_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_cancel_registration(p_reg INT, p_by INT DEFAULT NULL) RETURNS VOID AS $$
DECLARE v_status VARCHAR(10);
BEGIN
    SELECT status INTO v_status FROM registration WHERE reg_id = p_reg FOR UPDATE;
    IF v_status IS NULL THEN RAISE EXCEPTION 'Registration % does not exist', p_reg; END IF;
    IF v_status <> 'REGISTERED' THEN
        RAISE EXCEPTION 'Only a waiting registration can be cancelled (this one is %)', v_status;
    END IF;
    UPDATE registration SET status = 'CANCELLED' WHERE reg_id = p_reg;
    PERFORM fn_log(p_by, 'REG_CANCELLED', 'registration', p_reg, NULL);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_record_screening(
    p_reg INT, p_member INT, p_hb NUMERIC, p_weight NUMERIC, p_sys INT, p_dia INT, p_pulse INT, p_temp NUMERIC,
    p_reason INT DEFAULT NULL, p_remarks VARCHAR DEFAULT NULL
) RETURNS TEXT AS $$
DECLARE v_reason VARCHAR(100);
BEGIN
    PERFORM fn_assert_role(p_member, 'ADMIN', 'COORDINATOR');
    INSERT INTO screening (reg_id, screened_by, hemoglobin, weight_kg, bp_systolic, bp_diastolic, pulse, temperature_c, reason_id, remarks)
    VALUES (p_reg, p_member, p_hb, p_weight, p_sys, p_dia, p_pulse, p_temp, p_reason, NULLIF(p_remarks, ''));
    SELECT dr.reason INTO v_reason FROM screening s JOIN deferral_reason dr ON dr.reason_id = s.reason_id WHERE s.reg_id = p_reg;
    RETURN CASE WHEN v_reason IS NULL THEN 'ELIGIBLE' ELSE 'DEFERRED: ' || v_reason END;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_record_donation(p_reg INT, p_member INT, p_bag VARCHAR, p_volume INT DEFAULT NULL)
RETURNS INT AS $$
DECLARE v_id INT; v_weight NUMERIC;
BEGIN
    PERFORM fn_assert_role(p_member, 'ADMIN', 'COORDINATOR');
    SELECT weight_kg INTO v_weight FROM screening WHERE reg_id = p_reg;
    INSERT INTO donation (reg_id, bag_no, volume_ml, collected_by)
    VALUES (p_reg, p_bag, COALESCE(p_volume, CASE WHEN v_weight > 55 THEN 450 ELSE 350 END), p_member)
    RETURNING donation_id INTO v_id;
    RETURN v_id;
EXCEPTION
    WHEN unique_violation THEN
        RAISE EXCEPTION 'Bag number % is already used, or this registration already has a donation', p_bag;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_hand_over_units(p_drive INT, p_member INT) RETURNS INT AS $$
DECLARE n INT;
BEGIN
    PERFORM fn_assert_role(p_member, 'ADMIN', 'COORDINATOR');
    UPDATE donation SET status = 'HANDED_OVER', handed_over_at = CURRENT_TIMESTAMP
    WHERE status = 'COLLECTED' AND reg_id IN (SELECT reg_id FROM registration WHERE drive_id = p_drive);
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n > 0 THEN PERFORM fn_log(p_member, 'UNITS_HANDED_OVER', 'event', p_drive, n || ' bag(s) given to the blood bank'); END IF;
    RETURN n;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_discard_unit(p_donation INT, p_member INT, p_reason VARCHAR) RETURNS VOID AS $$
BEGIN
    PERFORM fn_assert_role(p_member, 'ADMIN', 'COORDINATOR');
    UPDATE donation SET status = 'DISCARDED' WHERE donation_id = p_donation AND status <> 'DISCARDED';
    IF NOT FOUND THEN RAISE EXCEPTION 'Donation % does not exist or is already discarded', p_donation; END IF;
    PERFORM fn_log(p_member, 'UNIT_DISCARDED', 'donation', p_donation, p_reason);
END;
$$ LANGUAGE plpgsql;

-- ------------------------------------------------------------ events/drives
CREATE OR REPLACE FUNCTION fn_add_event(
    p_member INT, p_title VARCHAR, p_type VARCHAR, p_venue INT, p_start TIMESTAMP, p_end TIMESTAMP,
    p_budget NUMERIC DEFAULT 0, p_description TEXT DEFAULT NULL,
    p_bank INT DEFAULT NULL, p_target INT DEFAULT NULL, p_max INT DEFAULT NULL
) RETURNS INT AS $$
DECLARE v_id INT;
BEGIN
    PERFORM fn_assert_role(p_member, 'ADMIN', 'COORDINATOR');
    IF p_type = 'BLOOD_DRIVE' AND (p_bank IS NULL OR p_target IS NULL OR p_max IS NULL) THEN
        RAISE EXCEPTION 'A blood drive needs a blood bank, a target and a donor limit';
    END IF;
    INSERT INTO event (title, event_type, description, venue_id, starts_at, ends_at, coordinator_id, budget)
    VALUES (p_title, p_type, p_description, p_venue, p_start, p_end, p_member, COALESCE(p_budget, 0))
    RETURNING event_id INTO v_id;
    IF p_type = 'BLOOD_DRIVE' THEN
        INSERT INTO blood_drive (event_id, bank_id, target_units, max_donors) VALUES (v_id, p_bank, p_target, p_max);
    END IF;
    INSERT INTO event_volunteer (event_id, member_id, duty) VALUES (v_id, p_member, 'Overall coordination');
    PERFORM fn_log(p_member, 'EVENT_CREATED', 'event', v_id, p_title);
    RETURN v_id;
EXCEPTION
    WHEN exclusion_violation THEN
        RAISE EXCEPTION 'The venue is already booked for some of those hours';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_set_event_status(p_member INT, p_event INT, p_status VARCHAR) RETURNS VOID AS $$
DECLARE v_old VARCHAR(10);
BEGIN
    PERFORM fn_assert_role(p_member, 'ADMIN', 'COORDINATOR');
    SELECT status INTO v_old FROM event WHERE event_id = p_event FOR UPDATE;
    IF v_old IS NULL THEN RAISE EXCEPTION 'Event % does not exist', p_event; END IF;
    IF NOT ((v_old = 'PLANNED' AND p_status IN ('ONGOING', 'CANCELLED', 'COMPLETED'))
         OR (v_old = 'ONGOING' AND p_status IN ('COMPLETED', 'CANCELLED'))) THEN
        RAISE EXCEPTION 'An event cannot change from % to %', v_old, p_status;
    END IF;
    UPDATE event SET status = p_status WHERE event_id = p_event;
EXCEPTION
    WHEN exclusion_violation THEN RAISE EXCEPTION 'The venue is booked by another event';
END;
$$ LANGUAGE plpgsql;

-- closes a drive: waiting registrations become NO_SHOW; refuses if bags are still to be recorded
CREATE OR REPLACE FUNCTION fn_close_drive(p_drive INT, p_member INT) RETURNS TEXT AS $$
DECLARE v_pending INT; v_noshow INT; v_units INT; v_ml INT;
BEGIN
    PERFORM fn_assert_role(p_member, 'ADMIN', 'COORDINATOR');
    IF NOT EXISTS (SELECT 1 FROM blood_drive WHERE event_id = p_drive) THEN RAISE EXCEPTION 'Drive % does not exist', p_drive; END IF;
    SELECT COUNT(*) INTO v_pending FROM registration WHERE drive_id = p_drive AND status = 'SCREENED';
    IF v_pending > 0 THEN
        RAISE EXCEPTION '% donor(s) passed screening but have no donation recorded yet', v_pending;
    END IF;
    UPDATE registration SET status = 'NO_SHOW' WHERE drive_id = p_drive AND status = 'REGISTERED';
    GET DIAGNOSTICS v_noshow = ROW_COUNT;
    UPDATE blood_drive SET registration_open = false WHERE event_id = p_drive;
    PERFORM fn_set_event_status(p_member, p_drive, 'COMPLETED');
    SELECT COUNT(*), COALESCE(SUM(volume_ml), 0) INTO v_units, v_ml
    FROM donation dn JOIN registration r ON r.reg_id = dn.reg_id WHERE r.drive_id = p_drive;
    RETURN 'Drive closed: ' || v_units || ' unit(s), ' || v_ml || ' ml collected; ' || v_noshow || ' no-show(s)';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_assign_volunteer(p_by INT, p_event INT, p_member INT, p_duty VARCHAR DEFAULT 'General help')
RETURNS VOID AS $$
BEGIN
    PERFORM fn_assert_role(p_by, 'ADMIN', 'COORDINATOR');
    INSERT INTO event_volunteer (event_id, member_id, duty) VALUES (p_event, p_member, p_duty)
    ON CONFLICT (event_id, member_id) DO UPDATE SET duty = EXCLUDED.duty;
    PERFORM fn_log(p_by, 'VOLUNTEER_ASSIGNED', 'event', p_event, 'member ' || p_member || ': ' || p_duty);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_log_hours(p_by INT, p_event INT, p_member INT, p_hours NUMERIC) RETURNS VOID AS $$
BEGIN
    PERFORM fn_assert_role(p_by, 'ADMIN', 'COORDINATOR');
    UPDATE event_volunteer SET hours = p_hours WHERE event_id = p_event AND member_id = p_member;
    IF NOT FOUND THEN RAISE EXCEPTION 'Member % is not a volunteer of event %', p_member, p_event; END IF;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_add_sponsorship(p_by INT, p_event INT, p_sponsor INT, p_amount NUMERIC, p_received DATE DEFAULT CURRENT_DATE)
RETURNS VOID AS $$
BEGIN
    PERFORM fn_assert_role(p_by, 'ADMIN', 'COORDINATOR');
    INSERT INTO event_sponsor (event_id, sponsor_id, amount, received_on) VALUES (p_event, p_sponsor, p_amount, p_received)
    ON CONFLICT (event_id, sponsor_id) DO UPDATE SET amount = event_sponsor.amount + EXCLUDED.amount, received_on = EXCLUDED.received_on;
    PERFORM fn_log(p_by, 'SPONSORSHIP', 'event', p_event, 'sponsor ' || p_sponsor || ': Rs ' || p_amount);
END;
$$ LANGUAGE plpgsql;

-- ------------------------------------------------------- emergency requests
CREATE OR REPLACE FUNCTION fn_raise_request(
    p_member INT, p_hospital INT, p_patient VARCHAR, p_bg INT, p_units INT, p_required_by DATE,
    p_urgency VARCHAR DEFAULT 'NORMAL', p_contact VARCHAR DEFAULT NULL, p_note VARCHAR DEFAULT NULL
) RETURNS INT AS $$
DECLARE v_id INT;
BEGIN
    PERFORM fn_assert_role(p_member, 'ADMIN', 'COORDINATOR');
    IF p_required_by < CURRENT_DATE THEN RAISE EXCEPTION 'The required-by date is in the past'; END IF;
    INSERT INTO blood_request (hospital_id, patient_name, bg_id, units_needed, required_by, urgency, contact_phone, note, raised_by)
    VALUES (p_hospital, p_patient, p_bg, p_units, p_required_by, p_urgency, p_contact, NULLIF(p_note, ''), p_member)
    RETURNING request_id INTO v_id;
    RETURN v_id;
EXCEPTION
    WHEN unique_violation THEN
        RAISE EXCEPTION 'An open request for this patient, hospital and blood group already exists';
END;
$$ LANGUAGE plpgsql;

-- eligible donors who can serve a request: compatible group, eligible today, willing to be contacted
CREATE OR REPLACE FUNCTION fn_eligible_donors_for_request(p_request INT)
RETURNS TABLE (donor_id INT, donor_name TEXT, group_name VARCHAR, exact_match BOOLEAN, city VARCHAR, phone VARCHAR,
               donations INT, last_donated_on DATE, response VARCHAR) AS $$
    SELECT v.donor_id, v.donor_name, v.group_name, (v.bg_id = r.bg_id), v.city, v.phone,
           v.donations::INT, v.last_donated_on, p.status
    FROM blood_request r
    JOIN hospital h            ON h.hospital_id = r.hospital_id
    JOIN blood_compatibility c ON c.recipient_bg = r.bg_id
    JOIN v_donor_status v      ON v.bg_id = c.donor_bg
    LEFT JOIN request_pledge p ON p.request_id = r.request_id AND p.donor_id = v.donor_id
    WHERE r.request_id = p_request AND v.eligible_now AND v.consent_contact
    ORDER BY (v.bg_id = r.bg_id) DESC, (v.city = h.city) DESC, v.last_donated_on ASC NULLS LAST, v.donor_name;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION fn_contact_donor(p_request INT, p_donor INT, p_member INT) RETURNS VOID AS $$
DECLARE v_msg TEXT;
BEGIN
    PERFORM fn_assert_role(p_member, 'ADMIN', 'COORDINATOR');
    INSERT INTO request_pledge (request_id, donor_id) VALUES (p_request, p_donor);
    SELECT 'Urgent: ' || r.units_needed || ' unit(s) of ' || bg.group_name || ' needed at ' || h.hospital_name
           || ' by ' || to_char(r.required_by, 'DD Mon') || '. Can you help? Reply YES to the College Rotaract Club.'
      INTO v_msg
    FROM blood_request r JOIN hospital h ON h.hospital_id = r.hospital_id JOIN blood_group bg ON bg.bg_id = r.bg_id
    WHERE r.request_id = p_request;
    INSERT INTO donor_reminder (donor_id, kind, message) VALUES (p_donor, 'REQUEST_ALERT', v_msg);
    PERFORM fn_log(p_member, 'DONOR_CONTACTED', 'blood_request', p_request, 'donor ' || p_donor);
EXCEPTION
    WHEN unique_violation THEN RAISE EXCEPTION 'This donor has already been contacted for this request';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_answer_pledge(p_request INT, p_donor INT, p_member INT, p_accept BOOLEAN) RETURNS VOID AS $$
BEGIN
    PERFORM fn_assert_role(p_member, 'ADMIN', 'COORDINATOR', 'VOLUNTEER');
    UPDATE request_pledge SET status = CASE WHEN p_accept THEN 'PLEDGED' ELSE 'DECLINED' END
    WHERE request_id = p_request AND donor_id = p_donor;
    IF NOT FOUND THEN RAISE EXCEPTION 'This donor was not contacted for request %', p_request; END IF;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_confirm_pledge_donated(p_request INT, p_donor INT, p_member INT) RETURNS VOID AS $$
BEGIN
    PERFORM fn_assert_role(p_member, 'ADMIN', 'COORDINATOR');
    UPDATE request_pledge SET status = 'DONATED' WHERE request_id = p_request AND donor_id = p_donor;
    IF NOT FOUND THEN RAISE EXCEPTION 'This donor was not contacted for request %', p_request; END IF;
    PERFORM fn_log(p_member, 'PLEDGE_DONATED', 'blood_request', p_request, 'donor ' || p_donor);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_close_request(p_request INT, p_member INT) RETURNS VOID AS $$
BEGIN
    PERFORM fn_assert_role(p_member, 'ADMIN', 'COORDINATOR');
    UPDATE blood_request SET status = 'CLOSED' WHERE request_id = p_request AND status = 'OPEN';
    IF NOT FOUND THEN RAISE EXCEPTION 'Request % is not open', p_request; END IF;
    PERFORM fn_log(p_member, 'REQUEST_CLOSED', 'blood_request', p_request, NULL);
END;
$$ LANGUAGE plpgsql;

-- run daily: open requests whose date has passed become EXPIRED
CREATE OR REPLACE FUNCTION fn_expire_requests() RETURNS INT AS $$
DECLARE n INT;
BEGIN
    UPDATE blood_request SET status = 'EXPIRED' WHERE status = 'OPEN' AND required_by < CURRENT_DATE;
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n > 0 THEN PERFORM fn_log(NULL, 'REQUESTS_EXPIRED', 'blood_request', NULL, n || ' request(s) passed their date'); END IF;
    RETURN n;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------- reminders
-- "you can donate again" messages, at most one per donor in 30 days
CREATE OR REPLACE FUNCTION fn_make_reminders(p_days INT DEFAULT 7) RETURNS INT AS $$
DECLARE n INT;
BEGIN
    INSERT INTO donor_reminder (donor_id, kind, message)
    SELECT v.donor_id, 'ELIGIBLE_AGAIN',
           'You can donate blood again from ' || to_char(v.next_eligible_on, 'DD Mon YYYY') || '. Join the next Rotaract drive!'
    FROM v_donor_status v
    WHERE v.is_active AND v.consent_contact AND NOT v.permanently_deferred
      AND v.next_eligible_on BETWEEN CURRENT_DATE AND CURRENT_DATE + p_days
      AND NOT EXISTS (SELECT 1 FROM donor_reminder dr
                      WHERE dr.donor_id = v.donor_id AND dr.kind = 'ELIGIBLE_AGAIN'
                        AND dr.created_at > CURRENT_TIMESTAMP - INTERVAL '30 days');
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END;
$$ LANGUAGE plpgsql;

-- reminders for donors whose drive is within p_days; at most one per donor and drive per day
CREATE OR REPLACE FUNCTION fn_make_drive_reminders(p_days INT DEFAULT 1) RETURNS INT AS $$
DECLARE n INT;
BEGIN
    INSERT INTO donor_reminder (donor_id, kind, message)
    SELECT r.donor_id, 'DRIVE_REMINDER',
           'Reminder: ' || e.title || ' on ' || to_char(e.starts_at, 'DD Mon') || ' at ' || vn.venue_name
           || COALESCE(', your slot is ' || to_char(r.slot_time, 'HH24:MI'), '') || '. Eat well and drink water.'
    FROM registration r
    JOIN event e  ON e.event_id = r.drive_id
    JOIN venue vn ON vn.venue_id = e.venue_id
    WHERE r.status = 'REGISTERED' AND e.status = 'PLANNED'
      AND e.starts_at::date BETWEEN CURRENT_DATE AND CURRENT_DATE + p_days
      AND NOT EXISTS (SELECT 1 FROM donor_reminder dr
                      WHERE dr.donor_id = r.donor_id AND dr.kind = 'DRIVE_REMINDER'
                        AND dr.created_at::date = CURRENT_DATE AND dr.message LIKE '%' || e.title || '%');
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_mark_reminder_sent(p_reminder INT, p_member INT) RETURNS VOID AS $$
BEGIN
    PERFORM fn_assert_role(p_member, 'ADMIN', 'COORDINATOR');
    UPDATE donor_reminder SET sent_at = CURRENT_TIMESTAMP WHERE reminder_id = p_reminder AND sent_at IS NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_mark_notifications_read(p_member INT) RETURNS INT AS $$
DECLARE n INT;
BEGIN
    UPDATE notification SET read_at = CURRENT_TIMESTAMP WHERE member_id = p_member AND read_at IS NULL;
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END;
$$ LANGUAGE plpgsql;
