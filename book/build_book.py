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
    if kind == "tag" and ("alert" in t or "vip" in t or "special" in t or t.startswith("event") or "private event" in t):
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
    "lakehouse": dict(
        name="The Lakehouse", footer="The Lakehouse · Today's Reso's",
        bg="#0e2748", ink="#ffffff", muted="rgba(255,255,255,0.8)", dim="rgba(255,255,255,0.5)",
        accent="#3e5170", accent2="#b9c6dc", panel="rgba(62,81,112,0.5)", line="rgba(255,255,255,0.18)",
        head_font="'Montserrat', Arial, sans-serif", num_font="'Karma', Georgia, serif",
        body_font="'Noto Serif', Georgia, serif",
        gfont="Montserrat:wght@500;600;700&family=Karma:wght@400;600;700&family=Noto+Serif:ital,wght@0,400;0,600;1,400",
        logo=os.path.join(HERE, "assets", "lakehouse-wordmark.png"), logo_h=116, logo_h_half=100, mark=None,
        hot="#e8c889", warm="#b9c6dc", light=False, head_upper=True, head_italic=False,
    ),
    "17river": dict(
        name="17 River Grille", footer="17 River Grille · Today's Reso's",
        bg="#63655f", ink="#ffffff", muted="rgba(255,255,255,0.82)", dim="rgba(255,255,255,0.55)",
        accent="#c9962f", accent2="#e6c46a", panel="rgba(0,0,0,0.18)", line="rgba(255,255,255,0.22)",
        head_font="'Libre Baskerville', 'Baskerville', Georgia, serif", num_font="'Libre Baskerville', Georgia, serif",
        body_font="'Montserrat', Arial, sans-serif",
        gfont="Libre+Baskerville:ital,wght@0,400;0,700;1,400&family=Montserrat:wght@400;500;600;700",
        logo=os.path.join(HERE, "assets", "17river-logo.png"), logo_h=100, logo_h_half=84, mark=None,
        hot="#c9962f", warm="#e6c46a", light=False, head_upper=False, head_italic=False,
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
    "beachwood":  dict(theme="ccg"),            # Cedar Creek Grille screen (was a CCG + Bar Italia split until 11.10.26)
    "bibeachwood": dict(theme="bi-beachwood"),  # Bar Italia Beachwood has its own screen as of 11.10.26
    "sarasota":   dict(theme="bi-sarasota"),
    "etc":        dict(theme="bi-etc"),
    "winterpark": dict(theme="bi-winterpark"),
    "lakewood":   dict(theme="bi-lakewood", lunch_days=[4, 5, 6], dinner_post="3:15 pm"),  # dinner digest lands ~3:10, built by the 3:15 run
    "17river":    dict(theme="17river"),
    "lakehouse":  dict(theme="lakehouse", single_shift=True, post_times={"weekday": "11:15 am", "weekend": "10:15 am"}),  # Python weekday: Fri, Sat, Sun only
}

# ----------------------------------------------------------------- Tripleseat (private events)

# Tripleseat "Daily Digest" (noreply@tripleseat.com, ~6:05 am ET): "Today's Events" table with
# Event · Time · Location · Status · Rooms · Guests. Abby or a manager often holds the table in
# OpenTable as a party of 1, so the book under-counts; Tripleseat has the real head count.

TS_LOCATION = {
    "lolas":         lambda L: "lola" in L,
    "jojos":         lambda L: "jojo" in L,
    "fuoco":         lambda L: "fuoco" in L or "apr" in L,
    "ccg":           lambda L: "cedar creek" in L,
    "bi-beachwood":  lambda L: "bar italia" in L and "beachwood" in L,
    "bi-sarasota":   lambda L: "bar italia" in L and ("sarasota" in L or "lakewood ranch" in L),
    "bi-etc":        lambda L: "bar italia" in L and ("easton" in L or "columbus" in L),
    "bi-winterpark": lambda L: "bar italia" in L and "winter park" in L,
    "bi-lakewood":   lambda L: "bar italia" in L and "lakewood" in L and "lakewood ranch" not in L,
    "17river":       lambda L: "17 river" in L,
    "lakehouse":     lambda L: "lakehouse" in L,
}

def parse_tripleseat(raw):
    """events from the Daily Digest's Today's Events table"""
    out = []
    m = re.search(r"Today(?:&#39;|')s Events</h2>\s*<table.*?</table>", raw, re.S)
    if not m:
        return out
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(0), re.S)
    cur = None
    for row in rows:
        cells = [_txt(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if not cells:
            continue
        if len(cells) >= 6:
            cur = {"name": cells[0], "time": cells[1], "location": cells[2], "status": cells[3], "rooms": cells[4],
                   "guests": int(re.sub(r"\D", "", cells[5]) or 0)}
            out.append(cur)
        elif len(cells) == 1 and cur is not None and cells[0].lower().startswith("location:"):
            for part in cells[0].split("·"):
                k, _, v = part.partition(":")
                k = k.strip().lower(); v = v.strip()
                if k == "location" and v: cur["location"] = v
                elif k == "status" and v: cur["status"] = v
                elif k == "rooms" and v: cur["rooms"] = v
    for e in out:
        mm = re.match(r"(\d{1,2}:\d{2}\s*[AP]M)", e["time"], re.I)
        e["start"] = mm.group(1).upper().replace(" ", "") if mm else ""
        e["guest_name"] = re.split(r"[*(\-–—/|]", e["name"])[0].strip()
    return out

def _in_shift(d, start):
    if not start:
        return True
    mins = _tkey(start)
    title = (d.get("title") or "").lower()
    if "lunch" in title or "brunch" in title:
        return mins < 15 * 60 + 30
    if "dinner" in title:
        return mins >= 14 * 60
    return True

def merge_events(d, events, theme_key):
    """fold Tripleseat events for this screen into the OpenTable book. Returns a list of plain-text notes."""
    notes = []
    want = TS_LOCATION.get(theme_key)
    if not d or not want:
        return notes
    d["ts_added"] = 0
    d["ts_events"] = 0
    for e in events:
        if not want(e["location"].lower()) or not _in_shift(d, e["start"]):
            continue
        if e["status"].lower() not in ("definite", "closed"):
            notes.append(f"{theme_key}: Tripleseat {e['status']} event not shown — {e['guest_name']} {e['start']} {e['guests']} guests ({e['rooms']})")
            continue
        gparts = [p for p in e["guest_name"].replace(".", "").split() if p.lower() not in ("jr", "sr", "ii", "iii", "iv")] or [""]
        last = gparts[-1].lower()
        first = gparts[0].lower()
        hit = None
        for r in d["reservations"]:
            parts = r["name"].lower().split()
            if parts and last and (parts[-1] == last or (parts[0] == first and len(parts) == 1)):
                hit = r; break
        if hit is None and e["start"]:
            # placeholder hold: a 1- or 2-top within 30 minutes with no other match
            near = [r for r in d["reservations"] if r["party"] <= 2 and abs(_tkey(r["time"]) - _tkey(e["start"])) <= 30]
            if len(near) == 1:
                hit = near[0]
                notes.append(f"{theme_key}: matched {e['guest_name']} ({e['guests']}) to placeholder {hit['name']} {hit['time']} party of {hit['party']} by time only")
        tag = f"Event · {e['rooms']}" if e["rooms"] else "Private event"
        d["ts_events"] += 1
        if hit is not None:
            if e["guests"] > hit["party"]:
                d["ts_added"] += e["guests"] - hit["party"]
                notes.append(f"{theme_key}: {hit['name']} {hit['time']} party of {hit['party']} → {e['guests']} per Tripleseat ({e['rooms'] or 'event'})")
                hit["party"] = e["guests"]
            if tag not in hit["tags"]:
                hit["tags"].insert(0, tag)
        else:
            d["reservations"].append({"name": e["guest_name"], "time": e["start"] or "", "party": e["guests"], "table": "",
                                      "tags": [tag], "requests": "", "visit_notes": "", "most_ordered": "", "details": "", "slot": ""})
            d["ts_added"] += e["guests"]
            notes.append(f"{theme_key}: added Tripleseat-only event {e['guest_name']} {e['start']} {e['guests']} guests ({e['rooms'] or 'event'})")
            for slot in d["slots"]:
                lo = _tkey(slot["range"].split(" - ")[0]); hi = _tkey(slot["range"].split(" - ")[-1])
                if e["start"] and lo <= _tkey(e["start"]) < hi:
                    slot["covers"] += e["guests"]; slot["reservations"] += 1
    if d["ts_added"]:
        d["covers"] += d["ts_added"]
    if d["ts_events"]:
        d["reservation_count"] = len(d["reservations"])
        d["parties5"] = sum(1 for r in d["reservations"] if r["party"] >= 5)
    return notes

# ----------------------------------------------------------------- render

def shift_label(d, single=False):
    if single:
        return "Today's Reso's"
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
.hero .tsnote{font-family:var(--body);font-size:17px;color:var(--dim);margin-top:10px;letter-spacing:.5px}
.half .hero .tsnote{font-size:14px;margin-top:6px}
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
.pace{display:flex;flex-direction:column;min-width:0}
.bars{flex:1;display:flex;align-items:flex-end;gap:14px;padding-top:56px;min-height:0}
.bar{flex:1;min-width:0;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%}
.bar .fill{width:100%;background:linear-gradient(180deg,var(--accent2),var(--accent));border-radius:6px 6px 2px 2px;min-height:8px}
.bar .cv{font-family:var(--num);font-weight:700;font-size:52px;color:var(--ink);margin-bottom:10px;line-height:1;text-align:center}
.bar .cv small{font-family:var(--body);font-size:14px;letter-spacing:2px;text-transform:uppercase;color:var(--muted);display:block;font-weight:600;margin-top:6px}
.bar .hr{font-family:var(--body);font-size:19px;letter-spacing:2px;text-transform:uppercase;color:var(--ink);margin-top:14px;font-weight:600;white-space:nowrap}
.bar .rs{font-size:14px;color:var(--dim);letter-spacing:1px;margin-top:5px;white-space:nowrap}
/* the book list */
.book{display:flex;flex-direction:column}
.rows{flex:1;display:flex;flex-direction:column;gap:10px;margin-top:18px;min-height:0;overflow:hidden}
.row{display:grid;grid-template-columns:126px 1fr;gap:16px;align-items:center;background:var(--panel);border-radius:4px;padding:11px 18px;border-left:4px solid transparent;flex:1 1 auto;max-height:112px;min-height:46px;overflow:hidden}
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
.chip.req{text-transform:none;letter-spacing:0;font-size:15px;border-style:dashed;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}
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

BIG_PARTY = 6  # a table of this size or larger is a "notable" reservation on its own

def priority(r):
    """Rank for a crowded book (lower = more important). Time order breaks ties.
    1 manager alert / VIP / special relationship
    2 party of BIG_PARTY+ (bigger parties first)
    3 birthday / anniversary / celebration
    4 guest request or visit note
    5 any other tag (Date Night, Employee, Business Meal, ...)
    9 nothing notable"""
    tags = [t.lower() for t in r["tags"]]
    if any("alert" in t or "vip" in t or "special" in t or t.startswith("event") or "private event" in t for t in tags):
        return (1, 0)
    if r["party"] >= BIG_PARTY:
        return (2, -r["party"])
    if any("birthday" in t or "anniversary" in t or "celebr" in t or "occasion" in t for t in tags):
        return (3, 0)
    if r["requests"] or r["visit_notes"]:
        return (4, 0)
    if tags:
        return (5, 0)
    return (9, 0)

MAX_CHIPS_FULL, MAX_CHIPS_HALF = 3, 2

def _chip_rank(kind, text):
    t = text.lower()
    if kind == "tag" and ("alert" in t or "vip" in t or "special" in t or t.startswith("event") or "private event" in t):
        return 0
    if kind in ("req", "note"):
        return 1
    if kind == "tag" and ("birthday" in t or "anniversary" in t or "celebr" in t or "occasion" in t):
        return 2
    return 3

def chips_for(r, half=False):
    """the chips a row actually shows: most important first, capped so a row never runs past three lines"""
    why = sorted(why_for(r), key=lambda kv: _chip_rank(*kv))
    return why[: (MAX_CHIPS_HALF if half else MAX_CHIPS_FULL)]

def _row_cost(r, half=False):
    # estimated rendered height: base row, + a line for a request/visit-note chip, + a line when two or more tag chips wrap
    base = 60 if half else 66
    shown = chips_for(r, half)
    extra = 34 if any(k in ("req", "note") for k, _ in shown) else 0
    if sum(1 for k, _ in shown if k == "tag") >= 2:
        extra += 34
    return base + extra

def fit_limit(res, budget, half=False):
    """how many rows fit in `budget` px, walking the book in the same priority order book_rows shows it"""
    ranked = sorted(res, key=lambda r: (priority(r), _tkey(r["time"])))
    chosen, used = [], 0
    for r in ranked:
        c = _row_cost(r, half)
        if used + c > budget:
            break
        chosen.append(r); used += c
    return max(1, len(chosen)) if res else 0

def book_rows(res, limit, half=False):
    res = sorted(res, key=lambda r: _tkey(r["time"]))
    if len(res) > limit:
        # crowded book: rank by priority() (alerts, big parties, celebrations, requests, other tags),
        # time order within a tier, take the top `limit`, then re-sort by seating time for display
        ranked = sorted(res, key=lambda r: (priority(r), _tkey(r["time"])))
        shown = sorted(ranked[:limit], key=lambda r: _tkey(r["time"]))
    else:
        shown = res
    out = []
    for r in shown:
        why = why_for(r)
        chips = "".join(
            f'<span class="{chip_class(k, v) if k not in ("req", "note") else "chip req"}">{html.escape(v[: (48 if half else 60)])}</span>'
            for k, v in chips_for(r, half))
        tbl = f'<span class="m">tbl {html.escape(r["table"])}</span>' if r["table"] else ""
        out.append(
            f'<div class="row{" flag" if (why or r["party"] >= BIG_PARTY) else ""}"><div class="t">{html.escape(r["time"].replace("AM", " am").replace("PM", " pm"))}</div>'
            f'<div class="who">{html.escape(short_name(r["name"]))}<span class="m{' big' if r["party"] >= 6 else ''}">party of {r["party"]}</span>{tbl}{chips}</div></div>')
    if len(res) > limit:
        rest = [r for r in res if r not in shown]
        out.append(f'<div class="more">+{len(rest)} more on the book · notable tables shown first</div>')
    if not out:
        out.append('<div class="empty">No reso&#39;s yet.<br>Walk-ins are the book tonight.</div>')
    return "".join(out)

def logo_block(t, half=False):
    sub = f'<div class="sub">{html.escape(t["sub"])}</div>' if t.get("sub") else ""
    h = t.get("logo_h_half", t["logo_h"]) if half else t["logo_h"]
    return (f'<div class="logowrap"><img class="logo" style="height:{h}px" src="{b64(t["logo"])}" '
            f'alt="{html.escape(t["name"])}">{sub}</div>')

def ts_note(d):
    if not d or not d.get("ts_added"):
        return ""
    n = d.get("ts_events", 0)
    return f'<div class="tsnote">incl. {d["ts_added"]} from {n} private event{"s" if n != 1 else ""} · Tripleseat</div>'

def render_full(d, t, received, single=False):
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
    rows = book_rows(d["reservations"], fit_limit(d["reservations"], 720))
    mark = f'<img class="mark" src="{b64(t["mark"])}" alt="">' if t.get("mark") else ""
    return f"""
<div class="pane full">
  {mark}
  <div class="hdr">
    {logo_block(t)}
    <div class="shiftlab">
      <div class="big">{shift_label(d, single)}</div>
      <div class="date">{pretty_date(d['date'])}</div>
      <div class="upd">OpenTable · updated {updated_label(received)}</div>
    </div>
  </div>
  <div class="body" style="display:grid;grid-template-columns:560px minmax(0,1fr) 700px;gap:56px;height:{body_h}px;padding:34px 64px 30px">
    <div class="hero" style="display:flex;flex-direction:column;justify-content:space-between;min-height:0">
      <div><div class="num">{d['covers']}</div><div class="cap">covers reserved</div>{ts_note(d)}</div>
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
      <div class="hero"><div class="num">{d['covers']}</div><div class="cap">covers reserved</div>{ts_note(d)}</div>
      <div class="stats" style="margin-top:28px">
        <div class="stat"><div class="v">{d['reservation_count']}</div><div class="k">Resos</div></div>
        <div class="stat"><div class="v">{d['parties5']}</div><div class="k">5+ tops</div></div>
        <div class="stat"><div class="v">{d['celebrations']}</div><div class="k">Celebr.</div></div>
        <div class="stat"><div class="v">{d['vip']}</div><div class="k">Alerts</div></div>
      </div>"""
        inner = f'<div class="book" style="margin-top:30px;min-height:0;flex:1"><div class="lbl">The reso&#39;s <span>by seating time</span></div><div class="rows{' roomy' if len(d['reservations']) <= 4 else ''}">{book_rows(d["reservations"], fit_limit(d["reservations"], 400, half=True), half=True)}</div></div>'
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

def page(title, t, inner, data_date, gfonts, lunch_days=None, post_times=None, dinner_post="2:15 pm"):
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
  var postTimes = {json.dumps(post_times) if post_times else "null"};
  var dinnerPost = {json.dumps(dinner_post)}; var dinnerHr = parseInt(dinnerPost, 10) + (dinnerPost.indexOf("pm") > -1 && parseInt(dinnerPost, 10) !== 12 ? 12 : 0);
  function check(){{
    var now = new Date();
    var p = new Intl.DateTimeFormat('en-CA',{{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',hour12:false}}).formatToParts(now);
    var o={{}}; p.forEach(function(x){{o[x.type]=x.value}});
    var today=o.year+'-'+o.month+'-'+o.day; var hr=parseInt(o.hour,10);
    var stale = dataDate && (today>dataDate) && hr>=0 && hr<10;  // next morning, before the 10:15 push
    var msg = "Today's reso's post at 10:15 am";
    if (postTimes) {{
      var dw = new Date(today + "T12:00:00").getDay(); var wk = (dw === 0 || dw === 5 || dw === 6);
      var pt = wk ? postTimes.weekend : postTimes.weekday; msg = "Today's reso's post at " + pt;
      var ph = parseInt(pt, 10) + (pt.indexOf("pm") > -1 && parseInt(pt, 10) !== 12 ? 12 : 0);
      stale = dataDate && (today>dataDate) && hr < ph;
    }}
    if (lunchDays) {{
      var dow = new Date(today + "T12:00:00").getDay();
      if (lunchDays.indexOf(dow) < 0 && hr < dinnerHr && (today>dataDate || dataDate === "")) {{ stale = true; msg = "Dinner only today · reso's post at " + dinnerPost; }}
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
    ap.add_argument("--events", help="Tripleseat Daily Digest HTML (today's). Events for this screen are folded into the book.")
    a = ap.parse_args()
    cfg = STORES[a.store]
    t = THEMES[cfg["theme"]]
    raw = open(a.email, encoding="utf-8", errors="replace").read()
    d = parse_digest(raw)
    if a.dump_json:
        print(json.dumps(d, indent=1))
    split = cfg.get("split_always") or a.force_split or (cfg.get("split_on") and d.get("date") in cfg["split_on"])
    events = parse_tripleseat(open(a.events, encoding="utf-8", errors="replace").read()) if a.events else []
    ts_notes = merge_events(d, events, cfg["theme"])
    if split:
        t2 = THEMES[cfg["right"]]
        d2 = None
        if a.email2:
            d2 = parse_digest(open(a.email2, encoding="utf-8", errors="replace").read())
            ts_notes += merge_events(d2, events, cfg["right"])
        right = render_half(d2, t2, a.received2 or a.received, "right",
                            placeholder=None if d2 else cfg["right_missing"])
        inner = render_half(d, t, a.received, "left") + right
        gf = [t["gfont"], t2["gfont"]]
        title = f"{t['name']} + {t2['name']} — {shift_label(d)}"
    else:
        inner = render_full(d, t, a.received, single=cfg.get("single_shift", False))
        gf = [t["gfont"]]
        title = f"{t['name']} — {shift_label(d, cfg.get('single_shift', False))}"
    out = page(title, t, inner, d.get("date", ""), gf, cfg.get("lunch_days"), cfg.get("post_times"), cfg.get("dinner_post", "2:15 pm"))
    open(a.out, "w", encoding="utf-8").write(out)
    print(f"wrote {a.out}: {d['restaurant']} {d['date']} {d['shift']} covers={d['covers']} res={d['reservation_count']} slots={len(d['slots'])} flagged={sum(1 for r in d['reservations'] if why_for(r))} split={bool(split)} tripleseat_added={d.get('ts_added', 0)}")
    for n in ts_notes:
        print("  tripleseat:", n)
    # Safety net (11.10.26): an older run book may still hand the Bar Italia Beachwood digest to
    # --store beachwood as --email2. Build it as its own screen instead of dropping it.
    if a.store == "beachwood" and a.email2 and not split:
        out2 = os.path.join(os.path.dirname(a.out), "bibeachwood-resos.html")
        d2 = parse_digest(open(a.email2, encoding="utf-8", errors="replace").read())
        n2 = merge_events(d2, events, "bi-beachwood")
        t2 = THEMES["bi-beachwood"]
        inner2 = render_full(d2, t2, a.received2 or a.received, single=False)
        open(out2, "w", encoding="utf-8").write(page(f"{t2['name']} — {shift_label(d2)}", t2, inner2, d2.get("date", ""), [t2["gfont"]], None, None, "2:15 pm"))
        print(f"wrote {out2}: {d2['restaurant']} {d2['date']} {d2['shift']} covers={d2['covers']} res={d2['reservation_count']} slots={len(d2['slots'])} flagged={sum(1 for r in d2['reservations'] if why_for(r))} split=False tripleseat_added={d2.get('ts_added', 0)}  (--email2 on beachwood → separate Bar Italia Beachwood screen)")
        for n in n2:
            print("  tripleseat:", n)

if __name__ == "__main__":
    main()
