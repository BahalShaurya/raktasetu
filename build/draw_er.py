#!/usr/bin/env python3
"""Draws the E-R diagram (Chen notation) to docs/er_diagram.png / .pdf"""
import os, math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Ellipse, Polygon
from PIL import ImageFont

ROOT = os.path.join(os.path.dirname(__file__), "..")
W, H = 2900, 2180
OX, OY = 90, 150
F = lambda px: ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", px)
tw = lambda s, px: F(px).getlength(s)
EN_PX, AT_PX, RL_PX, CD_PX = 25, 19, 19, 24
pt = lambda px: px * 0.72
INK = "#1a1a1a"

fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")

E, R, A = {}, {}, {}      # name -> (cx, cy, half_w, half_h)

def entity(name, x, y, weak=False):
    x += OX; y += OY
    w = max(tw(name, EN_PX) + 50, 190); h = 74
    E[name] = (x, y, w / 2, h / 2)
    ax.add_patch(Rectangle((x - w / 2, y - h / 2), w, h, fc="white", ec=INK, lw=2.0, zorder=5))
    if weak: ax.add_patch(Rectangle((x - w / 2 + 7, y - h / 2 + 7), w - 14, h - 14, fc="none", ec=INK, lw=1.6, zorder=5))
    ax.text(x, y, name, ha="center", va="center", fontsize=pt(EN_PX), fontweight="bold", zorder=6)

def rel(name, x, y, ident=False):
    x += OX; y += OY
    w = max(tw(name, RL_PX) + 70, 150); h = 100
    R[name] = (x, y, w / 2, h / 2)
    pts = [(x - w / 2, y), (x, y + h / 2), (x + w / 2, y), (x, y - h / 2)]
    ax.add_patch(Polygon(pts, closed=True, fc="white", ec=INK, lw=2.0, zorder=5))
    if ident:
        k = 0.82; p2 = [(x - k * w / 2, y), (x, y + k * h / 2), (x + k * w / 2, y), (x, y - k * h / 2)]
        ax.add_patch(Polygon(p2, closed=True, fc="none", ec=INK, lw=1.5, zorder=5))
    ax.text(x, y, name, ha="center", va="center", fontsize=pt(RL_PX), zorder=6)

def isa(name, x, y):
    x += OX; y += OY
    s = 62
    R[name] = (x, y, s, s)
    ax.add_patch(Polygon([(x - s, y + s * .55), (x + s, y + s * .55), (x, y - s * .75)], closed=True, fc="white", ec=INK, lw=2.0, zorder=5))
    ax.text(x, y + s * .22, "ISA", ha="center", va="center", fontsize=pt(AT_PX), fontweight="bold", zorder=6)

def attr(name, x, y, owner, key=False, multi=False, derived=False):
    x += OX; y += OY
    w = tw(name, AT_PX) + 40; h = 54
    A[name + "@" + owner] = (x, y, w / 2, h / 2)
    ax.add_patch(Ellipse((x, y), w, h, fc="white", ec=INK, lw=1.7, ls="--" if derived else "-", zorder=5))
    if multi: ax.add_patch(Ellipse((x, y), w - 12, h - 12, fc="none", ec=INK, lw=1.4, zorder=5))
    ax.text(x, y, name, ha="center", va="center", fontsize=pt(AT_PX), zorder=6)
    if key:
        ww = tw(name, AT_PX); ax.plot([x - ww / 2, x + ww / 2], [y - 11, y - 11], color=INK, lw=1.5, zorder=6)
    center = (E.get(owner) or R.get(owner))
    ax.plot([x, center[0]], [y, center[1]], color=INK, lw=1.5, zorder=1)

def boundary_offset(shape, dx, dy):
    """distance from shape centre to its boundary along direction (dx,dy)"""
    cx, cy, hw, hh = shape
    n = math.hypot(dx, dy); ux, uy = dx / n, dy / n
    return min(hw / abs(ux) if ux else 1e9, hh / abs(uy) if uy else 1e9)

def link(rname, ename, card, total=False, role=None, shift=(0, 0), lab_off=(0, 0), role_off=None):
    r = R[rname]; e = E[ename]
    ex, ey = e[0] + shift[0], e[1] + shift[1]
    dx, dy = ex - r[0], ey - r[1]; n = math.hypot(dx, dy); px, py = -dy / n, dx / n
    offs = [(-3.2, -3.2), (3.2, 3.2)] if total else [(0, 0)]
    for o in offs:
        ax.plot([r[0] + px * o[0], ex + px * o[1]], [r[1] + py * o[0], ey + py * o[1]], color=INK, lw=1.6, zorder=2)
    d = boundary_offset(e, -dx, -dy) + 26
    lx, ly = ex - dx / n * d + px * 20 + lab_off[0], ey - dy / n * d + py * 20 + lab_off[1]
    ax.text(lx, ly, card, ha="center", va="center", fontsize=pt(CD_PX), fontweight="bold", color="#b71c3a", zorder=7)
    if role:
        mx, my = (r[0] + ex) / 2, (r[1] + ey) / 2
        ro = role_off if role_off else (px * 22, py * 22)
        ax.text(mx + ro[0], my + ro[1], role, ha="center", va="center", fontsize=pt(18), style="italic", zorder=7)

def line(a, b, **kw):
    ax.plot([a[0], b[0]], [a[1], b[1]], color=INK, lw=1.6, zorder=2, **kw)

# =============================== entities ===============================
entity("HOSPITAL", 330, 1620)
entity("BLOOD_REQUEST", 1000, 1620)
entity("DONOR", 1000, 1130)
entity("BLOOD_GROUP", 1650, 1130)
entity("REGISTRATION", 1000, 650)
entity("SCREENING", 360, 650, weak=True)
entity("DONATION", 1000, 215)
entity("BLOOD_DRIVE", 1650, 650)
entity("BLOOD_BANK", 1650, 215)
entity("EVENT", 2250, 650)
entity("MEMBER", 2250, 1230)
entity("SPONSOR", 2250, 215)

# ============================== relationships ============================
rel("RAISES", 665, 1620); rel("NEEDS", 1650, 1620); rel("RESPONDS", 1000, 1385)
rel("HAS_GROUP", 1325, 1130); rel("CAN_DONATE_TO", 2010, 1130)
rel("MAKES", 1000, 890); rel("HAS_SCREENING", 690, 650, ident=True)
rel("FOR_DRIVE", 1325, 650); rel("RESULTS_IN", 1000, 435)
rel("COLLECTS", 1650, 435); isa("ISA", 1950, 650)
rel("ORGANIZES", 2090, 940); rel("VOLUNTEERS_AT", 2440, 940); rel("SPONSORS", 2250, 435)

# links:  relationship -> entity, cardinality, total participation
link("RAISES", "HOSPITAL", "1"); link("RAISES", "BLOOD_REQUEST", "N", total=True)
link("NEEDS", "BLOOD_REQUEST", "N", total=True); link("NEEDS", "BLOOD_GROUP", "1")
link("RESPONDS", "BLOOD_REQUEST", "N"); link("RESPONDS", "DONOR", "M")
link("HAS_GROUP", "DONOR", "N", total=True); link("HAS_GROUP", "BLOOD_GROUP", "1")
link("CAN_DONATE_TO", "BLOOD_GROUP", "M", role="donor", shift=(0, 30), lab_off=(2, 20), role_off=(48, 30))
link("CAN_DONATE_TO", "BLOOD_GROUP", "N", role="recipient", shift=(0, -30), lab_off=(2, -20), role_off=(48, -30))
link("MAKES", "DONOR", "1"); link("MAKES", "REGISTRATION", "N", total=True)
link("FOR_DRIVE", "REGISTRATION", "N", total=True); link("FOR_DRIVE", "BLOOD_DRIVE", "1")
link("HAS_SCREENING", "REGISTRATION", "1"); link("HAS_SCREENING", "SCREENING", "1", total=True)
link("RESULTS_IN", "REGISTRATION", "1"); link("RESULTS_IN", "DONATION", "1", total=True)
link("COLLECTS", "BLOOD_BANK", "1"); link("COLLECTS", "BLOOD_DRIVE", "N", total=True)
line((E["EVENT"][0], E["EVENT"][1]), (R["ISA"][0], R["ISA"][1]))
ax.plot([R["ISA"][0], E["BLOOD_DRIVE"][0]], [R["ISA"][1] - 3, E["BLOOD_DRIVE"][1] - 3], color=INK, lw=1.6, zorder=2)
ax.plot([R["ISA"][0], E["BLOOD_DRIVE"][0]], [R["ISA"][1] + 3, E["BLOOD_DRIVE"][1] + 3], color=INK, lw=1.6, zorder=2)
link("ORGANIZES", "MEMBER", "1"); link("ORGANIZES", "EVENT", "N", total=True)
link("VOLUNTEERS_AT", "MEMBER", "M"); link("VOLUNTEERS_AT", "EVENT", "N")
link("SPONSORS", "SPONSOR", "M"); link("SPONSORS", "EVENT", "N")

# ============================== attributes ===============================
def around(owner, items, cx, cy, spec):
    for (nm, ang, rad, *flags) in spec:
        x = cx + rad * math.cos(math.radians(ang)); y = cy + rad * math.sin(math.radians(ang))
        attr(nm, x, y, owner, key="key" in flags, multi="multi" in flags, derived="derived" in flags)

around("HOSPITAL", None, 330, 1620, [("hospital_id", 120, 210, "key"), ("hospital_name", 180, 265), ("city", 240, 205)])
around("BLOOD_REQUEST", None, 1000, 1620, [("request_id", 155, 285, "key"), ("patient_name", 112, 215), ("units_needed", 68, 215),
                                            ("required_by", 28, 270), ("urgency", 335, 250)])
attr("responded_at", 770, 1385, "RESPONDS"); attr("response_status", 1235, 1385, "RESPONDS")
attr("donor_id", 760, 1300, "DONOR", key=True); attr("department", 530, 1235, "DONOR"); attr("name", 480, 1130, "DONOR")
attr("gender", 500, 1020, "DONOR"); attr("date_of_birth", 665, 925, "DONOR"); attr("phone", 1190, 1000, "DONOR"); attr("city", 1190, 1255, "DONOR")
attr("bg_id", 1520, 975, "BLOOD_GROUP", key=True); attr("group_name", 1810, 975, "BLOOD_GROUP")
attr("reg_id", 740, 490, "REGISTRATION", key=True); attr("slot_time", 735, 790, "REGISTRATION"); attr("status", 1200, 490, "REGISTRATION")
around("SCREENING", None, 360, 650, [("hemoglobin", 100, 230), ("weight_kg", 137, 295), ("bp_systolic", 172, 305), ("bp_diastolic", 203, 305),
                                       ("pulse", 233, 265), ("temperature_c", 252, 330), ("deferral_reason", 290, 330), ("screened_at", 328, 285)])
around("DONATION", None, 1000, 215, [("donation_id", 150, 285, "key"), ("bag_number", 188, 285), ("volume_ml", 232, 185), ("collected_at", 312, 260), ("status", 352, 235)])
around("BLOOD_DRIVE", None, 1650, 650, [("target_units", 135, 255), ("max_donors", 45, 255)])
around("BLOOD_BANK", None, 1650, 215, [("bank_id", 180, 255, "key"), ("bank_name", 232, 280), ("license_no", 302, 270), ("city", 350, 270)])
for i, (nm, flags) in enumerate([("event_id", {"key": True}), ("title", {}), ("event_type", {}), ("starts_at", {}), ("ends_at", {}), ("status", {}), ("venue", {})]):
    ang = math.radians(25 - i * 12.5)
    attr(nm, 2250 + 395 * math.cos(ang), 650 + 395 * math.sin(ang), "EVENT", **flags)
around("MEMBER", None, 2250, 1230, [("member_id", 125, 250, "key"), ("name", 82, 235), ("usn", 40, 270), ("role", 3, 285), ("email", -38, 255), ("department", 172, 285)])
around("SPONSOR", None, 2250, 215, [("sponsor_id", 150, 265, "key"), ("sponsor_name", 205, 290), ("phone", 340, 245)])
attr("duty", 2640, 1010, "VOLUNTEERS_AT"); attr("hours", 2650, 900, "VOLUNTEERS_AT")
attr("amount", 2040, 440, "SPONSORS")

# legend
lx, ly = 90, 60
ax.text(lx, ly, "Legend:", fontsize=pt(20), fontweight="bold", va="center")
ax.add_patch(Rectangle((lx + 120, ly - 17), 70, 34, fc="white", ec=INK, lw=1.6)); ax.text(lx + 200, ly, "entity", fontsize=pt(18), va="center")
ax.add_patch(Rectangle((lx + 285, ly - 17), 70, 34, fc="white", ec=INK, lw=1.6)); ax.add_patch(Rectangle((lx + 291, ly - 11), 58, 22, fc="none", ec=INK, lw=1.2))
ax.text(lx + 365, ly, "weak entity", fontsize=pt(18), va="center")
ax.add_patch(Polygon([(lx + 520, ly), (lx + 555, ly + 20), (lx + 590, ly), (lx + 555, ly - 20)], fc="white", ec=INK, lw=1.6)); ax.text(lx + 600, ly, "relationship", fontsize=pt(18), va="center")
ax.add_patch(Ellipse((lx + 770, ly), 70, 32, fc="white", ec=INK, lw=1.6)); ax.text(lx + 810, ly, "attribute", fontsize=pt(18), va="center")
ax.text(lx + 935, ly, "key", fontsize=pt(18), va="center"); ax.plot([lx + 935, lx + 970], [ly - 12, ly - 12], color=INK, lw=1.5)
ax.plot([lx + 1010, lx + 1060], [ly - 3, ly - 3], color=INK, lw=1.6); ax.plot([lx + 1010, lx + 1060], [ly + 3, ly + 3], color=INK, lw=1.6)
ax.text(lx + 1070, ly, "total participation", fontsize=pt(18), va="center")
ax.text(lx + 1290, ly, "1 / N / M = cardinality", fontsize=pt(18), va="center", color="#b71c3a", fontweight="bold")

ax.text(W / 2, H - 50, "RaktaSetu — E-R diagram (simplified, Chen notation)", ha="center", va="center", fontsize=pt(32), fontweight="bold")
for ext in ("png", "pdf"):
    fig.savefig(os.path.join(ROOT, "docs", f"er_diagram.{ext}"), dpi=110 if ext == "png" else 100)
print("ER diagram drawn")
