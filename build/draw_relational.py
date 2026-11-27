#!/usr/bin/env python3
"""Draws the relational schema (docs/relational_schema.png / .pdf) from build/schema_info.json,
in the style of the sample: one row of cells per table, PK underlined, arrow from each FK to the key it references."""
import json, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from PIL import ImageFont

ROOT = os.path.join(os.path.dirname(__file__), "..")
info = json.load(open(os.path.join(ROOT, "build", "schema_info.json")))
T = {t["name"]: t for t in info["tables"]}
ORDER = [t["name"] for t in info["tables"]]

FONT_PX = 14
font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", FONT_PX)
bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", FONT_PX + 1)
tw = lambda s, f=font: f.getlength(s)

PAD, CELL_H, MAX_ROW_W = 8, 27, 800
LABEL_W = max(tw(n.upper(), bold) for n in ORDER) + 18
LANE0, LANE_GAP = 14, 7
N_EDGES = sum(len(T[n]["fks"]) * 1 + (0) for n in ORDER)
# one edge per FK column group (composite FKs do not exist here)
edges = []
for n in ORDER:
    for fk in T[n]["fks"]:
        edges.append(dict(child=n, col=fk["cols"][0], parent=fk["ref"], pcol=fk["refcols"][0]))
LEFT = LANE0 + LANE_GAP * (len(edges) + 1) + 10      # x where table labels end
X0 = LEFT + LABEL_W                                   # x where cells start

# ---- layout of cells ----
layout = {}
for n in ORDER:
    cols = [c["name"] for c in T[n]["columns"]]
    rows, cur, w = [], [], 0
    for c in cols:
        cw = tw(c) + 2 * PAD
        if cur and w + cw > MAX_ROW_W: rows.append(cur); cur, w = [], 0
        cur.append((c, cw)); w += cw
    rows.append(cur)
    # second and later rows are indented by the width of the first cell (like the sample)
    layout[n] = rows

# ---- vertical positions: gaps sized for the horizontal channel segments ----
seg_count = {n: 0 for n in ORDER}         # segments in gap above table n
seg_count["__bottom__"] = 0
def gap_key_for_child(e):
    rows = layout[e["child"]]
    for ri, r in enumerate(rows):
        if any(c == e["col"] for c, _ in r): break
    if ri == 0: return e["child"]
    i = ORDER.index(e["child"])
    return ORDER[i + 1] if i + 1 < len(ORDER) else "__bottom__"
for e in edges:
    e["child_gap"] = gap_key_for_child(e)
    seg_count[e["child_gap"]] += 1
    seg_count[e["parent"]] += 1
SEG_H = 7
y = 70; ypos = {}; gap_top = {}
for n in ORDER:
    gap_h = 20 + SEG_H * seg_count[n]
    gap_top[n] = y; y += gap_h
    ypos[n] = y                      # top of table block
    y += CELL_H * len(layout[n])
gap_top["__bottom__"] = y; y += 24 + SEG_H * seg_count["__bottom__"] + 10
H = y; W = X0 + MAX_ROW_W + 40

# ---- cell x positions ----
cellx = {}
for n in ORDER:
    for ri, r in enumerate(layout[n]):
        x = X0 + (0 if ri == 0 else 0)
        for c, cw in r:
            cellx[(n, c)] = (x, cw, ri); x += cw

# ---- assign lanes and channel y offsets ----
slot = {k: 0 for k in seg_count}
order = sorted(range(len(edges)), key=lambda i: (ORDER.index(edges[i]["child"]), edges[i]["col"]))
for lane, i in enumerate(order):
    edges[i]["lane_x"] = LANE0 + LANE_GAP * lane
def next_y(gkey):
    k = slot[gkey]; slot[gkey] += 1
    return gap_top[gkey] + 12 + SEG_H * k

fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off")
pt = lambda px: px * 0.72

ax.text(W / 2, 30, "RaktaSetu — Relational Schema", ha="center", va="center", fontsize=pt(28), fontweight="bold", family="DejaVu Sans")

CELL_FILL, EDGE = "#ffffff", "#1a1a1a"
for n in ORDER:
    top = ypos[n]
    ax.text(X0 - 12, top + CELL_H / 2, n.upper(), ha="right", va="center", fontsize=pt(FONT_PX + 1), fontweight="bold", family="DejaVu Sans")
    pk = set(T[n]["pk"])
    for ri, r in enumerate(layout[n]):
        for c, cw in r:
            x, _, _ = cellx[(n, c)]
            yy = top + ri * CELL_H
            ax.add_patch(Rectangle((x, yy), cw, CELL_H, fill=True, fc=CELL_FILL, ec=EDGE, lw=1.0))
            ax.text(x + cw / 2, yy + CELL_H / 2 + 0.5, c, ha="center", va="center", fontsize=pt(FONT_PX), family="DejaVu Sans")
            if c in pk:
                w = tw(c); ax.plot([x + cw / 2 - w / 2, x + cw / 2 + w / 2], [yy + CELL_H / 2 + 9, yy + CELL_H / 2 + 9], color="black", lw=1.0)

# ---- arrows ----
from collections import defaultdict
arrivals = defaultdict(list)
for i in order: arrivals[(edges[i]["parent"], edges[i]["pcol"])].append(i)
palette = ["#b71c3a", "#1f4e79", "#2e7d32", "#6a1b9a", "#e65100", "#00838f", "#5d4037", "#455a64"]
for k, i in enumerate(order):
    e = edges[i]; col = palette[k % len(palette)]
    cx, cw, cri = cellx[(e["child"], e["col"])]
    px, pw, pri = cellx[(e["parent"], e["pcol"])]
    x_fk = cx + cw / 2
    lst = arrivals[(e["parent"], e["pcol"])]; n_arr = len(lst); j = lst.index(i)
    step = min(9, (pw - 16) / max(n_arr - 1, 1)) if n_arr > 1 else 0
    x_pk = px + pw / 2 + (j - (n_arr - 1) / 2) * step
    child_top = ypos[e["child"]]
    start_y = child_top if cri == 0 else child_top + CELL_H * len(layout[e["child"]])
    ch_y = next_y(e["child_gap"])
    p_y = next_y(e["parent"])
    pk_y = ypos[e["parent"]]
    lx = e["lane_x"]
    path_x = [x_fk, x_fk, lx, lx, x_pk, x_pk]
    path_y = [start_y, ch_y, ch_y, p_y, p_y, pk_y]
    ax.plot(path_x, path_y, color=col, lw=1.1, solid_joinstyle="miter", zorder=5)
    ax.plot([x_fk], [start_y], marker="o", ms=4.2, color=col, zorder=6)
    ax.annotate("", xy=(x_pk, pk_y), xytext=(x_pk, pk_y - 7), arrowprops=dict(arrowstyle="-|>", color=col, lw=1.1, mutation_scale=9), zorder=6)

for ext in ("png", "pdf"):
    fig.savefig(os.path.join(ROOT, "docs", f"relational_schema.{ext}"), dpi=170 if ext == "png" else 100)
print("relational schema drawn", int(W), "x", int(H), "px;", len(edges), "arrows")
