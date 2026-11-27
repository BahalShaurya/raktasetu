import json, re
D = json.load(open("build/report_data.json")); SCH = json.load(open("build/schema_info.json")); C = SCH["counts"]
DBT = json.load(open("build/db_test_results.json")); FET = json.load(open("build/fe_test_results.json"))
TABLES = {t["name"]: t for t in SCH["tables"]}
PURPOSE = {
 "department": "Departments of the college (shared lookup)", "blood_group": "The eight ABO/Rh blood groups",
 "blood_compatibility": "Which donor group can be given to which recipient group (recursive M:N on blood_group)",
 "venue": "Places where events are held, with capacity", "blood_bank": "Partner blood banks that collect the bags",
 "hospital": "Hospitals that send emergency requests", "deferral_reason": "Reasons for turning a donor away, temporary or permanent, with waiting days",
 "sponsor": "Companies and people who fund events", "member": "Rotaract club members who run the system (admin, coordinator, volunteer) with login details",
 "donor": "People who donate blood: students, staff, alumni, public", "event": "Every club event: drive, awareness talk, fundraiser, etc.",
 "blood_drive": "Extra details of an event that is a blood drive (ISA specialisation of event)",
 "event_volunteer": "Members who worked at an event, with duty and hours (M:N)", "event_sponsor": "Sponsors of an event with amount received (M:N)",
 "registration": "A donor's booking for a blood drive, with slot and status", "screening": "Health check at the camp (weak entity of registration)",
 "donation": "One collected bag of blood, with bag number, volume and status", "blood_request": "Emergency request from a hospital for a blood group",
 "request_pledge": "Donors contacted for a request and their answer (M:N)", "notification": "Messages for members, written by triggers",
 "donor_reminder": "Reminders to be sent to donors (eligible again, drive tomorrow, etc.)", "activity_log": "Audit trail of every important action",
}
ORDER = [t["name"] for t in SCH["tables"]]
def fks_text(t):
    f = TABLES[t]["fks"]
    return "—" if not f else "; ".join(f"{','.join(x['cols'])} → {x['ref']}" for x in f)
def relation_line(t):
    tb = TABLES[t]; fkcols = {c for f in tb["fks"] for c in f["cols"]}; pk = set(tb["pk"]); parts = []
    for c in tb["columns"]:
        n = c["name"]
        if n in pk: n = f"<u>{n}</u>"
        if n.replace("<u>", "").replace("</u>", "") in fkcols: n = f"<i>{n}</i>"
        parts.append(n)
    return f"<b>{t.upper()}</b> ({', '.join(parts)})"
def create_blocks():
    sql = open("sql/01_create_tables.sql").read(); out = []
    for m in re.finditer(r"(?:--[^\n]*\n)*CREATE (?:TABLE|UNIQUE INDEX|INDEX|EXTENSION)[^;]*;", sql): out.append(m.group(0))
    return out
def snippet(fname, name, kind="FUNCTION"):
    s = open(f"sql/{fname}").read()
    m = re.search(rf"CREATE (?:OR REPLACE )?{kind} {re.escape(name)}\b.*?(?:\$\$ LANGUAGE [^;]*;|;\n\n)", s, re.S)
    if kind == "VIEW": m = re.search(rf"CREATE (?:OR REPLACE )?VIEW {re.escape(name)} AS.*?;\n", s, re.S)
    if kind == "TRIGGER": m = re.search(rf"CREATE TRIGGER {re.escape(name)}.*?;\n", s, re.S)
    return m.group(0).strip() if m else f"-- {name} not found"
