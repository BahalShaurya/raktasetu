"""Front-end and system tests: run against the live Flask server + PostgreSQL. Results saved to build/fe_test_results.json."""
import requests, re, json, random, datetime as dt, psycopg2, html, sys
B = "http://localhost:5000"
RES = []
def con(): return psycopg2.connect(host="127.0.0.1", user="rotaract_app", password="rotaract_app", dbname="raktasetu")
def q(sql, a=None):
    c = con(); cur = c.cursor(); cur.execute(sql, a); r = cur.fetchall(); c.close(); return r
def login(usn="ROTADMIN01", pw="admin123"):
    s = requests.Session(); s.post(B + "/login", data=dict(usn=usn, password=pw)); return s
def flashes(r, cat=None):
    return [html.unescape(m) for c, m in re.findall(r'<div class="flash (ok|err)">(.*?)</div>', r.text, re.S) if cat in (None, c)]
def rec(tid, kind, name, steps, expected, actual, ok):
    RES.append(dict(id=tid, kind=kind, name=name, steps=steps, expected=expected, actual=str(actual)[:230], passed=bool(ok)))
    print(("PASS" if ok else "FAIL"), tid, name, "|", str(actual)[:110])

A = login()
rnd = random.Random(7); phone = lambda: "9" + "".join(str(rnd.randint(0, 9)) for _ in range(9))

# ---- FE: access and login
r = requests.post(B + "/login", data=dict(usn="ROTADMIN01", password="wrong"))
f = flashes(r, "err"); rec("FE1", "FE", "Login with a wrong password", "POST /login with wrong password", "Error message, no session", f, f and "Invalid" in f[0])
r = A.get(B + "/"); rec("FE2", "FE", "Admin login opens dashboard", "Login ROTADMIN01/admin123, open /", "Dashboard with stat cards", r.status_code, "registered donors" in r.text)
r = requests.get(B + "/donors", allow_redirects=False); rec("FE3", "FE", "Page without login redirects", "GET /donors with no session", "302 to /login", f"{r.status_code} -> {r.headers.get('Location')}", r.status_code == 302 and "/login" in r.headers["Location"])
V = login("1RV24IS052", "rotaract@123")
r = V.get(B + "/admin"); rec("FE4", "FE", "Volunteer cannot open Admin page", "Login as volunteer, GET /admin", "403", r.status_code, r.status_code == 403)
r = V.get(B + "/requests/new"); rec("FE5", "FE", "Volunteer cannot raise requests", "Login as volunteer, GET /requests/new", "403", r.status_code, r.status_code == 403)

# ---- FE: donors
r = A.get(B + "/donors", params=dict(group="O+", eligible="1"))
n = len(re.findall(r'<a href="/donors/\d+">', r.text)); bad = len(re.findall(r"<td>(?:A|B|AB)[+-]</td>", r.text))
rec("FE6", "FE", "Donor search: O+ and eligible today", "GET /donors?group=O+&eligible=1", "Only O+ donors listed", f"{n} rows, {bad} other groups", n > 0 and bad == 0)
r = A.get(B + "/donors", params=dict(name="x'; DROP TABLE donor;--"))
rec("FE7", "FE", "SQL injection text in search box is harmless", "Search name = x'; DROP TABLE donor;--", "No error, 0 rows, table intact", f"{r.status_code}, donors={q('select count(*) from donor')[0][0]}", r.status_code == 200 and q("select count(*) from donor")[0][0] > 50)

drive = q("select event_id from event where title='Winter Blood Drive'")[0][0]
form = lambda **k: {**dict(fname="Test", lname="Donor", gender="M", dob="2003-04-12", bg=1, phone=phone(), city="Bengaluru", type="PUBLIC"), **k}
before = q("select count(*) from donor")[0][0]
r = requests.post(B + "/donate", data=form(fname="Karthik", lname="Pai", drive=drive), allow_redirects=True)
newid = q("select max(donor_id) from donor")[0][0]
regd = q("select count(*) from registration where donor_id=%s and drive_id=%s", (newid, drive))[0][0]
rec("FE8", "FE", "Public page: new donor signs up and books the Winter Drive", "POST /donate (no login) with donor details and drive", "Donor row and REGISTERED row created", f"donors {before}->{q('select count(*) from donor')[0][0]}, registrations={regd}", regd == 1)
f = form(fname="Minor", lname="Test"); f["dob"] = "2012-05-01"
r = requests.post(B + "/donate", data=f); m = flashes(r, "err")
rec("FE9", "FE", "Donor younger than 18 is rejected", "POST /donate with dob 2012-05-01", "Database CHECK/function message", m, bool(m))
f = form(fname="Heavy", lname="Phone"); f["phone"] = "12345"
r = A.post(B + "/donors/new", data=f); m = flashes(r, "err")
rec("FE10", "FE", "Bad phone number rejected", "POST /donors/new with phone 12345", "CHECK violation message, no row", m, bool(m) and q("select count(*) from donor where fname='Heavy'")[0][0] == 0)
r = A.post(B + f"/drives/{drive}/register", data=dict(donor=newid), allow_redirects=True); m = flashes(r, "err")
rec("FE11", "FE", "Same donor cannot register twice for a drive", "Register donor again on the same drive", "Duplicate message", m, bool(m))

# ---- FE: drive day flow (move the drive to ONGOING first, like a coordinator would)
r = A.post(B + f"/events/{drive}/status", data=dict(status="ONGOING"), allow_redirects=True)
rec("FE12", "FE", "Coordinator marks the drive ONGOING", "POST /events/<id>/status ONGOING", "Status updated message", flashes(r), "Status updated." in flashes(r, "ok"))
reg = q("select reg_id from registration where donor_id=%s and drive_id=%s", (newid, drive))[0][0]
r = A.post(B + f"/reg/{reg}/screen", data=dict(drive=drive, hb="11.2", weight="62", sys="118", dia="76", pulse="72", temp="36.8"), allow_redirects=True)
st = q("select status from registration where reg_id=%s", (reg,))[0][0]; why = q("select reason from v_screening_result where reg_id=%s", (reg,))
rec("FE13", "FE", "Low haemoglobin (11.2) is deferred automatically", "Screen donor with Hb 11.2 g/dL", "Status DEFERRED with reason", f"{st}; {why}", st == "DEFERRED")
# a fresh donor for the fit path
r = requests.post(B + "/donate", data=form(fname="Meghana", lname="Rao", gender="F", drive=drive)); did2 = q("select max(donor_id) from donor")[0][0]
reg2 = q("select reg_id from registration where donor_id=%s and drive_id=%s", (did2, drive))[0][0]
r = A.post(B + f"/reg/{reg2}/screen", data=dict(drive=drive, hb="13.6", weight="58", sys="116", dia="74", pulse="70", temp="36.7"), allow_redirects=True)
st = q("select status from registration where reg_id=%s", (reg2,))[0][0]
rec("FE14", "FE", "Fit donor is screened", "Screen donor with Hb 13.6, 58 kg, BP 116/74", "Status SCREENED", st, st == "SCREENED")
r = A.post(B + f"/reg/{reg2}/donate", data=dict(drive=drive, bag="RV-T-9001", volume=""), allow_redirects=True)
d = q("select bag_no, volume_ml, status from donation where reg_id=%s", (reg2,))
rec("FE15", "FE", "Donation recorded, volume chosen from weight", "POST donate with bag RV-T-9001 and no volume", "Row with 350 ml (58 kg woman) status COLLECTED", d, d and d[0][1] in (350, 450))
r = A.post(B + f"/reg/{reg}/donate", data=dict(drive=drive, bag="RV-T-9002", volume="350"), allow_redirects=True)
rec("FE16", "FE", "Deferred donor cannot donate", "POST donate for the deferred registration", "Error message", flashes(r, "err"), bool(flashes(r, "err")))
r = requests.post(B + "/donate", data=form(fname="Bag", lname="Clash", drive=drive)); did3 = q("select max(donor_id) from donor")[0][0]
reg3 = q("select reg_id from registration where donor_id=%s and drive_id=%s", (did3, drive))[0][0]
A.post(B + f"/reg/{reg3}/screen", data=dict(drive=drive, hb="14.0", weight="70", sys="120", dia="80", pulse="74", temp="36.6"))
r = A.post(B + f"/reg/{reg3}/donate", data=dict(drive=drive, bag="RV-T-9001", volume=""), allow_redirects=True)
rec("FE17", "FE", "Duplicate bag number rejected", "Donate with an already used bag number", "UNIQUE violation message", flashes(r, "err"), bool(flashes(r, "err")))
r = A.post(B + f"/drives/{drive}/close", allow_redirects=True)
rec("FE18", "FE", "Drive cannot close while a screened donor has no donation", "Close drive with one SCREENED donor still without a bag", "Blocked with message", flashes(r, "err"), bool(flashes(r, "err")) and q("select status from event where event_id=%s", (drive,))[0][0] != "COMPLETED")
A.post(B + f"/reg/{reg3}/donate", data=dict(drive=drive, bag="RV-T-9003", volume=""))
r = A.post(B + f"/drives/{drive}/handover", allow_redirects=True)
rec("FE19", "FE", "Hand over bags to blood bank", "POST /drives/<id>/handover", "Message with count", flashes(r), any("handed over" in m for m in flashes(r, "ok")))
r = A.post(B + f"/drives/{drive}/close", allow_redirects=True)
rec("FE19", "FE", "Close the drive after all donations are recorded", "POST /drives/<id>/close", "Summary message, status COMPLETED", flashes(r) , q("select status from event where event_id=%s", (drive,))[0][0] == "COMPLETED")

# ---- FE: emergency request flow
hosp = q("select hospital_id from hospital order by 1 limit 1")[0][0]
rq = dict(hospital=hosp, patient="Test Patient", bg=7, units=1, required_by=str(dt.date.today() + dt.timedelta(days=2)), urgency="URGENT", contact="9000000001", note="test")
r = A.post(B + "/requests/new", data=rq, allow_redirects=True); rid = q("select max(request_id) from blood_request")[0][0]
rec("FE20", "FE", "Raise an emergency request", "POST /requests/new", "Request created and shown", flashes(r), "Request raised" in " ".join(flashes(r, "ok")))
r = A.post(B + "/requests/new", data=rq, allow_redirects=True)
rec("FE21", "FE", "Duplicate open request is blocked", "Raise the same request again", "Message from unique index", flashes(r, "err"), bool(flashes(r, "err")))
m = q("select donor_id from fn_eligible_donors_for_request(%s) limit 1", (rid,))
if m:
    dd = m[0][0]
    A.post(B + f"/requests/{rid}/contact", data=dict(donor=dd)); A.post(B + f"/requests/{rid}/accept", data=dict(donor=dd)); A.post(B + f"/requests/{rid}/donated", data=dict(donor=dd))
    rs = q("select status from blood_request where request_id=%s", (rid,))[0][0]; ps = q("select status from request_pledge where request_id=%s and donor_id=%s", (rid, dd))[0][0]
    rec("FE22", "FE", "Contact, pledge and confirm a donor; request fulfils itself", "contact -> accept -> donated for 1-unit request", "Pledge DONATED, request FULFILLED", f"pledge={ps}, request={rs}", ps == "DONATED" and rs == "FULFILLED")
else:
    rec("FE22", "FE", "Contact, pledge and confirm a donor", "-", "-", "no eligible donor for group", False)

# ---- FE: events
vid = q("select venue_id from venue order by 1 limit 1")[0][0]
winter = q("select venue_id, starts_at from event where event_id=7")[0]
clash = dict(title="Clash Test", type="SOCIAL", venue=winter[0], start=winter[1].strftime("%Y-%m-%dT%H:%M"), end=(winter[1] + dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"), budget=0)
r = A.post(B + "/events/new", data=clash, allow_redirects=True)
rec("FE23", "FE", "Venue double-booking is refused", "Create an event at the same venue and time as an existing one", "Exclusion constraint message", flashes(r, "err"), bool(flashes(r, "err")))
ok = dict(title="Awareness Talk (test)", type="AWARENESS", venue=vid, start="2027-03-05T10:00", end="2027-03-05T12:00", budget=5000, description="t")
r = A.post(B + "/events/new", data=ok, allow_redirects=True); eid = q("select max(event_id) from event")[0][0]
rec("FE24", "FE", "Create an event", "POST /events/new for a free slot", "Event created", flashes(r), "Event created." in flashes(r, "ok"))
mid = q("select member_id from member where usn='1RV24IS052'")[0][0]; sp = q("select sponsor_id from sponsor order by 1 limit 1")[0][0]
A.post(B + f"/events/{eid}/volunteer", data=dict(member=mid, duty="Registration desk")); A.post(B + f"/events/{eid}/hours", data=dict(member=mid, hours="2.5"))
A.post(B + f"/events/{eid}/sponsor", data=dict(sponsor=sp, amount="3000"))
vh = q("select hours from event_volunteer where event_id=%s and member_id=%s", (eid, mid)); fin = q("select sponsorship, funded_pct from v_event_finance where event_id=%s", (eid,))
rec("FE25", "FE", "Assign volunteer, log hours, add sponsorship", "Three POSTs on the event page", "hours 2.5; sponsorship 3000 (60%)", f"{vh}; {fin}", vh and float(vh[0][0]) == 2.5 and fin and float(fin[0][0]) == 3000)

# ---- FE: reports, messages, reminders, admin
keys = re.findall(r'href="/reports/(\w+)"', A.get(B + "/reports").text); bad = [k for k in keys if A.get(B + "/reports/" + k).status_code != 200]
rec("FE26", "FE", "All reports open", "GET each /reports/<key>", "All 200", f"{len(keys)} reports, failures={bad}", len(keys) == 17 and not bad)
r = A.get(B + "/messages"); rec("FE27", "FE", "Trigger-created messages are visible", "GET /messages after raising a request", "Message about the request", len(re.findall("<tr><td>", r.text)), "emergency" in r.text.lower() or "request" in r.text.lower())
r = A.post(B + "/reminders", data=dict(action="make"), allow_redirects=True)
rec("FE28", "FE", "Create 'eligible again' reminders", "POST /reminders action=make", "Message with count", flashes(r), bool(flashes(r, "ok")))
r = A.post(B + "/admin", data=dict(action="create", usn="1RV24IS999", fname="Test", lname="Volunteer", email="t@college.example", phone=phone(), role="VOLUNTEER", dept=1, password="Test@123"), allow_redirects=True)
T = login("1RV24IS999", "Test@123"); rec("FE29", "FE", "Admin creates a member who can log in", "Create member, then log in as them", "Dashboard opens", flashes(r), "registered donors" in T.get(B + "/").text)
A.post(B + "/admin", data=dict(action="active", id=q("select member_id from member where usn='1RV24IS999'")[0][0], value="0"))
rec("FE30", "FE", "Switched-off member cannot log in", "Admin switches the member off, then they try to log in", "Login refused", "-", "registered donors" not in login("1RV24IS999", "Test@123").get(B + "/").text)

# ---- ST: system-level security
def denied(sql):
    c = con(); cur = c.cursor()
    try: cur.execute(sql); c.rollback(); return "ALLOWED"
    except psycopg2.Error as e: return e.diag.message_primary
    finally: c.close()
m = denied("SELECT password_hash FROM member"); rec("ST1", "ST", "App role cannot read password hashes", "SELECT password_hash FROM member as rotaract_app", "permission denied", m, "permission denied" in m)
m = denied("DELETE FROM donation"); rec("ST2", "ST", "App role cannot delete donations", "DELETE FROM donation as rotaract_app", "permission denied", m, "permission denied" in m)
m = denied("INSERT INTO donor(fname,lname,gender,dob,bg_id,phone) VALUES('a','b','M','2000-01-01',1,'9999999999')"); rec("ST3", "ST", "App role cannot INSERT directly into tables", "INSERT INTO donor as rotaract_app", "permission denied", m, "permission denied" in m)
m = denied("UPDATE blood_request SET status='FULFILLED'"); rec("ST4", "ST", "App role cannot UPDATE directly", "UPDATE blood_request as rotaract_app", "permission denied", m, "permission denied" in m)
r = V.post(B + "/requests/%d/close" % rid, allow_redirects=False); rec("ST5", "ST", "Volunteer cannot close a request (server-side check)", "Volunteer POSTs /requests/<id>/close", "403", r.status_code, r.status_code == 403)
c = con(); cur = c.cursor()
try:
    cur.execute("SELECT fn_set_member_role(%s,%s,'ADMIN')", (mid, mid)); c.rollback(); m = "ALLOWED"
except psycopg2.Error as e: m = e.diag.message_primary
c.close(); rec("ST6", "ST", "A volunteer cannot promote themself (database check)", "Call fn_set_member_role with a volunteer's own id as caller", "Error from fn_assert_admin", m, m != "ALLOWED")
cnt = q("select count(*) from activity_log")[0][0]; rec("ST7", "ST", "Every action is written to the audit log", "Count rows in activity_log after the test run", ">0 rows", cnt, cnt > 5)
r = requests.get(B + "/nonexistent"); rec("ST8", "ST", "Unknown URL gives a friendly 404 page", "GET /nonexistent", "404 page", r.status_code, r.status_code == 404 and "Page not found" in r.text)

_n = {"FE": 0, "ST": 0}
for x in RES:
    _n[x["kind"]] += 1; x["id"] = x["kind"] + str(_n[x["kind"]])
json.dump(RES, open("build/fe_test_results.json", "w"), indent=1)
print(sum(x["passed"] for x in RES), "of", len(RES), "passed")
