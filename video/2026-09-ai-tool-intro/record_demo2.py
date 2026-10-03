"""Record the real LegalDebate UI at a steady 30 fps.

Virtual clock: for every output frame we set the cursor / scroll state, then capture — so scrolls are
smooth. The one step whose timing matters (live citation verification) is captured in real time with
the CDP screencast and resampled; everything after it is scheduled from the real completion time.
Outputs full/demo/frames/NNNNN.jpg (30 fps, frame 0 = recording t=0) and full/demo/log.json.
"""
import asyncio, base64, json, math, pathlib, time
from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8000/#/test-2026-08-09-e2e-001/"
OUT = pathlib.Path("full/demo"); FR = OUT / "frames"
FPS, PRE, GAP = 30, 0.8, 0.5
D = json.load(open("full/words.json", encoding="utf-8"))


def wt(seg, sub):
    text = D[seg]["text"]; pos = text.index(sub); cur = 0; best = D[seg]["words"][0]["t"]
    for w in D[seg]["words"]:
        p = text.find(w["w"], cur)
        if p < 0: continue
        if p <= pos: best = w["t"]
        else: break
        cur = p + len(w["w"])
    return best


def dur(seg): return D[seg]["dur"]
def ease(x): x = min(1, max(0, x)); return 4 * x ** 3 if x < .5 else 1 - (-2 * x + 2) ** 3 / 2


CURSOR_JS = open("full/record_demo.py", encoding="utf-8").read().split('CURSOR_JS = r"""')[1].split('"""')[0]
HELPERS_JS = r"""
window.__findText = (txt) => { const all = [...document.querySelectorAll('#panel *')].filter(e => (e.innerText || '').includes(txt)); return all[all.length - 1] || null; };
window.__rect = (el) => { const r = el.getBoundingClientRect(); return {x:r.left, y:r.top, w:r.width, h:r.height}; };
window.__scrollTargetFor = (el, frac) => { const p = document.getElementById('panel'); const pr = p.getBoundingClientRect(); const r = el.getBoundingClientRect();
  return Math.max(0, Math.min(p.scrollHeight - p.clientHeight, p.scrollTop + (r.top - pr.top) - p.clientHeight*frac)); };
true;
"""


async def main():
    FR.mkdir(parents=True, exist_ok=True)
    for f in FR.glob("*.jpg"): f.unlink()
    log = {"fps": FPS, "seg": {}, "rects": {}, "events": {}}
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1280, "height": 720}, device_scale_factor=1.5)
        await ctx.add_init_script(CURSOR_JS)
        pg = await ctx.new_page()
        await pg.goto(BASE + "overview"); await pg.wait_for_timeout(1500)
        await pg.evaluate(HELPERS_JS)
        cdp = await ctx.new_cdp_session(pg)

        st = {"frame": 0, "cur": (1000.0, 560.0)}
        cursor_moves = []   # (r0, r1, (x0,y0) or None, (x1,y1))
        scrolls = []        # dicts: r0, r1, target_js, y0, y1
        events = []         # (r, coroutine factory)

        async def capture():
            r = await cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 92})
            (FR / f"{st['frame']:05d}.jpg").write_bytes(base64.b64decode(r["data"]))
            st["frame"] += 1

        async def advance_to(r_end):
            """render virtual frames until time r_end"""
            while st["frame"] / FPS < r_end:
                r = st["frame"] / FPS
                for ev in [e for e in events if e[0] <= r]:
                    events.remove(ev); await ev[1]()
                for m in cursor_moves:
                    if m[0] <= r:
                        if m[2] is None: m[2] = st["cur"]
                        k = ease((r - m[0]) / max(1e-6, m[1] - m[0]))
                        st["cur"] = (m[2][0] + (m[3][0] - m[2][0]) * k, m[2][1] + (m[3][1] - m[2][1]) * k)
                cursor_moves[:] = [m for m in cursor_moves if m[1] > r]
                await pg.mouse.move(*st["cur"])
                for s in scrolls:
                    if s["r0"] <= r:
                        if s["y0"] is None:
                            s["y0"] = await pg.evaluate("document.getElementById('panel').scrollTop")
                            s["y1"] = await pg.evaluate(s["target_js"])
                        y = s["y0"] + (s["y1"] - s["y0"]) * ease((r - s["r0"]) / (s["r1"] - s["r0"]))
                        await pg.evaluate(f"document.getElementById('panel').scrollTop = {y}")
                scrolls[:] = [s for s in scrolls if s["y0"] is None or s["r1"] + 1 / FPS > r]
                await capture()

        async def center(sel):
            bb = await pg.locator(sel).first.bounding_box(); return (bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)

        def move(r0, r1, xy): cursor_moves.append([r0, r1, None, xy])
        def scroll(r0, r1, target_js): scrolls.append({"r0": r0, "r1": r1, "target_js": target_js, "y0": None, "y1": None})

        def rect(r, name, js_el):
            async def f():
                log["rects"][name] = {"t": st["frame"] / FPS, **(await pg.evaluate(f"(() => __rect({js_el}))()"))}
            events.append((r, f))

        async def schedule_tab(label, r_click):
            sel = f"#tabs >> text={label}"
            xy = await center(sel)
            move(r_click - 0.6, r_click - 0.05, xy)
            async def f():
                await pg.locator(sel).first.click()
                log["events"]["tab_" + label] = st["frame"] / FPS
                await pg.wait_for_timeout(120); await pg.evaluate(HELPERS_JS)
            events.append((r_click, f))

        # ---------- s6 overview → s7 Q4
        s6 = PRE; s7 = s6 + dur("s6") + GAP
        log["seg"].update(s6=s6, s7=s7)
        rect(s6 + 0.2, "facts", "document.querySelector('#panel section.card')")
        rect(s6 + 0.2, "banner", "document.querySelector('#panel .banner.rec')")
        await schedule_tab("攻防過程", s6 + dur("s6") - 0.15)
        await advance_to(s7 - 0.15)
        scroll(s7 - 0.15, s7 + 1.15, "__scrollTargetFor(document.querySelectorAll('.judge-q')[3], 0.22)")
        move(s7, s7 + 1.0, (1160, 660))
        rect(s7 + 1.35, "q4", "document.querySelectorAll('.judge-q')[3]")
        rect(s7 + 1.35, "q4basis", "document.querySelectorAll('.judge-q')[3].querySelector('.judge-q-basis')")

        # ---------- s8a verify (live)
        s8a = s7 + dur("s7") + GAP; log["seg"]["s8a"] = s8a
        await advance_to(s8a - 0.9)
        await schedule_tab("引用查證", s8a - 0.4)
        await advance_to(s8a - 0.3)
        click_r = s8a + wt("s8a", "查證")
        move(click_r - 0.65, click_r - 0.05, await center("#panel button.btn.primary"))
        await advance_to(click_r)

        frames_rt = []
        async def on_frame(ev):
            frames_rt.append((time.time(), ev["data"]))
            try: await cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
            except Exception: pass
        cdp.on("Page.screencastFrame", lambda ev: asyncio.ensure_future(on_frame(ev)))
        await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": 1920, "maxHeight": 1080})
        await asyncio.sleep(0.25)
        t_click = time.time()
        await pg.locator("#panel button.btn.primary").first.click()
        await pg.wait_for_function("document.querySelector('#panel button.btn.primary').innerText.includes('查證中')", timeout=5000, polling=30)
        await pg.wait_for_function("!document.querySelector('#panel button.btn.primary').innerText.includes('查證中')", timeout=90000, polling=50)
        elapsed = time.time() - t_click
        await asyncio.sleep(0.3)
        await cdp.send("Page.stopScreencast")
        frames_rt.sort()
        n_rt = math.ceil(elapsed * FPS)
        last = None
        for k in range(n_rt):
            tk = t_click + k / FPS
            cand = [d for (ts, d) in frames_rt if ts <= tk]
            last = cand[-1] if cand else (last or frames_rt[0][1])
            (FR / f"{st['frame']:05d}.jpg").write_bytes(base64.b64decode(last)); st["frame"] += 1
        r_done = st["frame"] / FPS
        log["events"].update(verify_click=click_r, verify_done=r_done, verify_elapsed=elapsed, verify_rt_frames=len(frames_rt))
        await pg.evaluate(HELPERS_JS)
        move(r_done + 0.1, r_done + 0.8, (1170, 670))
        rect(r_done + 0.3, "vrow", "__findText('最高法院105年度台簡上字第33號').closest('.vrow')")
        rect(r_done + 0.3, "vbtn", "document.querySelector('#panel button.btn.primary')")
        rect(r_done + 0.3, "vusedby", "[...__findText('最高法院105年度台簡上字第33號').closest('.vrow').querySelectorAll('.chip')].find(c => c.innerText.includes('引用者'))")
        rect(r_done + 0.3, "vsummary", "document.querySelector('#panel .controls').nextElementSibling")

        # ---------- s8b / s9 finalize
        s8b = max(r_done + 0.6, s8a + dur("s8a") + GAP); s9 = s8b + dur("s8b") + GAP
        log["seg"].update(s8b=s8b, s9=s9)
        await schedule_tab("機械彙整", s9 - 0.6)
        await advance_to(s9 - 0.5)
        run_xy = await center("#panel button.btn.primary")
        move(s9 - 0.5, s9 - 0.02, run_xy)
        async def fin():
            await pg.locator("#panel button.btn.primary").first.click()
            await pg.wait_for_function("(document.getElementById('panel').innerText||'').includes('0.3158')", timeout=10000, polling=30)
            log["events"]["finalize_click"] = st["frame"] / FPS
            await pg.evaluate(HELPERS_JS)
        events.append((s9, fin))
        scroll(s9 + 0.9, s9 + 2.0, "__scrollTargetFor(document.querySelector('.drift-row').closest('.card') || document.querySelector('.drift-row'), 0.0)")
        move(s9 + 0.9, s9 + 1.6, (1170, 670))
        rect(s9 + 2.2, "drift_p", "document.querySelectorAll('.drift-row')[0]")
        rect(s9 + 2.2, "dropped", "[...document.querySelectorAll('.drift-row')[0].querySelectorAll('*')].filter(e => (e.innerText||'').includes('不再引用') && (e.innerText||'').includes('105')).pop()")
        rect(s9 + 2.2, "drift_all", "document.querySelector('.drift-row').parentElement")

        # ---------- s10 pleading
        s10 = s9 + dur("s9") + GAP; end = s10 + dur("s10") + 0.8
        log["seg"].update(s10=s10, end=end)
        await advance_to(s10 - 1.2)
        await schedule_tab("訴狀骨架", s10 - 0.5)
        a = s10 + wt("s10", "訴之聲明") - 0.6
        scroll(a, a + 1.1, "__scrollTargetFor([...document.querySelectorAll('.pl-head')].find(e => e.innerText.trim() === '訴之聲明'), 0.06)")
        move(s10, s10 + 0.8, (1170, 670))
        rect(a + 1.3, "claims", "[...document.querySelectorAll('.pl-head')].find(e => e.innerText.trim() === '訴之聲明').parentElement")
        rect(a + 1.3, "claims_head", "[...document.querySelectorAll('.pl-head')].find(e => e.innerText.trim() === '訴之聲明')")
        c = s10 + wt("s10", "事實") - 0.3
        scroll(c, c + 1.6, "__scrollTargetFor([...document.querySelectorAll('.pl-head')].find(e => e.innerText.trim().startsWith('事實')), 0.06)")
        await advance_to(end)
        log["frames"] = st["frame"]
        json.dump(log, open(OUT / "log.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("frames", st["frame"], "segs", {k: round(v, 2) for k, v in log["seg"].items()})
        print("events", {k: (round(v, 2) if isinstance(v, float) else v) for k, v in log["events"].items()})
        await b.close()

asyncio.run(main())
