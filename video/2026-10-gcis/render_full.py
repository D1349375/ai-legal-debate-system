"""Resumable parallel frame renderer for video.html (60 fps). Usage: render_full.py W K"""
import pathlib, json, time, base64, sys
from playwright.sync_api import sync_playwright
W, K = int(sys.argv[1]), int(sys.argv[2])
FPS = 60
url = pathlib.Path("video.html").resolve().as_uri() + "#capture"
out = pathlib.Path("frames"); out.mkdir(exist_ok=True)
t0 = time.time()

def session(p):
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1920, "height": 1080})
    pg.goto(url); pg.wait_for_timeout(800)
    return b, pg, pg.context.new_cdp_session(pg)

with sync_playwright() as p:
    b, pg, cdp = session(p)
    total = pg.evaluate("TOTAL")
    if K == 0:
        json.dump({"total": total, "start": pg.evaluate("START"), "subs": pg.evaluate("SUBS")}, open("timeline.json", "w", encoding="utf-8"), ensure_ascii=False)
    n = int(total * FPS); i = K
    while i < n:
        f = out / f"{i:05d}.jpg"
        if f.exists() and f.stat().st_size > 0: i += W; continue
        try:
            pg.evaluate(f"render({i / FPS})")
            r = cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 93})
            f.write_bytes(base64.b64decode(r["data"])); i += W
        except Exception as e:
            print("retry", i, type(e).__name__, flush=True)
            try: b.close()
            except Exception: pass
            b, pg, cdp = session(p)
    b.close()
print("worker", K, "done", round(time.time() - t0), "s", flush=True)
