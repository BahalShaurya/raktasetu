-- =====================================================================
-- 08_verify_seed.sql : every query must return 0. Checks that the sample data
-- obeys the same rules the triggers enforce on new data.
-- =====================================================================
SELECT 'donation gap shorter than rule' AS check_name, COUNT(*) AS violations FROM (
    SELECT x.donor_id, x.on_date, LAG(x.on_date) OVER (PARTITION BY x.donor_id ORDER BY x.on_date) AS prev_date, d.gender
    FROM (SELECT r.donor_id, dn.collected_at::date AS on_date FROM donation dn JOIN registration r ON r.reg_id = dn.reg_id
          UNION ALL
          SELECT donor_id, donated_at::date FROM request_pledge WHERE status = 'DONATED') x
    JOIN donor d ON d.donor_id = x.donor_id) t
WHERE prev_date IS NOT NULL AND on_date - prev_date < fn_gap_days(gender)
UNION ALL
SELECT 'donation without a passed screening', COUNT(*) FROM donation dn
    LEFT JOIN screening s ON s.reg_id = dn.reg_id WHERE s.reg_id IS NULL OR s.reason_id IS NOT NULL
UNION ALL
SELECT '450 ml from a donor of 55 kg or less', COUNT(*) FROM donation dn JOIN screening s ON s.reg_id = dn.reg_id
    WHERE dn.volume_ml = 450 AND s.weight_kg <= 55
UNION ALL
SELECT 'donated registration without donation', COUNT(*) FROM registration r
    WHERE r.status = 'DONATED' AND NOT EXISTS (SELECT 1 FROM donation dn WHERE dn.reg_id = r.reg_id)
UNION ALL
SELECT 'registration status does not match screening', COUNT(*) FROM registration r LEFT JOIN screening s ON s.reg_id = r.reg_id
    WHERE (r.status = 'DEFERRED' AND (s.reg_id IS NULL OR s.reason_id IS NULL))
       OR (r.status = 'SCREENED' AND (s.reg_id IS NULL OR s.reason_id IS NOT NULL))
       OR (r.status IN ('REGISTERED', 'NO_SHOW', 'CANCELLED') AND s.reg_id IS NOT NULL)
UNION ALL
SELECT 'vitals outside limits but no deferral', COUNT(*) FROM screening s
    WHERE s.reason_id IS NULL AND (s.hemoglobin < 12.5 OR s.weight_kg < 45 OR s.temperature_c >= 37.5
          OR s.bp_systolic NOT BETWEEN 100 AND 180 OR s.bp_diastolic NOT BETWEEN 50 AND 100 OR s.pulse NOT BETWEEN 50 AND 100)
UNION ALL
SELECT 'drive over its donor limit', COUNT(*) FROM v_upcoming_drives WHERE seats_left < 0
UNION ALL
SELECT 'pledge from an incompatible group', COUNT(*) FROM request_pledge p
    JOIN blood_request r ON r.request_id = p.request_id JOIN donor d ON d.donor_id = p.donor_id
    WHERE NOT EXISTS (SELECT 1 FROM blood_compatibility c WHERE c.donor_bg = d.bg_id AND c.recipient_bg = r.bg_id)
UNION ALL
SELECT 'fulfilled request with too few donations', COUNT(*) FROM blood_request r
    WHERE r.status = 'FULFILLED' AND r.units_needed > (SELECT COUNT(*) FROM request_pledge p WHERE p.request_id = r.request_id AND p.status = 'DONATED')
UNION ALL
SELECT 'registered for a drive before donor was ever registered', COUNT(*) FROM registration r JOIN donor d ON d.donor_id = r.donor_id
    WHERE r.registered_at::date < d.registered_on;
