-- =====================================================================
-- 03_views.sql : two small helper functions and the views used by the
-- website and the Reports page.
-- =====================================================================

-- days a donor must wait between whole-blood donations (NBTC: 3 months men, 4 months women)
CREATE OR REPLACE FUNCTION fn_gap_days(p_gender CHAR) RETURNS INT AS $$
    SELECT CASE WHEN p_gender = 'F' THEN 120 ELSE 90 END;
$$ LANGUAGE sql IMMUTABLE;

CREATE OR REPLACE FUNCTION fn_age(p_dob DATE, p_on DATE) RETURNS INT AS $$
    SELECT date_part('year', age(p_on, p_dob))::INT;
$$ LANGUAGE sql IMMUTABLE;

-- ---------------------------------------------------------------------
-- v_donor_status : last donation, next eligible date and eligibility today.
-- Nothing here is stored: it is always calculated from the donation,
-- pledge and screening rows, so it can never disagree with them.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_donor_status AS
WITH drive_don AS (
    SELECT r.donor_id, COUNT(*) AS n, MAX(dn.collected_at::date) AS last_on
    FROM donation dn JOIN registration r ON r.reg_id = dn.reg_id
    GROUP BY r.donor_id
), emergency AS (
    SELECT donor_id, COUNT(*) AS n, MAX(donated_at::date) AS last_on
    FROM request_pledge WHERE status = 'DONATED' GROUP BY donor_id
), deferral AS (
    SELECT r.donor_id,
           MAX(s.screened_at::date + dr.defer_days) AS until_date,
           bool_or(dr.is_permanent)                 AS permanent
    FROM screening s
    JOIN registration r     ON r.reg_id = s.reg_id
    JOIN deferral_reason dr ON dr.reason_id = s.reason_id
    GROUP BY r.donor_id
), base AS (
    SELECT d.donor_id,
           d.fname || COALESCE(' ' || d.lname, '')               AS donor_name,
           d.gender, d.bg_id, bg.group_name, d.city, d.donor_type, d.phone,
           d.is_active, d.consent_contact, d.dept_id, d.dob,
           fn_age(d.dob, CURRENT_DATE)                           AS age,
           COALESCE(dd.n, 0) + COALESCE(em.n, 0)                 AS donations,
           GREATEST(dd.last_on, em.last_on)                      AS last_donated_on,
           COALESCE(df.permanent, false)                         AS permanently_deferred,
           CASE WHEN COALESCE(df.permanent, false) THEN NULL
                ELSE GREATEST(GREATEST(dd.last_on, em.last_on) + fn_gap_days(d.gender), df.until_date)
           END                                                   AS next_eligible_on
    FROM donor d
    JOIN blood_group bg ON bg.bg_id = d.bg_id
    LEFT JOIN drive_don dd ON dd.donor_id = d.donor_id
    LEFT JOIN emergency em ON em.donor_id = d.donor_id
    LEFT JOIN deferral  df ON df.donor_id = d.donor_id
)
SELECT b.*,
       (b.is_active
        AND b.age BETWEEN 18 AND 65
        AND NOT b.permanently_deferred
        AND (b.next_eligible_on IS NULL OR b.next_eligible_on <= CURRENT_DATE)) AS eligible_now
FROM base b;

-- upcoming drives with seats left
CREATE OR REPLACE VIEW v_upcoming_drives AS
SELECT e.event_id, e.title, e.starts_at::date AS drive_date, e.starts_at, e.ends_at, e.status,
       vn.venue_name, bb.bank_name, c.fname || ' ' || COALESCE(c.lname, '') AS coordinator,
       bd.target_units, bd.max_donors, bd.registration_open,
       COUNT(r.reg_id) FILTER (WHERE r.status NOT IN ('CANCELLED', 'NO_SHOW')) AS registered,
       bd.max_donors - COUNT(r.reg_id) FILTER (WHERE r.status NOT IN ('CANCELLED', 'NO_SHOW')) AS seats_left
FROM event e
JOIN blood_drive bd ON bd.event_id = e.event_id
JOIN venue vn       ON vn.venue_id = e.venue_id
JOIN blood_bank bb  ON bb.bank_id = bd.bank_id
JOIN member c       ON c.member_id = e.coordinator_id
LEFT JOIN registration r ON r.drive_id = e.event_id
WHERE e.status IN ('PLANNED', 'ONGOING')
GROUP BY e.event_id, vn.venue_name, bb.bank_name, c.fname, c.lname, bd.target_units, bd.max_donors, bd.registration_open
ORDER BY e.starts_at;

-- one row per drive: how it went
CREATE OR REPLACE VIEW v_drive_summary AS
SELECT e.event_id AS drive_id, e.title, e.starts_at::date AS drive_date, e.status,
       vn.venue_name, bb.bank_name, bd.target_units, bd.max_donors,
       COUNT(r.reg_id) FILTER (WHERE r.status <> 'CANCELLED')            AS registered,
       COUNT(r.reg_id) FILTER (WHERE r.status = 'CANCELLED')             AS cancelled,
       COUNT(r.reg_id) FILTER (WHERE r.status = 'NO_SHOW')               AS no_show,
       COUNT(s.reg_id)                                                   AS screened,
       COUNT(s.reg_id) FILTER (WHERE s.reason_id IS NOT NULL)            AS deferred,
       COUNT(dn.donation_id)                                             AS units_collected,
       COUNT(dn.donation_id) FILTER (WHERE dn.status = 'DISCARDED')      AS discarded,
       COALESCE(SUM(dn.volume_ml), 0)                                    AS volume_ml,
       ROUND(100.0 * COUNT(dn.donation_id) / bd.target_units, 1)         AS target_pct
FROM event e
JOIN blood_drive bd ON bd.event_id = e.event_id
JOIN venue vn       ON vn.venue_id = e.venue_id
JOIN blood_bank bb  ON bb.bank_id = bd.bank_id
LEFT JOIN registration r ON r.drive_id = e.event_id
LEFT JOIN screening s    ON s.reg_id = r.reg_id
LEFT JOIN donation dn    ON dn.reg_id = r.reg_id
GROUP BY e.event_id, e.title, e.starts_at, e.status, vn.venue_name, bb.bank_name, bd.target_units, bd.max_donors;

-- blood collected per blood group (discarded bags are not counted)
CREATE OR REPLACE VIEW v_blood_by_group AS
SELECT bg.group_name, COUNT(dn.donation_id) AS units, COALESCE(SUM(dn.volume_ml), 0) AS volume_ml
FROM blood_group bg
LEFT JOIN donor d         ON d.bg_id = bg.bg_id
LEFT JOIN registration r  ON r.donor_id = d.donor_id
LEFT JOIN donation dn     ON dn.reg_id = r.reg_id AND dn.status <> 'DISCARDED'
GROUP BY bg.bg_id, bg.group_name
ORDER BY bg.bg_id;

-- why donors were turned away
CREATE OR REPLACE VIEW v_deferral_summary AS
SELECT dr.reason, dr.is_permanent, dr.defer_days, COUNT(s.reg_id) AS times_used
FROM deferral_reason dr
LEFT JOIN screening s ON s.reason_id = dr.reason_id
GROUP BY dr.reason_id, dr.reason, dr.is_permanent, dr.defer_days
ORDER BY times_used DESC, dr.reason;

-- screening with its outcome in words
CREATE OR REPLACE VIEW v_screening_result AS
SELECT s.reg_id, r.drive_id, r.donor_id, s.screened_at, s.hemoglobin, s.weight_kg,
       s.bp_systolic || '/' || s.bp_diastolic AS bp, s.pulse, s.temperature_c,
       CASE WHEN s.reason_id IS NULL THEN 'ELIGIBLE' ELSE 'DEFERRED' END AS outcome,
       dr.reason, s.remarks
FROM screening s
JOIN registration r          ON r.reg_id = s.reg_id
LEFT JOIN deferral_reason dr ON dr.reason_id = s.reason_id;

-- bag-level register (what the partner blood bank receives)
CREATE OR REPLACE VIEW v_donation_register AS
SELECT dn.donation_id, dn.bag_no, bg.group_name, dn.volume_ml, dn.collected_at, dn.status, dn.handed_over_at,
       e.event_id AS drive_id, e.title AS drive, bb.bank_name,
       d.donor_id, d.fname || COALESCE(' ' || d.lname, '') AS donor_name
FROM donation dn
JOIN registration r  ON r.reg_id = dn.reg_id
JOIN donor d         ON d.donor_id = r.donor_id
JOIN blood_group bg  ON bg.bg_id = d.bg_id
JOIN event e         ON e.event_id = r.drive_id
JOIN blood_drive bd  ON bd.event_id = e.event_id
JOIN blood_bank bb   ON bb.bank_id = bd.bank_id;

-- open emergency requests with what is still needed
CREATE OR REPLACE VIEW v_open_requests AS
SELECT r.request_id, h.hospital_name, h.city, r.patient_name, bg.group_name, r.urgency,
       r.units_needed,
       COUNT(p.donor_id) FILTER (WHERE p.status = 'DONATED')   AS units_donated,
       r.units_needed - COUNT(p.donor_id) FILTER (WHERE p.status = 'DONATED') AS units_still_needed,
       COUNT(p.donor_id) FILTER (WHERE p.status = 'PLEDGED')   AS pledged,
       COUNT(p.donor_id) FILTER (WHERE p.status = 'CONTACTED') AS awaiting_reply,
       r.required_by, r.required_by - CURRENT_DATE AS days_left
FROM blood_request r
JOIN hospital h     ON h.hospital_id = r.hospital_id
JOIN blood_group bg ON bg.bg_id = r.bg_id
LEFT JOIN request_pledge p ON p.request_id = r.request_id
WHERE r.status = 'OPEN'
GROUP BY r.request_id, h.hospital_name, h.city, r.patient_name, bg.group_name, r.urgency, r.units_needed, r.required_by;

-- hours put in by each volunteer
CREATE OR REPLACE VIEW v_volunteer_hours AS
SELECT m.member_id, m.fname || ' ' || COALESCE(m.lname, '') AS member, m.role,
       COUNT(ev.event_id) AS events, COALESCE(SUM(ev.hours), 0) AS total_hours
FROM member m
LEFT JOIN event_volunteer ev ON ev.member_id = m.member_id
GROUP BY m.member_id, m.fname, m.lname, m.role;

-- money raised against budget for every event
CREATE OR REPLACE VIEW v_event_finance AS
SELECT e.event_id, e.title, e.event_type, e.starts_at::date AS event_date, e.status, e.budget,
       COALESCE(SUM(es.amount), 0)                                   AS sponsorship,
       COALESCE(SUM(es.amount), 0) - e.budget                        AS surplus,
       CASE WHEN e.budget = 0 THEN NULL ELSE ROUND(100.0 * COALESCE(SUM(es.amount), 0) / e.budget, 1) END AS funded_pct
FROM event e
LEFT JOIN event_sponsor es ON es.event_id = e.event_id
GROUP BY e.event_id, e.title, e.event_type, e.starts_at, e.status, e.budget;
