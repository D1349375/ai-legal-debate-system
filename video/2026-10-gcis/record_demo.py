"""Record the real LegalDebate UI for s8–s11 at a steady 30 fps (run in the work folder, server on :8000).

Virtual clock: for every output frame we set the cursor / scroll state, then capture, so scrolls are smooth.
Steps whose timing is real (live citation verification, live party check) are captured in real time with the
CDP screencast and resampled; everything after them is scheduled from the real completion time.
The citation-verification wait is cut: we keep the first KEEP_HEAD and last KEEP_TAIL seconds and log how many
seconds were skipped, so video.html can label the cut.

The dissolved company's BAN is read from the DISSOLVED_BAN environment variable (or dissolved_ban.txt next to the
work folder) and is never written anywhere. Its name, BAN and address are blurred by CSS injected before page load.
Outputs full/demo/frames/NNNNN.jpg (frame 0 = recording t=0) and full/demo/log.json.
"""
import asyncio, base64, json, math, os, pathlib, sys, time
from playwright.async_api import async_playwright

CASE = "test-2026-08-08-001"
BASE = f"http://127.0.0.1:8000/#/{CASE}/"
OUT = pathlib.Path("full/demo"); FR = OUT / "frames"
FPS, PRE, GAP = 30, 0.8, 0.4
KEEP_HEAD, KEEP_TAIL, CUT_OVER = 1.6, 1.0, 12.0   # only cut waits longer than CUT_OVER seconds
PLAINTIFF_BAN = "22099131"
DEFENDANT_BAN = os.environ.get("DISSOLVED_BAN") or pathlib.Path("dissolved_ban.txt").read_text(encoding="utf-8").strip()
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

# Blur the defendant (dissolved company): BAN / name inputs, result name, main-office address, director list,
# and in the pleading card the second row's name, BAN and address. Injected before any page script runs.
MASK_CSS = r"""
.party-grid > section.card:nth-child(2) .party-controls input,
.party-grid > section.card:nth-child(2) .party-result-title strong,
.party-grid > section.card:nth-child(2) .party-facts > .party-fact:nth-child(3) > span:last-child,
.party-grid > section.card:nth-child(2) .party-list-row,
.party-pleading-row ~ .party-pleading-row > .party-fact:nth-child(2) > span:last-child,
.party-pleading-row ~ .party-pleading-row > .party-fact:nth-child(3) > span:last-child,
.party-pleading-row ~ .party-pleading-row > .party-fact:nth-child(5) > span:last-child
{ filter: blur(9px) !important; user-select: none !important; }
.party-grid > section.card:nth-child(2) .party-controls input { color: transparent !important; text-shadow: 0 0 14px #9aa3b2 !important; }
.party-grid > section.card:nth-child(2) details.fold .fold-body { display: none !important; }
"""
MASK_JS = """(() => { const add = () => { if (document.getElementById('__mask')) return;
  const s = document.createElement('style'); s.id = '__mask'; s.textContent = %s; (document.head || document.documentElement).appendChild(s); };
  if (document.documentElement) add(); document.addEventListener('DOMContentLoaded', add); })();""" % json.dumps(MASK_CSS)

HELPERS_JS = r"""
window.__findText = (txt) => { const all = [...document.querySelectorAll('#panel *')].filter(e => (e.innerText || '').includes(txt)); return all[all.length - 1] || null; };
window.__rect = (el) => { const r = el.getBoundingClientRect(); return {x:r.left, y:r.top, w:r.width, h:r.height}; };
window.__scrollTargetFor = (el, frac) => { const p = document.getElementById('panel'); const pr = p.getBoundingClientRect(); const r = el.getBoundingClientRect();
  return Math.max(0, Math.min(p.scrollHeight - p.clientHeight, p.scrollTop + (r.top - pr.top) - p.clientHeight*frac)); };
window.__dcard = () => document.querySelectorAll('.party-grid > section.card')[1];
window.__pcard = () => [...document.querySelectorAll('#panel section.card')].find(c => (c.querySelector('.card-title')||{}).innerText === '當事人資料（依商工登記帶入）');
window.__plHead = (s) => [...document.querySelectorAll('.pl-head')].find(e => e.innerText.trim().startsWith(s));
window.__fact = (root, label) => [...root.querySelectorAll('.party-fact')].find(f => f.innerText.startsWith(label));
window.__jcard = () => [...document.querySelectorAll('#panel section.card')].find(c => (c.querySelector('.card-title')||{}).innerText === '被告管轄法院建議');
true;
"""


async def main():
    FR.mkdir(parents=True, exist_ok=True)
    for f in FR.glob("*.jpg"): f.unlink()
    log = {"fps": FPS, "seg": {}, "rects": {}, "events": {}}
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1280, "height": 720}, device_scale_factor=1.5)
        await ctx.add_init_script(MASK_JS)
        await ctx.add_init_script(CURSOR_JS)
        pg = await ctx.new_page()

        # ---------- preparation (not recorded): live party checks for both sides
        await pg.goto(BASE + "parties"); await pg.wait_for_timeout(1500)
        await pg.evaluate(HELPERS_JS)
        assert await pg.evaluate("!!document.getElementById('__mask')"), "mask CSS missing"
        for idx, ban in ((0, PLAINTIFF_BAN), (1, DEFENDANT_BAN)):
            cardsel = f".party-grid > section.card >> nth={idx}"
            await pg.locator(cardsel).locator(".party-controls input").first.fill(ban)
            await pg.locator(cardsel).locator(".party-controls button.btn.primary").click()
            await pg.wait_for_function(f"(() => {{ const c = document.querySelectorAll('.party-grid > section.card')[{idx}]; return c && c.querySelector('.party-result') && !c.innerText.includes('查詢中'); }})()", timeout=30000)
            txt = await pg.evaluate(f"document.querySelectorAll('.party-grid > section.card')[{idx}].innerText")
            if "錄製的查詢結果" in txt or "即時查詢失敗" in txt or "查核未完成" in txt:
                sys.exit(f"prep: party check {idx} was not a live success; re-run")
        dtxt = await pg.evaluate("__dcard().innerText")
        assert "解散" in dtxt and "待確認" in dtxt and "全體股東為清算人" in dtxt and "監察人" not in dtxt, "defendant warnings unexpected"
        await pg.locator("#tabs >> text=案件總覽").first.click(); await pg.wait_for_timeout(800)
        await pg.evaluate("document.getElementById('panel').scrollTop = 0")
        await pg.evaluate(HELPERS_JS)
        cdp = await ctx.new_cdp_session(pg)

        st = {"frame": 0, "cur": (1000.0, 560.0)}
        cursor_moves, scrolls, events = [], [], []

        async def capture():
            r = await cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 92})
            (FR / f"{st['frame']:05d}.jpg").write_bytes(base64.b64decode(r["data"]))
            st["frame"] += 1

        async def advance_to(r_end):
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

        async def center(js_el):
            r = await pg.evaluate(f"(() => __rect({js_el}))()"); return (r["x"] + r["w"] / 2, r["y"] + r["h"] / 2)

        def move(r0, r1, xy): cursor_moves.append([r0, r1, None, xy])
        def scroll(r0, r1, target_js): scrolls.append({"r0": r0, "r1": r1, "target_js": target_js, "y0": None, "y1": None})

        def rect(r, name, js_el):
            async def f():
                log["rects"][name] = {"t": st["frame"] / FPS, **(await pg.evaluate(f"(() => __rect({js_el}))()"))}
            events.append((r, f))

        async def schedule_tab(label, r_click):
            sel = f"#tabs >> text={label}"
            bb = await pg.locator(sel).first.bounding_box(); xy = (bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
            move(r_click - 0.6, r_click - 0.05, xy)
            async def f():
                await pg.locator(sel).first.click()
                log["events"]["tab_" + label] = st["frame"] / FPS
                await pg.wait_for_timeout(120); await pg.evaluate(HELPERS_JS)
                await pg.evaluate("document.getElementById('panel').scrollTop = 0")
            events.append((r_click, f))

        async def realtime(started_js, done_js, timeout_ms, cut=False):
            """click at the cursor, screencast in real time until done, resample to FPS (optionally cutting the middle)."""
            frames_rt = []
            async def on_frame(ev):
                frames_rt.append((time.time(), ev["data"]))
                try: await cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
                except Exception: pass
            handler = lambda ev: asyncio.ensure_future(on_frame(ev))
            cdp.on("Page.screencastFrame", handler)
            await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": 1920, "maxHeight": 1080})
            await asyncio.sleep(0.25)
            t_click = time.time()
            await pg.mouse.click(*st["cur"])
            await pg.wait_for_function(started_js, timeout=5000, polling=30)
            await pg.wait_for_function(done_js, timeout=timeout_ms, polling=50)
            elapsed = time.time() - t_click
            await asyncio.sleep(0.3)
            await cdp.send("Page.stopScreencast")
            cdp.remove_listener("Page.screencastFrame", handler)
            frames_rt.sort()
            n_rt = math.ceil(elapsed * FPS)
            ks = list(range(n_rt)); cut_info = None
            if cut and elapsed > CUT_OVER:
                head, tail0 = int(KEEP_HEAD * FPS), n_rt - int(KEEP_TAIL * FPS)
                ks = list(range(head)) + list(range(tail0, n_rt))
                cut_info = {"cut_r": st["frame"] / FPS + head / FPS, "skipped": (tail0 - head) / FPS, "tail_from": tail0 / FPS}
            last = None
            for k in ks:
                tk = t_click + k / FPS
                cand = [d for (ts, d) in frames_rt if ts <= tk]
                last = cand[-1] if cand else (last or frames_rt[0][1])
                (FR / f"{st['frame']:05d}.jpg").write_bytes(base64.b64decode(last)); st["frame"] += 1
            await pg.evaluate(HELPERS_JS)
            return elapsed, len(frames_rt), cut_info

        # ---------- s8: overview → debate, judge question 1
        s8 = PRE; log["seg"]["s8"] = s8
        rect(s8 + 0.2, "facts", "document.querySelector('#panel section.card')")
        rect(s8 + 0.2, "banner", "document.querySelector('#panel .banner.rec')")
        move(s8, s8 + 1.0, (900, 520))
        q_r = s8 + wt("s8", "法官追問")
        await schedule_tab("攻防過程", q_r - 1.3)
        await advance_to(q_r - 0.75)
        scroll(q_r - 0.75, q_r + 0.45, "__scrollTargetFor(document.querySelectorAll('.judge-q')[0], 0.18)")
        move(q_r - 0.6, q_r + 0.5, (1150, 650))
        rect(q_r + 0.6, "q1", "document.querySelectorAll('.judge-q')[0]")
        rect(q_r + 0.6, "q1text", "document.querySelectorAll('.judge-q')[0].querySelector('.judge-q-text')")

        # ---------- s9: live citation verification (wait cut)
        s9 = s8 + dur("s8") + GAP; log["seg"]["s9"] = s9
        await advance_to(s9 - 0.9)
        await schedule_tab("引用查證", s9 - 0.45)
        await advance_to(s9 - 0.35)
        btn = "document.querySelector('#panel .controls button.btn.primary')"
        click_r = s9 + 0.35
        move(click_r - 0.6, click_r - 0.05, await center(btn))
        await advance_to(click_r)
        elapsed, nrt, cut = await realtime(f"{btn}.innerText.includes('查證中')",
                                           f"!{btn}.innerText.includes('查證中')", 600000, cut=True)
        r_done = st["frame"] / FPS
        tiles = await pg.evaluate("document.querySelector('#panel .stat-grid').innerText")
        rows = await pg.evaluate("[...document.querySelectorAll('#panel .vrow')].map(v => v.querySelector('.pill').innerText.trim())")
        log["events"].update(verify_click=click_r, verify_done=r_done, verify_elapsed=elapsed, verify_rt_frames=nrt,
                             verify_cut=cut, verify_tiles=tiles, verify_rows=rows)
        print("verify", round(elapsed, 1), "s", cut, rows, flush=True)
        move(r_done + 0.1, r_done + 0.8, (1170, 670))
        rect(r_done + 0.2, "vtiles", "document.querySelector('#panel .stat-grid')")
        rect(r_done + 0.2, "vtile_ok", "document.querySelector('#panel .stat-grid').children[0]")

        # ---------- s10: pleading with party card
        s10 = max(r_done + 1.0, s9 + dur("s9") + GAP); log["seg"]["s10"] = s10
        await advance_to(s10 - 0.9)
        await schedule_tab("訴狀骨架", s10 - 0.45)
        rect(s10 - 0.2, "pcard0", "__pcard()")
        rect(s10 - 0.2, "prow_p0", "__pcard().querySelectorAll('.party-pleading-row')[0]")
        a = s10 + wt("s10", "訴之聲明") - 0.5
        scroll(a, a + 1.0, "__scrollTargetFor(__plHead('訴之聲明'), 0.06)")
        move(s10, s10 + 0.8, (1170, 670))
        rect(a + 1.1, "claims_head", "__plHead('訴之聲明')")
        c = s10 + wt("s10", "事實") - 0.3
        scroll(c, c + 1.0, "__scrollTargetFor(__plHead('事實'), 0.06)")
        rect(c + 1.1, "facts_head", "__plHead('事實')")
        u = s10 + wt("s10", "上方") - 0.5
        scroll(u, u + 1.1, "__scrollTargetFor(__pcard(), 0.02)")
        rect(u + 1.2, "pcard", "__pcard()")
        rect(u + 1.2, "prow_p", "__pcard().querySelectorAll('.party-pleading-row')[0]")
        rect(u + 1.2, "prow_d", "__pcard().querySelectorAll('.party-pleading-row')[1]")

        # ---------- s11: party check (live) on the dissolved company
        s11 = s10 + dur("s10") + GAP; log["seg"]["s11"] = s11
        await advance_to(s11 - 0.9)
        await schedule_tab("當事人查核", s11 - 0.45)
        await advance_to(s11 - 0.3)
        rect(s11 - 0.25, "dcard_pre", "__dcard()")
        dbtn = "__dcard().querySelector('.party-controls button.btn.primary')"
        pc_r = s11 + wt("s11", "我們以")
        move(pc_r - 0.7, pc_r - 0.05, await center(dbtn))
        await advance_to(pc_r)
        elapsed2, nrt2, _ = await realtime("__dcard().innerText.includes('查詢中')",
                                          "!__dcard().innerText.includes('查詢中') && !!__dcard().querySelector('.party-result')", 30000)
        r_pc = st["frame"] / FPS
        dtxt = await pg.evaluate("__dcard().innerText")
        live_ok = not any(x in dtxt for x in ("錄製的查詢結果", "即時查詢失敗", "查核未完成"))
        log["events"].update(party_click=pc_r, party_done=r_pc, party_elapsed=elapsed2, party_live_ok=live_ok)
        print("party", round(elapsed2, 2), "s live_ok", live_ok, flush=True)
        if not live_ok: sys.exit("party check fell back to recorded data; re-record")
        t_name = max(r_pc + 0.2, s11 + wt("s11", "名稱已遮蔽") - 0.2)
        move(t_name, t_name + 0.7, (1180, 660))
        rect(t_name, "dtitle", "__dcard().querySelector('.party-result-title')")
        w0 = max(r_pc + 0.5, s11 + wt("s11", "系統警示") - 0.6)
        scroll(w0, w0 + 1.1, "__scrollTargetFor(__fact(__dcard(), '法定代理人'), 0.12)")
        rect(w0 + 1.2, "drep", "__fact(__dcard(), '法定代理人')")
        w1 = max(w0 + 1.5, s11 + wt("s11", "有限公司原則上") - 0.7)
        scroll(w1, w1 + 1.0, "__scrollTargetFor(__dcard().querySelector('.party-warning.bad'), 0.08)")
        rect(w1 + 1.1, "dwarn", "__dcard().querySelector('.party-warning.bad')")
        rect(w1 + 1.1, "dwarn_title", "__dcard().querySelector('.party-warning.bad .party-warning-title')")
        rect(w1 + 1.1, "dwarn_chips", "__dcard().querySelector('.party-warning.bad .chip-row')")
        j0 = max(w1 + 1.5, s11 + wt("s11", "實務上") - 0.5)
        scroll(j0, j0 + 1.2, "__scrollTargetFor(__jcard(), 0.25)")
        rect(j0 + 1.3, "jcard", "__jcard()")
        end = s11 + dur("s11") + 0.6
        log["seg"].update(end=end)
        await advance_to(end)
        log["frames"] = st["frame"]
        json.dump(log, open(OUT / "log.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("frames", st["frame"], "segs", {k: round(v, 2) for k, v in log["seg"].items()})
        print("events", {k: (round(v, 2) if isinstance(v, float) else v) for k, v in log["events"].items() if k not in ("verify_rows",)})
        await b.close()

asyncio.run(main())
