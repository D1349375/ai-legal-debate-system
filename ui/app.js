/* LegalDebate UI：所有資料皆來自後端 API(/api/*)，本檔案不含任何寫死的案件內容。
   一律以 DOM 節點建構(不使用 innerHTML)，API 回傳的文字只會被當作純文字。 */
(function () {
  "use strict";

  var API_BASE = location.protocol === "file:" ? "http://127.0.0.1:8000" : "";
  var THEME_KEY = "legaldebate-theme";

  var SIDE = {
    plaintiff: { label: "原告", agent: "原告代理人" },
    defendant: { label: "被告", agent: "被告代理人" },
  };
  var SIDES = ["plaintiff", "defendant"];

  var TABS = [
    { key: "overview", label: "案件總覽" },
    { key: "debate", label: "攻防過程" },
    { key: "aggregate", label: "機械彙整" },
    { key: "verify", label: "引用查證" },
    { key: "verdict", label: "爭點評估" },
    { key: "pleading", label: "訴狀骨架" },
  ];

  var CASE_STATUS = {
    completed: { cls: "ok", label: "✓ 完整紀錄" },
    in_progress: { cls: "warn", label: "進行中" },
    case_only: { cls: "neutral", label: "僅案件" },
    input_only: { cls: "neutral", label: "僅案件輸入" },
  };

  var STATUS = {
    published: { cls: "ok", icon: "✓", label: "已查證通過" },
    local_cache_only: { cls: "warn", icon: "◐", label: "僅本地快取,未比對官方" },
    not_found: { cls: "bad", icon: "✗", label: "確認查無此依據" },
    verification_failed: { cls: "warn", icon: "⏱", label: "無法完成查證" },
    unparseable: { cls: "warn", icon: "?", label: "無法解析" },
    unknown_law: { cls: "warn", icon: "?", label: "法規不在查證範圍" },
  };
  function statusLabel(status) { return (STATUS[status] && STATUS[status].label) || status; }
  var VIA = {
    law_moj_live: "全國法規資料庫(law.moj.gov.tw)即時查詢",
    local_corpus: "本地判決語料庫(司法院裁判書開放資料)",
    fjud_live: "司法院裁判書查詢系統 FJUD 即時查詢",
    local_statute_cache: "本地法典快取(非權威來源)",
  };
  var LIVE_OUTCOME = {
    ok: "即時查詢成功",
    timeout: "即時查詢逾時",
    network_error: "即時查詢連線失敗",
    skipped_offline_mode: "離線模式:未連網",
    skipped_after_failure: "前一筆已連線失敗,本筆略過即時查詢",
    not_attempted: "本地已命中,無須連網",
  };

  var state = {
    cases: [], caseId: null, detail: null, tab: "overview", loading: false, error: null,
    health: null, runs: {}, verifyOpts: { mode: "auto", timeout: 6, persist: true },
  };

  // ───────────── 小工具 ─────────────
  function h(tag, props) {
    var el = document.createElement(tag);
    var p = props || {};
    Object.keys(p).forEach(function (k) {
      var v = p[k];
      if (v == null || v === false) return;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.slice(0, 2) === "on" && typeof v === "function") el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    });
    for (var i = 2; i < arguments.length; i++) add(el, arguments[i]);
    return el;
  }
  function add(el, kid) {
    if (kid == null || kid === false) return;
    if (Array.isArray(kid)) { kid.forEach(function (k) { add(el, k); }); return; }
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  function chip(cls, text, extra) { return h("span", Object.assign({ class: "chip " + cls }, extra || {}), text); }
  function sideChip(side, text) { return chip(side, text || SIDE[side].label); }
  function fmtTime(iso) {
    return iso ? iso.replace("T", " ").replace(/:\d\dZ$/, " UTC") : "—";
  }
  function pct(x) { return (x * 100).toFixed(1) + "%"; }
  function banner(cls, icon, kids) {
    return h("div", { class: "banner " + cls, role: cls === "bad" ? "alert" : null },
      h("span", { class: "b-ico", "aria-hidden": "true", text: icon }), h("div", null, kids));
  }
  function recChip() { return chip("rec", "⏺ 錄製紀錄", { title: "已落地資料庫的內容重播，非即時生成" }); }
  function panelHead(title, chips, lede) {
    return h("div", { class: "panel-head" }, h("h2", { text: title }), chips, lede ? h("p", { class: "lede", text: lede }) : null);
  }
  function card(title, body, extraHeader) {
    return h("section", { class: "card" },
      title ? h("div", { class: "card-header" }, h("span", { class: "card-title", text: title }), extraHeader) : null,
      h("div", { class: "card-body" }, body));
  }
  function field(label, node) { return h("div", null, h("div", { class: "field-label", text: label }), node); }
  function fold(summary, body, open) {
    return h("details", { class: "fold", open: open ? true : null }, h("summary", { text: summary }), h("div", { class: "fold-body" }, body));
  }
  // 把一長段沒有分段標記的文字，依標點與「第X層/一、/此外」等轉折詞拆成較短的可讀段落；
  // 已有空行分段的文字則先照原分段，只在單段仍過長時才進一步拆句。
  var PARA_MARKER = /^(【[^】]{1,40}】|第[一二三四五六七八九十]+[層點項]為?|[一二三四五六七八九十]+、|此外[,，]?|又[,，]|另(?:外)?[,，]|惟|再者|至於)/;
  function splitReadable(text) {
    var MAXLEN = 160;
    var out = [];
    String(text || "").split(/\n{2,}/).forEach(function (block) {
      if (block.length <= MAXLEN) { out.push(block); return; }
      var buf = "";
      block.split(/(?<=[。;])/).filter(Boolean).forEach(function (s) {
        var startsMarker = PARA_MARKER.test(s.replace(/^\s+/, ""));
        if (buf && (startsMarker || buf.length + s.length > MAXLEN)) { out.push(buf); buf = ""; }
        buf += s;
      });
      if (buf) out.push(buf);
    });
    return out;
  }
  function paragraphs(text) {
    return splitReadable(text).map(function (par) {
      var m = par.match(PARA_MARKER);
      return m ? h("p", null, h("strong", { text: m[0] }), par.slice(m[0].length)) : h("p", { text: par });
    });
  }
  function emptyState(kids) { return h("div", { class: "empty" }, kids); }

  async function api(path, opts) {
    var res = await fetch(API_BASE + path, opts);
    var body = null;
    try { body = await res.json(); } catch (e) { /* 非 JSON 回應 */ }
    if (!res.ok) {
      var detail = body && body.detail;
      var msg = typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : "HTTP " + res.status;
      var err = new Error(msg);
      err.status = res.status;
      throw err;
    }
    return body;
  }

  function runsFor(caseId) {
    if (!state.runs[caseId]) state.runs[caseId] = { finalize: null, finalizing: false, verify: { results: {}, busy: false, pending: null, notice: null } };
    return state.runs[caseId];
  }
  function citeIndex(d) {
    var idx = {};
    d.citations.forEach(function (c) { idx[c.citation_text] = c; });
    return idx;
  }
  function usedByLabel(used) {
    return used.map(function (u) { return SIDE[u.side].label + " S" + u.stage; }).join("、");
  }

  // ───────────── 主題切換 ─────────────
  function currentTheme() { return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark"; }
  function updateThemeBtn() {
    var btn = document.getElementById("theme-toggle");
    var light = currentTheme() === "light";
    var actionLabel = light ? "切換為深色模式" : "切換為淺色模式";
    btn.replaceChildren(h("span", { "aria-hidden": "true", text: light ? "☾" : "☀" }));
    btn.title = actionLabel;
    btn.setAttribute("aria-label", actionLabel);
  }
  function setTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* 無法儲存時照常運作，只是不記憶 */ }
    updateThemeBtn();
  }

  // ───────────── 側欄 / 頂欄 / 分頁 ─────────────
  function renderCaseList() {
    var box = document.getElementById("case-list");
    box.replaceChildren();
    if (!state.cases.length) { box.append(h("div", { class: "detail-note", text: "資料庫中沒有案件。" })); return; }
    state.cases.forEach(function (c) {
      var st = CASE_STATUS[c.status] || CASE_STATUS.case_only;
      box.append(h("button", {
        class: "case-item", type: "button", "aria-current": c.case_id === state.caseId ? "true" : "false",
        onclick: function () { selectCase(c.case_id, "overview"); },
      },
        h("div", { class: "case-item-id", text: c.case_id }),
        h("div", { class: "case-item-title", text: c.case_type || "(未填案由)" }),
        h("div", { class: "case-item-meta" }, chip(st.cls, st.label),
          c.arguments ? chip("neutral", "論證 " + c.arguments) : null)));
    });
  }

  function renderTopbar() {
    var d = state.detail;
    document.getElementById("topbar-id").textContent = d ? d.case.case_id : "—";
    document.getElementById("topbar-title").textContent = d ? (d.case.case_type || "案件") : "LegalDebate AI";
    document.getElementById("topbar-sub").textContent = !d ? "" :
      d.case.source === "input_only" ? "民事 ／ 案件輸入(data/cases，尚未落地資料庫)" :
        "民事 ／ 案件落地於 " + fmtTime(d.case.created_at);
    document.getElementById("export-btn").disabled = !d;
  }

  function renderTabs() {
    var nav = document.getElementById("tabs");
    nav.replaceChildren();
    TABS.forEach(function (t, i) {
      nav.append(h("button", {
        class: "stage-tab", type: "button", role: "tab", "aria-selected": String(t.key === state.tab),
        onclick: function () { switchTab(t.key); },
      }, h("span", { class: "stage-num", text: String(i + 1) }), t.label));
    });
  }

  // ───────────── 分頁：案件總覽 ─────────────
  function provenanceBanner(d) {
    var p = d.provenance;
    if (p.kind === "recorded_replay") {
      return banner("rec", "⏺", [
        h("strong", { text: "錄製紀錄重播" }),
        "：本案原告、被告、法官的論證由 AI 產生於 " + fmtTime(p.first_recorded_at) + " ～ " + fmtTime(p.last_recorded_at) +
        "，事後寫入系統紀錄；此處是重播記錄內容，不是即時生成。「機械彙整」與「引用查證」兩個分頁則是點擊按鈕後，系統當場計算／查詢。",
      ]);
    }
    return banner("warn", "!", [
      h("strong", { text: "尚無攻防紀錄" }),
      "：此案件只有案件輸入，資料庫沒有任何論證或訊問。第一階段的 UI 不即時生成辯論(需 LLM，屬第二階段規劃)。",
    ]);
  }

  function overviewPanel(d) {
    var s = d.stats;
    return [
      panelHead("案件總覽", d.case.source === "database" ? recChip() : null),
      provenanceBanner(d),
      card("案件事實(原始輸入全文)", paragraphs(d.case.facts_summary),
        chip("neutral", d.case.case_type || "未填案由")),
      card("請求／訴之聲明(原始輸入全文)", paragraphs(d.case.claims)),
      h("p", { class: "detail-note",
        text: "以上為本案唯一的原始文字輸入，系統沒有另外收到起訴狀、契約或證物等檔案；正式使用時應以律師提供的完整案件卷證作為輸入。" }),
      h("div", { class: "stat-grid" },
        stat(s.arguments + " / 6", "攻防論證(雙方 × 3 階段)"),
        stat(String(s.questions), "法官訊問(皆有依據可回溯)"),
        stat(String(s.citations), "論證中的不重複引用"),
        stat(s.citations ? s.citations_published + " / " + s.citations : "—", "已查證通過的引用數",
          s.citations && s.citations_published < s.citations ? "warn" : (s.citations ? "ok" : "")),
        stat(d.verdict ? "已完成" : "—", "法官爭點強弱評估"),
        stat(d.pleading ? "已完成" : "—", "訴狀骨架初稿")),
    ];
  }
  function stat(num, label, cls) {
    return h("div", { class: "stat " + (cls || "") }, h("div", { class: "stat-num", text: num }), h("div", { class: "stat-label", text: label }));
  }

  // ───────────── 分頁：攻防過程 ─────────────
  function citeChip(text, idx) {
    var entry = idx[text];
    var rec = entry && entry.db_record;
    var chk = entry && entry.recorded_check;
    var cls, mark, title;
    if (rec && rec.status === "published") {
      cls = "ok"; mark = "✓"; title = "查證紀錄：已通過(" + fmtTime(rec.verified_at) + ")";
    } else if (chk && chk.status === "not_found") {
      cls = "bad"; mark = "✗"; title = "先前查證(" + fmtTime(chk.checked_at) + ")：查無此字號";
    } else {
      cls = "warn"; mark = "?"; title = "尚無查證通過的紀錄";
    }
    return h("span", { class: "cite " + cls, title: title }, h("span", { class: "cite-mark", "aria-hidden": "true", text: mark }), text);
  }

  function argCard(a, idx) {
    var cites = a.cited_statutes.concat(a.cited_precedents);
    return h("article", { class: "arg " + a.side },
      h("div", { class: "arg-head" }, sideChip(a.side, SIDE[a.side].agent), chip("neutral", "Stage " + a.stage),
        h("span", { class: "arg-time", text: "落地 " + fmtTime(a.created_at), title: "model_id：" + (a.model_id || "落地時未記錄") })),
      h("div", { class: "arg-body" },
        field("主張立場", h("div", { class: "arg-position prewrap", text: a.position })),
        fold("展開完整推理(" + a.reasoning.length + " 字)", paragraphs(a.reasoning)),
        cites.length ? field("引用(✓ 已查證通過／✗ 先前查證為查無／? 尚無查證通過的紀錄)", h("div", { class: "chip-row" },
          a.cited_precedents.map(function (t) { return citeChip(t, idx); }),
          a.cited_statutes.map(function (t) { return citeChip(t, idx); }))) : null,
        a.falsifier ? field("讓步條件 — 若對方補上何種證據，本方即讓步", h("div", { class: "falsifier prewrap", text: a.falsifier })) : null));
  }

  function stageGroup(d, stage, title, idx) {
    var items = d.arguments.filter(function (a) { return a.stage === stage; });
    if (!items.length) return null;
    return h("div", { class: "stage-group" }, h("div", { class: "section-title", text: title }),
      h("div", { class: "debate-layout" }, SIDES.map(function (side) {
        var a = items.filter(function (x) { return x.side === side; })[0];
        return a ? argCard(a, idx) : h("div", { class: "empty", text: SIDE[side].label + "此階段沒有落地紀錄" });
      })));
  }

  function questionsBlock(d) {
    if (!d.questions.length) return null;
    return h("section", { class: "judge-band" },
      h("div", { class: "judge-band-title" }, chip("judge", "法官"), "訊問 — 基於雙方 Stage 1，共 " + d.questions.length + " 則", recChip()),
      d.questions.map(function (q) {
        return h("div", { class: "judge-q" },
          h("div", { class: "judge-q-head" }, sideChip(q.target_side, "問" + SIDE[q.target_side].label + "(第 " + q.seq + " 則)"),
            h("span", { class: "arg-time", text: "落地 " + fmtTime(q.created_at) })),
          h("div", { class: "judge-q-text prewrap", text: q.question_text }),
          h("div", { class: "judge-q-basis" }, h("b", { text: "訊問依據(based_on，須回溯至具體論點)：" }), q.based_on));
      }));
  }

  function changesCard(d) {
    if (!d.citation_changes.length) return null;
    var rows = d.citation_changes.map(function (c) {
      var none = !c.dropped.length && !c.added.length;
      return h("div", { class: "drift-row" },
        h("div", { class: "drift-label" }, h("span", null, sideChip(c.side), " ", chip("neutral", "Stage " + c.from_stage + " → " + c.to_stage))),
        none ? h("div", { class: "detail-note", text: "引用集合無變化" }) : h("div", { class: "drift-sets" },
          c.dropped.length ? h("div", null, "後一階段不再引用：", h("span", { class: "chip-row" }, c.dropped.map(function (t) { return h("span", { class: "cite warn" }, h("span", { class: "cite-mark", "aria-hidden": "true", text: "−" }), t); }))) : null,
          c.added.length ? h("div", null, "後一階段新增引用：", h("span", { class: "chip-row" }, c.added.map(function (t) { return h("span", { class: "cite ok" }, h("span", { class: "cite-mark", "aria-hidden": "true", text: "+" }), t); }))) : null));
    });
    return card("階段間引用變化", [
      h("p", { class: "detail-note", text: "機械集合差(前一階段有、後一階段沒有者列為「不再引用」)，不做語意判斷；為何不再引用，請對照該方 Stage 推理全文。" }),
      rows]);
  }

  function debatePanel(d) {
    if (!d.arguments.length) return [panelHead("攻防過程"), emptyState(["此案件沒有攻防紀錄。", h("br"), "第一階段的 UI 不即時生成辯論。"])];
    var idx = citeIndex(d);
    return [
      panelHead("攻防過程", recChip(),
        "協議：Stage 1 雙方獨立盲判 → 法官依 Stage 1 訊問 → Stage 2 訊問攻防 → Stage 3 辯論終結。以下皆為資料庫已落地的原文。"),
      stageGroup(d, 1, "Stage 1 — 爭點整理(雙方獨立盲判，互相看不到對方輸出)", idx),
      questionsBlock(d),
      stageGroup(d, 2, "Stage 2 — 訊問攻防(回應法官訊問)", idx),
      stageGroup(d, 3, "Stage 3 — 辯論終結", idx),
      changesCard(d),
    ];
  }

  // ───────────── 分頁：機械彙整 ─────────────
  async function runFinalize() {
    var d = state.detail, run = runsFor(d.case.case_id);
    run.finalizing = true; run.finalize = null; renderPanel();
    try {
      var r = await api("/api/cases/" + encodeURIComponent(d.case.case_id) + "/finalize", { method: "POST" });
      run.finalize = { result: r, at: new Date() };
    } catch (e) {
      run.finalize = { error: e.message, status: e.status };
    }
    run.finalizing = false;
    if (state.detail === d) renderPanel();
  }

  function driftRow(side, dd) {
    var has = dd && dd.ratio != null;
    return h("div", { class: "drift-row" },
      h("div", { class: "drift-label" }, sideChip(side), h("span", { class: "drift-value", text: has ? dd.ratio.toFixed(4) + "(" + pct(dd.ratio) + ")" : "無法計算" })),
      has ? [
        h("div", { class: "drift-track", role: "img", "aria-label": SIDE[side].label + "位移度 " + pct(dd.ratio) },
          h("div", { class: "drift-fill " + side, style: "width:" + (dd.ratio * 100) + "%" })),
        h("div", { class: "drift-formula", text: "Jaccard 距離 = 1 − |交集| ÷ |聯集| = 1 − " + dd.intersection + "/" + dd.union + " = " + dd.ratio }),
        h("div", { class: "drift-sets" },
          h("div", { text: "Stage 1 引用 " + dd.stage1_count + " 條 → Stage 3 引用 " + dd.stage3_count + " 條" }),
          dd.dropped.length ? h("div", null, "不再引用：", h("span", { class: "chip-row" }, dd.dropped.map(function (t) { return h("span", { class: "cite warn" }, h("span", { class: "cite-mark", "aria-hidden": "true", text: "−" }), t); }))) : null,
          dd.added.length ? h("div", null, "新增引用：", h("span", { class: "chip-row" }, dd.added.map(function (t) { return h("span", { class: "cite ok" }, h("span", { class: "cite-mark", "aria-hidden": "true", text: "+" }), t); }))) : null),
      ] : h("div", { class: "detail-note", text: "該方缺少 Stage 1 或 Stage 3 紀錄" }));
  }

  function aggregatePanel(d) {
    var run = runsFor(d.case.case_id);
    var ready = d.progress.filter(function (s) { return s.key === "finalize"; })[0].state === "ready";
    var out = [
      panelHead("機械死穴彙整與立場位移", null,
        "本頁不呼叫任何 AI 模型，只用固定規則計算：弱點取雙方最後階段自陳的讓步條件；立場位移以雙方前後階段引用的法條/判例集合差異量化。法官的評估不得偏離這裡算出的結果。"),
      h("div", { class: "controls" },
        h("button", { class: "btn primary", type: "button", disabled: !ready || run.finalizing ? true : null, onclick: runFinalize },
          h("span", { class: "ico", "aria-hidden": "true", text: "▶" }), run.finalizing ? "計算中…" : (run.finalize ? "重新計算一次" : "執行彙整計算")),
        ready ? h("span", { class: "detail-note", text: "系統會重新計算一次弱點彙整與立場位移，不會更動任何已存資料。" })
          : h("span", { class: "detail-note", text: "須雙方皆完成 Stage 3 才能執行" })),
    ];
    var f = run.finalize;
    if (!f) {
      if (!run.finalizing) out.push(emptyState(ready ? "尚未執行。按下「執行彙整計算」由系統當場計算。" : "此案件尚無法執行機械彙整。"));
      return out;
    }
    if (f.error) { out.push(banner("bad", "✗", [h("strong", { text: "執行失敗" }), "：" + f.error])); return out; }
    var r = f.result;
    out.push(banner("ok", "⚡", [h("strong", { text: "剛剛由系統即時計算" }), "(" + f.at.toLocaleTimeString("zh-TW") + "，耗時 " + r.elapsed_ms + " ms；來源為資料庫中的 Stage 1／Stage 3 落地紀錄)"]));
    out.push(h("div", { class: "section-title", text: "弱點彙整" }));
    out.push(h("div", { class: "weak-grid" }, r.weak_points.map(function (w, i) {
      return h("div", { class: "weak-card " + w.side },
        h("div", { class: "arg-head" }, sideChip(w.side, SIDE[w.side].label + "方讓步條件"), h("span", { class: "weak-rank", text: "排序 " + (i + 1) })),
        h("div", { class: "weak-text prewrap", text: w.falsifier || "(該方未提供讓步條件)" }),
        w.response_excerpt ? h("div", { style: "margin-top:10px" }, fold("該方 Stage 3 推理全文", paragraphs(w.response_excerpt))) : null);
    })));
    out.push(card("立場位移", [
      driftRow("plaintiff", r.drift_detail.plaintiff), driftRow("defendant", r.drift_detail.defendant),
      h("p", { class: "detail-note", text: "0 = 兩階段引用集合完全相同，1 = 完全不重疊。以引用的法條/判例集合為代理指標，不代表論述語意的變化幅度。" })]));
    out.push(anchorBanner(d.verdict && d.verdict.anchor_check));
    return out;
  }

  // ───────────── 分頁：引用查證 ─────────────
  function statusMeta(status) { return STATUS[status] || { cls: "warn", icon: "?", label: status }; }

  async function runVerify(list) {
    var d = state.detail, run = runsFor(d.case.case_id), v = run.verify, opts = state.verifyOpts;
    if (v.busy) return;
    v.busy = true; v.notice = null;
    var skip = false;
    for (var i = 0; i < list.length; i++) {
      var text = list[i];
      v.pending = text; renderPanel();
      try {
        var resp = await api("/api/verify", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ citations: [text], mode: opts.mode, timeout_sec: opts.timeout, persist: opts.persist, skip_live: skip }),
        });
        var r = resp.results[0];
        v.results[text] = r;
        var oc = r.live_attempt && r.live_attempt.outcome;
        if ((oc === "timeout" || oc === "network_error") && !skip) {
          skip = true;
          v.notice = "偵測到即時查詢無法連線(" + LIVE_OUTCOME[oc] + ")：其餘引用改以本地資料比對，並如實標示為「僅本地快取」或「無法完成查證」。";
        }
      } catch (e) {
        v.results[text] = { error: e.message };
      }
      if (state.detail !== d) { v.busy = false; v.pending = null; return; }
    }
    v.busy = false; v.pending = null;
    if (opts.persist && state.detail === d) await reloadDetailQuietly();
    renderPanel();
  }

  async function reloadDetailQuietly() {
    try { state.detail = await api("/api/cases/" + encodeURIComponent(state.caseId)); renderDetail(); } catch (e) { /* 保留舊資料 */ }
  }

  function verifyRow(c, r, busy, pendingText) {
    var pending = pendingText === c.citation_text;
    var meta, cls = "";
    if (pending) meta = { cls: "idle", icon: "", label: "查證中…" };
    else if (!r) meta = { cls: "idle", icon: "·", label: "待查證" };
    else if (r.error) meta = { cls: "warn", icon: "!", label: "請求失敗" };
    else meta = statusMeta(r.status);
    if (r && r.gate === "blocked") cls = r.status === "not_found" ? "blocked" : "local";

    var lines = [];
    var line = function (k, v) { lines.push(h("div", null, h("span", { class: "k", text: k + "：" }), v)); };
    if (r && r.error) line("錯誤", r.error);
    if (r && !r.error) {
      if (r.verified_via) line("來源", VIA[r.verified_via] || r.verified_via);
      if (r.primary_source_url) line("原文", h("a", { href: r.primary_source_url, target: "_blank", rel: "noopener noreferrer", text: "開啟官方頁面" }));
      if (r.live_attempt) line("即時查詢", (LIVE_OUTCOME[r.live_attempt.outcome] || r.live_attempt.outcome) + (r.live_attempt.error ? "(" + r.live_attempt.error + ")" : ""));
      if (r.local_cache) line("本地快取資料", "取得於 " + fmtTime(r.local_cache.fetched_at) + "；法規修正日 " + (r.local_cache.amendment_date || "—"));
      if (r.status === "not_found" && r.fjud_query) line("查詢結果", "以「" + r.fjud_query + "」查詢司法院系統，回傳 " + r.fjud_hit_count + " 筆近似結果，無一為此字號");
      if (r.note) line("說明", r.note);
    }
    var prior = (r && r.previous_record) || c.db_record;
    line("先前查證紀錄(非本次結果)", prior ? statusLabel(prior.status) + "(" + fmtTime(prior.verified_at) + ")" : "尚無查證通過紀錄");
    var chk = (r && r.recorded_check) || c.recorded_check;
    if (chk) line("先前錄製的即時查證(非本次結果)", statusLabel(chk.status) + "，記錄於 " + fmtTime(chk.checked_at));

    return h("div", { class: "vrow " + cls },
      h("div", null, h("span", { class: "pill " + meta.cls, role: "status" }, pending ? h("span", { class: "spinner", "aria-hidden": "true" }) : h("span", { "aria-hidden": "true", text: meta.icon }), meta.label)),
      h("div", null,
        h("div", { class: "vrow-cite", text: c.citation_text }),
        h("div", { class: "vrow-meta" }, chip("neutral", c.kind === "judgment" ? "判例" : c.kind === "statute" ? "法條" : "未分類"),
          c.used_by.length ? chip("neutral", "引用者：" + usedByLabel(c.used_by)) : null,
          r && r.gate ? (r.gate === "pass" ? chip("ok", "✓ 本次放行")
            : r.status === "not_found" ? chip("bad", "✗ 閘門攔截，不得進入訴狀") : chip("warn", "本次未放行(不視為已查證)")) : null),
        h("div", { class: "vrow-lines" }, lines),
        r && !r.error ? h("div", { style: "margin-top:8px" }, fold("原始回應(JSON)", h("pre", { class: "raw", text: JSON.stringify(r, null, 2) }))) : null),
      h("div", { class: "vrow-side" },
        r && r.elapsed_ms != null ? h("span", { text: r.elapsed_ms + " ms" }) : null,
        h("button", { class: "btn small", type: "button", disabled: busy ? true : null, onclick: function () { runVerify([c.citation_text]); }, text: "查證此條" })));
  }

  function verifyPanel(d) {
    var run = runsFor(d.case.case_id), v = run.verify, opts = state.verifyOpts;
    var cites = d.citations;
    var head = panelHead("引用查證", null,
      "每一條引用都當作「未經證實」處理：判例先比對本地判決語料庫(1,000 餘份最高法院裁判)，未命中再即時查司法院系統；法條即時查全國法規資料庫，逾時則退回本地法典快取——但退回的結果只標示為「僅本地快取」，不算通過、不寫入紀錄。");
    if (!cites.length) return [head, emptyState("此案件的論證沒有引用任何法條或判例。")];

    var seg = h("div", { class: "seg", role: "group", "aria-label": "查證模式" },
      [["auto", "自動：本地優先 → 即時查詢"], ["offline", "離線：只比對本地"]].map(function (m) {
        return h("button", { type: "button", "aria-pressed": String(opts.mode === m[0]), text: m[1], disabled: v.busy ? true : null,
          onclick: function () { opts.mode = m[0]; renderPanel(); } });
      }));
    var sel = h("select", { id: "v-timeout", disabled: v.busy ? true : null, onchange: function (e) { opts.timeout = Number(e.target.value); } },
      [3, 6, 12].map(function (s) { return h("option", { value: String(s), selected: opts.timeout === s ? true : null, text: s + " 秒" }); }));
    var persist = h("input", { type: "checkbox", id: "v-persist", checked: opts.persist ? true : null, disabled: v.busy ? true : null,
      onchange: function (e) { opts.persist = e.target.checked; } });
    var controls = h("div", { class: "controls" }, seg,
      h("label", { for: "v-timeout" }, "即時查詢逾時", sel),
      h("label", { for: "v-persist" }, persist, "查證通過的引用要記錄下來"),
      h("button", { class: "btn primary", type: "button", disabled: v.busy ? true : null,
        onclick: function () { runVerify(cites.map(function (c) { return c.citation_text; })); } },
        h("span", { class: "ico", "aria-hidden": "true", text: "▶" }), v.busy ? "查證中…" : "逐條查證全部(" + cites.length + " 條)"));

    var results = cites.map(function (c) { return v.results[c.citation_text]; }).filter(function (r) { return r && !r.error; });
    var count = function (fn) { return results.filter(fn).length; };
    var tiles = h("div", { class: "stat-grid" },
      stat(results.length ? String(count(function (r) { return r.status === "published"; })) : "—", "✓ 已查證通過", "ok"),
      stat(results.length ? String(count(function (r) { return r.status === "local_cache_only"; })) : "—", "◐ 僅本地快取(未比對官方)", "warn"),
      stat(results.length ? String(count(function (r) { return r.status === "not_found"; })) : "—", "✗ 確認查無", "bad"),
      stat(results.length ? String(count(function (r) { return ["verification_failed", "unparseable", "unknown_law"].indexOf(r.status) >= 0; })) : "—", "⏱ 無法完成查證／無法解析", "warn"));

    var out = [head, controls, tiles];
    if (v.notice) out.push(banner("warn", "!", [h("strong", { text: "網路狀態" }), "：" + v.notice]));

    var done = cites.filter(function (c) { return v.results[c.citation_text]; });
    if (done.length && !v.busy) {
      var blocked = results.filter(function (r) { return r.gate === "blocked"; });
      var all = done.length === cites.length;
      if (!blocked.length && all && results.length === cites.length) {
        out.push(banner("ok", "✓", [h("strong", { text: "本次全部引用通過機械查證" }), "：" + results.length + " 條皆已查證通過，可用於訴狀或判決引用。"]));
      } else if (blocked.length) {
        var quote = function (rs) { return rs.map(function (r) { return "「" + r.citation_text + "」"; }).join("、"); };
        var notFound = blocked.filter(function (r) { return r.status === "not_found"; });
        var localOnly = blocked.filter(function (r) { return r.status === "local_cache_only"; });
        var unresolved = blocked.filter(function (r) { return r.status !== "not_found" && r.status !== "local_cache_only"; });
        var parts = [];
        if (notFound.length) parts.push("官方來源確認查無：" + quote(notFound) + "，閘門攔截，不得進入訴狀或判決");
        if (unresolved.length) parts.push("本次無法完成官方查證：" + quote(unresolved) + "，依零容忍原則不視為已查證");
        if (localOnly.length) parts.push(localOnly.length + " 條法條僅在本地快取找到、未與官方原文比對，本次不視為已查證");
        out.push(banner(notFound.length ? "bad" : "warn", notFound.length ? "✗" : "!", [
          h("strong", { text: "本次有 " + blocked.length + " 條未放行" }), "：" + parts.join("；") + "。"]));
      }
    }

    var group = function (title, kind) {
      var items = cites.filter(function (c) { return c.kind === kind; });
      if (!items.length) return null;
      return [h("div", { class: "section-title", text: title + "(" + items.length + ")" }),
        items.map(function (c) { return verifyRow(c, v.results[c.citation_text], v.busy, v.pending); })];
    };
    out.push(group("判例", "judgment"), group("法條", "statute"), group("未分類", "unknown"));
    out.push(h("p", { class: "detail-note", text: "查證範圍說明：判例僅確認「裁判字號存在」，未比對裁判全文是否支持該論點；法條為官網即時原文。" }));
    return out;
  }

  // ───────────── 分頁：爭點評估 ─────────────
  function verdictPanel(d) {
    var v = d.verdict;
    var head = panelHead("法官爭點強弱評估", recChip(),
      "評估的用途是協助律師決定訴狀火力與蒐證優先順序，不是預測法院會怎麼判。以下為法官角色落地的原文。");
    if (!v) return [head, emptyState("此案件尚未落地爭點強弱評估。")];
    var risk = v.risk_map || {};
    var list = function (items) { return h("ul", { class: "risk-list" }, (items || []).map(function (t) { return h("li", { text: t }); })); };
    var out = [head,
      card("評估結論", paragraphs(delabelJargon(v.verdict_main_text)), chip("neutral", "落地 " + fmtTime(v.created_at))),
      card("評估理由", paragraphs(delabelJargon(v.verdict_reasoning))),
      h("div", { class: "risk-grid" },
        card("對原告不利之處", list(risk["對原告不利之處"]), sideChip("plaintiff")),
        card("對被告不利之處", list(risk["對被告不利之處"]), sideChip("defendant"))),
      card("建議補強證據", list(risk["建議補強證據"]))];
    out.push(anchorBanner(v.anchor_check));
    return out;
  }

  function anchorBanner(a) {
    if (!a) return null;
    var ps = a.recomputed.position_drift;
    if (!a.consistent) return banner("bad", "✗", [h("strong", { text: "與落地時的計算結果不一致" }), "：" + a.differences.join("；")]);
    if (a.minor_differences.length) {
      return banner("warn", "!", [
        h("strong", { text: "位移數值一致，但讓步條件文字有細微出入" }),
        "。落地時記錄的立場位移，與現在重新計算的結果相同(原告 " + pct(ps.plaintiff) + "、被告 " + pct(ps.defendant) + ")；但 " +
        a.minor_differences.map(function (m) { return m.note; }).join("；") + "。",
        a.minor_differences.map(function (m) {
          return fold("查看" + SIDE[m.side].label + "方文字差異", [
            h("p", null, h("strong", { text: "落地紀錄的版本：" }), m.stored),
            h("p", null, h("strong", { text: "Stage 3 原文(現行)：" }), m.current)]);
        }),
      ]);
    }
    return banner("ok", "✓", [h("strong", { text: "與落地時的計算結果一致" }),
      "：落地時記錄的立場位移與弱點，跟現在重新計算的結果完全相同(原告 " + pct(ps.plaintiff) + "、被告 " + pct(ps.defendant) + ")。"]);
  }

  // ───────────── 分頁：訴狀骨架 ─────────────
  // 部分早期錄製的內容(草稿標題／附註、判決推理)夾帶了內部開發代號或欄位名稱
  // (Skill 名稱、Phase 編號、weak_points/position_drift/falsifier 等)，這裡只做
  // 「代換為中性中文說法／移除純內部備註」的顯示層清理，不更動實質法律內容或數值。
  // 順序有意義：先代換較長的複合代號，再代換其後可能單獨殘留的字詞(如「該 Skill」)。
  var TEXT_JARGON = [
    [/【[^】]*】/g, ""],
    [/taiwan-legal-pleading(\s*Skill)?/gi, "系統潤飾規則"],
    [/legal-debate\s*skill/gi, "系統流程"],
    [/engine\/verify\.py/gi, "查證程式"],
    [/LegalDebate\s*系統\s*Stage\s*3/gi, "系統攻防推演最終階段"],
    [/position\/reasoning\s*原文/gi, "主張與理由原文"],
    [/position\s*\+\s*reasoning/gi, "主張與理由"],
    [/position_drift/gi, "立場位移度"],
    [/weak_points?/gi, "弱點清單"],
    [/\bfalsifier\b/gi, "讓步條件"],
    [/\bplaintiff\b/gi, "原告方"],
    [/\bdefendant\b/gi, "被告方"],
    [/Phase\s*[12]\b/gi, "後續階段"],
    [/\bStep(\d+)\b/gi, "步驟$1"],
    [/\bSkill\b/gi, "潤飾規則"],
    [/\bpublished\b/gi, "已通過"],
  ];
  function delabelJargon(raw) {
    var text = String(raw || "");
    TEXT_JARGON.forEach(function (pair) { text = text.replace(pair[0], pair[1]); });
    return text;
  }
  function cleanDraftNote(raw) {
    return delabelJargon(raw)
      .replace(/^-{2,}\s*$/gm, "")
      .split("\n").map(function (l) { return l.replace(/^[-•]\s*/, "").trim(); })
      .filter(function (l) { return l && l !== "。" && !/^骨架版[,，]?.*潤飾[。.]?$/.test(l); })
      .join("\n\n").replace(/\n{3,}/g, "\n\n").trim();
  }

  function pleadingPanel(d) {
    var p = d.pleading;
    var head = panelHead("訴狀骨架初稿", recChip(),
      "骨架版：僅套用司法院官方起訴狀結構，直接帶入系統攻防結果原文，尚未經法律用語潤飾。須由執業律師審核修訂、補正當事人資訊與證物清單後方可使用，不得逕行送出。");
    if (!p) return [head, emptyState("此案件尚未落地訴狀草稿。")];
    var text = p.draft_text;
    var noteIdx = text.search(/-{2,}\s*\n\s*(?=【)|【(?:骨架版聲明|本稿產出說明)/);
    var note = noteIdx >= 0 ? cleanDraftNote(text.slice(noteIdx)) : null;
    if (noteIdx >= 0) text = text.slice(0, noteIdx);
    var lines = delabelJargon(text).replace(/\s+$/, "").split("\n");
    var doc = h("div", { class: "pleading-doc" },
      lines.map(function (ln, i) {
        if (i === 0) return [
          h("div", { class: "pl-title", text: ln.replace(/[（(][\s\S]*[）)]\s*$/, "").trim() || "民事起訴狀" }),
          h("div", { class: "pl-subtitle", text: "骨架版初稿．尚未經法律用語潤飾．須經律師審核後使用" }),
        ];
        var headLine = /^(訴之聲明|事實及理由|證物名稱及件數|為.*事：)/.test(ln);
        if (!ln.trim()) return h("div", { class: "pl-gap", "aria-hidden": "true" });
        return h("div", { class: "pl-line" + (headLine ? " pl-head" : ""), text: ln });
      }));

    var checks = p.citation_check;
    var okN = checks.filter(function (c) { return c.db_record && c.db_record.status === "published"; }).length;
    var rows = checks.map(function (c) {
      var ok = c.db_record && c.db_record.status === "published";
      return h("div", { class: "vrow" + (ok ? "" : " blocked") },
        h("div", null, h("span", { class: "pill " + (ok ? "ok" : "bad") }, h("span", { "aria-hidden": "true", text: ok ? "✓" : "✗" }), ok ? "已查證通過" : "尚無查證通過紀錄")),
        h("div", null, h("div", { class: "vrow-cite", text: c.citation_text }),
          h("div", { class: "vrow-lines" }, c.db_record ? h("div", null, h("span", { class: "k", text: "查證紀錄：" }), statusLabel(c.db_record.status) + "(" + fmtTime(c.db_record.verified_at) + ")" +
            (c.db_record.matched_by === "normalized" ? "；以同條文比對，對應紀錄「" + c.db_record.db_citation_text + "」" : "")) : null)),
        h("div"));
    });
    return [head,
      banner("rec", "⏺", [h("strong", { text: "錄製紀錄" }), "：草稿產生於 " + fmtTime(p.generated_at) +
        (p.draft_count > 1 ? "；此案件共有 " + p.draft_count + " 份草稿，此處顯示最新一份" : "") + "。"]),
      doc,
      note ? card("系統補充說明(供律師參考，非訴狀正文)", paragraphs(note)) : null,
      card("草稿內引用的查證狀態", [
        h("div", { style: "margin-bottom:10px" }, okN === checks.length && checks.length ? chip("ok", "✓ " + okN + " / " + checks.length + " 條已查證通過") : chip("bad", "✗ " + okN + " / " + checks.length + " 條已查證通過")),
        rows,
        h("p", { class: "detail-note", text: "由草稿文字重新找出其中的法條與裁判字號，對照目前的查證紀錄。" })]),
    ];
  }

  // ───────────── 右側資訊欄 ─────────────
  function renderDetail() {
    var box = document.getElementById("detail");
    box.replaceChildren();
    var d = state.detail;
    if (!d) return;
    var hl = state.health;
    var mark = { done: "✓", partial: "◐", ready: "▶", pending: "·" };
    box.append(
      h("div", { class: "detail-section" }, h("div", { class: "detail-section-title", text: "流程進度(依資料庫實況計算)" }),
        h("ul", { class: "steps" }, d.progress.map(function (s) {
          return h("li", { class: "step " + s.state }, h("span", { class: "step-dot", "aria-hidden": "true", text: mark[s.state] }),
            h("span", { class: "step-label", text: s.label }), h("span", { class: "step-detail", text: s.detail }));
        }))),
      h("div", { class: "detail-section" }, h("div", { class: "detail-section-title", text: "案件摘要" }),
        meta("案件 ID", d.case.case_id), meta("案由", d.case.case_type || "—"),
        meta("落地時間", fmtTime(d.case.created_at)), meta("論證／訊問", d.stats.arguments + " 筆／" + d.stats.questions + " 則"),
        meta("引用查證", d.stats.citations ? d.stats.citations_published + "/" + d.stats.citations + " 已查證通過" : "—")),
      h("div", { class: "detail-section" }, h("div", { class: "detail-section-title", text: "資料來源" }),
        h("p", { class: "detail-note", text: "案件與論證：本機資料庫。" +
          (hl && hl.database.seeded_from_fixture ? "本次啟動時資料庫為空，已自動匯入示範案例存檔。" : "") }),
        hl ? h("p", { class: "detail-note", text: "本地語料庫：最高法院判決 " + hl.corpus.judgments + " 份、法典 " + hl.corpus.statutes + " 部。" }) : null,
        h("p", { class: "detail-note", text: "查證權威來源：法規＝法務部全國法規資料庫；判決＝本地語料庫 → 司法院裁判書查詢系統。" })),
      h("div", { class: "detail-section" }, h("div", { class: "detail-section-title", text: "第一階段限制" }),
        h("p", { class: "detail-note", text: "不即時呼叫 LLM 生成辯論；論證內容皆為錄製紀錄。引用查證僅確認條文／字號存在，未比對判決全文是否支持該論點。研究原型，非法律意見，訴狀須由律師審核。" })));
  }
  function meta(k, v) { return h("div", { class: "meta-row" }, h("span", { class: "meta-key", text: k }), h("span", { class: "meta-val", text: v })); }

  // ───────────── 主要繪製流程 ─────────────
  function renderPanel() {
    var panel = document.getElementById("panel");
    var top = panel.scrollTop;
    panel.replaceChildren();
    var d = state.detail;
    if (state.error) {
      panel.append(emptyState([h("strong", { text: "無法載入資料" }), h("br"), state.error, h("br"),
        "請確認後端已啟動：在專案目錄執行 ", h("code", { text: "python main.py serve" })]));
      return;
    }
    if (state.loading || !d) { panel.append(emptyState("載入中…")); return; }
    try {
      var view = { overview: overviewPanel, debate: debatePanel, aggregate: aggregatePanel, verify: verifyPanel, verdict: verdictPanel, pleading: pleadingPanel }[state.tab];
      add(panel, view(d));
    } catch (e) {
      panel.append(banner("bad", "✗", [h("strong", { text: "畫面繪製失敗" }), "：" + e.message]));
    }
    panel.scrollTop = top;
  }

  function renderAll() { renderCaseList(); renderTopbar(); renderTabs(); renderDetail(); renderPanel(); }

  function setHash() { try { history.replaceState(null, "", "#/" + encodeURIComponent(state.caseId || "") + "/" + state.tab); } catch (e) { /* file:// 等環境略過 */ } }

  function switchTab(key) { state.tab = key; setHash(); renderTabs(); renderPanel(); document.getElementById("panel").scrollTop = 0; }

  async function selectCase(caseId, tab) {
    state.caseId = caseId; state.tab = tab || state.tab; state.loading = true; state.error = null; state.detail = null;
    setHash(); renderAll();
    try {
      var d = await api("/api/cases/" + encodeURIComponent(caseId));
      if (state.caseId !== caseId) return;
      state.detail = d;
    } catch (e) { state.error = e.message; }
    state.loading = false;
    renderAll();
  }

  function exportCase() {
    var d = state.detail;
    if (!d) return;
    var run = state.runs[d.case.case_id] || {};
    var payload = {
      exported_at: new Date().toISOString(),
      note: "資料庫已落地的錄製紀錄(論證由 Claude Code subagent 產生，非即時生成)與本次工作階段的機械執行結果。",
      case_detail: d,
      session_finalize: run.finalize && run.finalize.result ? run.finalize.result : null,
      session_verify: run.verify ? Object.keys(run.verify.results).map(function (k) { return run.verify.results[k]; }) : [],
    };
    var url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
    var a = h("a", { href: url, download: d.case.case_id + ".json" });
    document.body.append(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function parseHash() {
    var m = location.hash.match(/^#\/([^/]*)\/([a-z]*)$/);
    return { caseId: m ? decodeURIComponent(m[1]) : null,
      tab: m && TABS.some(function (t) { return t.key === m[2]; }) ? m[2] : "overview" };
  }

  // 瀏覽器上一頁/下一頁只改變網址片段(不會整頁重新載入)，需另外監聽並同步畫面。
  window.addEventListener("hashchange", function () {
    var h = parseHash();
    if (!h.caseId || h.caseId === state.caseId) { if (h.tab !== state.tab) switchTab(h.tab); return; }
    selectCase(h.caseId, h.tab);
  });

  async function init() {
    updateThemeBtn();
    document.getElementById("theme-toggle").addEventListener("click", function () { setTheme(currentTheme() === "light" ? "dark" : "light"); });
    document.getElementById("export-btn").addEventListener("click", exportCase);
    renderTabs();
    try {
      state.health = await api("/api/health");
      state.cases = (await api("/api/cases")).cases;
    } catch (e) {
      state.error = "無法連線後端：" + e.message;
      renderAll();
      return;
    }
    var h = parseHash();
    var pick = state.cases.some(function (c) { return c.case_id === h.caseId; }) ? h.caseId : (state.cases[0] && state.cases[0].case_id);
    if (!pick) { state.error = "資料庫中沒有任何案件"; renderAll(); return; }
    await selectCase(pick, h.tab);
  }

  init();
})();
