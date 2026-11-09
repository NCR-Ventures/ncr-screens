#!/usr/bin/env python3
"""
build_book.py — turn an OpenTable "Pre-shift Digest" email into a 1920x1080
"Today's Reso's" slide for The Daily.

usage:
  build_book.py --store lolas --email digest.html --received 2026-11-09T15:03:44Z --out lolas-book.html
  build_book.py --store jojos --email jojos.html --fuoco-email fuoco.html --received ... --out jojos-book.html

--store      lolas | jojos | fuoco
--email      saved HTML body of the OpenTable Pre-shift Digest
--fuoco-email  (jojos only) Après Fuoco / Bar Fuoco digest for split-screen dates
--received   ISO time the email arrived (UTC ok) -> "updated h:mm am"
--force-split  render the JoJo's/Après split regardless of date (for testing)

Rules baked in (Tim, 11.9.26):
  * guest names on the board are first name + last initial only. never phone, never spend.
  * split screen at JoJo's on Après Fuoco dates (APRES_DATES below).
  * shift label: "Lunch Book" for a Lunch digest, "Dinner Reso's" for Dinner.
"""
import argparse, base64, datetime as dt, html, json, os, re, sys
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ET = ZoneInfo("America/New_York")

APRES_DATES = {  # JoJo's screen splits with Après Fuoco on these dates
    "2026-11-25", "2026-11-27", "2026-11-28",
    "2026-12-04", "2026-12-05", "2026-12-11", "2026-12-12",
    "2026-12-18", "2026-12-19",
}

# ----------------------------------------------------------------- parsing

def _txt(s):
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()

def parse_digest(raw):
    d = {"metrics": {}, "notes": [], "slots": [], "reservations": []}
    m = re.search(r'class="[^"]*title-date[^"]*"[^>]*>(.*?)</div>', raw, re.S)
    d["date_text"] = _txt(m.group(1)) if m else ""
    m = re.search(r'class="title-name"[^>]*>(.*?)</div>', raw, re.S)
    d["title"] = _txt(m.group(1)) if m else "Pre-shift Digest"
    m = re.search(r'class="[^"]*title-restaurant[^"]*"[^>]*>(.*?)</div>', raw, re.S)
    d["restaurant"] = _txt(m.group(1)) if m else ""
    for mm in re.finditer(r'class="metric-block"[^>]*>(.*?)</div>', raw, re.S):
        t = _txt(mm.group(1))
        k = re.match(r"(.*?)(\d+)\s*$", t)
        if k:
            d["metrics"][k.group(1).strip().lower()] = int(k.group(2))
    m = re.search(r'shift-overview/(\d{4}-\d{2}-\d{2})/(\w+)', raw)
    if m:
        d["date"], d["shift"] = m.group(1), m.group(2)
    else:
        d["date"], d["shift"] = "", ("lunch" if "lunch" in d["title"].lower() else "dinner")
    # general notes
    for nm in re.finditer(r'class="title-shift-notes"[^>]*>(.*?)</div>.*?class="shift-name-shift-notes"[^>]*>(.*?)</div>.*?class="description-shift-notes"[^>]*>(.*?)</div>', raw, re.S):
        d["notes"].append({"title": _txt(nm.group(1)), "when": _txt(nm.group(2)), "text": _txt(nm.group(3))})
    # hour slots + reservations (walk in document order)
    pos_slots = [(m.start(), "slot", m) for m in re.finditer(
        r'class="shift-title disabled_smart_link"[^>]*>(.*?)</div>\s*<div class="shift-title"[^>]*>(.*?)</div>', raw, re.S)]
    pos_res = [(m.start(), "res", m) for m in re.finditer(
        r'<div class="content-section content-reservation[^"]*"[^>]*>(.*?)(?=<div class="content-section content-reservation|<div class="content-background|</td>)', raw, re.S)]
    cur = None
    for pos, kind, m in sorted(pos_slots + pos_res, key=lambda x: x[0]):
        if kind == "slot":
            cur = {"range": _txt(m.group(1)), "summary": _txt(m.group(2)), "reservations": 0, "covers": 0}
            k = re.search(r"(\d+)\s+Reservations?\s*•\s*(\d+)\s+covers", cur["summary"])
            if k:
                cur["reservations"], cur["covers"] = int(k.group(1)), int(k.group(2))
            d["slots"].append(cur)
        else:
            blk = m.group(1)
            r = {"tags": [], "requests": "", "visit_notes": "", "most_ordered": "", "details": ""}
            k = re.search(r'class="url-link guest-name"[^>]*>(.*?)</a>', blk, re.S)
            r["name"] = _txt(k.group(1)) if k else ""
            k = re.search(r'class="content-text-weight content-profile"[^>]*>\s*(\d{1,2}:\d{2}\s*[AP]M)\s+(\d+)(?:\s+([^\s<]+))?', blk)
            if k:
                r["time"], r["party"], r["table"] = k.group(1).replace(" ", ""), int(k.group(2)), (k.group(3) or "")
            else:
                r["time"], r["party"], r["table"] = "", 0, ""
            for line in re.findall(r'class="content-text"[^>]*>(.*?)</div>', blk, re.S):
                t = _txt(line)
                low = t.lower()
                if low.startswith("tags:"):
                    r["tags"] = [x.strip() for x in re.split(r"\s{2,}|,", t[5:]) if x.strip()]
                    if len(r["tags"]) == 1 and "  " not in t[5:]:
                        r["tags"] = [t[5:].strip()]
                elif low.startswith("guest requests:"):
                    r["requests"] = t.split(":", 1)[1].strip()
                elif low.startswith("visit notes:"):
                    r["visit_notes"] = t.split(":", 1)[1].strip()
                elif low.startswith("most ordered items:"):
                    r["most_ordered"] = t.split(":", 1)[1].strip()
                elif low.startswith("guest details:"):
                    r["details"] = t.split(":", 1)[1].strip()
            r["slot"] = cur["range"] if cur else ""
            d["reservations"].append(r)
            if cur is not None:
                cur.setdefault("items", []).append(r)
    d["covers"] = d["metrics"].get("total covers", sum(r["party"] for r in d["reservations"]))
    d["reservation_count"] = d["metrics"].get("total reservations", len(d["reservations"]))
    d["parties5"] = d["metrics"].get("parties of 5+", sum(1 for r in d["reservations"] if r["party"] >= 5))
    d["vip"] = d["metrics"].get("special relationships", sum(1 for r in d["reservations"] if any("alert" in t.lower() or "vip" in t.lower() for t in r["tags"])))
    d["celebrations"] = sum(1 for r in d["reservations"] if any(t.lower() in ("birthday", "anniversary", "celebration", "special occasion") for t in r["tags"]))
    d["first_timers"] = sum(1 for r in d["reservations"] if r["details"] and "visits last year" not in r["details"].lower() and "last visit" not in r["details"].lower())
    return d

# ----------------------------------------------------------------- helpers

def short_name(n):
    parts = [p for p in n.strip().split() if p]
    if not parts:
        return "Guest"
    first = parts[0].capitalize() if parts[0].islower() else parts[0]
    if len(parts) == 1:
        return first
    return f"{first} {parts[-1][0].upper()}."

def b64(path):
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()

def updated_label(received_iso):
    if not received_iso:
        return ""
    t = dt.datetime.fromisoformat(received_iso.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    t = t.astimezone(ET)
    return t.strftime("%-I:%M %p").lower()

def pretty_date(iso):
    if not iso:
        return ""
    d = dt.date.fromisoformat(iso)
    return d.strftime("%A, %B %-d")

def flagged(res, limit):
    out = []
    for r in res:
        why = []
        for t in r["tags"]:
            why.append(("tag", t))
        if r["party"] >= 6:
            why.append(("size", f"Party of {r['party']}"))
        if r["requests"]:
            why.append(("req", r["requests"]))
        if r["visit_notes"]:
            why.append(("note", r["visit_notes"]))
        if why:
            out.append((r, why))
    return out[:limit]

def chip_class(kind, text):
    t = text.lower()
    if kind == "tag" and ("alert" in t or "vip" in t or "special" in t):
        return "chip hot"
    if kind == "tag" and ("birthday" in t or "anniversary" in t or "celebr" in t):
        return "chip warm"
    if kind == "size":
        return "chip size"
    return "chip"

# ----------------------------------------------------------------- themes

THEMES = {
    "lolas": dict(
        name="Lola's Bistro", footer="Lola's Bistro · Today's Reso's",
        bg="#27262a", ink="#ffffff", muted="#d9d4ca", dim="rgba(217,212,202,0.55)",
        accent="#4a6881", accent2="#7fa3c0", panel="rgba(74,104,129,0.22)", line="rgba(217,212,202,0.22)",
        head_font="'Jost', 'Futura', Arial, sans-serif", num_font="'Libre Baskerville', Georgia, serif",
        body_font="'Libre Baskerville', Georgia, serif",
        gfont="Jost:wght@400;500;600;700&family=Libre+Baskerville:ital,wght@0,400;0,700;1,400",
        logo=os.path.join(HERE, "assets", "lola-wordmark.png"), logo_h=118,
        mark=os.path.join(HERE, "assets", "lola-dog.png"),
        hot="#e3b76c", warm="#7fa3c0", light=False, head_upper=True, head_italic=False,
    ),
    "jojos": dict(
        name="JoJo's Bar", footer="JoJo's Bar · Today's Reso's",
        bg="#0e2748", ink="#ffffff", muted="rgba(255,255,255,0.78)", dim="rgba(255,255,255,0.5)",
        accent="#3e5170", accent2="#aab9d6", panel="rgba(62,81,112,0.45)", line="rgba(255,255,255,0.18)",
        head_font="'Libre Baskerville', 'Baskerville', Georgia, serif", num_font="'Libre Baskerville', Georgia, serif",
        body_font="'Montserrat', Arial, sans-serif",
        gfont="Libre+Baskerville:ital,wght@0,400;0,700;1,400&family=Montserrat:wght@400;500;600;700",
        logo=os.path.join(HERE, "assets", "jojos-script.png"), logo_h=122, mark=None,
        hot="#e8c889", warm="#aab9d6", light=False, head_upper=False, head_italic=True,
    ),
    "ccg": dict(
        name="Cedar Creek Grille", footer="Cedar Creek Grille · Today's Reso's",
        bg="#074b64", ink="#ffffff", muted="rgba(255,255,255,0.8)", dim="rgba(255,255,255,0.5)",
        accent="#475b6d", accent2="#bcd3e0", panel="rgba(71,91,109,0.55)", line="rgba(255,255,255,0.2)",
        head_font="'Libre Baskerville', 'Baskerville', Georgia, serif", num_font="'Libre Baskerville', Georgia, serif",
        body_font="'Montserrat', Arial, sans-serif",
        gfont="Libre+Baskerville:ital,wght@0,400;0,700;1,400&family=Montserrat:wght@400;500;600;700",
        logo=os.path.join(HERE, "assets", "ccg-monogram.png"), logo_h=104, logo_h_half=96, mark=None,
        hot="#e8c889", warm="#bcd3e0", light=False, head_upper=False, head_italic=False,
    ),
    "fuoco": dict(
        name="Après Fuoco", footer="Après Fuoco · Dinner Reso's",
        bg="#faf6ef", ink="#3a2a2a", muted="#7a5a5a", dim="rgba(58,42,42,0.55)",
        accent="#a02828", accent2="#a02828", panel="rgba(160,40,40,0.10)", line="rgba(160,40,40,0.25)",
        head_font="'Caveat', cursive", num_font="'Lora', Georgia, serif", body_font="'Jost', Arial, sans-serif",
        gfont="Caveat:wght@500;700&family=Lora:ital,wght@0,400;0,700;1,400&family=Jost:wght@400;500;600",
        logo=os.path.join(HERE, "assets", "apres-wordmark-red.png"), logo_h=120, logo_h_half=104,
        mark=os.path.join(HERE, "assets", "apres-badge.png"),
        hot="#a02828", warm="#c98638", light=True, head_upper=False, head_italic=False,
    ),
}

def bar_italia(location, slug):
    return dict(
        name=f"Bar Italia {location}", sub=location, footer=f"Bar Italia · {location} · Today's Reso's",
        bg="#142b1a", ink="#f4ede0", muted="#a8946a", dim="rgba(244,237,224,0.5)",
        accent="#e3b76c", accent2="#e3b76c", panel="rgba(227,183,108,0.12)", line="rgba(244,237,224,0.18)",
        head_font="Georgia, 'Times New Roman', serif", num_font="Georgia, 'Times New Roman', serif",
        body_font="Arial, Helvetica, sans-serif", gfont="",
        logo=os.path.join(HERE, "assets", "bar-italia-logo.png"), logo_h=84, logo_h_half=52, mark=None,
        hot="#e98638", warm="#e3b76c", light=False, head_upper=False, head_italic=False,
    )

for _loc, _slug in [("Beachwood", "bi-beachwood"), ("Lakewood Ranch", "bi-sarasota"), ("Easton", "bi-etc"),
                    ("Winter Park", "bi-winterpark"), ("Lakewood", "bi-lakewood")]:
    THEMES[_slug] = bar_italia(_loc, _slug)

# store -> how the screen is built
STORES = {
    "lolas":      dict(theme="lolas"),
    "jojos":      dict(theme="jojos", split_on=APRES_DATES, right="fuoco",
                       right_missing="Après Fuoco reso&#39;s<br>not connected to OpenTable yet"),
    "beachwood":  dict(theme="ccg", split_always=True, right="bi-beachwood",
                       right_missing="Bar Italia Beachwood digest<br>not received today"),
    "sarasota":   dict(theme="bi-sarasota"),
    "etc":        dict(theme="bi-etc"),
    "winterpark": dict(theme="bi-winterpark"),
    "lakewood":   dict(theme="bi-lakewood", lunch_days=[4, 5, 6]),  # Python weekday: Fri, Sat, Sun only
}

# ----------------------------------------------------------------- render

def shift_label(d):
    return "Lunch Reso's" if d.get("shift") == "lunch" else "Dinner Reso's"

def css_vars(t):
    return (f"--bg:{t['bg']};--ink:{t['ink']};--muted:{t['muted']};--dim:{t['dim']};--accent:{t['accent']};"
            f"--accent2:{t['accent2']};--panel:{t['panel']};--line:{t['line']};--hot:{t['hot']};--warm:{t['warm']};"
            f"--head:{t['head_font']};--num:{t['num_font']};--body:{t['body_font']};")

BASE_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1920px;height:1080px;overflow:hidden;background:var(--bg);color:var(--ink);font-family:var(--body)}
.stage{width:1920px;height:1080px;position:relative;overflow:hidden;background:var(--bg)}
.pane{position:absolute;top:0;bottom:0;overflow:hidden;background:var(--bg);color:var(--ink)}
.pane.full{left:0;width:1920px}
.pane.left{left:0;width:960px}
.pane.right{left:960px;width:960px;border-left:1px solid var(--line)}
.hdr{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:1px solid var(--line);position:relative;z-index:2}
.full .hdr{height:160px;padding:30px 64px 26px}
.half .hdr{height:150px;padding:28px 44px 22px}
.logo{display:block;object-fit:contain}
.logowrap .sub{font-family:var(--body);font-size:19px;letter-spacing:6px;text-transform:uppercase;color:var(--accent2);margin-top:14px;font-weight:600}
.half .logowrap .sub{font-size:16px;letter-spacing:5px;margin-top:10px}
.shiftlab{text-align:right}
.shiftlab .big{font-family:var(--head);color:var(--ink);line-height:1}
.full .shiftlab .big{font-size:64px}
.half .shiftlab .big{font-size:46px}
.shiftlab .date{font-family:var(--body);color:var(--accent2);letter-spacing:3px;text-transform:uppercase;margin-top:12px;font-weight:600}
.full .shiftlab .date{font-size:21px}
.half .shiftlab .date{font-size:16px;letter-spacing:2px}
.shiftlab .upd{font-size:15px;color:var(--dim);letter-spacing:2px;text-transform:uppercase;margin-top:7px}
.lbl{font-family:var(--body);letter-spacing:4px;text-transform:uppercase;color:var(--accent2);font-weight:600}
.full .lbl{font-size:17px}
.half .lbl{font-size:15px;letter-spacing:3px}
.lbl span{color:var(--dim);font-weight:400;letter-spacing:2px;margin-left:14px;text-transform:none}
.ftr{position:absolute;bottom:0;left:0;right:0;height:48px;padding:15px 64px;display:flex;justify-content:space-between;font-size:14px;color:var(--dim);letter-spacing:3px;text-transform:uppercase;border-top:1px solid var(--line);font-family:var(--body);z-index:2;background:var(--bg)}
.half .ftr{padding:15px 44px}
.body{position:relative;z-index:1}
/* hero */
.hero .num{font-family:var(--num);font-weight:700;line-height:.84;color:var(--ink);letter-spacing:-8px}
.full .hero .num{font-size:360px}
.half .hero .num{font-size:200px;letter-spacing:-5px}
.hero .cap{font-family:var(--head);color:var(--accent2);margin-top:22px}
.full .hero .cap{font-size:40px}
.half .hero .cap{font-size:28px}
.stats{display:grid;gap:16px}
.full .stats{grid-template-columns:1fr 1fr}
.half .stats{grid-template-columns:repeat(4,1fr);gap:12px}
.stat{background:var(--panel);border-left:5px solid var(--accent);padding:20px 24px 18px;border-radius:2px}
.half .stat{padding:14px 16px 12px;border-left-width:4px}
.stat .v{font-family:var(--num);font-weight:700;line-height:1;color:var(--ink)}
.full .stat .v{font-size:92px}
.half .stat .v{font-size:56px}
.stat .k{font-family:var(--body);font-size:17px;letter-spacing:3px;text-transform:uppercase;color:var(--muted);margin-top:12px;font-weight:600}
.half .stat .k{font-size:12px;letter-spacing:2px;margin-top:8px}
/* pace */
.pace{display:flex;flex-direction:column}
.bars{flex:1;display:flex;align-items:flex-end;gap:22px;padding-top:56px;min-height:0}
.bar{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%}
.bar .fill{width:100%;background:linear-gradient(180deg,var(--accent2),var(--accent));border-radius:6px 6px 2px 2px;min-height:8px}
.bar .cv{font-family:var(--num);font-weight:700;font-size:52px;color:var(--ink);margin-bottom:10px;line-height:1;text-align:center}
.bar .cv small{font-family:var(--body);font-size:14px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);display:block;font-weight:600;margin-top:6px}
.bar .hr{font-family:var(--body);font-size:19px;letter-spacing:2px;text-transform:uppercase;color:var(--ink);margin-top:14px;font-weight:600;white-space:nowrap}
.bar .rs{font-size:14px;color:var(--dim);letter-spacing:1px;margin-top:5px}
/* the book list */
.book{display:flex;flex-direction:column}
.rows{flex:1;display:flex;flex-direction:column;gap:10px;margin-top:18px;min-height:0;overflow:hidden}
.row{display:grid;grid-template-columns:126px 1fr;gap:16px;align-items:center;background:var(--panel);border-radius:4px;padding:11px 18px;border-left:4px solid transparent;flex:1 1 0;max-height:78px;min-height:46px}
.more{flex:0 0 auto}
.row.flag{border-left-color:var(--accent2)}
.half .row{grid-template-columns:110px 1fr;padding:10px 14px}
.row .t{font-family:var(--num);font-weight:700;font-size:30px;line-height:1;color:var(--ink);letter-spacing:-1px}
.half .row .t{font-size:26px}
.row .who{font-family:var(--body);font-size:23px;color:var(--ink);font-weight:600;line-height:1.2;display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px}
.half .row .who{font-size:19px}
.row .who .m.big{color:var(--hot);font-weight:700}
.row .who .m{color:var(--muted);font-weight:400;font-size:19px;letter-spacing:1px}
.half .row .who .m{font-size:16px}
.chip{font-family:var(--body);font-size:14px;letter-spacing:1.5px;text-transform:uppercase;padding:5px 11px;border-radius:14px;border:1px solid var(--accent2);color:var(--accent2);font-weight:600;line-height:1;white-space:nowrap}
.chip.hot{background:var(--hot);border-color:var(--hot);color:var(--bg)}
.chip.warm{background:var(--warm);border-color:var(--warm);color:var(--bg)}
.chip.size{border-color:var(--ink);color:var(--ink)}
.chip.req{text-transform:none;letter-spacing:0;font-size:15px;border-style:dashed;font-weight:500;white-space:normal}
.roomy .row{max-height:150px;padding:18px 24px;grid-template-columns:180px 1fr}
.roomy .row .t{font-size:42px}
.roomy .row .who{font-size:32px;gap:10px 18px}
.roomy .row .who .m{font-size:24px}
.roomy .chip{font-size:17px;padding:7px 14px}
.roomy .chip.req{font-size:19px}
.half .roomy .row{max-height:120px;padding:14px 18px;grid-template-columns:150px 1fr}
.half .roomy .row .t{font-size:34px}
.half .roomy .row .who{font-size:26px}
.half .roomy .row .who .m{font-size:20px}
.more{font-family:var(--num);font-style:italic;font-size:21px;color:var(--muted);padding:8px 18px}
.empty{font-family:var(--num);font-style:italic;font-size:30px;color:var(--muted);line-height:1.4;margin-top:30px}
.mark{position:absolute;right:40px;bottom:70px;width:440px;opacity:.06;pointer-events:none;z-index:0}
.half .mark.half-mark{right:30px;bottom:60px;width:420px;opacity:.05}
.wait{position:absolute;inset:0;display:none;align-items:center;justify-content:center;background:var(--bg);text-align:center;z-index:9}
.wait .w1{font-family:var(--num);font-size:84px;color:var(--ink);line-height:1.1}
.wait .w2{font-family:var(--body);font-size:22px;letter-spacing:5px;text-transform:uppercase;color:var(--accent2);margin-top:24px}
body.stale .wait{display:flex}
"""

def why_for(r):
    why = []
    for tg in r["tags"]:
        why.append(("tag", tg))
    if r["requests"]:
        why.append(("req", r["requests"]))
    if r["visit_notes"]:
        why.append(("note", r["visit_notes"]))
    return why

def _tkey(tm):
    m = re.match(r"(\d{1,2}):(\d{2})\s*([AP]M)", tm.replace(" ", ""))
    if not m:
        return 0
    h, mi, ap = int(m.group(1)) % 12, int(m.group(2)), m.group(3)
    return (h + (12 if ap == "PM" else 0)) * 60 + mi

def book_rows(res, limit, half=False):
    res = sorted(res, key=lambda r: _tkey(r["time"]))
    if len(res) > limit:
        # keep every flagged reservation first, then fill from the top of the book, then re-sort by time
        flagged_rows = [r for r in res if why_for(r)][:limit]
        fill = [r for r in res if r not in flagged_rows][: max(0, limit - len(flagged_rows))]
        shown = sorted(flagged_rows + fill, key=lambda r: _tkey(r["time"]))
    else:
        shown = res
    out = []
    for r in shown:
        why = why_for(r)
        chips = "".join(
            f'<span class="{chip_class(k, v) if k not in ("req", "note") else "chip req"}">{html.escape(v[: (48 if half else 60)])}</span>'
            for k, v in why)
        tbl = f'<span class="m">tbl {html.escape(r["table"])}</span>' if r["table"] else ""
        out.append(
            f'<div class="row{" flag" if why else ""}"><div class="t">{html.escape(r["time"].replace("AM", " am").replace("PM", " pm"))}</div>'
            f'<div class="who">{html.escape(short_name(r["name"]))}<span class="m{' big' if r["party"] >= 6 else ''}">party of {r["party"]}</span>{tbl}{chips}</div></div>')
    if len(res) > limit:
        rest = [r for r in res if r not in shown]
        out.append(f'<div class="more">+{len(rest)} more on the book · flagged tables shown first</div>')
    if not out:
        out.append('<div class="empty">No reso&#39;s yet.<br>Walk-ins are the book tonight.</div>')
    return "".join(out)

def logo_block(t, half=False):
    sub = f'<div class="sub">{html.escape(t["sub"])}</div>' if t.get("sub") else ""
    h = t.get("logo_h_half", t["logo_h"]) if half else t["logo_h"]
    return (f'<div class="logowrap"><img class="logo" style="height:{h}px" src="{b64(t["logo"])}" '
            f'alt="{html.escape(t["name"])}">{sub}</div>')

def render_full(d, t, received):
    body_h = 1080 - 160 - 48
    slots = d["slots"]
    mx = max([s["covers"] for s in slots] + [1])
    bars = "".join(
        f'<div class="bar"><div class="cv">{s["covers"]}<small>covers</small></div>'
        f'<div class="fill" style="height:{max(8, int(540 * s["covers"] / mx))}px"></div>'
        f'<div class="hr">{html.escape(s["range"].split(" - ")[0].replace(":00", "").lower())}</div>'
        f'<div class="rs">{s["reservations"]} reso{"s" if s["reservations"] != 1 else ""}</div></div>'
        for s in slots) or '<div class="empty">No reso&#39;s yet.</div>'
    # how many rows fit: ~58px plain, chips push to ~64; budget 760px
    rows = book_rows(d["reservations"], 11)
    mark = f'<img class="mark" src="{b64(t["mark"])}" alt="">' if t.get("mark") else ""
    return f"""
<div class="pane full">
  {mark}
  <div class="hdr">
    {logo_block(t)}
    <div class="shiftlab">
      <div class="big">{shift_label(d)}</div>
      <div class="date">{pretty_date(d['date'])}</div>
      <div class="upd">OpenTable · updated {updated_label(received)}</div>
    </div>
  </div>
  <div class="body" style="display:grid;grid-template-columns:560px 1fr 700px;gap:56px;height:{body_h}px;padding:34px 64px 30px">
    <div class="hero" style="display:flex;flex-direction:column;justify-content:space-between;min-height:0">
      <div><div class="num">{d['covers']}</div><div class="cap">covers reserved</div></div>
      <div class="stats">
        <div class="stat"><div class="v">{d['reservation_count']}</div><div class="k">Reservations</div></div>
        <div class="stat"><div class="v">{d['parties5']}</div><div class="k">Parties of 5+</div></div>
        <div class="stat"><div class="v">{d['celebrations']}</div><div class="k">Celebrations</div></div>
        <div class="stat"><div class="v">{d['vip']}</div><div class="k">Manager alerts</div></div>
      </div>
    </div>
    <div class="pace" style="min-height:0"><div class="lbl">The pace</div><div class="bars">{bars}</div></div>
    <div class="book" style="min-height:0"><div class="lbl">The reso&#39;s <span>by seating time</span></div><div class="rows{' roomy' if len(d['reservations']) <= 5 else ''}">{rows}</div></div>
  </div>
  <div class="ftr"><span>{html.escape(t['footer'])}</span><span>Staff only · names stay in the building</span></div>
</div>"""

def render_half(d, t, received, side, placeholder=None):
    body_h = 1080 - 150 - 48
    if placeholder:
        hero = ""
        inner = f'<div class="empty" style="margin-top:140px;text-align:center">{placeholder}</div>'
    else:
        hero = f"""
      <div class="hero"><div class="num">{d['covers']}</div><div class="cap">covers reserved</div></div>
      <div class="stats" style="margin-top:28px">
        <div class="stat"><div class="v">{d['reservation_count']}</div><div class="k">Resos</div></div>
        <div class="stat"><div class="v">{d['parties5']}</div><div class="k">5+ tops</div></div>
        <div class="stat"><div class="v">{d['celebrations']}</div><div class="k">Celebr.</div></div>
        <div class="stat"><div class="v">{d['vip']}</div><div class="k">Alerts</div></div>
      </div>"""
        inner = f'<div class="book" style="margin-top:30px;min-height:0;flex:1"><div class="lbl">The reso&#39;s <span>by seating time</span></div><div class="rows{' roomy' if len(d['reservations']) <= 4 else ''}">{book_rows(d["reservations"], 6, half=True)}</div></div>'
    return f"""
<div class="pane half {side}" style="{css_vars(t)}">
  {f'<img class="mark half-mark" src="{b64(t["mark"])}" alt="">' if t.get("mark") else ""}
  <div class="hdr">
    {logo_block(t, half=True)}
    <div class="shiftlab">
      <div class="big">{shift_label(d) if d else "Dinner Reso's"}</div>
      <div class="date">{pretty_date(d['date']) if d else ''}</div>
      <div class="upd">OpenTable · updated {updated_label(received)}</div>
    </div>
  </div>
  <div class="body" style="display:flex;flex-direction:column;height:{body_h}px;padding:30px 44px 26px">
    {hero}{inner}
  </div>
  <div class="ftr"><span>{html.escape(t['footer'])}</span><span>Staff only</span></div>
</div>"""

def page(title, t, inner, data_date, gfonts, lunch_days=None):
    gf = [g for g in gfonts if g]
    fonts = "&family=".join(sorted(set(gf)))
    fontlink = f'<link rel="preconnect" href="https://fonts.googleapis.com">\n<link href="https://fonts.googleapis.com/css2?family={fonts}&display=swap" rel="stylesheet">' if fonts else ""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=1920">
<title>{html.escape(title)}</title>
{fontlink}
<style>:root{{{css_vars(t)}}}{BASE_CSS}</style></head>
<body><div class="stage">{inner}
<div class="wait"><div><div class="w1" id="waitmsg">Today's reso's post at 10:15 am</div><div class="w2">{html.escape(t['name'])} · The Daily</div></div></div>
</div>
<script>
(function(){{
  var dataDate = "{data_date}";
  var lunchDays = {json.dumps([(d + 1) % 7 for d in lunch_days]) if lunch_days else "null"};  // JS getDay(): 0=Sun
  function check(){{
    var now = new Date();
    var p = new Intl.DateTimeFormat('en-CA',{{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',hour12:false}}).formatToParts(now);
    var o={{}}; p.forEach(function(x){{o[x.type]=x.value}});
    var today=o.year+'-'+o.month+'-'+o.day; var hr=parseInt(o.hour,10);
    var stale = dataDate && (today>dataDate) && hr>=0 && hr<10;  // next morning, before the 10:15 push
    var msg = "Today's reso's post at 10:15 am";
    if (lunchDays) {{
      var dow = new Date(today + "T12:00:00").getDay();
      if (lunchDays.indexOf(dow) < 0 && hr < 14 && (today>dataDate || dataDate === "")) {{ stale = true; msg = "Dinner only today · reso's post at 2:15 pm"; }}
    }}
    document.getElementById('waitmsg').textContent = msg;
    document.body.classList.toggle('stale', !!stale);
  }}
  check(); setInterval(check, 60000);
}})();
</script></body></html>"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True, choices=list(STORES))
    ap.add_argument("--email", required=True, help="digest HTML for the store (left half on a split)")
    ap.add_argument("--email2", "--fuoco-email", dest="email2", help="digest HTML for the right half of a split")
    ap.add_argument("--received", default="")
    ap.add_argument("--received2", "--fuoco-received", dest="received2", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--force-split", action="store_true")
    ap.add_argument("--dump-json", action="store_true")
    a = ap.parse_args()
    cfg = STORES[a.store]
    t = THEMES[cfg["theme"]]
    raw = open(a.email, encoding="utf-8", errors="replace").read()
    d = parse_digest(raw)
    if a.dump_json:
        print(json.dumps(d, indent=1))
    split = cfg.get("split_always") or a.force_split or (cfg.get("split_on") and d.get("date") in cfg["split_on"])
    if split:
        t2 = THEMES[cfg["right"]]
        d2 = None
        if a.email2:
            d2 = parse_digest(open(a.email2, encoding="utf-8", errors="replace").read())
        right = render_half(d2, t2, a.received2 or a.received, "right",
                            placeholder=None if d2 else cfg["right_missing"])
        inner = render_half(d, t, a.received, "left") + right
        gf = [t["gfont"], t2["gfont"]]
        title = f"{t['name']} + {t2['name']} — {shift_label(d)}"
    else:
        inner = render_full(d, t, a.received)
        gf = [t["gfont"]]
        title = f"{t['name']} — {shift_label(d)}"
    out = page(title, t, inner, d.get("date", ""), gf, cfg.get("lunch_days"))
    open(a.out, "w", encoding="utf-8").write(out)
    print(f"wrote {a.out}: {d['restaurant']} {d['date']} {d['shift']} covers={d['covers']} res={d['reservation_count']} slots={len(d['slots'])} flagged={sum(1 for r in d['reservations'] if why_for(r))} split={bool(split)}")

if __name__ == "__main__":
    main()
