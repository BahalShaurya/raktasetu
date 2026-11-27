"""RaktaSetu - Rotaract blood donation management (Flask front end).
The app connects as the low-privilege role `rotaract_app`: it can SELECT from tables/views
and every change goes through a stored function, so business rules live in PostgreSQL."""
import os, functools, datetime as dt
import psycopg2, psycopg2.extras
from flask import Flask, g, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.security import check_password_hash, generate_password_hash
from reports import REPORTS, BY_KEY

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "raktasetu-dev-key")
DSN = dict(host=os.environ.get("PGHOST", "127.0.0.1"), dbname=os.environ.get("PGDATABASE", "raktasetu"),
           user="rotaract_app", password="rotaract_app")

# ---------- database helpers ----------
def db():
    if "db" not in g:
        g.db = psycopg2.connect(**DSN)
    return g.db

@app.teardown_appcontext
def close_db(_):
    c = g.pop("db", None)
    if c: c.close()

def rows(sql, args=None):
    with db().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, args); r = cur.fetchall()
    db().rollback()
    return r

def one(sql, args=None):
    r = rows(sql, args); return r[0] if r else None

def call(sql, args=None, ok=None):
    """Run a write (stored function). Shows the database's own message on failure."""
    try:
        with db().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, args)
            res = cur.fetchone() if cur.description else None
        db().commit()
        if ok: flash(ok, "ok")
        return res or True
    except psycopg2.Error as e:
        db().rollback()
        flash(e.diag.message_primary or str(e), "err")
        return None

def val(res):
    return list(res.values())[0] if isinstance(res, dict) else None

# ---------- auth ----------
def login_required(*roles):
    def deco(f):
        @functools.wraps(f)
        def w(*a, **k):
            if "uid" not in session: return redirect(url_for("login", next=request.path))
            if roles and session["role"] not in roles: abort(403)
            return f(*a, **k)
        return w
    return deco

@app.context_processor
def inject():
    unread = 0
    if "uid" in session:
        unread = one("SELECT COUNT(*) n FROM notification WHERE member_id=%s AND read_at IS NULL", (session["uid"],))["n"]
    return dict(me=session.get("name"), role=session.get("role"), unread=unread, today=dt.date.today())

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = one("SELECT * FROM fn_login_info(%s)", (request.form["usn"].strip().upper(),))
        if u and u["is_active"] and check_password_hash(u["password_hash"], request.form["password"]):
            session.update(uid=u["member_id"], name=f'{u["fname"]} {u["lname"]}', role=u["role"])
            return redirect(request.args.get("next") or url_for("home"))
        flash("Invalid USN/ID or password, or the account is switched off.", "err")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))

# ---------- dashboard ----------
@app.route("/")
@login_required()
def home():
    return render_template("home.html", ov=one("SELECT * FROM v_admin_overview"),
        drives=rows("SELECT * FROM v_upcoming_drives ORDER BY drive_date"),
        reqs=rows("SELECT * FROM v_open_requests ORDER BY CASE urgency WHEN 'CRITICAL' THEN 1 WHEN 'URGENT' THEN 2 ELSE 3 END, required_by"),
        groups=rows("SELECT * FROM v_blood_by_group"))

# ---------- donors ----------
@app.route("/donors")
@login_required()
def donors():
    f = request.args
    res = rows("SELECT * FROM fn_search_donors(%s,%s,%s,%s,%s)",
               (f.get("group") or None, f.get("city") or None, f.get("eligible") == "1",
                f.get("type") or None, f.get("name") or None))
    return render_template("donors.html", donors=res, groups=rows("SELECT * FROM blood_group ORDER BY bg_id"), f=f)

def donor_form_data():
    return dict(groups=rows("SELECT * FROM blood_group ORDER BY bg_id"), depts=rows("SELECT * FROM department ORDER BY dept_name"))

def add_donor_from_form(by):
    f = request.form
    return call("SELECT fn_add_donor(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) AS id",
                (f["fname"], f["lname"], f["gender"], f["dob"], f["bg"], f["phone"], f.get("email") or None,
                 f.get("city") or "Bengaluru", f["type"], (f.get("usn") or "").upper() or None,
                 f.get("dept") or None, by))

@app.route("/donors/new", methods=["GET", "POST"])
@login_required()
def donor_new():
    if request.method == "POST":
        r = add_donor_from_form(session["uid"])
        if r: flash("Donor added.", "ok"); return redirect(url_for("donor", did=val(r)))
    return render_template("donor_new.html", **donor_form_data(), public=False)

@app.route("/donate", methods=["GET", "POST"])
def public_register():
    """Public page: a student signs up as a donor and picks a drive."""
    if request.method == "POST":
        r = add_donor_from_form(None)
        if r:
            did = val(r)
            if request.form.get("drive"):
                call("SELECT fn_register_for_drive(%s,%s,NULL,NULL) AS id", (did, request.form["drive"]),
                     ok="You are registered. Thank you for donating!")
            else:
                flash("You are now in the donor list. Thank you!", "ok")
            return redirect(url_for("public_register"))
    return render_template("donor_new.html", **donor_form_data(), public=True,
                           drives=rows("SELECT * FROM v_upcoming_drives WHERE registration_open ORDER BY drive_date"))

@app.route("/donors/<int:did>", methods=["GET", "POST"])
@login_required()
def donor(did):
    d = one("SELECT * FROM v_donor_status WHERE donor_id=%s", (did,))
    if not d: abort(404)
    if request.method == "POST":
        call("SELECT fn_register_for_drive(%s,%s,NULL,%s) AS id", (did, request.form["drive"], session["uid"]), ok="Registered for the drive.")
        return redirect(url_for("donor", did=did))
    return render_template("donor.html", d=d, hist=rows("SELECT * FROM fn_donor_history(%s)", (did,)),
        drives=rows("SELECT * FROM v_upcoming_drives WHERE registration_open ORDER BY drive_date"),
        info=one("SELECT phone, email, usn, gender FROM donor WHERE donor_id=%s", (did,)))

# ---------- drives ----------
@app.route("/drives")
@login_required()
def drives():
    return render_template("drives.html", upcoming=rows("SELECT * FROM v_upcoming_drives ORDER BY drive_date"),
        done=rows("SELECT * FROM v_drive_summary WHERE status<>'PLANNED' ORDER BY drive_date DESC"))

@app.route("/drives/<int:eid>")
@login_required()
def drive(eid):
    s = one("SELECT * FROM v_drive_summary WHERE drive_id=%s", (eid,))
    if not s: abort(404)
    regs = rows("""SELECT r.reg_id, r.status, to_char(r.slot_time,'HH24:MI') slot, d.donor_id, d.fname||' '||d.lname donor,
                   bg.group_name, sr.outcome, sr.reason, dn.donation_id, dn.bag_no, dn.volume_ml, dn.status dstatus
                   FROM registration r JOIN donor d ON d.donor_id=r.donor_id JOIN blood_group bg ON bg.bg_id=d.bg_id
                   LEFT JOIN v_screening_result sr ON sr.reg_id=r.reg_id LEFT JOIN donation dn ON dn.reg_id=r.reg_id
                   WHERE r.drive_id=%s ORDER BY r.slot_time, donor""", (eid,))
    return render_template("drive.html", s=s, regs=regs,
        ev=one("SELECT * FROM v_upcoming_drives WHERE event_id=%s", (eid,)),
        reasons=rows("SELECT * FROM deferral_reason ORDER BY reason_id"),
        donors=rows("SELECT donor_id, donor_name, group_name FROM v_donor_status WHERE is_active ORDER BY donor_name"))

@app.post("/drives/<int:eid>/register")
@login_required()
def drive_register(eid):
    call("SELECT fn_register_for_drive(%s,%s,NULL,%s) AS id", (request.form["donor"], eid, session["uid"]), ok="Donor registered.")
    return redirect(url_for("drive", eid=eid))

@app.post("/reg/<int:rid>/cancel")
@login_required()
def reg_cancel(rid):
    call("SELECT fn_cancel_registration(%s,%s)", (rid, session["uid"]), ok="Registration cancelled.")
    return redirect(request.referrer or url_for("drives"))

@app.post("/reg/<int:rid>/screen")
@login_required()
def reg_screen(rid):
    f = request.form
    r = call("SELECT fn_record_screening(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) AS outcome",
             (rid, session["uid"], f["hb"], f["weight"], f["sys"], f["dia"], f["pulse"], f["temp"],
              f.get("reason") or None, f.get("remarks") or None))
    if r: flash("Screening saved: " + str(val(r)), "ok")
    return redirect(f"/drives/{f['drive']}")

@app.post("/reg/<int:rid>/donate")
@login_required()
def reg_donate(rid):
    f = request.form
    call("SELECT fn_record_donation(%s,%s,%s,%s) AS id", (rid, session["uid"], f["bag"], f.get("volume") or None), ok="Donation recorded.")
    return redirect(f"/drives/{f['drive']}")

@app.post("/drives/<int:eid>/handover")
@login_required("ADMIN", "COORDINATOR")
def drive_handover(eid):
    r = call("SELECT fn_hand_over_units(%s,%s) AS n", (eid, session["uid"]))
    if r: flash(f"{val(r)} bags handed over to the blood bank.", "ok")
    return redirect(url_for("drive", eid=eid))

@app.post("/drives/<int:eid>/close")
@login_required("ADMIN", "COORDINATOR")
def drive_close(eid):
    r = call("SELECT fn_close_drive(%s,%s) AS msg", (eid, session["uid"]))
    if r: flash(str(val(r)), "ok")
    return redirect(url_for("drive", eid=eid))

@app.post("/donation/<int:did>/discard")
@login_required("ADMIN", "COORDINATOR")
def donation_discard(did):
    call("SELECT fn_discard_unit(%s,%s,%s)", (did, session["uid"], request.form["reason"]), ok="Bag discarded.")
    return redirect(request.referrer or url_for("drives"))

# ---------- emergency requests ----------
@app.route("/requests")
@login_required()
def requests_():
    return render_template("requests.html", open=rows("SELECT * FROM v_open_requests ORDER BY CASE urgency WHEN 'CRITICAL' THEN 1 WHEN 'URGENT' THEN 2 ELSE 3 END, required_by"),
        old=rows("""SELECT r.request_id, h.hospital_name, r.patient_name, bg.group_name, r.units_needed, r.status, r.raised_at::date raised
                    FROM blood_request r JOIN hospital h USING(hospital_id) JOIN blood_group bg USING(bg_id)
                    WHERE r.status<>'OPEN' ORDER BY r.raised_at DESC"""))

@app.route("/requests/new", methods=["GET", "POST"])
@login_required("ADMIN", "COORDINATOR")
def request_new():
    if request.method == "POST":
        f = request.form
        r = call("SELECT fn_raise_request(%s,%s,%s,%s,%s,%s,%s,%s,%s) AS id",
                 (session["uid"], f["hospital"], f["patient"], f["bg"], f["units"], f["required_by"], f["urgency"],
                  f.get("contact") or None, f.get("note") or None))
        if r: flash("Request raised. Coordinators have been notified.", "ok"); return redirect(url_for("request_", rid=val(r)))
    return render_template("request_new.html", hospitals=rows("SELECT * FROM hospital ORDER BY hospital_name"),
                           groups=rows("SELECT * FROM blood_group ORDER BY bg_id"))

@app.route("/requests/<int:rid>")
@login_required()
def request_(rid):
    r = one("""SELECT r.*, h.hospital_name, h.city, bg.group_name FROM blood_request r
               JOIN hospital h USING(hospital_id) JOIN blood_group bg USING(bg_id) WHERE request_id=%s""", (rid,))
    if not r: abort(404)
    return render_template("request.html", r=r, donors=rows("SELECT * FROM fn_eligible_donors_for_request(%s)", (rid,)),
        pledges=rows("""SELECT p.*, d.fname||' '||d.lname donor, d.phone, bg.group_name FROM request_pledge p
                        JOIN donor d USING(donor_id) JOIN blood_group bg ON bg.bg_id=d.bg_id WHERE request_id=%s ORDER BY contacted_at""", (rid,)))

@app.post("/requests/<int:rid>/<action>")
@login_required("ADMIN", "COORDINATOR")
def request_action(rid, action):
    me, did = session["uid"], request.form.get("donor")
    if action == "contact":   call("SELECT fn_contact_donor(%s,%s,%s)", (rid, did, me), ok="Donor marked as contacted.")
    elif action == "accept":  call("SELECT fn_answer_pledge(%s,%s,%s,true)", (rid, did, me), ok="Pledge recorded.")
    elif action == "decline": call("SELECT fn_answer_pledge(%s,%s,%s,false)", (rid, did, me), ok="Decline recorded.")
    elif action == "donated": call("SELECT fn_confirm_pledge_donated(%s,%s,%s)", (rid, did, me), ok="Donation confirmed.")
    elif action == "close":   call("SELECT fn_close_request(%s,%s)", (rid, me), ok="Request closed.")
    else: abort(404)
    return redirect(url_for("request_", rid=rid))

# ---------- events ----------
@app.route("/events")
@login_required()
def events():
    return render_template("events.html", ev=rows("""SELECT e.event_id, e.title, e.event_type, e.starts_at, e.status, v.venue_name,
                                         m.fname||' '||m.lname coordinator FROM event e JOIN venue v USING(venue_id)
                                         JOIN member m ON m.member_id=e.coordinator_id ORDER BY e.starts_at DESC"""))

@app.route("/events/new", methods=["GET", "POST"])
@login_required("ADMIN", "COORDINATOR")
def event_new():
    if request.method == "POST":
        f = request.form
        r = call("SELECT fn_add_event(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) AS id",
                 (session["uid"], f["title"], f["type"], f["venue"], f["start"], f["end"], f.get("budget") or 0,
                  f.get("description") or None, f.get("bank") or None, f.get("target") or None, f.get("max") or None))
        if r: flash("Event created.", "ok"); return redirect(url_for("event", eid=val(r)))
    return render_template("event_new.html", venues=rows("SELECT * FROM venue ORDER BY venue_name"),
                           banks=rows("SELECT * FROM blood_bank ORDER BY bank_name"))

@app.route("/events/<int:eid>")
@login_required()
def event(eid):
    e = one("SELECT e.*, v.venue_name FROM event e JOIN venue v USING(venue_id) WHERE event_id=%s", (eid,))
    if not e: abort(404)
    return render_template("event.html", e=e,
        vols=rows("SELECT ev.*, m.fname||' '||m.lname member FROM event_volunteer ev JOIN member m USING(member_id) WHERE event_id=%s ORDER BY member", (eid,)),
        sponsors=rows("SELECT s.sponsor_name, es.amount, es.received_on FROM event_sponsor es JOIN sponsor s USING(sponsor_id) WHERE event_id=%s", (eid,)),
        fin=one("SELECT * FROM v_event_finance WHERE event_id=%s", (eid,)),
        members=rows("SELECT member_id, fname||' '||lname name FROM member WHERE is_active ORDER BY fname"),
        allsp=rows("SELECT * FROM sponsor ORDER BY sponsor_name"))

@app.post("/events/<int:eid>/<action>")
@login_required("ADMIN", "COORDINATOR")
def event_action(eid, action):
    f, me = request.form, session["uid"]
    if action == "volunteer": call("SELECT fn_assign_volunteer(%s,%s,%s,%s)", (me, eid, f["member"], f.get("duty") or "General help"), ok="Volunteer assigned.")
    elif action == "hours":   call("SELECT fn_log_hours(%s,%s,%s,%s)", (me, eid, f["member"], f["hours"]), ok="Hours logged.")
    elif action == "sponsor": call("SELECT fn_add_sponsorship(%s,%s,%s,%s)", (me, eid, f["sponsor"], f["amount"]), ok="Sponsorship recorded.")
    elif action == "status":  call("SELECT fn_set_event_status(%s,%s,%s)", (me, eid, f["status"]), ok="Status updated.")
    else: abort(404)
    return redirect(url_for("event", eid=eid))

# ---------- reports, messages, reminders ----------
@app.route("/reports")
@login_required()
def reports():
    return render_template("reports.html", reports=[r for r in REPORTS if not r.get("admin_only") or session["role"] == "ADMIN"])

@app.route("/reports/<key>")
@login_required()
def report(key):
    r = BY_KEY.get(key) or abort(404)
    if r.get("admin_only") and session["role"] != "ADMIN": abort(403)
    data = rows(r["sql"])
    return render_template("report.html", r=r, data=data, cols=list(data[0].keys()) if data else [])

@app.route("/messages", methods=["GET", "POST"])
@login_required()
def messages():
    if request.method == "POST":
        call("SELECT fn_mark_notifications_read(%s)", (session["uid"],), ok="All marked as read.")
        return redirect(url_for("messages"))
    return render_template("messages.html", items=rows("SELECT * FROM notification WHERE member_id=%s ORDER BY created_at DESC LIMIT 50", (session["uid"],)))

@app.route("/reminders", methods=["GET", "POST"])
@login_required("ADMIN", "COORDINATOR")
def reminders():
    if request.method == "POST":
        a = request.form["action"]
        if a == "make":  r = call("SELECT fn_make_reminders(7) AS n"); r and flash(f"{val(r)} 'eligible again' reminders created.", "ok")
        elif a == "drive": r = call("SELECT fn_make_drive_reminders(1) AS n"); r and flash(f"{val(r)} drive reminders created.", "ok")
        elif a == "sent": call("SELECT fn_mark_reminder_sent(%s,%s)", (request.form["id"], session["uid"]), ok="Marked as sent.")
        return redirect(url_for("reminders"))
    return render_template("reminders.html", items=rows("""SELECT r.*, d.fname||' '||d.lname donor, d.phone FROM donor_reminder r
                           JOIN donor d USING(donor_id) ORDER BY (sent_at IS NOT NULL), created_at DESC LIMIT 60"""))

# ---------- admin ----------
@app.route("/admin", methods=["GET", "POST"])
@login_required("ADMIN")
def admin():
    me = session["uid"]
    if request.method == "POST":
        f, a = request.form, request.form["action"]
        if a == "create":
            call("SELECT fn_create_member(%s,%s,%s,%s,%s,%s,%s,%s,%s) AS id",
                 (me, f["usn"].upper(), f["fname"], f["lname"], f["email"], f["phone"], f["role"], f.get("dept") or None,
                  generate_password_hash(f["password"])), ok="Member created.")
        elif a == "active": call("SELECT fn_set_member_active(%s,%s,%s)", (me, f["id"], f["value"] == "1"), ok="Member updated.")
        elif a == "role":   call("SELECT fn_set_member_role(%s,%s,%s)", (me, f["id"], f["role"]), ok="Role changed.")
        elif a == "password": call("SELECT fn_set_password(%s,%s,%s)", (me, f["id"], generate_password_hash(f["password"])), ok="Password reset.")
        return redirect(url_for("admin"))
    return render_template("admin.html", members=rows("SELECT member_id, usn, fname, lname, email, phone, role, is_active FROM member ORDER BY member_id"),
                           depts=rows("SELECT * FROM department ORDER BY dept_name"),
                           log=rows("SELECT * FROM fn_get_activity(%s,60)", (me,)))

@app.errorhandler(403)
def forbidden(_): return render_template("error.html", code=403, msg="Your role cannot open this page."), 403
@app.errorhandler(404)
def nf(_): return render_template("error.html", code=404, msg="Page not found."), 404

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
