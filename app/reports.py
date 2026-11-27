"""Report queries: used by the Reports page of the website AND by the written project report,
so the printed outputs are exactly what the site shows."""

REPORTS = [
 dict(key="search", n=1, title="Eligible O+ donors in Bengaluru",
      note="Stored function fn_search_donors reads the view v_donor_status and applies the filters.",
      sql="""SELECT donor_name, group_name, city, donations, last_donated_on, next_eligible_on
FROM fn_search_donors('O+', 'Bengaluru', true)"""),
 dict(key="upcoming", n=2, title="Upcoming blood drives with seats left",
      note="View v_upcoming_drives: a join of five tables with a conditional COUNT.",
      sql="""SELECT title, drive_date, venue_name, bank_name, target_units, registered, seats_left
FROM v_upcoming_drives"""),
 dict(key="registrations", n=3, title="Registrations for the Winter Blood Drive",
      note="Join of four tables, ordered by time slot.",
      sql="""SELECT to_char(r.slot_time, 'HH24:MI') AS slot, d.fname || ' ' || d.lname AS donor,
       bg.group_name, d.donor_type, r.status
FROM registration r
JOIN donor d        ON d.donor_id = r.donor_id
JOIN blood_group bg ON bg.bg_id = d.bg_id
JOIN event e        ON e.event_id = r.drive_id
WHERE e.title = 'Winter Blood Drive'
ORDER BY r.slot_time, donor
LIMIT 10"""),
 dict(key="drives", n=4, title="How each completed drive went",
      note="View v_drive_summary: registered, screened, deferred, bags collected and progress to target.",
      sql="""SELECT title, drive_date, registered, screened, deferred, units_collected, volume_ml, target_pct
FROM v_drive_summary
WHERE status = 'COMPLETED'
ORDER BY drive_date"""),
 dict(key="by_group", n=5, title="Blood collected by blood group",
      note="GROUP BY over four tables; discarded bags are not counted.",
      sql="""SELECT group_name, units, volume_ml
FROM v_blood_by_group"""),
 dict(key="never", n=6, title="Donors who registered but never donated",
      note="EXISTS and NOT EXISTS together (anti-join).",
      sql="""SELECT d.fname || ' ' || d.lname AS donor, bg.group_name, d.donor_type,
       (SELECT COUNT(*) FROM registration r WHERE r.donor_id = d.donor_id) AS registrations
FROM donor d
JOIN blood_group bg ON bg.bg_id = d.bg_id
WHERE EXISTS (SELECT 1 FROM registration r WHERE r.donor_id = d.donor_id)
  AND NOT EXISTS (SELECT 1 FROM registration r JOIN donation dn ON dn.reg_id = r.reg_id
                  WHERE r.donor_id = d.donor_id)
ORDER BY registrations DESC, donor
LIMIT 8"""),
 dict(key="repeat", n=7, title="Repeat donors (two or more donations)",
      note="GROUP BY with HAVING.",
      sql="""SELECT d.fname || ' ' || d.lname AS donor, bg.group_name,
       COUNT(*) AS donations, SUM(dn.volume_ml) AS total_ml
FROM donation dn
JOIN registration r ON r.reg_id = dn.reg_id
JOIN donor d        ON d.donor_id = r.donor_id
JOIN blood_group bg ON bg.bg_id = d.bg_id
GROUP BY d.donor_id, d.fname, d.lname, bg.group_name
HAVING COUNT(*) >= 2
ORDER BY donations DESC, total_ml DESC, donor
LIMIT 8"""),
 dict(key="deferrals", n=8, title="Why donors were deferred",
      note="View v_deferral_summary (LEFT JOIN so unused reasons show 0).",
      sql="""SELECT reason, times_used
FROM v_deferral_summary
WHERE times_used > 0"""),
 dict(key="soon", n=9, title="Donors who become eligible again in the next 30 days",
      note="Calculated from the last donation or deferral; nothing is stored.",
      sql="""SELECT donor_name, group_name, last_donated_on, next_eligible_on,
       next_eligible_on - CURRENT_DATE AS days_to_wait
FROM v_donor_status
WHERE is_active AND NOT eligible_now
  AND next_eligible_on BETWEEN CURRENT_DATE AND CURRENT_DATE + 30
ORDER BY next_eligible_on, donor_name
LIMIT 8"""),
 dict(key="open_req", n=10, title="Open emergency requests",
      note="View v_open_requests, most urgent first.",
      sql="""SELECT hospital_name, patient_name, group_name, urgency, units_needed,
       units_still_needed, pledged, awaiting_reply, days_left
FROM v_open_requests
ORDER BY CASE urgency WHEN 'CRITICAL' THEN 1 WHEN 'URGENT' THEN 2 ELSE 3 END, required_by"""),
 dict(key="match", n=11, title="Matching donors for the most urgent open request",
      note="Function fn_eligible_donors_for_request uses the compatibility table, eligibility and consent.",
      sql="""SELECT donor_name, group_name, exact_match, city, donations, last_donated_on
FROM fn_eligible_donors_for_request(
       (SELECT request_id FROM blood_request WHERE status = 'OPEN'
        ORDER BY CASE urgency WHEN 'CRITICAL' THEN 1 WHEN 'URGENT' THEN 2 ELSE 3 END, raised_at DESC LIMIT 1))"""),
 dict(key="dept", n=12, title="Donor participation by department",
      note="Two LEFT JOINs keep departments with no donations.",
      sql="""SELECT dep.dept_name, COUNT(DISTINCT d.donor_id) AS donors, COUNT(dn.donation_id) AS donations
FROM department dep
LEFT JOIN donor d        ON d.dept_id = dep.dept_id
LEFT JOIN registration r ON r.donor_id = d.donor_id
LEFT JOIN donation dn    ON dn.reg_id = r.reg_id
GROUP BY dep.dept_id, dep.dept_name
ORDER BY donations DESC, dep.dept_name"""),
 dict(key="volunteers", n=13, title="Volunteer hours leaderboard",
      note="View v_volunteer_hours.",
      sql="""SELECT member, role, events, total_hours
FROM v_volunteer_hours
WHERE total_hours > 0
ORDER BY total_hours DESC, member
LIMIT 6"""),
 dict(key="finance", n=14, title="Sponsorship against budget for completed events",
      note="View v_event_finance.",
      sql="""SELECT title, event_type, budget, sponsorship, funded_pct
FROM v_event_finance
WHERE status = 'COMPLETED'
ORDER BY event_date"""),
 dict(key="running", n=15, title="Running total of bags collected (window function)",
      note="SUM() OVER (ORDER BY ...) gives the cumulative total after each drive.",
      sql="""SELECT drive_date, title, units_collected,
       SUM(units_collected) OVER (ORDER BY drive_date) AS running_total
FROM v_drive_summary
WHERE status = 'COMPLETED'
ORDER BY drive_date"""),
 dict(key="first_time", n=16, title="First-time and repeat donors at each drive (window function)",
      note="ROW_NUMBER() numbers each donor's donations; number 1 is the first-time donor.",
      sql="""WITH d AS (
    SELECT r.drive_id, ROW_NUMBER() OVER (PARTITION BY r.donor_id ORDER BY dn.collected_at) AS nth
    FROM donation dn JOIN registration r ON r.reg_id = dn.reg_id)
SELECT e.title, COUNT(*) FILTER (WHERE nth = 1) AS first_time, COUNT(*) FILTER (WHERE nth > 1) AS repeat_donors
FROM d JOIN event e ON e.event_id = d.drive_id
GROUP BY e.event_id, e.title, e.starts_at
ORDER BY e.starts_at"""),
 dict(key="overview", n=17, title="Club overview (admin)",
      note="View v_admin_overview.", admin_only=True,
      sql="""SELECT members, donors, donors_eligible_now, upcoming_events, units_collected, litres_ml,
       open_requests, reminders_waiting
FROM v_admin_overview"""),
]
BY_KEY = {r["key"]: r for r in REPORTS}
