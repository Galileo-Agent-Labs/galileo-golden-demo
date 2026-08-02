"""Retro-clinical EHR theme + HTML render layer.

Everything here returns plain strings (CSS or HTML fragments) so it can be
dropped into Streamlit via ``st.markdown(..., unsafe_allow_html=True)`` *and*
rendered into a standalone ``.html`` file for design iteration with no server.

Design language — "a pretty good vibe-coded EHR":
  * big calm whitespace between white panels on a warm paper background
  * dense, tabular data grids with monospaced tabular numerals and H/L flags
  * slightly retro clinical chrome — hospital teal + navy, small-caps section
    rules, squared-off status chips, hairline borders, inline SVG trend lines
"""

from __future__ import annotations

import html
from datetime import datetime

BRAND = "Evercrest Health"

# ---------------------------------------------------------------------------
# Design system (self-contained — no Streamlit selectors here so it also works
# in the standalone preview)
# ---------------------------------------------------------------------------
FONTS = (
    "@import url('https://fonts.googleapis.com/css2?"
    "family=IBM+Plex+Mono:wght@400;500;600&"
    "family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');"
)

EHR_CSS = """
:root{
  --paper:#e9ebe4; --paper2:#eef0e9;
  --panel:#ffffff; --panel-head:#f4f6f0;
  --ink:#1b262c; --ink2:#39454d; --muted:#6b7680; --faint:#96a0a6;
  --line:#d7dbd2; --line2:#e6e9e1;
  --teal:#0d6a72; --teal-d:#0a5158; --navy:#14324a; --navy2:#1d4767;
  --red:#b23b34; --red-bg:#fbeeec; --amber:#9a6a15; --amber-bg:#fbf3e2;
  --green:#2f6b46; --green-bg:#eaf3ec;
  --zebra:#f7f8f4; --accent:#0d6a72;
  --mono:'IBM Plex Mono','SFMono-Regular',Menlo,Consolas,monospace;
  --sans:'IBM Plex Sans','Helvetica Neue',Arial,sans-serif;
}
.ehr-root, .ehr-root *{ box-sizing:border-box; }
.ehr-root{
  font-family:var(--sans); color:var(--ink);
  font-size:13px; line-height:1.45; letter-spacing:.005em;
  -webkit-font-smoothing:antialiased;
}
.ehr-root .mono{ font-family:var(--mono); font-variant-numeric:tabular-nums; }

/* ---- top chrome ---- */
.ehr-topbar{
  display:flex; align-items:center; justify-content:space-between;
  background:linear-gradient(180deg,var(--navy2),var(--navy));
  color:#eaf1f4; padding:11px 20px;
  border:1px solid var(--teal-d);
  border-bottom:3px double rgba(255,255,255,.32);
  border-radius:7px 7px 0 0;
}
.ehr-brand{ display:flex; align-items:center; gap:12px; }
.ehr-cross{
  width:26px;height:26px;border-radius:5px;background:#fff;color:var(--teal);
  display:flex;align-items:center;justify-content:center;font-weight:700;
  font-size:19px;box-shadow:inset 0 0 0 2px var(--teal);
}
.ehr-brand b{ font-size:15.5px; letter-spacing:.02em; font-weight:700; }
.ehr-brand .sub{ font-size:10.5px; color:#9fc0cb; letter-spacing:.16em; text-transform:uppercase; }
.ehr-topmeta{ display:flex; align-items:center; gap:22px; font-size:11.5px; }
.ehr-topmeta .lbl{ color:#8fb2be; text-transform:uppercase; letter-spacing:.11em; font-size:9.5px; display:block; }
.ehr-topmeta .val{ color:#eef5f7; }
.ehr-topmeta .clock{ font-family:var(--mono); }
.ehr-tabs{ display:flex; gap:2px; background:var(--navy); border-left:1px solid var(--teal-d); border-right:1px solid var(--teal-d);
  padding:0 8px; }
.ehr-tab{ color:#9fc0cb; font-size:11px; letter-spacing:.09em; text-transform:uppercase; padding:7px 13px; border-bottom:2px solid transparent; }
.ehr-tab.on{ color:#fff; border-bottom-color:#4fd0d8; }

/* ---- patient banner ---- */
.ehr-banner{
  background:var(--panel); border:1px solid var(--line);
  border-left:5px solid var(--teal); border-top:none;
  padding:13px 20px; display:flex; align-items:stretch; gap:0;
  flex-wrap:wrap;
}
.ehr-banner .idblock{ min-width:250px; padding-right:22px; border-right:1px solid var(--line2); }
.ehr-banner .pname{ font-size:20px; font-weight:700; letter-spacing:.01em; line-height:1.15; }
.ehr-banner .pmeta{ color:var(--muted); font-size:12px; margin-top:2px; }
.ehr-banner .pmeta b{ color:var(--ink2); font-weight:600; }
.ehr-idrow{ margin-top:6px; display:flex; gap:8px; flex-wrap:wrap; }
.ehr-fields{ display:flex; gap:0; flex-wrap:wrap; padding-left:22px; flex:1; }
.ehr-field{ padding:0 20px 0 0; margin-right:20px; border-right:1px solid var(--line2); min-width:96px; }
.ehr-field:last-child{ border-right:none; }
.ehr-field .k{ font-size:9.5px; text-transform:uppercase; letter-spacing:.11em; color:var(--faint); }
.ehr-field .v{ font-size:12.5px; color:var(--ink); margin-top:2px; }
.ehr-field .v.mono{ font-size:12px; }

/* chips */
.chip{ display:inline-flex; align-items:center; gap:5px; font-size:10.5px; font-weight:600;
  padding:2px 7px; border-radius:3px; letter-spacing:.03em; border:1px solid transparent; white-space:nowrap; }
.chip.tiny{ font-size:9.5px; padding:1px 6px; }
.chip.teal{ background:#e5f1f1; color:var(--teal-d); border-color:#c5e0e0; }
.chip.navy{ background:#e7edf3; color:var(--navy); border-color:#cdd9e4; }
.chip.red{ background:var(--red-bg); color:var(--red); border-color:#eccbc7; }
.chip.amber{ background:var(--amber-bg); color:var(--amber); border-color:#ecdcb6; }
.chip.green{ background:var(--green-bg); color:var(--green); border-color:#c9e0cf; }
.chip.grey{ background:#eef0ec; color:var(--ink2); border-color:var(--line); }
.chip .dot{ width:6px;height:6px;border-radius:50%;background:currentColor; }

/* ---- stat snapshot ---- */
.ehr-snap{ display:grid; grid-template-columns:repeat(6,1fr); gap:1px; background:var(--line);
  border:1px solid var(--line); border-top:none; }
.ehr-stat{ background:var(--panel); padding:9px 14px 10px; }
.ehr-stat .k{ font-size:9.5px; text-transform:uppercase; letter-spacing:.1em; color:var(--faint); }
.ehr-stat .v{ font-family:var(--mono); font-size:20px; font-weight:600; color:var(--ink); line-height:1.05; margin-top:3px; }
.ehr-stat .v small{ font-size:11px; color:var(--muted); font-weight:500; }
.ehr-stat .u{ font-size:10px; color:var(--muted); }
.ehr-stat.flag .v{ color:var(--red); }

/* ---- grid + panels ---- */
.ehr-grid{ display:grid; grid-template-columns:minmax(300px,1fr) minmax(0,2.25fr); gap:16px; margin-top:16px; }
.ehr-col{ display:flex; flex-direction:column; gap:16px; min-width:0; }
.panel{ background:var(--panel); border:1px solid var(--line); border-radius:5px; overflow:hidden; }
.panel > .head{
  display:flex; align-items:center; justify-content:space-between;
  background:var(--panel-head); border-bottom:1px solid var(--line);
  padding:7px 13px;
}
.panel > .head .title{ font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.1em; color:var(--teal-d); }
.panel > .head .meta{ font-size:10.5px; color:var(--muted); font-family:var(--mono); }
.panel > .head .title .n{ color:var(--faint); margin-left:6px; font-weight:600; }
.panel > .body{ padding:11px 13px; }
.panel > .body.flush{ padding:0; }

/* tables */
table.grid{ width:100%; border-collapse:collapse; font-size:12px; }
table.grid th{ text-align:left; font-size:9.5px; text-transform:uppercase; letter-spacing:.09em; color:var(--faint);
  font-weight:600; padding:7px 10px; border-bottom:1px solid var(--line); background:#fbfcfa; }
table.grid td{ padding:6px 10px; border-bottom:1px solid var(--line2); vertical-align:middle; }
table.grid tr:nth-child(even) td{ background:var(--zebra); }
table.grid tr:last-child td{ border-bottom:none; }
table.grid td.num{ font-family:var(--mono); font-variant-numeric:tabular-nums; text-align:right; white-space:nowrap; }
table.grid td.c{ text-align:center; }
table.grid .drug{ font-weight:600; color:var(--ink); }
table.grid .sub{ color:var(--muted); font-size:11px; }
.flag{ font-family:var(--mono); font-weight:600; font-size:11px; margin-left:5px; }
.flag.H{ color:var(--red); } .flag.L{ color:var(--navy2); }
td.hi{ color:var(--red); } td.lo{ color:var(--navy2); }

/* problem list / list rows */
.lrow{ display:flex; justify-content:space-between; align-items:baseline; gap:10px;
  padding:7px 0; border-bottom:1px solid var(--line2); }
.lrow:last-child{ border-bottom:none; }
.lrow .main{ color:var(--ink); font-weight:500; }
.lrow .code{ font-family:var(--mono); color:var(--faint); font-size:10.5px; margin-left:6px; }
.lrow .side{ color:var(--muted); font-size:11px; text-align:right; white-space:nowrap; }

/* key/value */
.kv{ display:grid; grid-template-columns:auto 1fr; gap:5px 14px; font-size:12px; }
.kv .k{ color:var(--muted); }
.kv .v{ color:var(--ink); text-align:right; }
.kv .v.mono{ font-family:var(--mono); }

/* allergy panel */
.panel.alert{ border-color:#e6c7c2; }
.panel.alert > .head{ background:var(--red-bg); border-bottom-color:#eccbc7; }
.panel.alert > .head .title{ color:var(--red); }
.alrow{ display:flex; justify-content:space-between; align-items:center; padding:7px 0; border-bottom:1px solid var(--line2); }
.alrow:last-child{ border-bottom:none; }
.alrow .a{ font-weight:600; color:var(--red); }
.alrow .r{ color:var(--muted); font-size:11px; }
.nkda{ color:var(--green); font-weight:600; font-size:12px; }

/* encounters timeline */
.tl{ position:relative; }
.tlrow{ display:grid; grid-template-columns:88px 1fr; gap:12px; padding:8px 0; border-bottom:1px solid var(--line2); }
.tlrow:last-child{ border-bottom:none; }
.tlrow .when{ font-family:var(--mono); font-size:10.5px; color:var(--muted); padding-top:1px; }
.tlrow .what .ty{ font-weight:600; color:var(--teal-d); font-size:11px; text-transform:uppercase; letter-spacing:.05em; }
.tlrow .what .dt{ color:var(--ink2); margin-top:1px; }

/* vitals flowsheet */
table.flow{ width:100%; border-collapse:collapse; font-size:11.5px; }
table.flow th, table.flow td{ padding:5px 8px; border-bottom:1px solid var(--line2); white-space:nowrap; }
table.flow thead th{ font-size:9.5px; text-transform:uppercase; letter-spacing:.06em; color:var(--faint);
  background:#fbfcfa; text-align:right; font-family:var(--mono); }
table.flow thead th.lbl{ text-align:left; letter-spacing:.09em; }
table.flow td.lbl{ text-align:left; color:var(--muted); font-size:10.5px; text-transform:uppercase; letter-spacing:.05em; }
table.flow td.val{ text-align:right; font-family:var(--mono); font-variant-numeric:tabular-nums; color:var(--ink); }
table.flow td.val.recent{ font-weight:600; }
table.flow td.trend{ text-align:center; width:88px; }
table.flow tr:last-child td{ border-bottom:none; }

.spark{ display:inline-block; vertical-align:middle; }
.foot{ padding:7px 13px; border-top:1px solid var(--line2); background:#fbfcfa; color:var(--faint);
  font-size:10px; font-family:var(--mono); letter-spacing:.03em; display:flex; justify-content:space-between; }
"""


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def sparkline(values, w=80, h=22, stroke="#0d6a72", pad=3, dot=True) -> str:
    """Inline SVG trend line for a numeric series (oldest -> newest)."""
    vals = [float(v) for v in values if v is not None]
    if len(vals) < 2:
        return '<span style="color:var(--faint);font-size:10px">—</span>'
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    n = len(vals)
    innerw, innerh = w - pad * 2, h - pad * 2
    pts = []
    for i, v in enumerate(vals):
        x = pad + (innerw * i / (n - 1))
        y = pad + innerh - (innerh * (v - lo) / rng)
        pts.append((x, y))
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    lx, ly = pts[-1]
    end_dot = (
        f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="2.1" fill="{stroke}"/>' if dot else ""
    )
    return (
        f'<svg class="spark" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
        f'<polyline points="{poly}" fill="none" stroke="{stroke}" '
        f'stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round"/>'
        f"{end_dot}</svg>"
    )


def _sev_chip(sev: str) -> str:
    cls = {"High": "red", "Moderate": "amber", "Low": "grey"}.get(sev, "grey")
    return f'<span class="chip tiny {cls}">{_e(sev)}</span>'


# ---------------------------------------------------------------------------
# chrome
# ---------------------------------------------------------------------------
def render_topbar(practitioner: str, now: datetime | None = None, active_tab="Chart") -> str:
    now = now or datetime.now()
    clock = now.strftime("%a %b %d, %Y · %H:%M")
    tabs = ["Chart Review", "Orders", "Results", "Notes", "Meds", "Flowsheets"]
    tabhtml = "".join(
        f'<div class="ehr-tab{" on" if t.startswith(active_tab) else ""}">{_e(t)}</div>'
        for t in tabs
    )
    return f"""
<div class="ehr-topbar">
  <div class="ehr-brand">
    <div class="ehr-cross">✚</div>
    <div><b>{_e(BRAND)}</b><div class="sub">Practitioner Workstation · EHR</div></div>
  </div>
  <div class="ehr-topmeta">
    <div><span class="lbl">Provider</span><span class="val">{_e(practitioner)}</span></div>
    <div><span class="lbl">Encounter</span><span class="val mono">OUT-4471</span></div>
    <div><span class="lbl">Session</span><span class="val clock">{_e(clock)}</span></div>
  </div>
</div>
<div class="ehr-tabs">{tabhtml}</div>
"""


def render_banner(c: dict) -> str:
    allergy_chip = (
        '<span class="chip red"><span class="dot"></span>'
        + f'{len(c["allergies"])} ALLERGY' + ("IES" if len(c["allergies"]) != 1 else "")
        + "</span>"
        if c.get("allergies")
        else '<span class="chip green">NKDA</span>'
    )
    code = c.get("code_status", "Full Code")
    code_chip = f'<span class="chip {"red" if code!="Full Code" else "grey"}">{_e(code)}</span>'
    status_chip = (
        '<span class="chip navy">' + _e(c.get("status_word", "")) + "</span>"
    )
    return f"""
<div class="ehr-banner">
  <div class="idblock">
    <div class="pname">{_e(c['name'])}</div>
    <div class="pmeta"><b>{_e(c['age'])} yr</b> · {_e(c['sex'])} · DOB {_e(c['dob'])}</div>
    <div class="ehr-idrow">
      {allergy_chip}{status_chip}{code_chip}
    </div>
  </div>
  <div class="ehr-fields">
    <div class="ehr-field"><div class="k">MRN</div><div class="v mono">{_e(c['mrn'])}</div></div>
    <div class="ehr-field"><div class="k">Location</div><div class="v">{_e(c['location'])}</div></div>
    <div class="ehr-field"><div class="k">PCP</div><div class="v">{_e(c['care_team'][0]['name'])}</div></div>
    <div class="ehr-field"><div class="k">Coverage</div><div class="v">{_e(c['insurance']['payer'])}</div></div>
    <div class="ehr-field"><div class="k">Language</div><div class="v">{_e(c['language'])}</div></div>
    <div class="ehr-field"><div class="k">Contact</div><div class="v mono">{_e(c['phone'])}</div></div>
  </div>
</div>
"""


def render_snapshot(c: dict) -> str:
    v = c["vitals"][0]
    sys = v["sys"]
    bp_flag = " flag" if sys >= 140 else ""
    spo2_flag = " flag" if v["SpO2"] < 94 else ""
    tiles = [
        ("Blood Pressure", f'{v["BP"]}', "mmHg", bp_flag),
        ("Pulse", f'{v["HR"]}', "bpm", ""),
        ("Temp", f'{v["Temp"]}', "°F", ""),
        ("SpO₂", f'{v["SpO2"]}', "%", spo2_flag),
        ("Weight", f'{v["Wt"]:.0f}', "lb", ""),
        ("BMI", f'{v["BMI"]}', "kg/m²", " flag" if v["BMI"] >= 30 else ""),
    ]
    cells = "".join(
        f'<div class="ehr-stat{flag}"><div class="k">{_e(k)}</div>'
        f'<div class="v">{_e(val)}</div><div class="u">{_e(u)}</div></div>'
        for k, val, u, flag in tiles
    )
    return f'<div class="ehr-snap">{cells}</div>'


# ---------------------------------------------------------------------------
# panels
# ---------------------------------------------------------------------------
def _panel(title, body, n=None, meta="", alert=False, foot="") -> str:
    ncount = f'<span class="n">{n}</span>' if n is not None else ""
    metahtml = f'<div class="meta">{meta}</div>' if meta else ""
    foothtml = f'<div class="foot">{foot}</div>' if foot else ""
    cls = "panel alert" if alert else "panel"
    return f"""<div class="{cls}">
  <div class="head"><div class="title">{_e(title)}{ncount}</div>{metahtml}</div>
  <div class="body">{body}</div>{foothtml}</div>"""


def panel_problems(c) -> str:
    rows = []
    for p in c["problems"]:
        rows.append(
            f'<div class="lrow"><div class="main">{_e(p["problem"])}'
            f'<span class="code">{_e(p["code"])}</span></div>'
            f'<div class="side">{_e(p["specialty"])} · since {_e(p["since"])}</div></div>'
        )
    return _panel("Problem List", "".join(rows), n=len(c["problems"]))


def panel_allergies(c) -> str:
    al = c["allergies"]
    if not al:
        body = '<div class="nkda">✓ No Known Drug Allergies</div>'
        return _panel("Allergies", body, alert=False)
    rows = []
    for a in al:
        rows.append(
            f'<div class="alrow"><div><div class="a">{_e(a["allergen"])}</div>'
            f'<div class="r">{_e(a["reaction"])}</div></div>{_sev_chip(a["severity"])}</div>'
        )
    return _panel("Allergies & Intolerances", "".join(rows), n=len(al), alert=True)


def panel_care_team(c) -> str:
    rows = []
    for t in c["care_team"]:
        rows.append(
            f'<div class="lrow"><div class="main">{_e(t["name"])}</div>'
            f'<div class="side">{_e(t["role"])}</div></div>'
        )
    return _panel("Care Team", "".join(rows))


def panel_immunizations(c) -> str:
    rows = []
    for im in c["immunizations"]:
        rows.append(
            f'<div class="lrow"><div class="main">{_e(im["vaccine"])}</div>'
            f'<div class="side mono">{_e(im["date"])}</div></div>'
        )
    return _panel("Immunizations", "".join(rows), n=len(c["immunizations"]))


def panel_coverage(c) -> str:
    ins = c["insurance"]
    body = f"""<div class="kv">
      <div class="k">Payer</div><div class="v">{_e(ins['payer'])}</div>
      <div class="k">Plan</div><div class="v">{_e(ins['plan'])}</div>
      <div class="k">Member ID</div><div class="v mono">{_e(ins['member'])}</div>
      <div class="k">Group</div><div class="v mono">{_e(ins['group'])}</div>
      <div class="k">Guarantor</div><div class="v">Self</div>
    </div>"""
    return _panel("Coverage", body)


def panel_medications(c) -> str:
    rows = []
    for m in c["medications"]:
        due = m["refills"] <= 0
        refill_cell = (
            '<span class="chip tiny red">REFILL DUE</span>'
            if due
            else f'<span class="mono">{m["refills"]}</span>'
        )
        rows.append(
            f"<tr><td><span class='drug'>{_e(m['medication'])}</span><br>"
            f"<span class='sub'>{_e(m['sig'])}</span></td>"
            f"<td class='c'><span class='chip tiny grey'>{_e(m['route'])}</span></td>"
            f"<td class='num'>{_e(m['start'])}</td>"
            f"<td class='c'>{refill_cell}</td></tr>"
        )
    body = (
        "<table class='grid'><thead><tr>"
        "<th>Medication &amp; Sig</th><th class='c'>Route</th>"
        "<th style='text-align:right'>Started</th><th class='c'>Refills</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )
    return _panel(
        "Active Medications",
        body,
        n=len(c["medications"]),
        meta="reconciled today",
    )


def panel_vitals(c) -> str:
    vit = c["vitals"]  # newest-first
    dates = [v["date"].strftime("%m/%d") for v in vit]
    head = "<th class='lbl'>Vital</th>" + "".join(
        f"<th>{d}</th>" for d in dates
    ) + "<th class='lbl' style='text-align:center'>Trend</th>"

    def row(label, key, fmt="{}", spark_key=None, spark_stroke="#0d6a72"):
        cells = []
        for i, v in enumerate(vit):
            val = fmt.format(v[key])
            recent = " recent" if i == 0 else ""
            cells.append(f"<td class='val{recent}'>{_e(val)}</td>")
        series = [v[spark_key or key] for v in reversed(vit)]
        try:
            sp = sparkline(series, stroke=spark_stroke)
        except Exception:
            sp = "—"
        return (
            f"<tr><td class='lbl'>{_e(label)}</td>{''.join(cells)}"
            f"<td class='trend'>{sp}</td></tr>"
        )

    body = (
        "<table class='flow'><thead><tr>" + head + "</tr></thead><tbody>"
        + row("BP mmHg", "BP", spark_key="sys", spark_stroke="#b23b34")
        + row("Pulse", "HR")
        + row("Resp", "RR")
        + row("Temp °F", "Temp", fmt="{:.1f}")
        + row("SpO₂ %", "SpO2")
        + row("Weight lb", "Wt", fmt="{:.1f}", spark_stroke="#14324a")
        + row("BMI", "BMI", fmt="{:.1f}")
        + row("Pain 0–10", "Pain")
        + "</tbody></table>"
    )
    return _panel(
        "Vitals Flowsheet",
        body,
        meta=f"{len(vit)} encounters",
        foot="◀ newest &nbsp;·&nbsp; trend oldest→newest ▶",
    )


def panel_labs(c) -> str:
    trends = c.get("trends", {})
    blocks = []
    for pnl in c["labs"]:
        rows = []
        for r in pnl["rows"]:
            flag = r["flag"]
            fcls = {"H": "hi", "L": "lo"}.get(flag, "")
            fhtml = f'<span class="flag {flag}">{flag}</span>' if flag else ""
            series = trends.get(r["analyte"])
            spark = sparkline(series, w=70, h=18, stroke="#0d6a72") if series else ""
            rows.append(
                f"<tr><td>{_e(r['analyte'])}</td>"
                f"<td class='num {fcls}'>{_e(r['value'])} {fhtml}</td>"
                f"<td class='num sub'>{_e(r['unit'])}</td>"
                f"<td class='num sub'>{_e(r['ref'])}</td>"
                f"<td class='c'>{spark}</td></tr>"
            )
        date = pnl["date"].strftime("%b %d, %Y") if hasattr(pnl["date"], "strftime") else str(pnl["date"])
        blocks.append(
            f"<div style='padding:9px 13px 2px;font-size:10px;text-transform:uppercase;"
            f"letter-spacing:.09em;color:var(--teal-d);font-weight:600;border-top:1px solid var(--line2)'>"
            f"{_e(pnl['title'])} <span class='mono' style='color:var(--faint);float:right'>{_e(date)}</span></div>"
            "<table class='grid'><thead><tr><th>Analyte</th>"
            "<th style='text-align:right'>Result</th><th style='text-align:right'>Units</th>"
            "<th style='text-align:right'>Reference</th><th class='c'>Trend</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table>"
        )
    # first block has an unwanted top border; strip once
    body = "".join(blocks).replace("border-top:1px solid var(--line2)", "border-top:none", 1)
    return _panel("Results — Laboratory", body, meta="most recent", )


def panel_encounters(c) -> str:
    rows = []
    for ev in c["encounters"][:8]:
        rows.append(
            f"<div class='tlrow'><div class='when'>{_e(ev['date'])}</div>"
            f"<div class='what'><div class='ty'>{_e(ev['type'])}</div>"
            f"<div class='dt'>{_e(ev['detail'])}</div></div></div>"
        )
    if not rows:
        rows = ["<div class='tlrow'><div class='when'>—</div><div class='what'><div class='dt'>No recorded history.</div></div></div>"]
    return _panel("Encounters & History", f"<div class='tl'>{''.join(rows)}</div>", n=len(c["encounters"]))


def render_chart(c: dict) -> str:
    left = "".join([
        panel_problems(c),
        panel_allergies(c),
        panel_care_team(c),
        panel_immunizations(c),
        panel_coverage(c),
    ])
    right = "".join([
        panel_vitals(c),
        panel_medications(c),
        panel_labs(c),
        panel_encounters(c),
    ])
    return (
        render_snapshot(c)
        + f'<div class="ehr-grid"><div class="ehr-col">{left}</div>'
        f'<div class="ehr-col">{right}</div></div>'
    )


def render_page(c: dict, practitioner="Dr. A. Morgan", now: datetime | None = None) -> str:
    """Topbar + banner + snapshot + chart, wrapped in .ehr-root (for preview/app)."""
    return (
        '<div class="ehr-root">'
        + render_topbar(practitioner, now)
        + render_banner(c)
        + render_chart(c)
        + "</div>"
    )


# ---------------------------------------------------------------------------
# Streamlit-specific overrides (only injected when running inside the app; kept
# out of EHR_CSS so the standalone preview stays clean)
# ---------------------------------------------------------------------------
STREAMLIT_CSS = """
.stApp{ background:var(--paper); }
.stApp, .stApp p, .stApp label, .stApp span, .stApp div{ font-family:var(--sans); }
[data-testid="stMainBlockContainer"], .block-container{
  max-width:1340px !important; padding-top:1.1rem !important; padding-bottom:3rem !important;
}
[data-testid="stHeader"]{ background:transparent; }
[data-testid="stToolbar"], #MainMenu, [data-testid="stDecoration"], footer{ display:none !important; }
[data-testid="stMain"] [data-testid="stVerticalBlock"]{ gap:.55rem; }

/* Keep the native form controls light on the clinical chart (belt-and-braces
   alongside the light theme in .streamlit/config.toml). */
[data-testid="stSelectbox"] > div > div{ background:#fff !important; border-color:var(--line) !important; }
[data-testid="stSelectbox"] > div > div:hover{ border-color:var(--teal) !important; }
[data-testid="stSelectbox"] input, [data-testid="stSelectbox"] div{ color:var(--ink) !important; -webkit-text-fill-color:var(--ink) !important; }
[data-testid="stSelectbox"] svg{ fill:var(--muted) !important; }
ul[role="listbox"], [data-baseweb="popover"] ul{ background:#fff !important; }
[role="option"]{ color:var(--ink) !important; }
[role="option"]:hover{ background:var(--paper2) !important; }
.stTextInput input{ background:#fff !important; color:var(--ink) !important; border-color:var(--line) !important; font-size:13px; }

/* control strip: patient picker + assistant button */
.stButton > button{
  border-radius:4px; border:1px solid var(--teal); background:var(--teal); color:#fff;
  font-weight:600; font-size:12.5px; letter-spacing:.02em; padding:.42rem .8rem;
  box-shadow:none; transition:background .12s;
}
.stButton > button:hover{ background:var(--teal-d); border-color:var(--teal-d); color:#fff; }
.stButton > button:focus:not(:active){ color:#fff; border-color:var(--teal-d); }
[data-testid="stSidebar"] .stButton > button{ font-size:12px; }

.stSelectbox label, .stTextInput label{
  font-size:9.5px !important; text-transform:uppercase; letter-spacing:.12em;
  color:var(--muted) !important; font-weight:600;
}
div[data-baseweb="select"] > div{
  border-radius:4px; border-color:var(--line); background:#fff;
  font-family:var(--mono); font-size:13px; min-height:40px;
}
div[data-baseweb="select"] > div:hover{ border-color:var(--teal); }

/* copilot dialog dressed as a clinical assistant panel */
div[role="dialog"]{ border-radius:9px; border-top:4px solid var(--teal); }
div[role="dialog"] [data-testid="stMarkdownContainer"] p{ font-size:13px; }

/* tighten the markdown-rendered EHR blocks against Streamlit's default gaps */
[data-testid="stMarkdownContainer"] .ehr-root{ margin-top:0; }
"""


def full_style() -> str:
    """Standalone preview style (no Streamlit DOM overrides)."""
    return f"<style>{FONTS}\n{EHR_CSS}</style>"


def app_style() -> str:
    """In-app style: design system + Streamlit overrides."""
    return f"<style>{FONTS}\n{EHR_CSS}\n{STREAMLIT_CSS}</style>"
