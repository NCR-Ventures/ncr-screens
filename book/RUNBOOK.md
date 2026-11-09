# Reso's slides — run book (10:15 am and 2:15 pm ET, daily)

What: turn the OpenTable "Pre-shift Digest" emails into `lolas-resos.html` and `jojos-resos.html`
and push them to `NCR-Ventures/ncr-screens` main. Tim points ScreenCloud at those two files.

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
- Style guides win: Lola's blue/oat milk on black beauty, JoJo's navy/PMS 540, Bar Fuoco light cream with #c98638.
- Google Fonts are blocked in the build container; the TV loads them. Fallback metrics are wider, so a fit here is a fit there.
- Never rename or re-route the live files. Tim repoints ScreenCloud.
