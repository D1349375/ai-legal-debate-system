"""Record the real LegalDebate UI (running at 127.0.0.1:8000) with CDP screencast.

Actions are scheduled against the narration timing in full/words.json; the verification step
waits for the real result, and the second half of that narration is placed after it finishes.
Outputs full/demo/raw/*.jpg + full/demo/log.json (frame timestamps, segment starts, highlight rects).
"""
import asyncio, base64, json, pathlib, time
from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8000/#/test-2026-08-09-e2e-001/"
OUT = pathlib.Path("full/demo"); RAW = OUT / "raw"
PRE, GAP = 0.8, 0.5
D = json.load(open("full/words.json", encoding="utf-8"))


def wt(seg, sub):
    """offset (s) inside segment of the word that contains substring `sub`"""
    text = D[seg]["text"]; pos = text.index(sub); cur = 0; best = D[seg]["words"][0]["t"]
    for w in D[seg]["words"]:
        p = text.find(w["w"], cur)
        if p < 0: continue
        if p <= pos: best = w["t"]
        else: break
        cur = p + len(w["w"])
    return best


def dur(seg): return D[seg]["dur"]


CURSOR_JS = r"""
(() => {
  const add = () => {
    if (document.getElementById('__cur')) return;
    const c = document.createElement('div'); c.id = '__cur';
    c.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M4 2 L4 19 L8.5 15 L11.5 22 L14.5 20.8 L11.6 14 L18 14 Z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    Object.assign(c.style, {position:'fixed', left:'0', top:'0', zIndex:2147483647, pointerEvents:'none',
      transform:'translate(1000px,560px)', filter:'drop-shadow(0 2px 3px rgba(0,0,0,.5))'});
    document.body.appendChild(c);
    const r = document.createElement('div'); r.id = '__rip';
    Object.assign(r.style, {position:'fixed', width:'44px', height:'44px', marginLeft:'-22px', marginTop:'-22px', borderRadius:'50%',
      border:'3px solid rgba(224,183,105,.95)', zIndex:2147483646, pointerEvents:'none', opacity:'0'});
    document.body.appendChild(r);
    addEventListener('mousemove', e => { c.style.transform = `translate(${e.clientX - 3}px,${e.clientY - 2}px)`; }, true);
    addEventListener('mousedown', e => {
      r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
      r.animate([{opacity:1, transform:'scale(.4)'}, {opacity:0, transform:'scale(1.6)'}], {duration: 550, easing:'ease-out'});
    }, true);
  };
  if (document.body) add(); else addEventListener('DOMContentLoaded', add);
})();
"""

HELPERS_JS = r"""
window.__scrollPanel = (target, ms) => {
  const el = document.getElementById('panel'); const y0 = el.scrollTop; const t0 = performance.now();
  const ease = x => x < .5 ? 4*x*x*x : 1 - Math.pow(-2*x + 2, 3)/2;
  const step = now => { const p = Math.min(1, (now - t0)/ms); el.scrollTop = y0 + (target - y0)*ease(p); if (p < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
};
window.__findText = (txt) => {
  const all = [...document.querySelectorAll('#panel *')].filter(e => (e.innerText || '').includes(txt));
  return all[all.length - 1] || null;   // deepest match
};
window.__rect = (el) => { const r = el.getBoundingClientRect(); return {x:r.left, y:r.top, w:r.width, h:r.height}; };
// scroll position so that element's top sits at `frac` of the panel viewport
window.__scrollTargetFor = (el, frac) => {
  const p = document.getElementById('panel'); const pr = p.getBoundingClientRect(); const r = el.getBoundingClientRect();
  return Math.max(0, Math.min(p.scrollHeight - p.clientHeight, p.scrollTop + (r.top - pr.top) - p.clientHeight*frac));
};
true;
"""


async def main():
    RAW.mkdir(parents=True, exist_ok=True)
    for f in RAW.glob("*.jpg"): f.unlink()
    log = {"frames": [], "seg": {}, "rects": {}, "events": {}}
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1280, "height": 720}, device_scale_factor=1.5)
        await ctx.add_init_script(CURSOR_JS)
        pg = await ctx.new_page()
        await pg.goto(BASE + "overview"); await pg.wait_for_timeout(1500)
        await pg.evaluate(HELPERS_JS)
        await pg.mouse.move(1000, 560)

        cdp = await ctx.new_cdp_session(pg)
        t0 = None; n = 0

        async def on_frame(ev):
            nonlocal n
            ts = time.time()
            (RAW / f"{n:05d}.jpg").write_bytes(base64.b64decode(ev["data"]))
            log["frames"].append(ts)
            n += 1
            try: await cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
            except Exception: pass

        cdp.on("Page.screencastFrame", lambda ev: asyncio.ensure_future(on_frame(ev)))
        await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": 1920, "maxHeight": 1080, "everyNthFrame": 1})
        t0 = time.time()
        now = lambda: time.time() - t0

        async def until(r):
            d = r - now()
            if d > 0: await asyncio.sleep(d)

        async def glide(x, y, ms=500):
            await pg.mouse.move(x, y, steps=max(8, ms // 16))

        async def center_of(locator):
            bb = await locator.bounding_box(); return bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2

        async def rect(name, js_el):
            await pg.wait_for_timeout(30)
            log["rects"][name] = {"t": now(), **(await pg.evaluate(f"(() => __rect({js_el}))()"))}

        async def tab(label, at):
            loc = pg.locator("#tabs >> text=" + label).first
            x, y = await center_of(loc)
            await until(at - 0.55); await glide(x, y, 450)
            await until(at); await loc.click()
            log["events"]["tab_" + label] = now()
            await pg.wait_for_timeout(150); await pg.evaluate(HELPERS_JS)

        # ---- s6: overview (case facts + recorded-replay banner)
        s6 = PRE; log["seg"]["s6"] = s6
        await until(s6 + 0.3); await rect("facts", "document.querySelector('#panel section.card')")
        await rect("banner", "document.querySelector('#panel .banner.rec')")
        await tab("攻防過程", s6 + dur("s6") - 0.2)

        # ---- s7: judge question 4
        s7 = s6 + dur("s6") + GAP; log["seg"]["s7"] = s7
        await until(s7 - 0.2)
        target = await pg.evaluate("__scrollTargetFor(document.querySelectorAll('.judge-q')[3], 0.22)")
        await pg.evaluate(f"__scrollPanel({target}, 1300)")
        await until(s7 + 1.4)
        await rect("q4", "document.querySelectorAll('.judge-q')[3]")
        await rect("q4basis", "document.querySelectorAll('.judge-q')[3].querySelector('.judge-q-basis')")

        # ---- s8a: verify all
        s8a = s7 + dur("s7") + GAP; log["seg"]["s8a"] = s8a
        await tab("引用查證", s8a - 0.5)
        btn = pg.locator("#panel button.btn.primary").first
        x, y = await center_of(btn)
        click_at = s8a + wt("s8a", "查證")
        await until(click_at - 0.6); await glide(x, y, 500)
        await until(click_at); await btn.click()
        log["events"]["verify_click"] = now()
        await pg.wait_for_function("document.querySelector('#panel button.btn.primary').innerText.includes('查證中')", timeout=5000, polling=30)
        await pg.wait_for_function("!document.querySelector('#panel button.btn.primary').innerText.includes('查證中')", timeout=60000, polling=100)
        log["events"]["verify_done"] = now()
        await pg.mouse.move(1180, 640, steps=12)
        await pg.wait_for_timeout(200)
        await rect("vrow", "__findText('最高法院105年度台簡上字第33號').closest('.vrow')")
        await rect("vbtn", "document.querySelector('#panel button.btn.primary')")
        await rect("vusedby", "[...__findText('最高法院105年度台簡上字第33號').closest('.vrow').querySelectorAll('.chip')].find(c => c.innerText.includes('引用者'))")

        # ---- s8b: result narration starts after the real run finished
        s8b = max(log["events"]["verify_done"] + 0.6, s8a + dur("s8a") + GAP); log["seg"]["s8b"] = s8b

        # ---- s9: finalize (aggregate tab)
        s9 = s8b + dur("s8b") + GAP; log["seg"]["s9"] = s9
        await tab("機械彙整", s9 - 0.6)
        fbtn = pg.locator("#panel button.btn.primary").first
        x, y = await center_of(fbtn)
        await until(s9 - 0.05); await glide(x, y, 400)
        await fbtn.click(); log["events"]["finalize_click"] = now()
        await pg.wait_for_function("(document.getElementById('panel').innerText||'').includes('0.3158')", timeout=10000, polling=50)
        log["events"]["finalize_done"] = now()
        await pg.evaluate(HELPERS_JS)
        await until(s9 + 1.0)
        target = await pg.evaluate("__scrollTargetFor(document.querySelector('.drift-row').closest('.card') || document.querySelector('.drift-row'), 0.0)")
        await pg.evaluate(f"__scrollPanel({target}, 1100)")
        await pg.mouse.move(1180, 640, steps=10)
        await until(s9 + 2.3)
        await rect("drift_p", "document.querySelectorAll('.drift-row')[0]")
        await rect("dropped", "[...document.querySelectorAll('.drift-row')[0].querySelectorAll('*')].filter(e => (e.innerText||'').includes('不再引用') && (e.innerText||'').includes('105')).pop()")
        await rect("drift_all", "document.querySelector('.drift-row').parentElement")

        # ---- s10: pleading skeleton
        s10 = s9 + dur("s9") + GAP; log["seg"]["s10"] = s10
        await tab("訴狀骨架", s10 - 0.5)
        await until(s10 + wt("s10", "訴之聲明") - 0.6)
        target = await pg.evaluate("__scrollTargetFor([...document.querySelectorAll('.pl-head')].find(e => e.innerText.trim() === '訴之聲明'), 0.08)")
        await pg.evaluate(f"__scrollPanel({target}, 1100)")
        await until(s10 + wt("s10", "訴之聲明") + 0.8)
        await rect("claims", "(() => { const h = [...document.querySelectorAll('.pl-head')].find(e => e.innerText.trim() === '訴之聲明'); return h; })()")
        await rect("pdoc", "document.querySelector('.pleading-doc')")
        await until(s10 + wt("s10", "事實") - 0.3)
        target = await pg.evaluate("__scrollTargetFor([...document.querySelectorAll('.pl-head')].find(e => e.innerText.trim().startsWith('事實')), 0.08)")
        await pg.evaluate(f"__scrollPanel({target}, 1600)")
        end = s10 + dur("s10") + 0.8
        await until(end)
        log["seg"]["end"] = end
        await cdp.send("Page.stopScreencast")
        await asyncio.sleep(0.3)
        log["t0"] = t0
        log["frames"] = [ts - t0 for ts in log["frames"]]
        json.dump(log, open(OUT / "log.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("frames", len(log["frames"]), "segs", {k: round(v, 2) for k, v in log["seg"].items()})
        print("events", {k: round(v, 2) for k, v in log["events"].items()})
        await b.close()

asyncio.run(main())
