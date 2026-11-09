#!/usr/bin/env python3
"""verify.py FILE.html [FILE2.html ...] -> screenshots + overflow numbers.
Renders at exactly 1920x1080, full_page=False, waits 2.5s for Google Fonts.
Prints scrollHeight/scrollWidth and count of elements past the edges.
Writes <name>.png next to the HTML (or into --outdir)."""
import sys, os, asyncio, argparse
from playwright.async_api import async_playwright

async def run(files, outdir, stale):
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1920, "height": 1080})
        ok = True
        for f in files:
            await pg.goto("file://" + os.path.abspath(f))
            await pg.wait_for_timeout(2500)
            if stale:
                await pg.evaluate("document.body.classList.add('stale')")
                await pg.wait_for_timeout(200)
            m = await pg.evaluate("""() => {
              const els=[...document.querySelectorAll('.stage *')].filter(e=>getComputedStyle(e).display!=='none');
              let bad=[];
              for (const e of els){const r=e.getBoundingClientRect(); if(r.width===0||r.height===0) continue;
                if(r.bottom>1080.5||r.right>1920.5) bad.push(e.className+' b='+Math.round(r.bottom)+' r='+Math.round(r.right));}
              return {sh:document.body.scrollHeight, sw:document.body.scrollWidth, bad:bad.slice(0,8), nbad:bad.length};
            }""")
            name = os.path.splitext(os.path.basename(f))[0] + (".stale" if stale else "") + ".png"
            out = os.path.join(outdir or os.path.dirname(os.path.abspath(f)), name)
            await pg.screenshot(path=out, full_page=False)
            flag = "OK " if (m["sh"] <= 1080 and m["sw"] <= 1920 and m["nbad"] == 0) else "FAIL"
            ok &= flag == "OK "
            print(f"{flag} {f}: scrollH={m['sh']} scrollW={m['sw']} overflow={m['nbad']} {m['bad']} -> {out}")
        await b.close()
        return ok

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--outdir")
    ap.add_argument("--stale", action="store_true")
    a = ap.parse_args()
    sys.exit(0 if asyncio.run(run(a.files, a.outdir, a.stale)) else 1)
