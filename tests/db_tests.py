#!/usr/bin/env python3
"""Database test cases (Chapter 5.1). Each test runs in its own transaction that is ROLLED BACK,
so the sample data never changes. Results (actual messages) are written to build/db_test_results.json."""
import json, os, sys, psycopg2, datetime as dt

HOST = os.environ.get("PGHOST", "127.0.0.1")
con = psycopg2.connect(host=HOST, user="postgres", dbname="raktasetu")
con.autocommit = False
cur = con.cursor()
ADMIN, ARAV, DIYA, ROHAN, MEERA = 1, 2, 3, 4, 5      # members: admin, coordinators, a volunteer
results = []

def one(sql, *a):
    cur.execute(sql, a); r = cur.fetchone(); return r[0] if r else None

def run(tid, title, steps, expected, check):
    """steps: function that executes SQL and returns the observed text. check(observed) -> bool."""
    try:
        obs = steps()
    except psycopg2.Error as e:
        obs = (e.diag.message_primary or str(e)).strip()
    finally:
        con.rollback()
    ok = check(obs)
    results.append(dict(id=tid, title=title, expected=expected, observed=str(obs), passed=bool(ok)))
    print(("PASS " if ok else "FAIL "), tid, title, "->", str(obs)[:110])

def expect_error(sql, params, contains):
    def go():
        cur.execute(sql, params); return "NO ERROR"
    return go

def has(s): return lambda o: s.lower() in str(o).lower()

# ids used below (looked up so the tests survive a reseed)
winter = one("SELECT event_id FROM event WHERE title='Winter Blood Drive'")
republic = one("SELECT event_id FROM event WHERE title='Republic Day Blood Drive'")
main_aud = one("SELECT venue_id FROM venue WHERE venue_name='Campus Main Auditorium'")
recent = one("SELECT donor_id FROM v_donor_status WHERE next_eligible_on > DATE '2026-12-12' AND next_eligible_on < DATE '2026-12-25' ORDER BY donor_id LIMIT 1")
registered = cur.execute("SELECT reg_id, donor_id FROM registration WHERE drive_id=%s AND status='REGISTERED' ORDER BY reg_id", (winter,)) or cur.fetchall()
reg1, donor1 = registered[0]; reg2, donor2 = registered[1]; reg3, donor3 = registered[2]
fresh = one("SELECT donor_id FROM v_donor_status WHERE eligible_now AND donor_id NOT IN (SELECT donor_id FROM registration WHERE drive_id=%s) ORDER BY donor_id LIMIT 1", winter)
a_plus = one("SELECT donor_id FROM v_donor_status WHERE eligible_now AND group_name='A+' ORDER BY donor_id LIMIT 1")
o_neg_bg = one("SELECT bg_id FROM blood_group WHERE group_name='O-'")
hosp1 = one("SELECT hospital_id FROM hospital ORDER BY hospital_id LIMIT 1")
b_plus = one("SELECT bg_id FROM blood_group WHERE group_name='B+'")
future = lambda d: (dt.date.today() + dt.timedelta(days=d)).isoformat()
heavy_reg = None

# --- DB1 venue clash
run("DB1", "Two events at the same venue and time",
    lambda: cur.execute("SELECT fn_add_event(%s,'Clash test','AWARENESS',%s,'2026-12-12 10:00','2026-12-12 12:00',0)", (DIYA, main_aud)) or "NO ERROR",
    "Exclusion constraint refuses the second booking: \"The venue is already booked for some of those hours\"", has("already booked"))
# --- DB2 donor who donated recently
run("DB2", "Register a donor who donated recently",
    lambda: cur.execute("SELECT fn_register_for_drive(%s,%s,NULL,%s)", (recent, winter, MEERA)) or "NO ERROR",
    "Trigger refuses: donor can donate again only from <date>", has("can donate again only from"))
# --- DB3 duplicate registration
run("DB3", "Register the same donor twice for one drive",
    lambda: cur.execute("SELECT fn_register_for_drive(%s,%s,NULL,%s)", (donor1, winter, MEERA)) or "NO ERROR",
    "Refused: \"This donor is already registered for this drive (registered)\"", has("already registered"))
# --- DB4 drive full
def db4():
    cur.execute("UPDATE blood_drive SET target_units=4, max_donors=4 WHERE event_id=%s", (republic,))
    cur.execute("SELECT fn_register_for_drive(%s,%s,NULL,%s)", (fresh, republic, MEERA)); return "NO ERROR"
run("DB4", "Register for a drive that is full",
    db4, "Trigger refuses: \"The drive is full (4 donors)\"", has("drive is full"))
# --- DB5 screening: low hemoglobin -> automatic deferral + reminder
def db5():
    cur.execute("SELECT fn_record_screening(%s,%s,11.8,62,118,76,72,36.8)", (reg1, ARAV)); out = cur.fetchone()[0]
    cur.execute("SELECT status FROM registration WHERE reg_id=%s", (reg1,)); st = cur.fetchone()[0]
    cur.execute("SELECT message FROM donor_reminder WHERE donor_id=%s AND kind='DEFERRAL_RETURN'", (donor1,)); m = cur.fetchone()[0]
    return f"{out} | registration={st} | reminder: {m}"
run("DB5", "Screening with low hemoglobin (11.8 g/dL)",
    db5, "Outcome DEFERRED: Low hemoglobin; registration becomes DEFERRED; donor gets a return-date reminder", lambda o: "DEFERRED: Low hemoglobin" in o and "registration=DEFERRED" in o and "You can donate again from" in o)
# --- DB6 full happy path
def db6():
    cur.execute("SELECT fn_record_screening(%s,%s,14.2,72,120,80,70,36.7)", (reg2, ARAV)); out = cur.fetchone()[0]
    cur.execute("SELECT fn_record_donation(%s,%s,'TEST-BAG-001')", (reg2, DIYA)); did = cur.fetchone()[0]
    cur.execute("SELECT volume_ml FROM donation WHERE donation_id=%s", (did,)); vol = cur.fetchone()[0]
    cur.execute("SELECT status FROM registration WHERE reg_id=%s", (reg2,)); st = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM donor_reminder WHERE donor_id=%s AND kind='THANK_YOU'", (donor2,)); r = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM activity_log WHERE action='DONATION' AND entity_id=%s", (did,)); lg = cur.fetchone()[0]
    return f"{out} | volume={vol} ml | registration={st} | thank-you reminders={r} | log rows={lg}"
run("DB6", "Screening passed, then blood collected",
    db6, "ELIGIBLE; 450 ml chosen for 72 kg; registration DONATED; thank-you reminder and activity-log row written by triggers",
    lambda o: o.startswith("ELIGIBLE") and "volume=450 ml" in o and "registration=DONATED" in o and "reminders=1" in o and "log rows=1" in o)
# --- DB7 450 ml for light donor
def db7():
    cur.execute("SELECT fn_record_screening(%s,%s,13.5,52,118,76,72,36.8)", (reg3, ARAV))
    cur.execute("SELECT fn_record_donation(%s,%s,'TEST-BAG-002',450)", (reg3, DIYA)); return "NO ERROR"
run("DB7", "450 ml requested from a 52 kg donor",
    db7, "Trigger refuses: \"450 ml needs a donor above 55 kg\"", has("450 ml needs a donor above 55 kg"))
# --- DB8 donation without screening
run("DB8", "Collect blood before screening",
    lambda: cur.execute("SELECT fn_record_donation(%s,%s,'TEST-BAG-003')", (reg1, DIYA)) or "NO ERROR",
    "Trigger refuses: registration is REGISTERED (it must be SCREENED)", has("must be SCREENED"))
# --- DB9 donation after deferral
def db9():
    cur.execute("SELECT fn_record_screening(%s,%s,11.0,62,118,76,72,36.8)", (reg1, ARAV))
    cur.execute("SELECT fn_record_donation(%s,%s,'TEST-BAG-004')", (reg1, DIYA)); return "NO ERROR"
run("DB9", "Collect blood from a deferred donor",
    db9, "Trigger refuses: registration is DEFERRED", has("is DEFERRED"))
# --- DB10 volunteer cannot screen
run("DB10", "Volunteer tries to record a screening",
    lambda: cur.execute("SELECT fn_record_screening(%s,%s,14,70,120,80,70,36.8)", (reg1, MEERA)) or "NO ERROR",
    "Refused: \"Only ADMIN or COORDINATOR can do this\"", has("Only ADMIN or COORDINATOR"))
# --- DB11 incompatible blood group
def db11():
    cur.execute("SELECT fn_raise_request(%s,%s,'Test Patient',%s,1,%s,'URGENT')", (DIYA, hosp1, o_neg_bg, future(2))); rid = cur.fetchone()[0]
    cur.execute("SELECT fn_contact_donor(%s,%s,%s)", (rid, a_plus, DIYA)); return "NO ERROR"
run("DB11", "Ask an A+ donor to help an O- patient",
    db11, "Trigger refuses: \"Blood group A+ cannot be given to a patient of group O-\"", has("A+ cannot be given to a patient of group O-"))
# --- DB12 pledge from donor who is not eligible
def db12():
    cur.execute("SELECT donor_id FROM v_donor_status WHERE group_name IN ('B+','O+','B-','O-') AND NOT eligible_now AND next_eligible_on IS NOT NULL ORDER BY donor_id LIMIT 1")
    d = cur.fetchone()[0]
    cur.execute("SELECT fn_raise_request(%s,%s,'Test Patient',%s,1,%s)", (DIYA, hosp1, b_plus, future(2))); rid = cur.fetchone()[0]
    cur.execute("SELECT fn_contact_donor(%s,%s,%s)", (rid, d, DIYA)); return "NO ERROR"
run("DB12", "Ask a donor who donated recently to help a patient",
    db12, "Trigger refuses: donor can donate again only from <date>", has("can donate again only from"))
# --- DB13 skipping a pledge state
def db13():
    cur.execute("SELECT fn_raise_request(%s,%s,'Test Patient',%s,1,%s)", (DIYA, hosp1, b_plus, future(2))); rid = cur.fetchone()[0]
    cur.execute("SELECT donor_id FROM fn_eligible_donors_for_request(%s) LIMIT 1", (rid,)); d = cur.fetchone()[0]
    cur.execute("SELECT fn_contact_donor(%s,%s,%s)", (rid, d, DIYA))
    cur.execute("SELECT fn_confirm_pledge_donated(%s,%s,%s)", (rid, d, DIYA)); return "NO ERROR"
run("DB13", "Mark a donor as donated before they accepted",
    db13, "Trigger refuses: \"A response cannot change from CONTACTED to DONATED\"", has("cannot change from CONTACTED to DONATED"))
# --- DB14 request becomes FULFILLED
def db14():
    cur.execute("SELECT fn_raise_request(%s,%s,'Test Patient',%s,1,%s)", (DIYA, hosp1, b_plus, future(2))); rid = cur.fetchone()[0]
    cur.execute("SELECT donor_id FROM fn_eligible_donors_for_request(%s) LIMIT 1", (rid,)); d = cur.fetchone()[0]
    cur.execute("SELECT fn_contact_donor(%s,%s,%s)", (rid, d, DIYA))
    cur.execute("SELECT fn_answer_pledge(%s,%s,%s,true)", (rid, d, MEERA))
    cur.execute("SELECT fn_confirm_pledge_donated(%s,%s,%s)", (rid, d, DIYA))
    cur.execute("SELECT status FROM blood_request WHERE request_id=%s", (rid,)); st = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM notification WHERE kind='REQUEST_FULFILLED' AND ref_id=%s", (rid,)); n = cur.fetchone()[0]
    return f"request status={st} | fulfilment notifications={n}"
run("DB14", "One unit needed, one donor donates",
    db14, "Trigger sets the request to FULFILLED and notifies the member who raised it", lambda o: "status=FULFILLED" in o and "notifications=1" in o)
# --- DB15 new request notifies
def db15():
    cur.execute("SELECT fn_raise_request(%s,%s,'Test Patient',%s,2,%s,'CRITICAL')", (DIYA, hosp1, b_plus, future(1))); rid = cur.fetchone()[0]
    cur.execute("SELECT count(*), min(message) FROM notification WHERE kind='REQUEST_NEW' AND ref_id=%s", (rid,)); n, m = cur.fetchone()
    return f"{n} notifications | {m}"
run("DB15", "Raise an emergency request",
    db15, "Trigger writes one notification for the admin and each of the 3 coordinators (4 in all)", lambda o: o.startswith("4 notifications"))
# --- DB16 CHECK constraint
run("DB16", "Insert a donor born in 2012 (under 18)",
    lambda: cur.execute("INSERT INTO donor (fname,gender,dob,bg_id,phone,donor_type) VALUES ('Tiny','M','2012-05-01',1,'9000000001','PUBLIC')") or "NO ERROR",
    "CHECK constraint donor_dob_check refuses the row", has("donor_dob_check"))
# --- DB17 function-level age
run("DB17", "Add a donor aged 17 through fn_add_donor",
    lambda: cur.execute("SELECT fn_add_donor('Young','Donor','M',%s,1,'9000000002',NULL,'Bengaluru','PUBLIC',NULL,NULL,%s)", (dt.date(2009, 12, 30), MEERA)) or "NO ERROR",
    "Refused: \"A donor must be between 18 and 65 years old\"", has("between 18 and 65"))
# --- DB18 cancelling a drive
def db18():
    cur.execute("SELECT fn_set_event_status(%s,%s,'CANCELLED')", (ARAV, republic))
    cur.execute("SELECT count(*) FROM registration WHERE drive_id=%s AND status='CANCELLED'", (republic,)); c = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM donor_reminder WHERE kind='DRIVE_CANCELLED'"); r = cur.fetchone()[0]
    return f"{c} registrations cancelled | {r} drive-cancelled reminders queued"
run("DB18", "Cancel a drive that has registrations",
    db18, "Trigger cancels all waiting registrations and queues a message for each donor", lambda o: o.startswith("4 registrations cancelled | 4 "))
# --- DB19 close drive with pending donation
def db19():
    cur.execute("SELECT fn_record_screening(%s,%s,14.2,72,120,80,70,36.7)", (reg2, ARAV))
    cur.execute("SELECT fn_close_drive(%s,%s)", (winter, ARAV)); return "NO ERROR"
run("DB19", "Close a drive while a screened donor has no bag recorded",
    db19, "Refused: \"1 donor(s) passed screening but have no donation recorded yet\"", has("passed screening but have no donation"))
# --- DB20 no delete
run("DB20", "Delete a donation row",
    lambda: cur.execute("DELETE FROM donation WHERE donation_id=1") or "NO ERROR",
    "Trigger refuses: rows of donation are never deleted", has("never deleted"))
# --- DB21/22 app role privileges
def as_app(sql):
    def go():
        cur.execute("SET ROLE rotaract_app"); cur.execute(sql); return "NO ERROR"
    return go
run("DB21", "Web-app role inserts into a table directly",
    as_app("INSERT INTO donor (fname,gender,dob,bg_id,phone,donor_type) VALUES ('X','M','1990-01-01',1,'9000000003','PUBLIC')"),
    "Refused: permission denied for table donor", has("permission denied for table donor"))
run("DB22", "Web-app role reads password hashes",
    as_app("SELECT password_hash FROM member"), "Refused: permission denied for table member", has("permission denied for table member"))
# --- DB23 admin-only
run("DB23", "A volunteer blocks a member",
    lambda: cur.execute("SELECT fn_set_member_active(%s,%s,false)", (MEERA, ARAV)) or "NO ERROR",
    "Refused: \"Only ADMIN can do this\"", has("Only ADMIN can do this"))
# --- DB24 reminder dedupe
def db24():
    cur.execute("SELECT fn_make_reminders(30)"); a = cur.fetchone()[0]
    cur.execute("SELECT fn_make_reminders(30)"); b = cur.fetchone()[0]
    return f"first call adds {a}, second call adds {b}"
run("DB24", "Eligible-again reminders run twice",
    db24, "First call adds reminders, second call adds 0 (one per donor in 30 days)", lambda o: not o.startswith("first call adds 0") and o.endswith("second call adds 0"))
# --- DB25 expire
def db25():
    cur.execute("INSERT INTO blood_request (hospital_id,patient_name,bg_id,units_needed,required_by,raised_by) VALUES (%s,'Old Request',%s,1,CURRENT_DATE-1,%s) RETURNING request_id", (hosp1, b_plus, DIYA)); rid = cur.fetchone()[0]
    cur.execute("SELECT fn_expire_requests()"); n = cur.fetchone()[0]
    cur.execute("SELECT status FROM blood_request WHERE request_id=%s", (rid,)); st = cur.fetchone()[0]
    return f"{n} expired | status={st}"
run("DB25", "Open request whose date has passed",
    db25, "fn_expire_requests sets it to EXPIRED", lambda o: o.endswith("status=EXPIRED"))
# --- DB26 duplicate bag number
def db26():
    cur.execute("SELECT fn_record_screening(%s,%s,14.2,72,120,80,70,36.7)", (reg2, ARAV))
    cur.execute("SELECT bag_no FROM donation ORDER BY donation_id LIMIT 1"); bag = cur.fetchone()[0]
    cur.execute("SELECT fn_record_donation(%s,%s,%s)", (reg2, DIYA, bag)); return "NO ERROR"
run("DB26", "Reuse a bag number",
    db26, "Refused by UNIQUE(bag_no): \"Bag number ... is already used\"", has("is already used"))
# --- DB27 hand-over
def db27():
    cur.execute("SELECT fn_record_screening(%s,%s,14.2,72,120,80,70,36.7)", (reg2, ARAV))
    cur.execute("SELECT fn_record_donation(%s,%s,'TEST-BAG-009')", (reg2, DIYA))
    cur.execute("SELECT fn_hand_over_units(%s,%s)", (winter, DIYA)); n = cur.fetchone()[0]
    cur.execute("SELECT status FROM donation WHERE bag_no='TEST-BAG-009'"); st = cur.fetchone()[0]
    return f"{n} bag handed over | status={st}"
run("DB27", "Hand the bags of a drive to the blood bank",
    db27, "Collected bag becomes HANDED_OVER with a timestamp", lambda o: o.startswith("1 bag handed over") and o.endswith("HANDED_OVER"))
# --- DB28 eligibility function
def db28():
    cur.execute("SELECT fn_eligibility_check(%s, DATE '2026-12-12')", (recent,)); a = cur.fetchone()[0]
    cur.execute("SELECT fn_eligibility_check(%s, DATE '2027-02-01')", (recent,)); b = cur.fetchone()[0]
    return f"on 12 Dec: {a} | on 1 Feb 2027: {b}"
run("DB28", "Eligibility function on two dates",
    db28, "Not eligible on 12 Dec 2026, eligible (NULL) on 1 Feb 2027", lambda o: "can donate again only from" in o and o.endswith("None"))

# --- DB29 duplicate open request
def db29():
    cur.execute("SELECT fn_raise_request(%s,%s,'Dup Patient',%s,1,%s)", (DIYA, hosp1, b_plus, future(3)))
    cur.execute("SELECT fn_raise_request(%s,%s,'Dup Patient',%s,2,%s)", (ARAV, hosp1, b_plus, future(4))); return "NO ERROR"
run("DB29", "Two open requests for the same patient, hospital and group",
    db29, "Partial unique index refuses the second: \"An open request for this patient ... already exists\"", has("open request for this patient"))

con.close()
os.makedirs(os.path.join(os.path.dirname(__file__), "..", "build"), exist_ok=True)
json.dump(results, open(os.path.join(os.path.dirname(__file__), "..", "build", "db_test_results.json"), "w"), indent=1)
bad = [r for r in results if not r["passed"]]
print(f"\n{len(results) - len(bad)}/{len(results)} passed"); sys.exit(1 if bad else 0)
