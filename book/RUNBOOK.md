# Reso's slides — run book (10:15 am, 11:15 am, and 2:15 pm ET, daily)

The 11:15 run exists for the Lakehouse Mon–Thu digest. At 11:15, build only stores whose newest digest arrived after 10:15 (normally just Lakehouse); if nothing new, push nothing and report nothing.

What: turn the OpenTable "Pre-shift Digest" emails into one `<store>-resos.html` per screen
and push them to `NCR-Ventures/ncr-screens` main. Tim points ScreenCloud at the files.

## Screens and digest matching (subject line → store)

| Output file | `--store` | Digest subject contains | Layout |
|---|---|---|---|
| lolas-resos.html | lolas | `Lola's Bistro` | full |
| 17river-resos.html | 17river | `17 River` | full |
| jojos-resos.html | jojos | `JoJo's Bar` (+ `Bar Fuoco` as `--email2` on Après dates) | full; split with Après Fuoco on 11/25, 11/27, 11/28, 12/4, 12/5, 12/11, 12/12, 12/18, 12/19 |
| beachwood-resos.html | beachwood | left `Cedar Creek`, right (`--email2`) `Bar Italia` + `Beachwood` | always split CCG / Bar Italia Beachwood |
| sarasota-resos.html | sarasota | `Bar Italia` + (`Sarasota` or `Lakewood Ranch`) | full, header "Lakewood Ranch" |
| etc-resos.html | etc | `Bar Italia` + (`Easton` or `Columbus`) | full |
| winterpark-resos.html | winterpark | `Bar Italia` + `Winter Park` | full |
| lakehouse-resos.html | lakehouse | `Lakehouse` | full, header "Today's Reso's" — **one shift a day**; digest arrives ~11:00 am Mon–Thu (built by the 11:15 run) and ~10:00 am Fri–Sun (10:15 run). The 2:15 run never rebuilds it. |
| lakewood-resos.html | lakewood | `Bar Italia` + `Lakewood` (not `Lakewood Ranch`) | full. **Lunch only Fri–Sun** — on Mon–Thu ignore any Lakewood lunch digest at the 10:15 run; the slide shows "Dinner only today · reso's post at 2:15 pm" until the dinner build. |

Bar Fuoco's OpenTable listing IS Après Fuoco (same restaurant; Bar Fuoco is closed for the season except those pop-up dates). Its digest arrives every day; on non-split dates ignore it silently — it is not an unmatched store and gets no slide of its own.
Unknown restaurant name in a digest → don't guess; skip it and name it in the report.

## Steps

1. Load Outlook tools: `ToolSearch select:mcp__Microsoft_365__outlook_email_search,mcp__Microsoft_365__read_resource`.
2. Find today's digests. Search `folderName: "OpenTable Reports"`, `order: newest`, limit 10.
   If that folder is empty, search the Inbox with `query: "Pre-shift Digest"`, `afterDateTime: today`.
   Keep only messages from `restaurant-insights@reporting.opentable.com` received **today** (ET).
   For each store take the newest one: subject contains `Lola's Bistro` → lolas; `JoJo's Bar` → jojos;
   `Bar Fuoco` or `Après Fuoco` → fuoco (only matters on split dates).
   At the 10:15 run the digest is the Lunch one; at 2:15 it should be the Dinner one. Use whatever is newest.
3. `read_resource` each message. Save `body.content` verbatim to the scratchpad as `<store>.html`
   (never into the repo — it has guest names and phone fragments). Note `receivedDateTime`.
4. `add_repo NCR-Ventures/ncr-screens` with push access, then
   `git clone --depth 1 https://github.com/NCR-Ventures/ncr-screens /home/claude/ncr-screens`.
5. Build:
   ```
   python3 book/build_book.py --store lolas --email <scratch>/lolas.html --received <iso> --out lolas-resos.html
   python3 book/build_book.py --store jojos --email <scratch>/jojos.html --received <iso> --out jojos-resos.html \
       [--fuoco-email <scratch>/fuoco.html --fuoco-received <iso>]   # on Après Fuoco dates, if a Fuoco digest exists
   ```
   The script decides the JoJo's/Après split from the date (APRES_DATES in build_book.py).
6. Verify: `python3 book/verify.py lolas-resos.html jojos-resos.html --outdir <scratch>` → every line must be `OK`.
   Then **view each PNG** and confirm nothing is clipped or empty-looking. FAIL → fix or stop; do not push a broken slide.
7. Commit only the two HTML files (`git add lolas-resos.html jojos-resos.html`), message like
   `resos: Lola's lunch 25 cov / JoJo's lunch 15 cov — 11.9 10:15`, push to main.
   Confirm with `git show origin/main:lolas-resos.html | grep -o "Lunch Reso\|Dinner Reso"`.
8. If a store has **no digest today**, leave its file alone and tell Tim which store is missing.
9. Report in one or two lines: store, shift, covers, reso count, anything flagged (alerts, big parties), pushed yes/no.

## Rules
- Names on the board are first name + last initial. Never phone numbers, never spend.
- Style guides win: Lola's blue/oat milk on black beauty, JoJo's navy/PMS 540, CCG digital blue #074b64, Bar Italia green/gold, Après Fuoco cream #faf6ef with Après red #a02828 (logos from Tim 11.9.26: apres-wordmark-red / -white, apres-badge in book/assets).
- Google Fonts are blocked in the build container; the TV loads them. Fallback metrics are wider, so a fit here is a fit there.
- Never rename or re-route the live files. Tim repoints ScreenCloud.
