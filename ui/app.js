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
  // 書狀：原告起訴狀 / 被告答辯狀。side 欄位新增前的舊紀錄由後端一律視為原告起訴狀。
  var DOCUMENT = {
    plaintiff: { label: "起訴狀(原告)", title: "民事起訴狀", short: "起訴狀",
      lede: "骨架版：僅套用司法院官方起訴狀結構，直接帶入原告方攻防結果原文，尚未經法律用語潤飾。" },
    defendant: { label: "答辯狀(被告)", title: "民事答辯狀", short: "答辯狀",
      lede: "骨架版：本機沒有司法院官方答辯狀範本，結構依民事訴訟法第116條、第266條第2項的書狀應記載事項整理，直接帶入被告方攻防結果原文，尚未經法律用語潤飾。模擬答辯：回應的是系統模擬的原告主張，不是實際起訴狀，只能用來預想防禦。" },
  };
  // 書狀交換流程(protocol v2)的書狀由程式依結構化 JSON 組成，說明不同；舊錄製案照舊用 DOCUMENT(審查 W4-4)
  var DOCUMENT_V2 = {
    plaintiff: Object.assign({}, DOCUMENT.plaintiff, {
      lede: "書狀交換流程：正文由程式依起訴狀的結構化內容組成，每個事實點〔CF〕對應證據或事實經過原文，尚未經法律用語潤飾。" }),
    defendant: Object.assign({}, DOCUMENT.defendant, {
      lede: "模擬答辯狀：被告方只讀起訴狀(關卡 1 確認的版本)，正文由程式依逐點表態與抗辯組成，不是對方實際的答辯；推測的內容標「推測」，只能用來預想防禦。" }),
  };
  function docOf(d, side) { return (isV2(d) ? DOCUMENT_V2 : DOCUMENT)[side]; }

  var TABS = [
    { key: "overview", label: "案件總覽" },
    { key: "parties", label: "起訴前檢查" },
    { key: "debate", label: "攻防過程" },
    { key: "aggregate", label: "機械彙整" },
    { key: "verify", label: "引用查證" },
    { key: "verdict", label: "爭點評估" },
    { key: "pleading", label: "訴狀骨架" },
  ];
  // 書狀交換流程(protocol v2)的分頁照流程排(交接 A);舊錄製案照舊 TABS
  var TABS_V2 = [
    { key: "overview", label: "案件總覽" },
    { key: "parties", label: "當事人與管轄" },
    { key: "complaint", label: "起訴狀" },
    { key: "answer", label: "對方答辯(模擬)" },
    { key: "sheet", label: "爭點整理" },
    { key: "rounds", label: "攻防模擬" },
    { key: "diagnosis", label: "弱點與修改建議" },
    { key: "verify", label: "引用查核" },
  ];
  // 舊網址的分頁(#/<id>/debate 等)對 v2 案件導到新分頁；新分頁的網址對舊案導回總覽，連結不會壞
  var TAB_ALIAS_V2 = { debate: "rounds", aggregate: "diagnosis", verdict: "diagnosis", pleading: "complaint" };
  function caseIsV2() {
    if (state.detail) return isV2(state.detail);
    var c = state.cases.filter(function (x) { return x.case_id === state.caseId; })[0];
    return !!(c && c.protocol === "v2");
  }
  function tabsNow() { return caseIsV2() ? TABS_V2 : TABS; }
  function tabLabel(key) { return (tabsNow().filter(function (t) { return t.key === key; })[0] || {}).label || key; }
  function normalizeTab(key) {
    var tabs = tabsNow();
    if (tabs === TABS_V2 && TAB_ALIAS_V2[key]) key = TAB_ALIAS_V2[key];
    return tabs.some(function (t) { return t.key === key; }) ? key : "overview";
  }

  var CASE_STATUS = {
    completed: { cls: "ok", label: "✓ 完整紀錄" },
    // 有論證但缺爭點評估或訴狀；只有執行中才叫「進行中」，否則是停在中途的紀錄(見 renderCaseList)
    in_progress: { cls: "warn", label: "◐ 未完成(部分落地)" },
    case_only: { cls: "neutral", label: "僅案件" },
    input_only: { cls: "neutral", label: "僅案件輸入" },
  };

  var STATUS = {
    published: { cls: "ok", icon: "✓", label: "已查證通過" },
    local_cache_only: { cls: "warn", icon: "◐", label: "僅過期或未確認的快取,未比對官方" },
    not_found: { cls: "bad", icon: "✗", label: "確認查無此依據" },
    network_error: { cls: "warn", icon: "⏱", label: "連線失敗,無法完成查證" },
    verification_failed: { cls: "warn", icon: "⏱", label: "無法完成查證" },
    unparseable: { cls: "warn", icon: "?", label: "無法解析" },
    unsupported_law: { cls: "warn", icon: "?", label: "法規不在名稱索引" },
    unknown_law: { cls: "warn", icon: "?", label: "法規不在查證範圍" },
    ambiguous: { cls: "warn", icon: "?", label: "同字號多份文件,須指定日期" },
    version_unverified: { cls: "warn", icon: "?", label: "舊版條文,版本未查證" },
  };
  function statusLabel(status) { return (STATUS[status] && STATUS[status].label) || status; }
  var VIA = {
    law_moj_live: "全國法規資料庫(law.moj.gov.tw)即時查詢",
    local_corpus: "本地判決語料庫(司法院裁判書開放資料)",
    fjud_live: "司法院裁判書查詢系統 FJUD 即時查詢",
    local_statute_cache: "本地法典快取(非權威來源)",
    retrieval_cache: "檢索快取(先前自官方抓取)",
    retrieval_cache_stale: "超過 7 天的條文快取(未與官方比對)",
    run_snapshot: "本次實跑快照(先前自官方抓取)",
  };
  var LIVE_OUTCOME = {
    ok: "即時查詢成功",
    timeout: "即時查詢逾時",
    network_error: "即時查詢連線失敗",
    skipped_offline_mode: "離線模式:未連網",
    skipped_after_failure: "前一筆已連線失敗,本筆略過即時查詢",
    not_attempted: "本地已命中,無須連網",
    cache_hit: "快取命中,無須連網",
  };

  var RUN_STATUS = {
    running: { cls: "warn", label: "⏳ 執行中" },
    succeeded: { cls: "ok", label: "✓ 執行完成" },
    incomplete: { cls: "warn", label: "◐ 執行結束但流程不完整" },
    failed: { cls: "bad", label: "✗ 執行失敗" },
    cancelled: { cls: "neutral", label: "已取消" },
    interrupted: { cls: "bad", label: "✗ 執行中斷" },
  };
  var EVENT_MARK = { info: "·", tool: "→", text: "✎", landed: "✓", warn: "!", error: "✗", result: "■" };

  var state = {
    cases: [], caseId: null, detail: null, tab: "overview", loading: false, error: null,
    health: null, runs: {}, verifyOpts: { mode: "auto", timeout: 6, persist: true },
    parties: {}, creating: null, caseNotices: {}, liveLogs: {}, liveBusy: {}, pollTimer: null,
    roundIssue: {}, roundKind: {}, pleadingSel: {}, pleadingEdit: {}, diffOn: {}, pleadingBusy: {}, pleadingNotice: {}, pleadingSide: {}, docChoice: {},
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
  // 時間一律以台灣時間顯示(資料庫存 UTC)；解析不了的字串照原樣顯示
  var TW_TIME = (function () {
    try { return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }); }
    catch (e) { return null; }
  })();
  function fmtTime(iso) {
    if (!iso) return "—";
    var t = Date.parse(iso);
    if (!TW_TIME || isNaN(t) || !/Z$|[+-]\d\d:?\d\d$/.test(iso)) return iso.replace("T", " ").replace(/:\d\dZ$/, " UTC");
    return TW_TIME.format(new Date(t));
  }
  function pct(x) { return (x * 100).toFixed(1) + "%"; }
  function banner(cls, icon, kids) {
    return h("div", { class: "banner " + cls, role: cls === "bad" ? "alert" : null },
      h("span", { class: "b-ico", "aria-hidden": "true", text: icon }), h("div", null, kids));
  }
  // 錄製紀錄只在頂部列標一次(renderTopbar)，各分頁不再重複；即時生成與混合的內容照舊逐筆標示
  function recChip() { return null; }
  // 「本次即時生成」只標在落於 UI 即時執行期間的紀錄(後端依 live_runs 起訖時間判定)，其餘一律是錄製紀錄。
  function originChip(o) {
    return o && o.kind === "live"
      ? chip("ok", "⚡ 本次即時生成・執行 #" + o.run_id, { title: "由 UI 觸發本機 Claude Code 即時產生並落地資料庫" })
      : recChip();
  }
  function provChip(items) {
    var live = items.filter(function (x) { return x.origin && x.origin.kind === "live"; });
    if (!items.length || !live.length) return recChip();
    if (live.length === items.length) return originChip(live[0].origin);
    return chip("warn", "混合：部分即時生成、部分錄製", { title: "逐筆標示於下方" });
  }
  function liveInfo() { return (state.health && state.health.live_generation) || { enabled: false, reason: "尚未取得後端狀態" }; }
  // lede 是一句話；more 是完整說明，收在「說明」裡不佔版面
  function panelHead(title, chips, lede, more) {
    return h("div", { class: "panel-head" }, h("h2", { text: title }), chips,
      lede && more ? h("div", { class: "lede-short" }, lede, h("details", null, h("summary", { text: "完整說明" }), h("p", { class: "detail-note", text: more })))
        : lede ? h("p", { class: "lede", text: lede }) : null);
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
  // 長文字預設只顯示 n 行，點一下展開全文(表格與清單用)
  function clamp(text, lines) {
    var el = h("div", { class: "clamp", role: "button", tabindex: "0", title: "點一下展開／收合", text: text == null || text === "" ? "—" : String(text) });
    if (lines && lines > 1) el.style.setProperty("--lines", String(lines));
    var toggle = function () { el.classList.toggle("open"); };
    el.addEventListener("click", toggle);
    el.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
    return el;
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
  function partyState(caseId, role) {
    var key = caseId + ":" + role;
    if (!state.parties[key]) state.parties[key] = { ban: "", inputName: "", searchOpen: false, query: "", search: null, more: null, searchingMore: false, searchSeq: 0, busy: false, searching: false, error: null, result: null };
    return state.parties[key];
  }
  function citeIndex(d) {
    var idx = {};
    d.citations.forEach(function (c) { idx[c.citation_text] = c; });
    return idx;
  }
  // v2 的 stage 1/2/3 對應起訴狀或答辯狀／準備書狀／言詞辯論意旨狀；舊流程照舊寫 S1–S3
  var V2_STAGE_DOC = { 1: { plaintiff: "起訴狀", defendant: "答辯狀" }, 2: "準備書狀", 3: "意旨狀" };
  function usedByLabel(used, v2) {
    if (!v2) return used.map(function (u) { return SIDE[u.side].label + " S" + u.stage; }).join("、");
    return SIDES.map(function (side) {
      var docs = [];
      used.forEach(function (u) {
        if (u.side !== side) return;
        var m = V2_STAGE_DOC[u.stage], name = m && typeof m === "object" ? m[side] : m || "S" + u.stage;
        if (docs.indexOf(name) < 0) docs.push(name);
      });
      return docs.length ? SIDE[side].label + "：" + docs.join("、") : null;
    }).filter(Boolean).join("；");
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
  // 側欄預設只列新流程(v2)且已存入資料庫的案件；舊流程測試案與只在 data/cases 的輸入檔用切換鈕顯示
  var ALL_CASES_KEY = "legaldebate-all-cases";
  var allCasesPref = (function () { try { return localStorage.getItem(ALL_CASES_KEY) === "1"; } catch (e) { return false; } })();
  function showAllCases() { return allCasesPref; }
  function visibleCases() {
    var main = state.cases.filter(function (c) { return c.protocol === "v2" && c.status !== "input_only"; });
    if (showAllCases() || !main.length) return state.cases;
    return state.cases.filter(function (c) { return main.indexOf(c) >= 0 || c.case_id === state.caseId; });
  }
  function renderCaseList() {
    var box = document.getElementById("case-list");
    box.replaceChildren();
    if (!state.cases.length) { box.append(h("div", { class: "detail-note", text: "資料庫中沒有案件。" })); return; }
    var list = visibleCases(), hidden = state.cases.length - list.length, all = showAllCases();
    var label = document.getElementById("case-list-label");
    if (label) label.replaceChildren(h("span", { text: all ? "全部案件" : "案件" }),
      hidden || all ? h("button", { class: "case-filter-btn", type: "button",
        title: all ? "只顯示新流程、已存入資料庫的案件" : "另有 " + hidden + " 件舊流程測試案或未存入資料庫的輸入檔",
        onclick: function () { allCasesPref = !all; try { localStorage.setItem(ALL_CASES_KEY, allCasesPref ? "1" : "0"); } catch (e) { /* 不記憶 */ } renderCaseList(); },
        text: all ? "只看新流程" : "顯示全部(" + state.cases.length + ")" }) : null);
    list.forEach(function (c) {
      var st = CASE_STATUS[c.status] || CASE_STATUS.case_only;
      if (c.status === "in_progress" && c.last_run_status === "running") st = { cls: "warn", label: "進行中" };
      box.append(h("button", {
        class: "case-item", type: "button", "aria-current": c.case_id === state.caseId ? "true" : "false",
        onclick: function () { selectCase(c.case_id, "overview"); },
      },
        h("div", { class: "case-item-id", text: c.case_id }),
        h("div", { class: "case-item-title", text: c.case_type || "(未填案由)" }),
        h("div", { class: "case-item-meta" }, chip(st.cls, st.label),
          c.arguments ? chip("neutral", "論證 " + c.arguments) : null,
          c.last_run_status ? chip(RUN_STATUS[c.last_run_status].cls, c.last_run_status === "succeeded" ? "⚡ 即時生成" : RUN_STATUS[c.last_run_status].label)
            : c.created_via === "ui" ? chip("neutral", "UI 建立") : null)));
    });
  }

  function renderTopbar() {
    var d = state.detail;
    // 新流程案件不顯示右側欄(案件摘要與頂部重複)，主畫面寬度留給書狀與表格
    document.body.classList.toggle("v2-case", !!d && !state.creating && isV2(d));
    if (state.creating) {
      document.getElementById("topbar-id").textContent = "新案件";
      document.getElementById("topbar-title").textContent = "建立新案件";
      document.getElementById("topbar-sub").textContent = "輸入案件事實與雙方當事人，寫入本機資料庫";
      document.getElementById("export-btn").disabled = true;
      return;
    }
    document.getElementById("topbar-id").textContent = d ? d.case.case_id : "—";
    var parties = d && d.case.parties, pn = function (side) { return parties && parties[side] && parties[side].name; };
    document.getElementById("topbar-title").textContent = !d ? "LegalDebate AI" :
      pn("plaintiff") && pn("defendant") ? pn("plaintiff") + " 對 " + pn("defendant") : (d.case.case_type || "案件");
    var kind = d && d.provenance && d.provenance.kind;
    document.getElementById("topbar-sub").replaceChildren(!d ? "" :
      d.case.source === "input_only" ? "民事 ／ 案件輸入(data/cases，尚未存入資料庫)" :
        "民事 ／ " + (pn("plaintiff") && pn("defendant") && d.case.case_type ? d.case.case_type + " ／ " : "") + "建立於 " + fmtTime(d.case.created_at),
      kind === "recorded_replay" ? chip("rec", "⏺ 示範資料(錄製重播)", { title: "內容是先前由 AI 產生並存入資料庫的紀錄，此處重播，不是即時生成" }) :
        kind === "mixed" ? chip("warn", "部分即時生成、部分錄製", { title: "各分頁逐筆標示" }) : null);
    document.getElementById("export-btn").disabled = !d;
  }

  function renderTabs() {
    var nav = document.getElementById("tabs");
    nav.replaceChildren();
    if (state.creating) return;
    tabsNow().forEach(function (t, i) {
      nav.append(h("button", {
        class: "stage-tab", type: "button", role: "tab", "aria-selected": String(t.key === state.tab),
        onclick: function () { switchTab(t.key); },
      }, h("span", { class: "stage-num", text: String(i + 1) }), t.label));
    });
  }

  // ───────────── 分頁：案件總覽 ─────────────
  function provenanceBanner(d) {
    var p = d.provenance;
    if (p.kind === "live_generated" || p.kind === "mixed") {
      var ids = Array.from(new Set(d.arguments.filter(function (a) { return a.origin.kind === "live"; })
        .map(function (a) { return "#" + a.origin.run_id; })));
      return banner(p.kind === "mixed" ? "warn" : "ok", "⚡", [
        h("strong", { text: p.kind === "mixed" ? "部分為本次即時生成" : "本次即時生成" }),
        "：本案論證由本機 Claude Code(UI 執行 " + ids.join("、") + "，模型 " + (p.model_ids.join("、") || "落地時未記錄") +
        ")即時產生，於 " + fmtTime(p.first_recorded_at) + " ～ " + fmtTime(p.last_recorded_at) + " 寫入資料庫，不是錄製紀錄重播。" +
        (p.kind === "mixed" ? "其中部分紀錄不在執行期間內，屬錄製紀錄，各分頁逐筆標示。" : ""),
      ]);
    }
    if (p.kind === "recorded_replay") {
      return banner("rec", "⏺", [
        h("strong", { text: "錄製紀錄重播" }),
        "：本案原告、被告、法官的論證由 AI 產生於 " + fmtTime(p.first_recorded_at) + " ～ " + fmtTime(p.last_recorded_at) +
        "，事後寫入系統紀錄；此處是重播記錄內容，不是即時生成。「當事人查核」、「機械彙整」與「引用查證」分頁則是點擊按鈕後，系統當場計算／查詢。",
      ]);
    }
    if (p.kind === "input_only") {
      return banner("warn", "!", [h("strong", { text: "尚未落地資料庫的案件輸入" }),
        "：此案件只存在 data/cases，UI 不對它開放即時執行；如需執行，請用「＋ 建立新案件」重新輸入。"]);
    }
    var hl = liveInfo();
    var running = (d.live_runs || []).some(function (r) { return r.status === "running"; });
    return banner("warn", running ? "⏳" : "!", [
      h("strong", { text: "尚無攻防紀錄" }),
      "：此案件只有案件輸入，資料庫還沒有任何論證或訊問。" +
        (running ? "即時執行進行中，各階段落地後會自動出現。" :
          hl.enabled ? "可在下方「即時執行」由本機 Claude Code 跑完整流程。" : "即時執行目前停用：" + hl.reason + "。"),
    ]);
  }

  function overviewPanel(d) {
    if (isV2(d)) return overviewPanelV2(d);
    var s = d.stats;
    return [
      panelHead("案件總覽", d.arguments.length ? provChip(d.arguments) : null),
      provenanceBanner(d),
      (state.caseNotices[d.case.case_id] || []).map(function (n) { return banner(n.cls, n.icon, n.text); }),
      liveRunCard(d),
      h("p", { class: "detail-note", text: partySummary(d) }),
      d.case.parties ? card("雙方當事人(使用者輸入)", SIDES.map(function (side) {
        var p = d.case.parties[side];
        return h("div", { class: "meta-row" }, h("span", { class: "meta-key", text: SIDE[side].label }),
          h("span", { class: "meta-val", text: p.name + (p.ban ? "(統編 " + p.ban + ")" : "(未提供統編，不查核)") }));
      })) : null,
      card("案件事實(原始輸入全文)", paragraphs(d.case.facts_summary), chip("neutral", d.case.case_type || "未填案由")),
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
        SIDES.map(function (side) {
          return stat(pleadingOf(d, side) ? "已完成" : "尚未產生", DOCUMENT[side].short + "骨架(" + SIDE[side].label + ")");
        })),
      prepListCard(d),
    ];
  }
  // v2 總覽:先給「走到哪、下一步、爭點強弱、書狀、引用」摘要，案件輸入與技術細節收合在下面
  function v2Summary(d) {
    var steps = (d.progress || []).filter(function (x) { return STEP_TAB[x.key]; });
    var doneN = steps.filter(function (x) { return x.state === "done"; }).length;
    var running = (d.live_runs || []).some(function (r) { return r.status === "running"; });
    var cur = steps.filter(function (x) { return x.state !== "done"; })[0], rp = d.resume;
    var next, nextTab = null;
    if (running) next = "即時執行進行中，各階段完成後會自動出現。";
    else if (rp && rp.gate_pending) { next = "起訴狀初稿已完成，請到「" + tabLabel("complaint") + "」確認或編輯，確認後才能續跑。"; nextTab = "complaint"; }
    else if (cur && rp && rp.possible) { next = "可從「" + rp.from_label + "」續跑(控制在下方「即時執行」)。"; }
    else if (cur) { next = "尚未完成的步驟：" + stepLabel(cur.label) + "。"; }
    else { next = "流程已全部完成。到「" + tabLabel("diagnosis") + "」看哪裡弱、怎麼改，到「" + tabLabel("complaint") + "」編輯或匯出書狀。"; nextTab = "diagnosis"; }
    var risk = (d.verdict && d.verdict.risk_map) || {}, assess = risk.issue_assessment || [];
    var cnt = { "強": 0, "中": 0, "弱": 0 };
    assess.forEach(function (a) { if (cnt[a.strength] != null) cnt[a.strength]++; });
    var todoN = (risk.evidence_todo || []).length, revN = (risk.complaint_revisions || []).length;
    var g = complaintGate(d), autoGate = g && g.by === "auto";
    var docs = (d.pleading_versions || []);
    var blockedDocs = docs.filter(function (v) { return v.exportable === false; }).length;
    var s = d.stats, badCites = s.citations - s.citations_published;
    var row = function (icon, label, text, tab, tabText) {
      return h("li", { class: "sum-row" }, h("span", { class: "sum-ico", "aria-hidden": "true", text: icon }), h("span", { class: "sum-label", text: label }),
        h("span", { class: "sum-text", text: text }),
        tab ? h("button", { class: "btn small", type: "button", text: tabText, onclick: function () { switchTab(tab); } }) : null);
    };
    var nextNote = nextTab === "complaint" ? "前往確認" : nextTab ? "查看" : null;
    // 頂端數字列：每格可點，直接跳到對應分頁(demo 時照著點就是講稿)
    var tile = function (num, label, cls, tab) {
      return h("button", { class: "kpi " + (cls || ""), type: "button", disabled: tab ? null : true, onclick: tab ? function () { switchTab(tab); } : null },
        h("span", { class: "kpi-num", text: num }), h("span", { class: "kpi-label", text: label }));
    };
    var kpis = h("div", { class: "kpi-row" },
      tile(assess.length ? String(assess.length) : "—", assess.length ? "個爭點：強 " + cnt["強"] + "／中 " + cnt["中"] + "／弱 " + cnt["弱"] : "尚未評估爭點強弱", cnt["弱"] ? "bad" : "", assess.length ? "diagnosis" : null),
      tile(todoN ? String(todoN) : "—", "項待補證據", todoN ? "warn" : "", todoN ? "diagnosis" : null),
      tile(revN ? String(revN) : "—", "項起訴狀修改建議", "", revN ? "diagnosis" : null),
      tile(s.citations ? s.citations_published + "/" + s.citations : "—", s.citations ? (badCites ? "條引用通過，" + badCites + " 條未過" : "條引用全部對到官方原文") : "沒有引用", s.citations ? (badCites ? "bad" : "ok") : "", s.citations ? "verify" : null));
    return [kpis, card(null, h("ul", { class: "sum-list" },
      row("▶", "下一步", next, nextTab, nextNote),
      autoGate ? row("!", "律師確認", "起訴狀初稿是流程自動採用的，尚未經律師確認。", "complaint", "看起訴狀") : null,
      row(running ? "⏳" : doneN === steps.length ? "✓" : "◐", "進度", "已完成 " + doneN + " / " + steps.length + " 步" + (cur && !running ? "，停在「" + stepLabel(cur.label) + "」" : ""), null),
      row(docs.length ? "✓" : "·", "書狀", docs.length ? docs.length + " 份書狀版本" + (blockedDocs ? "，其中 ✗ " + blockedDocs + " 份未放行不能匯出" : "，可閱讀、編輯、匯出") : "尚未產生書狀", docs.length ? "complaint" : null, "看書狀")))];
  }
  function overviewPanelV2(d) {
    var runs = (d.live_runs || []).filter(function (r) { return r.kind !== "pleadings"; }), latest = runs[runs.length - 1], rp = d.resume;
    var live = liveRunCard(d), c = d.case, checks = d.party_checks || {};
    // 未執行、執行中或還有可續跑的步驟時，執行控制放在前面；已跑完的執行紀錄收進「技術細節」
    var liveFront = live && (!latest || latest.status === "running" || (rp && (rp.possible || rp.gate_pending)));
    var party = function (side) {
      var p = c.parties && c.parties[side];
      return h("div", { class: "meta-row" }, h("span", { class: "meta-key", text: SIDE[side].label }),
        h("span", { class: "meta-val", text: p ? p.name + (p.ban ? "(統編 " + p.ban + ")" : "") : "—" }));
    };
    var input = card("案件輸入", [
      h("div", { class: "chip-row" }, chip("neutral", c.case_type || "未填案由"), chip("neutral", c.claim_amount == null ? "金額未填" : "金額 " + fmtAmount(c.claim_amount) + " 元")),
      party("plaintiff"), party("defendant"),
      field("事實經過", clamp(c.facts_summary, 3)), field("請求／訴之聲明", clamp(c.claims, 2)),
      c.evidence.length ? field("證據", c.evidence.map(function (e) {
        return h("div", { class: "meta-row" }, h("span", { class: "meta-key", text: e.id }), h("span", { class: "meta-val" }, clamp(e.description + (e.date ? "(" + e.date + ")" : ""))));
      })) : null]);
    var checkCards = SIDES.map(function (side) {
      var r = checks[side], p = c.parties && c.parties[side];
      return h("div", { class: "check-row" },
        sideChip(side),
        r ? [h("strong", { text: r.name || "官方未提供名稱" }), chip(r.status_level || "neutral", (r.status_level === "bad" ? "✗ " : r.status_level === "ok" ? "✓ " : "! ") + (r.status_text || "狀態未提供")),
          (r.warnings || []).length ? chip("warn", "警示 " + r.warnings.length) : chip("ok", "無警示"),
          h("span", { class: "detail-note", text: "法定代理人:" + partyRepresentativeText(r) })]
          : h("span", { class: "detail-note", text: p && p.ban ? "尚未查核" : "未提供統編，不查核" }));
    });
    var check = card("商工登記查核", [checkCards,
      h("div", { class: "controls" }, h("button", { class: "btn small", type: "button", text: "查看查核細節", onclick: function () { switchTab("parties"); } }))]);
    var steps = (d.progress || []).filter(function (x) { return STEP_TAB[x.key]; });
    var doneN = steps.filter(function (x) { return x.state === "done"; }).length;
    var running = (d.live_runs || []).some(function (r) { return r.status === "running"; });
    return [
      panelHead("案件總覽", d.arguments.length ? provChip(d.arguments) : null, "這個案件目前的結果，以及下一步要做什麼。"),
      (state.caseNotices[d.case.case_id] || []).map(function (n) { return banner(n.cls, n.icon, n.text); }),
      liveFront ? live : null,
      v2Summary(d),
      h("div", { class: "overview-split" }, input, check),
      // 流程進度和上方分頁列重複；跑完時收合，執行中或停在中途時展開
      fold("流程進度・已完成 " + doneN + " / " + steps.length + " 步", progressTrack(d), running || doneN < steps.length),
      fold("完整案件輸入與技術細節", [
        h("p", { class: "detail-note", text: partySummary(d) }),
        card("我方主張的事實經過", paragraphs(c.facts_summary)), card("請求／訴之聲明", paragraphs(c.claims)),
        caseInputCards(d), provenanceBanner(d), liveFront ? null : live, prepListCard(d), techDetails(d)]),
    ];
  }
  function isV2(d) { return d.case.protocol === "v2"; }
  function fmtAmount(n) { return Number(n).toLocaleString("en-US"); }
  function caseInputCards(d) {
    var c = d.case;
    return [
      card("證據清單", c.evidence.length ? c.evidence.map(function (e) {
        return h("div", { class: "meta-row" }, h("span", { class: "meta-key", text: e.id }),
          h("span", { class: "meta-val", text: e.description + (e.date ? "(" + e.date + ")" : "") + (e.proves ? "；待證事實：" + e.proves : "") }));
      }) : h("p", { class: "detail-note", text: "沒有列證據。" })),
      c.opponent_known_responses.length ? card("對方已知反應", c.opponent_known_responses.map(function (r) {
        return h("div", { class: "meta-row" }, h("span", { class: "meta-key", text: r.source || "來源未填" }),
          h("span", { class: "meta-val", text: r.text + (r.date ? "(" + r.date + ")" : "") }));
      })) : null,
      c.known_gaps.length ? card("已知缺口(只給律師與原告方)", c.known_gaps.map(function (g) { return h("p", { text: g }); })) : null,
    ];
  }
  function precheckCard(d) {
    var p = d.precheck;
    return card("程序與時效提示", [
      h("div", { class: "chip-row" }, chip("neutral", "程序類型：" + p.procedure.type), p.warnings.length ? chip("warn", "提示 " + p.warnings.length + " 則") : null),
      // 有時效或程序提示時直接攤開(這是本頁最該看的)；說明與程序類型細節收合
      p.warnings.map(function (w) {
        return h("div", { class: "precheck-row" }, h("p", { text: w.message }),
          w.legal_basis.length ? h("p", { class: "detail-note", text: "條文：" + w.legal_basis.join("、") }) : null);
      }),
      fold("程序類型說明", [h("p", { class: "detail-note", text: p.note }),
        h("p", null, p.procedure.message), h("p", { class: "detail-note", text: "條文：" + p.procedure.legal_basis.join("、") })])]);
  }
  function stat(num, label, cls) {
    return h("div", { class: "stat " + (cls || "") }, h("div", { class: "stat-num", text: num }), h("div", { class: "stat-label", text: label }));
  }

  // ───────────── 書狀交換流程(protocol v2)的分頁 ─────────────
  // 交接 B:總覽的進度軌。步驟與完成判定用後端的 progress(同 server/live_run.py RUN_STEPS_V2 與續跑判定)，UI 不自己重算
  // 進度格上方的小字：對應的分頁名稱(不用 P0–P6 代號)
  var STEP_TAB = { "case": "overview", analysis: "complaint", complaint: "complaint", gate1: "complaint", defense: "answer", answer: "answer",
    issue_sheet: "sheet", stage2: "rounds", brief: "rounds", stage3: "rounds", closing: "rounds", verdict: "diagnosis", revision: "diagnosis" };
  var STEP_PHASE = {};
  Object.keys(STEP_TAB).forEach(function (k) { STEP_PHASE[k] = (TABS_V2.filter(function (t) { return t.key === STEP_TAB[k]; })[0] || {}).label; });
  STEP_PHASE.gate1 = "律師確認";
  // 後端步驟名稱裡的流程代號換成律師用語(只換顯示)
  function stepLabel(label) {
    return String(label || "").replace(/關卡\s*1\s*律師確認起訴狀/, "律師確認起訴狀").replace(/起訴狀 v1/, "起訴狀初稿")
      .replace(/起訴狀 v2/, "修訂版起訴狀").replace(/第 2 輪論證/, "第一次書狀往返的論證").replace(/第 3 輪論證/, "最後辯論的論證");
  }
  var TRACK_STATE = { done: ["✓", "已完成"], active: ["⏳", "進行中"], partial: ["◐", "部分完成"], pending: ["·", "未開始"] };
  function progressTrack(d) {
    var steps = d.progress.filter(function (s) { return STEP_TAB[s.key]; });
    var running = (d.live_runs || []).some(function (r) { return r.status === "running"; });
    var current = running ? steps.filter(function (s) { return s.state !== "done"; })[0] : null;
    return card(null, [
      h("ol", { class: "track" }, steps.map(function (s) {
        var st = s === current ? "active" : s.state === "done" ? "done" : s.state === "partial" ? "partial" : "pending";
        var auto = s.key === "gate1" && /自動/.test(s.detail || "");
        // 關卡 1 寫明是律師確認、自動通過(未經律師確認)還是到此結束
        var label = s.key === "gate1" && s.state === "done" ? s.detail : TRACK_STATE[st][1] + (st === "partial" && s.detail ? "(" + s.detail + ")" : "");
        return h("li", { class: "track-step " + st + (auto ? " auto" : "") },
          h("button", { class: "track-btn", type: "button", title: "前往「" + tabLabel(STEP_TAB[s.key]) + "」分頁",
            onclick: function () { switchTab(STEP_TAB[s.key]); } },
            h("span", { class: "track-phase", text: STEP_PHASE[s.key] }),
            h("span", { class: "track-label", text: stepLabel(s.label) }),
            h("span", { class: "track-state", text: (auto ? "!" : TRACK_STATE[st][0]) + " " + label })));
      })),
      null]);
  }
  function v2Stats(d) {
    var sheet = d.issue_sheet && d.issue_sheet.sheet, s = d.stats;
    var docs = (d.pleading_versions || []).filter(function (v) { return v.source === "system" || v.source === "system_revision"; }).length;
    return h("div", { class: "stat-grid" },
      stat(sheet ? String((sheet.issues || []).length) : "—", "爭點(爭點整理表)"),
      stat(sheet ? String((sheet.undisputed || []).length) : "—", "不爭執事項"),
      stat(s.citations ? s.citations_published + " / " + s.citations : "—", "論證引用已查證通過",
        s.citations && s.citations_published < s.citations ? "warn" : (s.citations ? "ok" : "")),
      stat(String(docs), "系統產生的書狀(份)"));
  }
  function dataTable(heads, rows, wide) {
    return h("div", { class: "table-wrap" }, h("table", { class: "data-table" + (wide ? " wide" : "") },
      h("thead", null, h("tr", null, heads.map(function (t) { return h("th", { scope: "col", text: t }); }))),
      h("tbody", null, rows.map(function (cells) { return h("tr", null, cells.map(function (c) { return h("td", null, c == null || c === "" ? "—" : c); })); }))));
  }
  function bulletList(items) { return h("ul", { class: "risk-list" }, (items || []).map(function (t) { return h("li", { text: t }); })); }

  // 起訴狀(P1、關卡 1):起訴狀 v1、律師版與關卡卡片，加上起訴審查(補正寫在起訴狀「四、程序事項」)
  function complaintTabPanel(d) {
    var p = d.procedural_issues, n = p ? p.issues.length : 0;
    var checked = p && SIDES.some(function (s) { return p.parties[s]; });
    // 已查核且 0 項時不佔版面(「當事人與管轄」分頁已列查核結果)；有事項才顯示
    var pb = checked && !n ? null : proceduralBlock(d);
    return [].concat(pleadingPanel(d, { title: "起訴狀", fixedSide: true, reader: true,
        lede: "AI 依案情起草的起訴狀，須由執業律師審核後使用。" }),
      [pb && n ? fold("起訴審查(依商工登記命補正)・" + n + " 項", pb) : pb]);
  }

  // 交接 C:答辯狀的逐點表態表
  var STANCE = { admit: { cls: "ok", label: "不爭執" }, deny: { cls: "bad", label: "否認" },
    authenticity: { cls: "warn", label: "爭執其形式上真正" }, to_confirm: { cls: "neutral", label: "待被告本人確認" } };
  var GROUND_LABEL = { insufficient_proof: "原告舉證不足", alternative_explanation: "另一可能解釋(推測)" };
  // 抗辯種類是撰狀 subagent 寫的英文代號(範本只舉例)，認得的才加中文標籤，其餘不顯示代號
  var DEFENSE_LABEL = { payment: "清償", set_off: "抵銷", limitation: "時效", prescription: "時效", invalidity: "無效", procedural: "程序",
    exclusion_period: "除斥期間", no_claim: "請求權不存在", no_harm_to_creditor: "未害及債權", element_missing_alternative: "要件欠缺(備位)" };
  function docCiteChip(text, checks) {
    var c = checks.filter(function (x) { return x.citation_text === text; })[0], ok = c && c.gate === "pass";
    return h("span", { class: "cite " + (ok ? "ok" : "warn"), title: ok ? "書狀落地時已通過查證" : "書狀的引用查證找不到這一條" },
      h("span", { class: "cite-mark", "aria-hidden": "true", text: ok ? "✓" : "?" }), text);
  }
  function answerPanel(d) {
    var a = (d.pleadings || {}).defendant, st = a && a.structured;
    var full = pleadingPanel(d, { title: st ? "答辯狀全文" : "對方答辯狀(模擬)", fixedSide: true, reader: true, noHead: !!st });
    if (!st) return full;
    var facts = a.complaint_facts || {}, responses = st.responses || [], counts = {};
    var ver = (d.pleading_versions || []).filter(function (v) { return v.id === a.id; })[0], checks = ver ? ver.citation_check : [];
    responses.forEach(function (r) { counts[r.stance] = (counts[r.stance] || 0) + 1; });
    return [
      panelHead("對方答辯狀(模擬)", originChip(a.origin),
        "AI 扮演對方律師寫的答辯，用來預想對方會怎麼打；標「推測」的是 AI 猜的，不是對方實際主張。"),
      banner("rec", "🔒", [h("strong", { text: "模擬的對方律師只看得到你的起訴狀" }),
        "，看不到你的內部分析、事實經過全文與已知缺口。",
        h("span", { class: "detail-note", text: "(依執行紀錄稽核：對方角色沒有讀取我方分析的紀錄)" })]),
    ].concat(full, [fold("逐點表態、抗辯與待確認事項", [
      card("逐點表態(共 " + responses.length + " 點)", [
        h("div", { class: "chip-row" }, Object.keys(STANCE).filter(function (k) { return counts[k]; }).map(function (k) {
          return chip(STANCE[k].cls, STANCE[k].label + " " + counts[k] + " 點");
        })),
        !counts.admit ? h("p", { class: "detail-note", text: "沒有任何一點表示不爭執：範本要求模擬被告在沒有被告本人的事實時保守表態(否認或待被告本人確認)，所以爭點整理表的不爭執事項會是空的。" }) : null,
        dataTable(["事實點", "原告主張(起訴狀原文)", "表態", "理由"], responses.map(function (r) {
          var s = STANCE[r.stance] || { cls: "neutral", label: r.stance };
          return [h("span", { class: "nowrap", text: r.fact_id }), clamp(facts[r.fact_id] || "(起訴狀正文找不到這個事實點)"),
            h("div", { class: "chip-row" }, chip(s.cls, s.label),
              r.hypothetical && r.ground !== "alternative_explanation" ? chip("warn", "推測") : null),
            clamp((r.ground ? (GROUND_LABEL[r.ground] || r.ground) + "：" : "") + (r.reason || ""))];
        }))]),
      card("抗辯(共 " + (st.defenses || []).length + " 項)", (st.defenses || []).map(function (x, i) {
        return h("div", { class: "precheck-row" },
          h("div", { class: "chip-row" }, chip("defendant", "抗辯 " + (i + 1)), DEFENSE_LABEL[x.type] ? chip("neutral", DEFENSE_LABEL[x.type]) : null,
            x.hypothetical ? chip("warn", "推測") : null),
          h("p", { class: "prewrap", text: x.statement }),
          (x.legal_basis || []).length ? h("div", { class: "chip-row" }, x.legal_basis.map(function (t) { return docCiteChip(t, checks); })) : null);
      })),
      (st.to_confirm || []).length ? card("待被告本人確認(共 " + st.to_confirm.length + " 項)", [
        h("p", { class: "detail-note", text: "模擬被告沒有被告本人的事實，以下事項它無法表態，正式答辯前要由被告本人說明。" }),
        bulletList(st.to_confirm)]) : null])]);
  }

  // 交接 D:爭點整理表。表二、表三用結構化內容畫；表一(聲明與請求權基礎)、表四(證據清單)取後端 render_issue_sheet 組好的文字
  var BURDEN_LABEL = { plaintiff: "原告", defendant: "被告", undetermined: "未定" };
  var ISSUE_KIND = { fact: "事實", law: "法律", defense: "抗辯" };
  function sheetBlock(text, head) {  // 表頭那一行之後到第一個空行
    var i = text.indexOf(head);
    if (i < 0) return "";
    var rest = text.slice(i + head.length).replace(/^\n/, ""), j = rest.indexOf("\n\n");
    return (j < 0 ? rest : rest.slice(0, j)).trim();
  }
  function mdRows(block) {
    return block.split("\n").filter(function (l) { return /^\|/.test(l) && !/^\|[\s|-]+\|$/.test(l); })
      .map(function (l) { return l.replace(/^\||\|$/g, "").split("|").map(function (c) { return c.trim(); }); });
  }
  function sheetQuestion(q, clar) {
    var based = q.based_on || "", side = SIDE[q.target_side] ? q.target_side : "plaintiff";
    return h("div", { class: "judge-q" },
      h("div", { class: "judge-q-head" }, sideChip(side, (clar ? "闡明・對" : "訊問・對") + SIDE[side].label),
        /^官方事實層\(/.test(based) ? chip("judge", "補正追問") : null,
        isPrepQuestion(q) ? chip("judge", "準備題・假設") : null),
      h("div", { class: "judge-q-text prewrap", text: q.question || q.question_text }),
      h("div", { class: "judge-q-basis" }, h("b", { text: "依據：" }), based + (q.basis ? "(" + q.basis + ")" : "")));
  }
  // 爭點代號 I1 → 1(畫面上加「爭點」二字即可，代號律師看不懂)；非 I 開頭的(如程序事項)照原樣
  function issueNum(id) { var m = /^I(\d+)$/.exec(id || ""); return m ? m[1] : (id || "—"); }
  function factName(id) { var m = /^CF(\d+)$/.exec(id || ""); return m ? "事實 " + m[1] : (id || "—"); }
  function issueName(id) { var m = /^I(\d+)$/.exec(id || ""); return m ? "爭點 " + m[1] : (id || "—"); }
  function subLine(label, list) {
    return list && list.length ? h("div", { class: "cell-sub", text: label + "：" + list.join("、") }) : null;
  }
  function sheetPanel(d) {
    var s = d.issue_sheet;
    var head = panelHead("爭點整理(模擬)", s ? originChip(s.origin) : null,
      "模擬法官讀完起訴狀與答辯狀後，整理兩造到底在爭什麼；不是法院的爭點整理。",
      "法官角色只讀起訴狀與模擬答辯狀，照司法院民事訴訟事件審理須知例示的四張表格式整理聲明、不爭執事項、爭點與證據，並列出闡明與訊問。最重要的表三(爭點)放最前面。");
    if (!s) return [head, emptyState("尚未產生。書狀交換流程在模擬答辯狀之後由法官角色整理。")];
    var sh = s.sheet || {}, issues = sh.issues || [], und = sh.undisputed || [];
    var clar = sh.clarifications || [], qs = sh.questions || [];
    var t1 = sheetBlock(s.text, "表一　聲明與請求權基礎"), ev = mdRows(sheetBlock(s.text, "表四　證據清單"));
    var band = function (title, items, isClar) {
      return items.length ? h("section", { class: "judge-band" },
        h("div", { class: "judge-band-title" }, chip("judge", "法官"), title + "(" + items.length + " 則)"),
        items.map(function (q) { return sheetQuestion(q, isClar); })) : null;
    };
    var t2card = function () { return card("不爭執事項(表二)", und.length
        ? dataTable(["編號", "不爭執事項", "來源", "證據"], und.map(function (u) {
          return [u.id, u.text, (u.source || []).join("、"), (u.evidence || []).join("、") || "無"]; }))
        : h("p", { class: "detail-note", text: "(無)" }),
        chip("neutral", und.length + " 項", { title: s.undisputed_note + "；無不爭執事項是模擬被告保守表態的預期結果，不代表當事人真的每一點都爭執。" })); };
    return [head,
      // 5 欄：證據與法條併到主張／爭點格的小字，爭點全文不截斷，主張與抗辯先顯示 3 行(點一下看全文)
      card("爭點(表三)", dataTable(["#", "爭點", "原告主張", "被告抗辯", "舉證責任"],
        issues.map(function (i) {
          return [h("strong", { class: "nowrap", text: issueNum(i.id) }),
            [h("div", { class: "cell-main", text: i.text }), h("div", { class: "chip-row" }, ISSUE_KIND[i.kind] ? chip("neutral", ISSUE_KIND[i.kind]) : null,
              i.hypothetical ? chip("warn", "推測") : null),
              subLine("法律依據", i.legal_basis)],
            [clamp(i.plaintiff_claim, 3), subLine("證據", i.plaintiff_evidence)],
            [clamp(i.defendant_defense, 3), subLine("證據", i.defendant_evidence)],
            BURDEN_LABEL[i.burden] || i.burden];
        })), chip("neutral", issues.length + " 個爭點")),
      und.length ? t2card() : fold("不爭執事項(表二)・0 項", h("p", { class: "detail-note", text: s.undisputed_note + "；無不爭執事項是模擬被告保守表態的預期結果，不代表當事人真的每一點都爭執。" })),
      fold("聲明與請求權基礎(表一，取自起訴狀正文)", h("div", { class: "prewrap", text: t1 || "(起訴狀未列)" })),
      fold("證據清單(表四)", ev.length ? dataTable(["編號", "種類", "日期", "內容"], ev) : h("p", { class: "detail-note", text: "(起訴狀未附證據)" })),
      clar.length || qs.length ? fold("法官闡明與訊問(" + (clar.length + qs.length) + " 則)", [band("闡明", clar, true), band("訊問", qs, false)]) : null,
      fold("四張表的文字版(與匯出內容相同)", h("div", { class: "prewrap", text: s.text }))];
  }

  // 準備書狀與意旨狀(P4、P5):雙方各兩份書狀；論證原文折疊放在下面(取代舊流程的「攻防過程」)
  function roundsPanel(d) {
    var id = d.case.case_id, sheet = d.issue_sheet && d.issue_sheet.sheet, issues = (sheet && sheet.issues) || [];
    var docs = (d.pleading_versions || []).filter(function (v) { return ROUND_DOC[v.pleading_type]; });
    if (!issues.length || !docs.length) return roundsPanelFull(d);
    var kind = state.roundKind[id];
    if (!docs.some(function (v) { return v.pleading_type === kind; })) kind = docs.some(function (v) { return v.pleading_type === "brief"; }) ? "brief" : "closing";
    var issue = issues.filter(function (i) { return i.id === state.roundIssue[id]; })[0] || issues[0];
    var assess = {};
    ((d.verdict && d.verdict.risk_map && d.verdict.risk_map.issue_assessment) || []).forEach(function (a) { assess[a.issue_id] = a; });
    var docOfSide = function (side) { return docs.filter(function (v) { return v.pleading_type === kind && (v.side || "plaintiff") === side; })[0]; };
    var list = h("ol", { class: "issue-list", "aria-label": "爭點" }, issues.map(function (i) {
      var a = assess[i.id];
      return h("li", null, h("button", { type: "button", class: "issue-btn", "aria-pressed": String(i.id === issue.id),
        onclick: function () { state.roundIssue[id] = i.id; renderPanel(); } },
        h("strong", { text: issueName(i.id) }), h("span", { class: "issue-btn-text", text: i.text }),
        a ? chip(STRENGTH_CLS[a.strength] || "neutral", "我方 " + (a.strength === "強" ? "▲ " : a.strength === "弱" ? "▼ " : "● ") + a.strength,
          { title: "原告(我方)在這個爭點的強弱，不是勝訴機率" }) : null));
    }));
    var column = function (side) {
      var v = docOfSide(side), sec = v ? roundIssueSection(v.draft_text, issue.id) : null;
      return h("article", { class: "arg " + side },
        h("div", { class: "arg-head" }, sideChip(side, SIDE[side].agent), chip("neutral", ROUND_DOC[kind] + (v ? " #" + v.id : ""))),
        h("div", { class: "arg-body round-text" }, sec ? paragraphs(sec.replace(/\n/g, "\n\n"))
          : h("p", { class: "detail-note", text: v ? "這份書狀沒有針對這個爭點的陳述。" : SIDE[side].label + "沒有這份書狀。" })));
    };
    var kinds = h("div", { class: "seg", role: "group", "aria-label": "書狀種類" }, ["brief", "closing"].map(function (k) {
      return h("button", { type: "button", "aria-pressed": String(k === kind), disabled: docs.some(function (v) { return v.pleading_type === k; }) ? null : true,
        onclick: function () { state.roundKind[id] = k; renderPanel(); }, title: ROUND_DOC[k],
        text: k === "brief" ? "第一次書狀往返(準備書狀)" : "最後辯論(意旨狀)" }, null);
    }));
    return [
      panelHead("攻防模擬", d.arguments.length ? provChip(d.arguments) : null,
        "左邊選爭點，右邊並排看兩造書狀怎麼寫；皆為 AI 模擬，不是實際主張。"),
      h("div", { class: "issue-split" }, list,
        h("div", { class: "issue-main" },
          h("div", { class: "issue-title" }, h("strong", { text: issueName(issue.id) }), h("span", { text: issue.text }),
            ISSUE_KIND[issue.kind] ? chip("neutral", ISSUE_KIND[issue.kind]) : null, BURDEN_LABEL[issue.burden] ? chip("neutral", "舉證責任：" + BURDEN_LABEL[issue.burden]) : null,
            issue.hypothetical ? chip("warn", "推測") : null, kinds),
          h("div", { class: "debate-layout" }, column("plaintiff"), column("defendant")))),
      fold("完整書狀、論證原文與技術細節", roundsPanelFull(d).slice(1)),
    ];
  }
  // 書狀「二、陳述」中某一爭點的段落(從【爭點 Ix】下一行到下一個爭點或「三、引用」前)
  function roundIssueSection(text, issueId) {
    var lines = delabelJargon(splitDraftNote(text).body).split("\n"), start = -1, end = lines.length;
    for (var i = 0; i < lines.length; i++) {
      if (start < 0) { if (lines[i].indexOf("【爭點 " + issueId + "】") === 0) start = i; }
      else if (/^【爭點 /.test(lines[i]) || /^三、引用\s*$/.test(lines[i]) || /^證物名稱及件數/.test(lines[i])) { end = i; break; }
    }
    return start < 0 ? null : lines.slice(start + 1, end).join("\n").trim() || null;
  }
  function roundsPanelFull(d) {
    var idx = citeIndex(d);
    var foldStage = function (stage, title) {
      var g = stageGroup(d, stage, title, idx);
      return g ? fold(title, g) : null;
    };
    return [
      panelHead("攻防模擬", d.arguments.length ? provChip(d.arguments) : null,
        "準備書狀逐爭點回應，言詞辯論意旨狀收斂最終立場。皆為 AI 模擬，不是當事人或對方律師的實際主張。"),
      roundDocsCard(d) || emptyState("尚未產生。準備書狀在爭點整理表之後的續跑產生。"),
      d.arguments.length ? h("div", { class: "section-title", text: "論證原文(書狀正文由各方公開論證組成)" }) : null,
      foldStage(1, "起訴前與答辯前的分析(被告只讀起訴狀，看不到原告的分析)"),
      foldStage(2, "準備書狀的論證(依爭點整理表逐爭點回應)"),
      foldStage(3, "言詞辯論意旨狀的論證(收斂到最終立場)"),
      d.arguments.length ? fold("技術細節：階段間引用變化", changesCard(d)) : null];
  }

  // 交接 E、F:診斷新鍵與起訴狀 v2 的差異對照。不顯示勝訴機率(規格只給爭點強弱)
  var STRENGTH_CLS = { "強": "ok", "中": "warn", "弱": "bad" };
  var REVISION_KIND = { revise: "改寫", add_alternative: "新增備位", "delete": "刪除" };
  function revisionOf(d) {
    return (d.pleading_versions || []).filter(function (v) { return v.source === "system_revision"; }).slice(-1)[0] || null;
  }
  function diffBlock(diff) {
    return [h("p", { class: "detail-note", text: "綠＋新增 " + diff.added + " 行・紅−刪除 " + diff.removed + " 行(只比正文)" }),
      h("div", { class: "diff-doc" }, diff.lines.map(function (ln) {
        var mark = ln.op === "insert" ? "+" : ln.op === "delete" ? "−" : "";
        return h("div", { class: "diff-line " + ln.op },
          h("span", { class: "diff-mark", "aria-hidden": "true", text: mark }),
          ln.op === "equal" ? null : h("span", { class: "sr-only", text: ln.op === "insert" ? "新增：" : "刪除：" }),
          h("span", { class: "diff-text", text: ln.text || " " }));
      }))];
  }
  function diffToggle(d, v) {
    var id = d.case.case_id, on = !!state.diffOn[id];
    return h("div", { class: "seg", role: "group", "aria-label": "起訴狀 v2 的顯示方式" },
      h("button", { type: "button", "aria-pressed": String(!on), onclick: function () { state.diffOn[id] = false; renderPanel(); } }, "全文"),
      h("button", { type: "button", "aria-pressed": String(on), onclick: function () { state.diffOn[id] = true; renderPanel(); } }, "與 #" + v.parent_id + " 比較"));
  }
  function revisionCard(d, rev) {
    if (!rev) return card("修訂版起訴狀", h("p", { class: "detail-note", text: "尚未產生。診斷完成後由原告方依修改建議改寫。" }));
    var id = d.case.case_id, exportUrl = API_BASE + "/api/cases/" + encodeURIComponent(id) + "/pleadings/" + rev.id + "/export";
    return h("div", { id: "revision-card" }, card("修訂版起訴狀：和初稿相比改了什麼", [
      h("div", { class: "chip-row" }, originChip(rev.origin), chip(rev.exportable ? "ok" : "bad", rev.exportable ? "✓ 引用全部通過，可匯出" : "✗ 未放行，不能匯出"),
        chip("neutral", "依診斷建議產生", { title: "不是律師編輯版，也不取代律師確認的版本；引用在存入時已通過查證。存入於 " + fmtTime(rev.generated_at) })),
      h("div", { class: "controls" },
        h("button", { class: "btn small", type: "button", text: "在起訴狀分頁看全文",
          onclick: function () { state.pleadingSel[id] = rev.id; state.diffOn[id] = false; switchTab("complaint"); } }),
        rev.exportable ? h("a", { class: "btn small", href: exportUrl, download: "" }, "匯出修訂版 .txt") : null),
      rev.diff ? diffBlock(rev.diff) : h("p", { class: "detail-note", text: "找不到上一版，無法比較。" })],
      rev.diff ? chip("neutral", "＋" + rev.diff.added + " ／ −" + rev.diff.removed) : null));
  }
  function falsifierCard(d) {
    var items = d.arguments.filter(function (a) { return a.stage === 3 && a.falsifier; });
    if (!items.length) return null;
    return card("雙方讓步條件(第 3 輪論證)", [
      h("p", { class: "detail-note", text: "雙方在言詞辯論意旨狀的論證裡自己寫的假設句：若對方補上何種證據，本方即讓步。原樣列出，不代表系統判定弱點。舊流程的引用清單差異，新流程不適用。" }),
      h("div", { class: "weak-grid" }, items.map(function (a) {
        return h("div", { class: "weak-card " + a.side }, h("div", { class: "arg-head" }, sideChip(a.side, SIDE[a.side].label + "方讓步條件")),
          h("div", { class: "weak-text prewrap", text: a.falsifier }));
      }))]);
  }
  function diagnosisPanel(d) {
    var v = d.verdict;
    var head = panelHead("弱點與修改建議", v ? originChip(v.origin) : null,
      "模擬法官讀完雙方書狀後指出：哪個爭點弱、缺什麼證據、起訴狀怎麼改。不預測判決，不給勝訴機率。");
    if (!v) return [head, emptyState("此案件尚未完成診斷。書狀交換流程在言詞辯論意旨狀之後產生。"), revisionCard(d, revisionOf(d))];
    var risk = v.risk_map || {}, issues = {}, rev = revisionOf(d);
    ((d.issue_sheet && d.issue_sheet.sheet.issues) || []).forEach(function (i) { issues[i.id] = i; });
    var issueCell = function (id) {
      if (/^官方事實層\(/.test(id || "")) return [chip("judge", "程序"), h("div", { class: "detail-note", text: id })];
      return [h("strong", { text: issueName(id) }), issues[id] ? clamp(issues[id].text, 2) : null];
    };
    var revisions = risk.complaint_revisions || [];
    var assess = risk.issue_assessment || [], cnt = { "強": 0, "中": 0, "弱": 0 };
    assess.forEach(function (a) { if (cnt[a.strength] != null) cnt[a.strength]++; });
    var todo = risk.evidence_todo || [];
    var jump = function () { var el = document.getElementById("revision-card"); if (el) el.scrollIntoView({ behavior: "smooth", block: "start" }); };
    var summary = h("div", { class: "summary-bar" },
      assess.length ? [chip("ok", "▲ 強 " + cnt["強"]), chip("warn", "● 中 " + cnt["中"]), chip("bad", "▼ 弱 " + cnt["弱"])] : null,
      todo.length ? chip("neutral", "待補證據 " + todo.length + " 項") : null,
      revisions.length ? chip("neutral", "修改建議 " + revisions.length + " 項") : null,
      rev ? h("button", { class: "btn small primary", type: "button", text: "看修訂版起訴狀改了什麼 ↓", onclick: jump }) : null);
    // 一個爭點一張卡：強弱＋理由＋缺什麼證據，預設收合成一行(點開看理由)，避免同一爭點要跨三張表看
    var todoOf = function (id) { return todo.filter(function (e) { return e.issue_id === id; }); };
    var assessed = {};
    assess.forEach(function (a) { assessed[a.issue_id] = true; });
    var issueCard = function (a) {
      var t = todoOf(a.issue_id), sym = a.strength === "強" ? "▲ " : a.strength === "弱" ? "▼ " : "● ";
      var proc = /^官方事實層\(/.test(a.issue_id || "");
      return h("details", { class: "issue-card " + (STRENGTH_CLS[a.strength] || "neutral") },
        h("summary", null,
          chip(STRENGTH_CLS[a.strength] || "neutral", sym + a.strength),
          h("strong", { class: "issue-card-id", text: proc ? "程序" : issueName(a.issue_id) }),
          h("span", { class: "issue-card-text", text: proc ? a.issue_id : (issues[a.issue_id] ? issues[a.issue_id].text : "") }),
          t.length ? chip("neutral", "缺 " + t.length + " 項證據") : null),
        h("div", { class: "issue-card-body" },
          field("為什麼是「" + a.strength + "」", h("p", { text: a.reason })),
          t.length ? field("缺什麼證據", h("ul", { class: "risk-list" }, t.map(function (e) {
            return h("li", null, h("span", { text: e.missing }), e.why ? h("div", { class: "cell-sub", text: "為什麼需要：" + e.why }) : null);
          }))) : null));
    };
    var orphanTodo = todo.filter(function (e) { return !assessed[e.issue_id]; });
    return [head, summary,
      assess.length ? h("section", { class: "card" },
        h("div", { class: "card-header" }, h("span", { class: "card-title", text: "各爭點的強弱與待補證據(我方立場)" }),
          chip("neutral", "不是勝訴機率", { title: "強／中／弱指原告方在該爭點的立場，依目前的書狀與證據判斷" }),
          h("button", { class: "btn small", type: "button", style: "margin-left:auto", text: "展開弱的爭點",
            onclick: function (e) { var cards = e.target.closest(".card").querySelectorAll(".issue-card");
              var weak = Array.prototype.filter.call(cards, function (c) { return c.classList.contains("bad"); });
              var anyClosed = weak.some(function (c) { return !c.open; });
              weak.forEach(function (c) { c.open = anyClosed; }); e.target.textContent = anyClosed ? "收合" : "展開弱的爭點"; } })),
        h("div", { class: "card-body issue-cards" }, assess.map(issueCard))) : null,
      orphanTodo.length ? card("其他待補證據", dataTable(["爭點", "缺少什麼", "為什麼需要"], orphanTodo.map(function (e) {
        return [issueCell(e.issue_id), clamp(e.missing, 3), clamp(e.why, 3)];
      }))) : null,
      revisions.length ? card("起訴狀修改建議", [
        dataTable(["位置", "建議", "內容"], revisions.map(function (r) {
          return [h("span", { class: "nowrap", text: factName(r.fact_id) }), chip("neutral", REVISION_KIND[r.kind] || r.kind), clamp(r.suggestion, 3)];
        }))],
        chip("neutral", revisions.length + " 項")) : null,
      revisionCard(d, rev),
      fold("評估結論、事實缺口與雙方不利之處", [
      card("評估結論", paragraphs(delabelJargon(v.verdict_main_text)), chip("neutral", "存入 " + fmtTime(v.created_at))),
      proceduralRiskCard(d),
      (risk.fact_gaps || []).length ? card("事實缺口", bulletList(risk.fact_gaps)) : null,
      (risk.opponent_hypotheticals || []).length ? card("被告推測的事實，請向當事人確認", [
        h("p", { class: "detail-note", text: "模擬被告沒有被告本人的事實，以下是它推測可能提出的主張，不是對方實際的主張。" }),
        bulletList(risk.opponent_hypotheticals)]) : null,
      h("div", { class: "risk-grid" },
        card("對原告不利之處", bulletList(risk["對原告不利之處"]), sideChip("plaintiff")),
        card("對被告不利之處", bulletList(risk["對被告不利之處"]), sideChip("defendant"))),
      card("建議補強證據", bulletList(risk["建議補強證據"])),
        fold("完整評估理由與技術備註(轉述核對、讓步條件)", [
          card("評估理由(全文)", paragraphs(delabelJargon(v.verdict_reasoning))),
          attributionReview(v), falsifierCard(d), anchorBanner(v.anchor_check)])])];
  }

  // ───────────── 分頁：商工登記當事人查核 ─────────────
  function partySummary(d) {
    var checks = d.party_checks || {}, items = SIDES.map(function (side) { return checks[side]; }).filter(Boolean);
    if (!items.length) return "當事人查核：尚未查核";
    var completed = items.filter(function (item) { return item.query_status !== "failed"; }).length;
    var warnings = items.reduce(function (n, item) { return n + (item.warnings || []).length; }, 0);
    var issues = d.procedural_issues ? d.procedural_issues.issues.length : 0;
    return "當事人查核：已查 " + completed + "/2，警示 " + warnings + " 項" + (issues ? "，轉成起訴審查事項 " + issues + " 項" : "");
  }
  function partyRepresentativeText(result) {
    if (result.entity_type === "branch") return "本功能未查詢分公司登記資料";
    if (result.query_status === "failed") return "查核未完成，未自動帶入";
    if (result.basic_data_available === false) return "基本資料未取得，未自動帶入";
    var rep = result.legal_representative;
    if (rep) return rep.title + " " + rep.name;
    if ((result.warnings || []).some(function (w) { return w.code === "foreign_branch"; }))
      return "待確認(在臺負責人:" + (result.registered_responsible_name || "官方登記未提供") + ")";
    if ((result.warnings || []).some(function (w) { return w.code === "foreign_dissolved"; }))
      return "待確認(清算人)";
    if ((result.warnings || []).some(function (w) { return w.code === "dissolved"; })) return "待確認（清算人）";
    if (result.company_form === "股份有限公司" && (result.sources || []).some(function (s) {
      return s.dataset === "公司登記董監事資料" && !s.ok;
    })) return "董監事資料查詢失敗，未自動帶入";
    return "官方未提供／未自動帶入";
  }
  function partySourceFooter(result) {
    if (!result || !result.attribution) return null;
    return h("div", { class: "party-source" },
      h("div", { text: result.attribution }),
      h("div", { text: "查詢時間：" + fmtTime(result.fetched_at) }),
      h("a", { href: "https://data.gov.tw/license", target: "_blank", rel: "noopener noreferrer", text: "依政府資料開放授權條款第1版" }));
  }
  function partyFact(label, value) {
    return h("div", { class: "party-fact" }, h("span", { class: "field-label", text: label }),
      h("span", { text: value == null || value === "" ? "官方未提供" : String(value) }));
  }
  function partyMoney(value) { return value == null ? null : Number(value).toLocaleString("zh-TW") + " 元"; }
  function partyErrorList(result) {
    return (result.errors || []).map(function (e) {
      return banner("warn", "⏱", [h("strong", { text: e.dataset + (e.error.indexOf("類型資料顯示") >= 0 ? " 資料不完整" : " 查詢失敗") }), "：" + e.error]);
    });
  }
  function basisChips(list, d) {
    var v = runsFor(d.case.case_id).verify;
    return h("div", { class: "chip-row" }, (list || []).map(function (basis) {
      var check = v.results[basis], meta = check && !check.error ? statusMeta(check.status) : null;
      return chip(meta ? meta.cls : "neutral", (meta ? meta.icon + " " : "? ") + basis,
        { title: meta ? meta.label : "尚未執行本次法條查證" });
    }));
  }
  function verifyBasisButton(cites, d) {
    var v = runsFor(d.case.case_id).verify;
    return cites.length ? h("button", { class: "btn small", type: "button", disabled: v.busy ? true : null,
      onclick: function () { runVerify(cites); }, text: v.busy ? "查證中…" : "查證這些法條" }) : null;
  }
  function uniqueBasis(items) {
    return Array.from(new Set(items.reduce(function (all, w) { return all.concat(w.legal_basis || []); }, [])));
  }
  function partyWarnings(result, d) {
    var items = result.warnings || [];
    if (!items.length) return result.query_status === "failed" ? null : banner("ok", "✓", "目前無規則警示；仍須由律師核對案件時點與書狀內容。");
    return h("div", { class: "party-warnings" },
      h("div", { class: "party-warning-head" }, h("span", { class: "section-title", text: "程序警示（" + items.length + "）" }),
        verifyBasisButton(uniqueBasis(items), d)),
      items.map(function (w) {
        return h("div", { class: "party-warning " + w.level },
          h("div", { class: "party-warning-title" }, chip(w.level, w.level === "bad" ? "✗ 需處理" : "! 請確認"), w.message),
          basisChips(w.legal_basis, d));
      }));
  }
  function partyJurisdiction(result, role) {
    var j = result.jurisdiction || {};
    return card(SIDE[role].label + "管轄法院建議", [
      j.primary ? partyFact("主事務所", j.primary.court + "（" + j.primary.basis + "）") :
        partyFact("主事務所", j.primary_candidates && j.primary_candidates.length ? j.primary_candidates.join("、") + "；需依行政區確認" : j.note || "無法確認"),
      j.alternatives && j.alternatives.length ? h("div", { class: "party-alt-list" },
        h("div", { class: "field-label", text: "分公司所在地候選法院" }),
        j.alternatives.map(function (a) { return h("div", { text: a.court + "（" + a.basis + "；" + a.condition + "）" }); })) : null,
      h("p", { class: "detail-note", text: j.notice || "管轄區域以司法院公告為準；本建議不含合意管轄、專屬管轄等其他情形。" }),
      j.source_url ? h("a", { href: j.source_url, target: "_blank", rel: "noopener noreferrer", text: "司法院管轄區域來源" }) : null,
      partySourceFooter(result)]);
  }
  // 兩造的管轄建議合成一張卡，一方一行；分公司候選、說明與來源收在「細節」
  function jurisdictionCard(results) {
    var rows = results.map(function (x) {
      var j = x.result.jurisdiction || {};
      return h("div", { class: "meta-row juris-row" }, h("span", { class: "meta-key" }, sideChip(x.role, "依" + SIDE[x.role].label + "所在地")),
        h("span", { class: "meta-val", text: j.primary ? j.primary.court + "（" + j.primary.basis + "）"
          : j.primary_candidates && j.primary_candidates.length ? j.primary_candidates.join("、") + "；需依行政區確認" : j.note || "無法確認" }));
    });
    var alts = results.filter(function (x) { var j = x.result.jurisdiction || {}; return j.alternatives && j.alternatives.length; });
    var j0 = results[0].result.jurisdiction || {};
    return card("管轄法院建議", [rows,
      fold("細節：分公司所在地候選法院、管轄區域來源", [
        alts.map(function (x) {
          return h("div", { class: "party-alt-list" }, h("div", { class: "field-label", text: SIDE[x.role].label + "分公司所在地候選法院" }),
            x.result.jurisdiction.alternatives.map(function (a) { return h("div", { text: a.court + "（" + a.basis + "；" + a.condition + "）" }); }));
        }),
        h("p", { class: "detail-note", text: j0.notice || "管轄區域以司法院公告為準；本建議不含合意管轄、專屬管轄等其他情形。" }),
        j0.source_url ? h("a", { href: j0.source_url, target: "_blank", rel: "noopener noreferrer", text: "司法院管轄區域來源" }) : null])]);
  }
  function partyResultBlock(result, d) {
    if (!result) return emptyState("尚未查核。請輸入統一編號，或用名稱搜尋後點選候選公司。");
    var isBranch = result.entity_type === "branch";
    var noData = result.query_status === "failed" || result.entity_type === "not_found" || isBranch ||
      ((result.entity_type === "company" || result.entity_type === "business") && result.basic_data_available === false);
    var pieces = [
      h("div", { class: "party-result-title" }, h("strong", { text: isBranch ? "分公司統編" : result.name ||
        (result.query_status === "failed" ? "查核未完成" : noData ? "未取得登記名稱" : "官方未提供名稱") }),
        chip(result.status_level || "warn", isBranch ? "分公司" : result.query_status === "failed" ? "查核未完成" :
          result.basic_data_available === false && result.entity_type !== "not_found" ? "基本資料未取得" :
          result.status_text || (result.entity_type === "not_found" ? "查無" : "狀態未提供"))),
      result.via === "recorded" ? chip("rec", "⏺ 錄製的查詢結果（查詢時間 " + fmtTime(result.fetched_at) + "），非本次即時查詢") : null,
      result.via === "recorded" ? banner("warn", "⏱", "本次即時查詢失敗：" + (result.live_attempt && result.live_attempt.error || "無法連線") + "；下列資料為過去錄製結果。") : null,
      result.query_status === "failed" ? banner("bad", "✗", "本次商工查詢未完成，無法認定為查無；請重試。") : null,
      result.query_status === "partial" ? banner("warn", "!", "部分資料集查詢失敗，下列缺少的欄位不得視為查無。") : null,
      result.entity_type === "not_found" ? banner("bad", "✗", "商工登記查無此統編。") : null,
      isBranch ? banner("warn", "!", "此統編為分公司；本功能未查詢分公司登記資料，請改以總公司統編查核。") : null,
      partyErrorList(result),
    ];
    if (!noData) {
      pieces.push(h("div", { class: "party-facts" },
        partyFact("類型", ({ company: "公司", branch: "分公司", business: "商號" })[result.entity_type] || "未判定"),
        partyFact("法定代理人", partyRepresentativeText(result)),
        partyFact("主事務所／營業地址", result.address),
        partyFact("資本總額", result.capital && partyMoney(result.capital.registered)),
        partyFact("實收資本額", result.capital && partyMoney(result.capital.paid_in)),
        partyFact("核准設立日", result.setup_date), partyFact("最後異動日", result.last_change_date)));
      pieces.push(result.directors && result.directors.length ? fold("董監事（" + result.directors.length + " 人）",
        result.directors.map(function (x) { return h("div", { class: "party-list-row", text: [x.title, x.name, x.juristic_person ? "代表法人：" + x.juristic_person : ""].filter(Boolean).join("　") }); })) : null);
      pieces.push(result.branches && result.branches.count ? fold("分公司（" + result.branches.count + " 筆" + (result.branches.truncated ? "；僅顯示前 50 筆" : "") + "）",
        result.branches.items.map(function (x) { return h("div", { class: "party-list-row", text: [x.name, x.ban, x.address].filter(Boolean).join("　") }); })) : null);
    }
    pieces.push(partyWarnings(result, d));
    pieces.push(result.query_status !== "failed" && result.always_notes ?
      h("p", { class: "detail-note", text: result.always_notes.join("；") }) : null);
    // 資料來源與授權在 v2 分頁底部統一列一次；舊流程照舊每張卡各列
    if (!isV2(d)) pieces.push(partySourceFooter(result));
    return h("div", { class: "party-result" }, pieces);
  }
  function candidateButton(p) {
    return function (c) { return h("button", {
      class: "party-candidate" + (c.status_normal ? "" : " inactive"), type: "button",
      onclick: function () { p.ban = c.ban; p.searchOpen = false; renderPanel(); },
    }, h("strong", {}, c.name || "未提供名稱", c.status_normal ? null
        : h("span", { class: "chip bad", text: "⚠ " + (c.status_text || "狀態未提供") + "（非核准設立）" })),
    h("span", { text: "統編 " + c.ban + "　" + (c.status_text || "狀態未提供") }),
    h("span", { text: c.address || "地址未提供" })); };
  }
  async function searchParty(role) {
    var d = state.detail, p = partyState(d.case.case_id, role);
    if (p.query.trim().length < 2) { p.error = "公司名稱關鍵字至少 2 個字"; renderPanel(); return; }
    var seq = ++p.searchSeq, q = encodeURIComponent(p.query.trim());
    p.searching = true; p.error = null; p.search = null; p.more = null; renderPanel();
    try { p.search = await api("/api/party-search?q=" + q); }
    catch (e) { p.error = e.message; }
    p.searching = false;
    if (seq !== p.searchSeq) return;
    // 核准設立以外的狀態(已解散、廢止等)要逐一查 32 種狀態，較慢，先顯示核准設立的結果再補上
    p.searchingMore = !p.error;
    if (state.detail === d) renderPanel();
    if (p.error) return;
    try { var more = await api("/api/party-search?scope=inactive&q=" + q); }
    catch (e) { more = { ok: false, error: e.message, candidates: [], failed_statuses: [] }; }
    if (seq !== p.searchSeq) return;
    p.more = more; p.searchingMore = false;
    if (state.detail === d) renderPanel();
  }
  async function checkParty(role) {
    var d = state.detail, p = partyState(d.case.case_id, role);
    p.busy = true; p.error = null; renderPanel();
    try {
      p.result = await api("/api/party-check", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ban: p.ban, input_name: p.inputName || null, case_id: d.case.case_id, role: role }) });
      await reloadDetailQuietly();
    } catch (e) { p.error = e.message; }
    p.busy = false;
    if (state.caseId === d.case.case_id) { renderDetail(); renderPanel(); }
  }
  function partyCard(d, role) {
    var p = partyState(d.case.case_id, role), saved = d.party_checks && d.party_checks[role], result = p.result || saved;
    var controls = [
      h("div", { class: "party-controls" },
        h("label", null, "統一編號", h("input", { type: "text", inputmode: "numeric", maxlength: "12", value: p.ban,
          placeholder: "8 位數字", oninput: function (e) { p.ban = e.target.value; } })),
        h("label", null, "預期名稱（選填）", h("input", { type: "text", value: p.inputName,
          oninput: function (e) { p.inputName = e.target.value; } })),
        h("button", { class: "btn primary", type: "button", disabled: p.busy ? true : null,
          onclick: function () { checkParty(role); }, text: p.busy ? "查詢中…" : p.error ? "重試查核" : "查核" })),
      h("button", { class: "party-search-toggle", type: "button", onclick: function () { p.searchOpen = !p.searchOpen; renderPanel(); },
        text: p.searchOpen ? "收合名稱搜尋" : "用名稱搜尋" }),
      p.searchOpen ? h("div", { class: "party-search" },
        h("div", { class: "party-search-line" }, h("input", { type: "text", value: p.query,
          placeholder: "公司名稱關鍵字", oninput: function (e) { p.query = e.target.value; } }),
          h("button", { class: "btn", type: "button", disabled: p.searching ? true : null,
            onclick: function () { searchParty(role); }, text: p.searching ? "搜尋中…" : "搜尋候選" })),
        p.search && !p.search.ok ? banner("bad", "✗", "搜尋失敗：" + p.search.error) : null,
        p.search && p.search.ok ? [
          p.search.candidates.length ? p.search.candidates.map(candidateButton(p)) : null,
          p.searchingMore ? banner("warn", "⏱", "正在逐一查詢核准設立以外的 32 種公司狀態(已解散、廢止、撤銷等)，約需 20–30 秒…") : null,
          p.more && p.more.candidates.length ? [h("p", { class: "detail-note", text: "以下為核准設立以外的狀態，不是正常營業中的公司：" }),
            p.more.candidates.map(candidateButton(p))] : null,
          p.more && !p.more.ok ? banner("warn", "⚠", "其他狀態(已解散等)查詢失敗，以下結果只含核准設立的公司：" + p.more.error) : null,
          p.more && p.more.ok && p.more.failed_statuses.length ? banner("warn", "⚠", "其他狀態有 " + p.more.failed_statuses.length +
            " 種查詢失敗，已解散等候選可能不完整：" + p.more.error) : null,
          !p.searchingMore && !p.search.candidates.length && !(p.more && p.more.candidates.length)
            ? h("p", { class: "detail-note", text: "沒有候選公司；請改用統編查核。" }) : null,
          partySourceFooter(p.search)] : null) : null,
      p.error ? banner("bad", "✗", ["查詢失敗：" + p.error, h("button", { class: "btn small", type: "button", onclick: function () { checkParty(role); }, text: "重試" })]) : null,
      p.busy ? banner("warn", "⏱", "查詢中…") : null];
    return card(SIDE[role].label + "查核", [result && !p.searchOpen && !p.error && !p.busy ? fold("重新查核／名稱搜尋", controls) : controls,
      partyResultBlock(result, d)]);
  }
  function partiesPanel(d) {
    var checks = d.party_checks || {}, v2 = isV2(d);
    var resultOf = function (side) { return partyState(d.case.case_id, side).result || checks[side]; };
    var juris = SIDES.map(function (side) { var r = resultOf(side);
      return r && r.query_status !== "failed" && r.entity_type !== "not_found" && r.entity_type !== "branch" && r.address ? { role: side, result: r } : null; }).filter(Boolean);
    var footers = SIDES.map(resultOf).filter(function (r) { return r && r.attribution; });
    return [panelHead(v2 ? "當事人與管轄" : "起訴前檢查", chip("ok", "⚡ 即時查詢"),
      v2 ? "對方公司是否存在、誰是法定代理人、該告到哪個法院；直接查經濟部商工登記，不經 AI。" : "以統編查商工登記，確認當事人與管轄。",
      "以統一編號查詢經濟部商工登記，確認當事人名稱、法定代理人、公司狀態與管轄法院。本分頁為即時查詢，不呼叫 AI。查核結果僅反映商工登記公示資料，不代表該公司涉入本案；登記為查詢當下的狀態。"),
      v2 && d.precheck ? precheckCard(d) : null,
      h("div", { class: "party-grid" }, SIDES.map(function (side) { return partyCard(d, side); })),
      d.procedural_issues && d.procedural_issues.issues.length ? banner("rec", "→", [
        h("strong", { text: "這些警示已轉成 " + d.procedural_issues.issues.length + " 項起訴審查命補正事項" }),
        "：當事人能力與法定代理屬法院應依職權調查的事項，系統依固定規則把警示轉成命補正事項，在 Stage 1 之前交給雙方，並寫入爭點評估的機械錨點。 ",
        h("button", { class: "btn small", type: "button", onclick: function () { switchTab(isV2(d) ? "complaint" : "debate"); }, text: isV2(d) ? "到起訴狀分頁查看" : "到攻防過程查看" })]) : null,
      v2 ? (juris.length ? jurisdictionCard(juris) : null) : juris.map(function (x) { return partyJurisdiction(x.result, x.role); }),
      v2 && footers.length ? h("div", { class: "party-source" },
        h("div", { text: footers[0].attribution }),
        h("div", { text: "查詢時間：" + footers.map(function (r) { return fmtTime(r.fetched_at); }).filter(function (t, i, a) { return a.indexOf(t) === i; }).join("、") }),
        h("a", { href: "https://data.gov.tw/license", target: "_blank", rel: "noopener noreferrer", text: "依政府資料開放授權條款第1版" })) : null];
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
        a.review_warning_count ? chip("warn", "公開論證疑似含自我檢討 " + a.review_warning_count + " 則") : null,
        originChip(a.origin),
        h("span", { class: "arg-time", text: "落地 " + fmtTime(a.created_at), title: "model_id：" + (a.model_id || "落地時未記錄") })),
      h("div", { class: "arg-body" },
        field("主張立場", h("div", { class: "arg-position prewrap", text: a.position })),
        a.reasoning.indexOf("【內部檢討】") >= 0 ? h("p", { class: "detail-note", text: "【內部檢討】段落只給律師與該方後續輪次看，法官與對造讀不到。" }) : null,
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

  function isPrepQuestion(q) { return /^準備清單/.test(q.based_on || ""); }
  function attributionReview(row) {
    var items = row.attribution_items || [];
    if (!items.length) return null;
    var names = { close: "近似(非逐字)", falsifier: "引自讓步條件(假設句)", other_side: "只在另一方原文", missing: "兩方原文均找不到", unquoted: "未引述的承認" };
    var warns = { other_side: true, missing: true, unquoted: true };
    return h("div", { class: "attribution-review" },
      row.attribution_warning_count ? chip("warn", "轉述待核對 " + row.attribution_warning_count + " 處") : null,
      fold("查看轉述比對（共 " + items.length + " 處）", [
        h("p", { class: "detail-note", text: "程式比對,非 AI 判斷;只找得到有引號或寫『承認』的轉述。" }),
        items.map(function (item) {
          return h("div", { class: "field-label" },
            h("div", { class: "chip-row" },
              chip(warns[item.level] ? "warn" : "neutral", (warns[item.level] ? "待核對・" : "") + names[item.level]),
              sideChip(item.side)),
            item.quote ? h("p", { class: "prewrap", text: "比對的引號：「" + item.quote + "」" }) : null,
            h("p", { class: "prewrap", text: "法官原句：" + item.sentence }),
            item.source_snippet ? h("p", { class: "prewrap", text: "對照原文：" + item.source_snippet }) : null);
        }),
      ]));
  }
  function prepListCard(d) {
    var items = d.questions.filter(isPrepQuestion);
    if (!items.length) return null;
    return card("原告的準備清單(共 " + items.length + " 項)", [
      h("p", { class: "detail-note", text: "被告 agent 沒有被告本人的事實，所以法官把想問被告的事實題改成問原告。以下都是假設，不是對方實際主張；這個版本假設案件事實來自原告方。原告的回答在攻防過程分頁的 Stage 2。" }),
      items.map(function (q) { return h("div", { class: "judge-q-text prewrap", text: q.question_text }); }),
    ]);
  }

  function questionsBlock(d) {
    if (!d.questions.length) return null;
    return h("section", { class: "judge-band" },
      h("div", { class: "judge-band-title" }, chip("judge", "法官"), "訊問 — 基於雙方 Stage 1，共 " + d.questions.length + " 則", provChip(d.questions)),
      d.questions.map(function (q) {
        return h("div", { class: "judge-q" },
          h("div", { class: "judge-q-head" }, sideChip(q.target_side, "問" + SIDE[q.target_side].label + "(第 " + q.seq + " 則)"),
            /^官方事實層/.test(q.based_on || "") ? chip("judge", "補正追問・依商工登記") : null,
            isPrepQuestion(q) ? chip("judge", "準備題・假設") : null,
            h("span", { class: "arg-time", text: "落地 " + fmtTime(q.created_at) })),
          h("div", { class: "judge-q-text prewrap", text: q.question_text }),
          h("div", { class: "judge-q-basis" }, h("b", { text: "訊問依據(based_on，須回溯至具體論點)：" }), q.based_on),
          attributionReview(q));
      }));
  }

  // ───────────── 官方事實層 → 起訴審查命補正事項 ─────────────
  // 事項本身由後端規則依最新商工查核產生(非錄製內容)；錄製的攻防有沒有回應，只看原告 Stage 1 的
  // 「程序補正(<id>)」標記與法官追問 based_on 的事項代號，不判斷補正內容是否足夠。
  function proceduralCoverageBanner(p) {
    var c = p.coverage;
    if (c.where === "complaint") {  // 書狀交換流程：補正寫在起訴狀「四、程序事項」，法官在 P3 爭點整理表追問(舊設計殘留第 3 項)
      if (c.debate === "answered") return banner("ok", "✓", [h("strong", { text: "起訴狀已說明全部補正事項" }),
        "：系統以起訴狀「四、程序事項」的事項代號機械比對；補正是否足夠由法官在 P3 判斷，不足者在爭點整理表追問。"]);
      if (c.debate === "partial") return banner("warn", "!", [h("strong", { text: "起訴狀只說明部分補正事項" }), "：未說明者標示於下方。"]);
      if (c.debate === "not_answered") return banner("bad", "✗", [h("strong", { text: "起訴狀未說明下列補正事項" })]);
      return null;
    }
    if (c.debate === "answered") return banner("ok", "✓", [h("strong", { text: "原告已在 Stage 1 回應全部補正事項" }),
      "：系統以補正段落的事項代號機械比對；補正是否足夠由法官判斷，不足者會在 Stage 1 之後追問。"]);
    if (c.debate === "partial") return banner("warn", "!", [h("strong", { text: "原告 Stage 1 只回應部分補正事項" }), "：未回應者標示於下方。"]);
    if (c.debate === "predates_check") return banner("warn", "!", [h("strong", { text: "本案攻防錄製於當事人查核之前" }),
      "：攻防最後落地於 " + fmtTime(c.debate_last_recorded_at) + "，首次商工查核於 " + fmtTime(c.first_checked_at) +
      "。錄製當時還沒有起訴審查這一步，所以下方錄製的攻防沒有回應這些事項；重新執行完整流程時，原告會在 Stage 1 先行補正。"]);
    if (c.debate === "not_answered") return banner("bad", "✗", [h("strong", { text: "錄製的原告 Stage 1 未回應下列補正事項" }),
      "：商工查核早於攻防錄製，但原告 Stage 1 沒有對應的補正段落。"]);
    return null;
  }
  function procIssueItem(issue, d, withCoverage) {
    var followed = issue.followed_up_in || [];
    return h("div", { class: "party-warning " + issue.level },
      h("div", { class: "party-warning-title" },
        chip(issue.level, issue.level === "bad" ? "✗ 需處理" : "! 請確認"), chip("neutral", issue.kind),
        !issue.ex_officio ? chip("neutral", "非命補正事項・供原告策略參考") : !withCoverage ? null :
          issue.cured_in === "complaint" ? (issue.cured_in_stage1 ? chip("ok", "✓ 起訴狀已說明補正") : chip("warn", "起訴狀未說明"))
          : issue.cured_in_stage1 ? chip("ok", "✓ 原告 Stage 1 已回應補正") : chip("warn", "錄製的 Stage 1 未回應"),
        withCoverage && followed.length ? chip("judge", issue.cured_in === "complaint" ? "法官在爭點整理表追問 " + followed.length + " 則"
          : "法官第 " + followed.join("、") + " 則訊問追問") : null),
      h("div", { class: "proc-q prewrap" }, h("b", { text: (issue.ex_officio ? "命" + SIDE[issue.target_side].label + "補正／說明" : "提醒" + SIDE[issue.target_side].label) + "：" }), issue.question_text),
      issue.procedure ? h("div", { class: "proc-meta" }, h("b", { text: "程序效果：" }), issue.procedure) : null,
      basisChips(issue.legal_basis, d),
      h("div", { style: "margin-top:6px" }, fold("商工查核警示原文", h("p", { class: "proc-meta", text: issue.warning }))));
  }
  function proceduralBlock(d) {
    var p = d.procedural_issues;
    if (!p) return null;
    if (!SIDES.some(function (s) { return p.parties[s]; })) {
      return h("p", { class: "detail-note", text: "起訴審查(官方事實層)：本案尚未查核當事人商工登記，沒有命補正事項(不代表沒有程序問題)。可到「當事人查核」分頁以統一編號查核。" });
    }
    return h("section", { class: "judge-band" },
      h("div", { class: "judge-band-title" }, chip("judge", "審判長"), "起訴審查 — 依商工登記命補正(官方事實層)，共 " + p.issues.length + " 項",
        chip("ok", "⚙ 規則產生，非 AI", { title: p.source }), verifyBasisButton(uniqueBasis(p.issues), d)),
      h("p", { class: "detail-note", text: "實務上法院收狀後先審查當事人能力與法定代理權，有欠缺而可以補正者，審判長定期間命補正，逾期未補正以裁定駁回(民事訴訟法第249條第1項)；但法院須依職權調查實際代表權，不得僅憑登記認定(參最高法院115年度台抗字第105號裁定)。系統依「當事人查核」分頁的最新結果，以固定規則產生下列事項，" + (p.coverage && p.coverage.where === "complaint"
        ? "原告在起訴狀「四、程序事項」說明補正，法官在 P3 爭點整理表只就補正不足者追問。" : "在 Stage 1 之前交給雙方；原告在 Stage 1 補正，法官只就補正不足者追問。") +
        "本區文字由規則即時產生，不是錄製的 AI 內容。" }),
      proceduralCoverageBanner(p),
      p.issues.length ? p.issues.map(function (i) { return procIssueItem(i, d, true); })
        : banner("ok", "✓", "已查核的當事人沒有觸發程序規則；仍須由律師核對案件時點。"),
      p.notes.map(function (n) { return h("p", { class: "detail-note", text: n }); }));
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
    if (!d.arguments.length) {
      var running = (d.live_runs || []).some(function (r) { return r.status === "running"; });
      return [panelHead("攻防過程"), proceduralBlock(d), emptyState(["此案件還沒有攻防紀錄。", h("br"),
        running ? "即時執行進行中；各階段落地後會自動出現在這裡。" :
          liveInfo().enabled && d.case.source === "database" ? "可到「案件總覽」按「即時執行」。" : "即時執行目前停用。"])];
    }
    var idx = citeIndex(d);
    return [
      panelHead("攻防過程", provChip(d.arguments),
        "協議：起訴審查(依商工登記命補正) → Stage 1 雙方獨立盲判(原告一併補正) → 法官依 Stage 1 訊問(含補正不足之追問) → Stage 2 訊問攻防 → Stage 3 辯論終結。除標示「規則產生」的起訴審查事項外，以下皆為資料庫已落地的原文。"),
      banner("warn", "!", "雙方論證都是 AI 依輸入資料模擬，不是當事人或對方律師的實際主張。"),
      proceduralBlock(d),
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
    if (dd && dd.not_applicable) {  // 舊設計殘留第 2 項 B:書狀交換流程不算
      return h("div", { class: "drift-row" },
        h("div", { class: "drift-label" }, sideChip(side), h("span", { class: "drift-value", text: "新流程不適用" })));
    }
    var has = dd && dd.ratio != null;
    return h("div", { class: "drift-row" },
      h("div", { class: "drift-label" }, sideChip(side), h("span", { class: "drift-value", text: has ? dd.ratio.toFixed(4) + "(" + pct(dd.ratio) + ")" : "無法計算" })),
      has ? [
        h("div", { class: "drift-track", role: "img", "aria-label": SIDE[side].label + "引用清單差異 " + pct(dd.ratio) },
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
      panelHead("讓步條件與引用清單差異", null,
        "本頁不呼叫 AI。讓步條件是雙方自己寫的假設句，原樣列出，不代表系統判定弱點。引用清單差異只比較前後階段引用的法條與判決，不代表立場變化。"),
      h("div", { class: "controls" },
        h("button", { class: "btn primary", type: "button", disabled: !ready || run.finalizing ? true : null, onclick: runFinalize },
          h("span", { class: "ico", "aria-hidden": "true", text: "▶" }), run.finalizing ? "計算中…" : (run.finalize ? "重新計算一次" : "執行彙整計算")),
        ready ? h("span", { class: "detail-note", text: "系統會重新彙整一次讓步條件與引用清單差異，不會更動任何已存資料。" })
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
    out.push(h("div", { class: "section-title", text: "雙方讓步條件" }));
    out.push(h("div", { class: "weak-grid" }, r.weak_points.map(function (w, i) {
      return h("div", { class: "weak-card " + w.side },
        h("div", { class: "arg-head" }, sideChip(w.side, SIDE[w.side].label + "方讓步條件"), h("span", { class: "weak-rank", text: "排序 " + (i + 1) })),
        h("div", { class: "weak-text prewrap", text: w.falsifier || "(該方未提供讓步條件)" }),
        w.response_excerpt ? h("div", { style: "margin-top:10px" }, fold("該方 Stage 3 推理全文", paragraphs(w.response_excerpt))) : null);
    })));
    out.push(card("引用清單差異", [
      driftRow("plaintiff", r.drift_detail.plaintiff), driftRow("defendant", r.drift_detail.defendant),
      h("p", { class: "detail-note", text: r.drift_detail.not_applicable
        ? "書狀交換流程的第 1 輪是雙方的分析，不列判決；和第 3 輪比引用集合會失真，所以不計算。"
        : "0 = 兩階段引用集合完全相同，1 = 完全不重疊。只看引用的法條與判決，不代表立場或論述的變化。" })]));
    var pi = r.procedural_issues;
    if (pi) out.push(card("程序事項(官方事實層)", [
      h("p", { class: "detail-note", text: "依案件最新的商工查核結果，以固定規則轉換，與讓步條件、引用清單差異一起寫入評估紀錄；法官評估須先處理 ✗ 等級的程序事項。" }),
      pi.issues.length ? h("div", { class: "chip-row" }, pi.issues.map(function (i) {
        return chip(i.level, (i.level === "bad" ? "✗ " : "! ") + SIDE[i.party_role].label + "・" + i.kind);
      })) : h("div", { class: "detail-note", text: "已查核的當事人沒有觸發程序規則。" }),
      pi.notes.map(function (n) { return h("p", { class: "detail-note", text: n }); })]));
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

  function verifyRow(c, r, busy, pendingText, v2) {
    var pending = pendingText === c.citation_text;
    var meta, cls = "";
    if (pending) meta = { cls: "idle", icon: "", label: "查證中…" };
    else if (!r && c.db_record) { var pm = statusMeta(c.db_record.status); meta = { cls: pm.cls, icon: pm.icon, label: pm.label + "(先前紀錄)" }; }
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
      if (r.local_cache) line("快取資料", "抓取於 " + fmtTime(r.local_cache.fetched_at) + "；法規修正日 " + (r.local_cache.amendment_date || "—"));
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
          (r && r.primary_source_url) || (c.db_record && c.db_record.primary_source_url)
            ? h("a", { class: "chip neutral", href: (r && r.primary_source_url) || c.db_record.primary_source_url, target: "_blank", rel: "noopener noreferrer", text: "官方頁面 ↗" }) : null,
          c.used_by.length ? chip("neutral", (v2 ? "出現在 " : "引用者：") + usedByLabel(c.used_by, v2)) : null,
          r && r.gate ? (r.gate === "pass" ? chip("ok", "✓ 本次放行")
            : r.status === "not_found" ? chip("bad", "✗ 閘門攔截，不得進入訴狀") : chip("warn", "本次未放行(不視為已查證)")) : null),
        h("div", { style: "margin-top:6px" }, fold("查證細節", [h("div", { class: "vrow-lines" }, lines),
          r && !r.error ? fold("原始回應(JSON)", h("pre", { class: "raw", text: JSON.stringify(r, null, 2) })) : null]))),
      h("div", { class: "vrow-side" },
        r && r.elapsed_ms != null ? h("span", { text: r.elapsed_ms + " ms" }) : null,
        h("button", { class: "btn small", type: "button", disabled: busy ? true : null, onclick: function () { runVerify([c.citation_text]); }, text: "查證此條" })));
  }

  function verifyPanel(d) {
    var run = runsFor(d.case.case_id), v = run.verify, opts = state.verifyOpts;
    var cites = d.citations;
    var v2 = isV2(d);
    var head = panelHead(v2 ? "引用查核" : "引用查證", null,
      v2 ? "書狀裡引用的每條法條、判決，逐條對到官方原文；只確認存在，不代表判決支持該論點。" : "逐條比對官方來源。",
      "每條引用都當作「未經證實」；只確認字號／條文存在，不代表判決支持該論點。每一條引用都當作「未經證實」處理：判例先比對判決預先內容(1,000 餘份最高法院裁判)與快取，未命中再即時查司法院系統；法條 7 天內讀快取，否則即時查全國法規資料庫。連線失敗時，過期或未確認的快取只標示為待核，不算通過、不寫入紀錄。");
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
    // 主按鈕常駐；查詢模式、逾時、是否記錄收進「查證設定」
    var controls = h("div", { class: "controls" },
      h("button", { class: "btn primary", type: "button", disabled: v.busy ? true : null,
        onclick: function () { runVerify(cites.map(function (c) { return c.citation_text; })); } },
        h("span", { class: "ico", "aria-hidden": "true", text: "▶" }), v.busy ? "查證中…" : "現在重新逐條查證(" + cites.length + " 條)"),
      fold("查證設定", h("div", { class: "controls" }, seg,
        h("label", { for: "v-timeout" }, "即時查詢逾時", sel),
        h("label", { for: "v-persist" }, persist, "查證通過的引用要記錄下來"))));

    var results = cites.map(function (c) { return v.results[c.citation_text]; }).filter(function (r) { return r && !r.error; });
    var count = function (fn) { return results.filter(fn).length; };
    // 尚未按查證時，用資料庫的先前查證紀錄當數字(標明是先前紀錄)，不讓四格全是「—」
    var prior = !results.length;
    var effective = prior ? cites.map(function (c) { return c.db_record; }).filter(Boolean) : results;
    var ecount = function (fn) { return effective.filter(fn).length; };
    var tiles = h("div", { class: "stat-grid" },
      stat(effective.length ? String(ecount(function (r) { return r.status === "published"; })) : "—", "✓ 已查證通過" + (prior ? "(先前紀錄)" : ""), "ok"),
      stat(effective.length ? String(ecount(function (r) { return r.status === "local_cache_only"; })) : "—", "◐ 僅本地快取(未比對官方)", "warn"),
      stat(effective.length ? String(ecount(function (r) { return r.status === "not_found"; })) : "—", "✗ 確認查無", "bad"),
      stat(effective.length ? String(ecount(function (r) { return ["network_error", "verification_failed", "unparseable", "unsupported_law", "unknown_law", "version_unverified", "ambiguous"].indexOf(r.status) >= 0; })) : "—", "⏱ 無法完成查證／無法解析", "warn"));

    var okN = ecount(function (r) { return r.status === "published"; });
    var allOk = effective.length === cites.length && okN === cites.length;
    // 全部通過時四格大多是 0，改成一句話；有問題才顯示四格
    var out = [head, allOk ? banner("ok", "✓", [h("strong", { text: cites.length + " 條引用全部對到官方原文" }),
      prior ? "(依資料庫先前的查證紀錄；按下方按鈕可現在重新查一次)" : "(本次查證結果)"]) : tiles, controls];
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

    // 通過的(本次結果或先前紀錄為 published)收成一份精簡清單；有問題或尚未查的照舊逐條列出細節。查證進行中時全部逐條列出，才看得到進度
    var passed = function (c) {
      var r = v.results[c.citation_text];
      return r ? !r.error && r.status === "published" : !!(c.db_record && c.db_record.status === "published");
    };
    var group = function (title, kind, items) {
      items = items.filter(function (c) { return c.kind === kind; });
      if (!items.length) return null;
      return [h("div", { class: "section-title", text: title + "(" + items.length + ")" }),
        items.map(function (c) { return verifyRow(c, v.results[c.citation_text], v.busy, v.pending, v2); })];
    };
    var rest = v.busy ? cites : cites.filter(function (c) { return !passed(c); });
    var okList = v.busy ? [] : cites.filter(passed);
    if (rest.length) out.push(group("判例", "judgment", rest), group("法條", "statute", rest), group("未分類", "unknown", rest));
    if (okList.length) {
      var url = function (c) { var r = v.results[c.citation_text]; return (r && r.primary_source_url) || (c.db_record && c.db_record.primary_source_url); };
      var kindName = { judgment: "判決", statute: "法條" };
      out.push(fold("已通過的 " + okList.length + " 條(點開看清單與官方原文連結)", dataTable(["", "引用", "類型", "出現在", "官方原文"], okList.map(function (c) {
        var u = url(c);
        return [h("span", { class: "ok-mark", "aria-label": "已通過", text: "✓" }), h("span", { class: "nowrap", text: c.citation_text }),
          kindName[c.kind] || "未分類", c.used_by.length ? usedByLabel(c.used_by, v2) : "—",
          u ? h("a", { href: u, target: "_blank", rel: "noopener noreferrer", text: "開啟 ↗" }) : "—"];
      })), !rest.length));
    }
    return out;
  }

  // ───────────── 分頁：爭點評估 ─────────────
  function verdictPanel(d) {
    var v = d.verdict;
    var head = panelHead("法官爭點強弱評估", v ? originChip(v.origin) : null,
      "評估的用途是協助律師決定訴狀火力與蒐證優先順序，不是預測法院會怎麼判。以下為法官角色落地的原文。");
    if (!v) return [head, emptyState("此案件尚未落地爭點強弱評估。")];
    var oldRules = v.protocol_version === "v1-2026-08-07" ? banner("warn", "!", "這份評估在舊規則下產生，當時要求法官不得偏離彙整結果。文中的「錨點」「自承」不代表系統判定，請對照原文。") : null;
    var risk = v.risk_map || {};
    var list = function (items) { return h("ul", { class: "risk-list" }, (items || []).map(function (t) { return h("li", { text: t }); })); };
    var out = [head, oldRules, attributionReview(v),
      card("評估結論", paragraphs(delabelJargon(v.verdict_main_text)), chip("neutral", "存入 " + fmtTime(v.created_at))),
      card("評估理由", paragraphs(delabelJargon(v.verdict_reasoning))),
      proceduralRiskCard(d),
      h("div", { class: "risk-grid" },
        card("對原告不利之處", list(risk["對原告不利之處"]), sideChip("plaintiff")),
        card("對被告不利之處", list(risk["對被告不利之處"]), sideChip("defendant"))),
      card("建議補強證據", list(risk["建議補強證據"]))];
    out.push(anchorBanner(v.anchor_check));
    return out;
  }

  function proceduralRiskCard(d) {
    var p = d.procedural_issues;
    if (!p || !p.issues.length) return null;
    var c = p.coverage.verdict;
    return card("程序風險(官方事實層，規則產生)", [
      c === "included" ? banner("ok", "✓", "本評估落地時，彙整資料已含下列程序事項，法官角色須先處理程序再談實體。")
        : c === "not_included" ? banner("warn", "!", [h("strong", { text: "本評估錄製於程序事項串接之前" }),
          "：落地時的彙整資料沒有程序事項，上方評估文字未處理下列風險。下列內容由規則依最新商工查核即時產生，不是法官角色的評估。"]) : null,
      p.issues.map(function (i) { return procIssueItem(i, d, false); })]);
  }

  function anchorBanner(a) {
    if (!a) return null;
    var ps = a.recomputed.position_drift;
    // 書狀交換流程的引用清單差異不計算(值是 null),數字改寫「新流程不適用」
    var na = ps.plaintiff == null && ps.defendant == null;
    var drift = na ? "引用清單差異新流程不適用" : "原告 " + pct(ps.plaintiff) + "、被告 " + pct(ps.defendant);
    var note = a.notes && a.notes.length ? banner("rec", "i", a.notes.join("；")) : null;
    function withNote(main) { return note ? h("div", { class: "anchor-check" }, main, note) : main; }
    if (!a.consistent) return withNote(banner("bad", "✗", [
      h("strong", { text: "落地時的機械彙整與重算不同" }),
      "。這是落地紀錄與目前資料重算的差異；單憑比對不能判定原因。",
      a.stored_differs && a.stored_differs.length ? " 落地欄位差異：" + a.stored_differs.join("、") + "。" : "",
      a.differences.length ? " 其他比對差異：" + a.differences.join("；") + "。" : "",
      a.minor_differences.length ? " 另有僅括號內文字不同的讓步條件。" : "",
    ]));
    if (a.minor_differences.length) {
      return withNote(banner("warn", "!", [
        h("strong", { text: "引用清單差異一致，但讓步條件文字有細微出入" }),
        "。落地時記錄的引用清單差異，與現在重新計算的結果相同(" + drift + ")；但 " +
        a.minor_differences.map(function (m) { return m.note; }).join("；") + "。",
        a.minor_differences.map(function (m) {
          return fold("查看" + SIDE[m.side].label + "方文字差異", [
            h("p", null, h("strong", { text: "落地紀錄的版本：" }), m.stored),
            h("p", null, h("strong", { text: "Stage 3 原文(現行)：" }), m.current)]);
        }),
      ]));
    }
    return withNote(banner("ok", "✓", [h("strong", { text: "已比對欄位與落地時的計算結果一致" }),
      "：落地時記錄的" + (na ? "" : "引用清單差異、") + "讓步條件、論證摘錄" + (a.notes && a.notes.some(function (n) { return n.indexOf("商工") >= 0; }) ? "" : "與程序事項 ID") +
      "，跟現在重新計算的結果相同(" + drift + ")。"]));
  }

  // ───────────── 分頁：訴狀骨架 ─────────────
  // 部分早期錄製的內容(草稿標題／附註、判決推理)夾帶了內部開發代號或欄位名稱
  // (Skill 名稱、Phase 編號、weak_points/position_drift/falsifier 等)，這裡只做
  // 「代換為中性中文說法／移除純內部備註」的顯示層清理，不更動實質法律內容或數值。
  // 順序有意義：先代換較長的複合代號，再代換其後可能單獨殘留的字詞(如「該 Skill」)。
  // 【…】不在此清理：錄製評估用它標爭點標題，即時生成的訴狀用它寫舉證缺口與待調閱證據(含引用)，都是實質內容。
  var TEXT_JARGON = [
    [/taiwan-legal-pleading(\s*Skill)?/gi, "系統潤飾規則"],
    [/legal-debate\s*skill/gi, "系統流程"],
    [/engine\/verify\.py/gi, "查證程式"],
    [/LegalDebate\s*系統\s*Stage\s*3/gi, "系統攻防推演最終階段"],
    [/position\/reasoning\s*原文/gi, "主張與理由原文"],
    [/position\s*\+\s*reasoning/gi, "主張與理由"],
    [/position_drift/gi, "引用清單差異"],
    [/weak_points?/gi, "雙方讓步條件"],
    [/\bfalsifier\b/gi, "讓步條件"],
    [/\bplaintiff\b/gi, "原告方"],
    [/\bdefendant\b/gi, "被告方"],
    [/Phase\s*[12]\b/gi, "後續階段"],
    [/\bStep(\d+)\b/gi, "步驟$1"],
    [/\bSkill\b/gi, "潤飾規則"],
    [/\bpublished\b/gi, "已通過"],
    // 原文常把英文欄位名和中文並列(「falsifier 與讓步條件」「讓步條件(falsifier)」)，代換後會變成
    // 「讓步條件 與讓步條件」，所以最後把並列的重複說法收成一個
    [/[ \t]*((?:雙方)?讓步條件)[ \t]*(?:與|和|及|、|\/)[ \t]*(?:雙方)?讓步條件/g, "$1"],
    [/((?:雙方)?讓步條件)[ \t]*[(（][ \t]*(?:雙方)?讓步條件[ \t]*[)）]/g, "$1"],
  ];
  function delabelJargon(raw) {
    var text = String(raw || "");
    TEXT_JARGON.forEach(function (pair) { text = text.replace(pair[0], pair[1]); });
    return text;
  }
  function cleanDraftNote(raw) {
    return delabelJargon(raw)
      .replace(/【(?:骨架版聲明|本稿產出說明)[^】]*】/g, "")  // 附註區塊的標頭，畫面另有標題
      .replace(/^-{2,}\s*$/gm, "")
      .split("\n").map(function (l) { return l.replace(/^[-•]\s*/, "").trim(); })
      .filter(function (l) { return l && l !== "。" && !/^骨架版[,，]?.*潤飾[。.]?$/.test(l); })
      .join("\n\n").replace(/\n{3,}/g, "\n\n").trim();
  }

  // 版本：系統產生版(流程經查證閘門落地，原稿不改寫)與律師編輯版(UI 另存的新版本)。
  // 預設顯示最新的系統產生版，錄製案件的重播畫面因此不受律師編輯影響。
  function pleadingOf(d, side) {
    return (d.pleadings || {})[side] || (side === "plaintiff" ? d.pleading : null);
  }
  function pleadingSide(d) { return state.pleadingSide[d.case.case_id] || "plaintiff"; }
  // 版本列只放起訴狀與答辯狀；P4 準備書狀、P5 言詞辯論意旨狀是各方另一份書狀，列在 roundDocsCard
  var ROUND_DOC = { brief: "民事準備書狀", closing: "民事言詞辯論意旨狀" };
  function versionsOf(d, side) {
    return (d.pleading_versions || []).filter(function (v) { return (v.side || "plaintiff") === side && !ROUND_DOC[v.pleading_type]; });
  }
  function roundDocsCard(d) {
    var docs = (d.pleading_versions || []).filter(function (v) { return ROUND_DOC[v.pleading_type]; });
    if (!docs.length) return null;
    var id = d.case.case_id;
    return card("準備書狀與言詞辯論意旨狀", [
      h("p", { class: "detail-note", text: "正文由程式依各方公開論證組成(不含內部檢討與讓步條件)。" }),
      docs.map(function (v) {
        var lines = delabelJargon(splitDraftNote(v.draft_text).body).replace(/^\s+|\s+$/g, "").split("\n");
        var exportUrl = API_BASE + "/api/cases/" + encodeURIComponent(id) + "/pleadings/" + v.id + "/export";
        return fold(SIDE[v.side || "plaintiff"].label + " " + ROUND_DOC[v.pleading_type] + " #" + v.id + (v.exportable ? "・✓" : "・✗ 未放行"), [
          h("div", { class: "controls" }, v.exportable ? h("a", { class: "btn small", href: exportUrl, download: "" }, "匯出 .txt") : null,
            h("span", { class: "detail-note", text: "產生於 " + fmtTime(v.generated_at) })),
          h("div", { class: "pleading-doc" }, lines.map(function (ln, i) {
            if (i === 0) return h("div", { class: "pl-title", text: ln });
            return ln.trim() ? h("div", { class: "pl-line" + (/^【爭點/.test(ln) ? " pl-head" : ""), text: ln }) : h("div", { class: "pl-gap", "aria-hidden": "true" });
          }))]);
      })]);
  }
  function selectedVersion(d) {
    var vs = versionsOf(d, pleadingSide(d));
    var sel = vs.filter(function (v) { return v.id === state.pleadingSel[d.case.case_id]; })[0];
    if (sel) return sel;
    var g = complaintGate(d);  // 關卡 1 確認過的版本：之後各步驟讀的就是它，預設顯示
    var confirmed = g && pleadingSide(d) === "plaintiff" && vs.filter(function (v) { return v.id === g.version_id; })[0];
    if (confirmed) return confirmed;
    var sys = vs.filter(function (v) { return v.source === "system"; });
    return sys[sys.length - 1] || vs[vs.length - 1];
  }
  function versionChip(v) {
    if (v.source === "system_revision") return chip("neutral", "修訂版(依診斷建議)", { title: "診斷後由系統依修改建議產生的版本，不是律師編輯版" });
    return v.source === "lawyer_edit" ? chip("judge", "✎ 律師編輯版", { title: "律師在 UI 編輯後另存的版本" }) : originChip(v.origin);
  }
  function systemMade(v) { return v.source === "system" || v.source === "system_revision"; }
  function splitDraftNote(text) {
    var noteIdx = text.search(/-{2,}\s*\n\s*(?=【)|【(?:骨架版聲明|本稿產出說明)/);
    return noteIdx >= 0 ? { body: text.slice(0, noteIdx), note: cleanDraftNote(text.slice(noteIdx)) } : { body: text, note: null };
  }
  function editableText(v) {
    return systemMade(v) ? delabelJargon(splitDraftNote(v.draft_text).body).trim() : v.draft_text;
  }
  function pleadingDoc(v) {
    var system = systemMade(v), doc = DOCUMENT[v.side || "plaintiff"];
    var lines = (system ? delabelJargon(splitDraftNote(v.draft_text).body) : v.draft_text).replace(/^\s+|\s+$/g, "").split("\n");
    // 標題是第一個不是整行【…】的行；之前的整行【…】(如即時生成稿開頭的骨架版說明)照原文列在標題上方
    var titleIdx = 0;
    while (titleIdx < lines.length - 1 && (!lines[titleIdx].trim() || /^【[^】]*】$/.test(lines[titleIdx].trim()))) titleIdx++;
    return h("div", { class: "pleading-doc" },
      lines.map(function (ln, i) {
        if (i < titleIdx) return ln.trim() ? h("div", { class: "pl-line", text: ln }) : null;
        if (i === titleIdx) return [
          h("div", { class: "pl-title", text: ln.replace(/[（(][\s\S]*[）)]\s*$/, "").trim() || doc.title }),
          h("div", { class: "pl-subtitle", text: (v.source === "system_revision" ? "修訂版．依診斷建議．須經律師審核後使用"
            : system ? "骨架版初稿．尚未經法律用語潤飾．須經律師審核後使用" : "律師編輯版．須經律師審核後使用") + (v.side === "defendant" ? "．模擬答辯，非針對實際起訴狀" : "") }),
        ];
        var headLine = /^(訴之聲明|答辯聲明|事實及理由|證物名稱及件數|為.*事[：:])/.test(ln);
        if (!ln.trim()) return h("div", { class: "pl-gap", "aria-hidden": "true" });
        return h("div", { class: "pl-line" + (headLine ? " pl-head" : ""), text: ln });
      }));
  }
  function versionBanner(v, d) {
    if (v.source === "system_revision") {  // 審查 W7-3:不是律師編輯版，引用在落地時已過查證閘門
      return banner("rec", "i", [h("strong", { text: "修訂版起訴狀(依診斷建議)" }), "：診斷後由系統依修改建議產生，於 " +
        fmtTime(v.generated_at) + " 存入，接在 #" + v.parent_id + " 之後。不是律師編輯版，也不會取代律師確認的版本；引用在存入時已通過查證。"]);
    }
    if (v.source === "lawyer_edit") {
      return banner("rec", "✎", [h("strong", { text: "律師編輯版" }), "：於 " + fmtTime(v.generated_at) + " 存檔，基於 #" + v.parent_id +
        "。原稿 #" + v.parent_id + " 保留不動；本版的引用在存檔時逐條查證，結果列於下方。"]);
    }
    var live = v.origin && v.origin.kind === "live";
    var sysCount = versionsOf(d, v.side || "plaintiff").filter(function (x) { return x.source === "system"; }).length;
    return banner(live ? "ok" : "rec", live ? "⚡" : "⏺", [h("strong", { text: live ? "系統產生版・本次即時生成" : "系統產生版・錄製紀錄" }),
      "：草稿產生於 " + fmtTime(v.generated_at) + (live ? "(UI 執行 #" + v.origin.run_id + ")" : "") +
      (sysCount > 1 ? "；此案件共有 " + sysCount + " 份" + DOCUMENT[v.side || "plaintiff"].short + "系統草稿" : "") + "。"]);
  }
  function pleadingCiteRow(c, lawyer) {
    var ok = c.gate === "pass";
    var meta = c.status === "no_record" ? { cls: "bad", icon: "✗", label: "尚無查證通過紀錄" } : statusMeta(c.status);
    var lines = [];
    if (c.note) lines.push(h("div", null, h("span", { class: "k", text: "說明：" }), c.note));
    if (c.verified_via && c.verified_via !== "previous_record") lines.push(h("div", null, h("span", { class: "k", text: "來源：" }), VIA[c.verified_via] || c.verified_via));
    if (c.live_attempt && c.live_attempt.tried) lines.push(h("div", null, h("span", { class: "k", text: "即時查詢：" }),
      (LIVE_OUTCOME[c.live_attempt.outcome] || c.live_attempt.outcome) + (c.live_attempt.error ? "(" + c.live_attempt.error + ")" : "")));
    if (c.primary_source_url) lines.push(h("div", null, h("span", { class: "k", text: "原文：" }),
      h("a", { href: c.primary_source_url, target: "_blank", rel: "noopener noreferrer", text: "開啟官方頁面" })));
    if (!lawyer && c.db_record) lines.push(h("div", null, h("span", { class: "k", text: "查證紀錄：" }),
      statusLabel(c.db_record.status) + "(" + fmtTime(c.db_record.verified_at) + ")" +
      (c.db_record.matched_by === "normalized" ? "；以同條文比對，對應紀錄「" + c.db_record.db_citation_text + "」" : "")));
    return h("div", { class: "vrow" + (ok ? "" : " blocked") },
      h("div", null, h("span", { class: "pill " + (ok ? "ok" : meta.cls === "bad" ? "bad" : "warn") },
        h("span", { "aria-hidden": "true", text: ok ? "✓" : meta.icon }), ok ? "已查證通過" : meta.label)),
      h("div", null, h("div", { class: "vrow-cite", text: c.citation_text }),
        lawyer ? h("div", { class: "vrow-meta" }, chip("neutral", c.change === "added" ? "新增或改動的引用" : "沿用原稿引用"),
          chip(c.verified_now ? "ok" : "neutral", c.verified_now ? "存檔時重新查證" : "沿用查證紀錄"),
          ok ? chip("ok", "✓ 放行") : chip("bad", "✗ 未放行")) : null,
        h("div", { class: "vrow-lines" }, lines)),
      h("div"));
  }
  async function savePleadingEdit(d, ed) {
    var id = d.case.case_id;
    ed.busy = true; ed.error = null; renderPanel();
    try {
      var v = await api("/api/cases/" + encodeURIComponent(id) + "/pleadings", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ parent_id: ed.parentId, draft_text: ed.text, mode: state.verifyOpts.mode, timeout_sec: state.verifyOpts.timeout }) });
      var added = v.citation_check.filter(function (c) { return c.change === "added"; }).length;
      state.pleadingNotice[id] = banner(v.exportable ? "ok" : "bad", v.exportable ? "✓" : "✗", [
        h("strong", { text: "已另存 " + v.label }), "：共 " + v.citation_check.length + " 條引用(新增或改動 " + added + " 條)" +
          (v.exportable ? "，全部通過查證，可以匯出。" : "，其中 " + v.blocked_count + " 條未通過查證，此版本未放行、不能匯出。") +
          (v.removed_citations.length ? "相較原稿移除：" + v.removed_citations.join("、") + "。" : "")]);
      state.pleadingSel[id] = v.id;
      delete state.pleadingEdit[id];
      await reloadDetailQuietly();
    } catch (e) {
      ed.error = e.message;
    }
    ed.busy = false;
    if (state.caseId === id) renderPanel();
  }
  async function reverifyVersion(d, v) {
    var id = d.case.case_id;
    state.pleadingBusy[id] = true; renderPanel();
    try {
      var r = await api("/api/cases/" + encodeURIComponent(id) + "/pleadings/" + v.id + "/reverify", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: state.verifyOpts.mode, timeout_sec: state.verifyOpts.timeout }) });
      state.pleadingNotice[id] = banner(r.exportable ? "ok" : "warn", r.exportable ? "✓" : "!", r.exportable
        ? r.label + " 重新查證後全部通過，可以匯出。" : r.label + " 重新查證後仍有 " + r.blocked_count + " 條未通過，未放行。");
      await reloadDetailQuietly();
    } catch (e) {
      state.pleadingNotice[id] = banner("bad", "✗", "重新查證失敗：" + e.message);
    }
    state.pleadingBusy[id] = false;
    if (state.caseId === id) renderPanel();
  }
  function pleadingEditor(d, ed) {
    return card("編輯" + DOCUMENT[pleadingSide(d)].short + "為新版本(基於 #" + ed.parentId + ")", [
      h("p", { class: "detail-note", text: "存檔時原稿保留不動，另存為「律師編輯版」新版本。新增或改動的引用會當場重新查證(判例先比對本地語料庫再查司法院；法條查全國法規資料庫)；未通過者照實標示，該版本不能匯出。" }),
      d.gates && pleadingSide(d) === "plaintiff" ? h("p", { class: "detail-note", text: "〔CF…〕是事實點編號，之後模擬被告逐點表態時用；匯出時會移除。新寫的段落沒有〔CF…〕時不會進逐點表態，存檔後會提示，不阻擋。" }) : null,
      h("p", { class: "detail-note", text: "系統只辨識「法規名第N條」與「最高法院N年度台X字第N號」寫法；其他看起來像引用的文字(如其他法規、下級審字號)會標為無法查證、不放行。" }),
      h("label", { class: "pleading-editor", for: "pleading-text" },
        h("span", { class: "field-label", text: "訴狀內容" }),
        (function () {
          var ta = h("textarea", { id: "pleading-text", rows: "24", disabled: ed.busy ? true : null,
            oninput: function (e) { ed.text = e.target.value; } });
          ta.value = ed.text;
          return ta;
        })()),
      ed.error ? banner("bad", "✗", "存檔失敗：" + ed.error) : null,
      h("div", { class: "controls" },
        h("button", { class: "btn primary", type: "button", disabled: ed.busy ? true : null, onclick: function () { savePleadingEdit(d, ed); },
          text: ed.busy ? "查證中…" : "另存新版本並查證" }),
        h("button", { class: "btn", type: "button", disabled: ed.busy ? true : null, text: "取消",
          onclick: function () { delete state.pleadingEdit[d.case.case_id]; renderPanel(); } }))]);
  }

  // ───────────── 關卡 1:律師確認起訴狀(書狀交換流程) ─────────────
  function complaintGate(d) { return d.gates ? d.gates.complaint : null; }
  var GATE_ACTION = { "continue": "確認並繼續", finish: "到此結束" };
  function gateHow(g) { return g.by === "auto" ? "無人值守執行自動通過，未經律師確認" : "在 UI 確認"; }
  async function confirmGate(d, v, action) {
    var id = d.case.case_id, kind = v.source === "lawyer_edit" ? "律師編輯版" : "系統原稿";
    var ok = window.confirm(action === "continue"
      ? "以「" + kind + " #" + v.id + "」確認起訴狀並繼續？\n\n・之後的步驟(被告防禦分析起)一律讀這一版。\n・確認後不能更改；要用別的版本只能另建案件。\n・確認後回到案件總覽按「續跑」才會開始，不會自動花費。"
      : "在關卡 1 到此結束，採用「" + kind + " #" + v.id + "」？\n\n・案件停在起訴狀，不再往下跑；這一版可以匯出。\n・確認後不能更改。");
    if (!ok) return;
    state.pleadingBusy[id] = true; delete state.pleadingNotice[id]; renderPanel();
    try {
      await api("/api/cases/" + encodeURIComponent(id) + "/gates/complaint", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version_id: v.id, action: action }) });
      state.pleadingNotice[id] = banner("ok", "✓", "關卡 1 已記錄：" + GATE_ACTION[action] + "，採用" + kind + " #" + v.id + "。" +
        (action === "continue" ? "回到案件總覽即可從「被告防禦分析」續跑。" : "案件停在這裡。"));
      await reloadDetailQuietly();
    } catch (e) {
      state.pleadingNotice[id] = banner("bad", "✗", "無法確認：" + e.message);
    }
    state.pleadingBusy[id] = false;
    if (state.caseId === id) renderPanel();
  }
  function gateCard(d, v) {
    if (!d.gates || pleadingSide(d) !== "plaintiff") return null;
    var g = d.gates.complaint, id = d.case.case_id;
    if (g) {
      var kind = g.source === "lawyer_edit" ? "律師編輯版" : "系統原稿";
      return banner(g.by === "auto" ? "warn" : "ok", g.by === "auto" ? "!" : "✓", [
        h("strong", { text: g.by === "auto" ? "尚未經律師確認" : "律師已確認" }),
        "：" + (g.by === "auto" ? "流程自動採用" : "採用") + kind + " #" + g.version_id + (g.action === "finish" ? "，案件停在起訴狀" : "，以這一版往下模擬") + "。" +
        (v.id !== g.version_id ? "目前檢視的 #" + v.id + " 不是採用的版本。" : ""),
        h("span", { class: "sr-only", text: gateHow(g) + "，" + fmtTime(g.recorded_at) })]);
    }
    if (!d.gates.pending) return null;
    var running = (d.live_runs || []).some(function (r) { return r.status === "running"; });
    var busy = state.pleadingBusy[id] || running;
    var blocked = !v.exportable, noCf = v.new_paragraphs_without_cf || [];
    return card("關卡 1：確認起訴狀", [
      h("p", { class: "detail-note", text: "流程停在這裡等你決定；目前選定：" + v.label + (v.source === "lawyer_edit" ? "(基於 #" + v.parent_id + ")" : "") + "。要換版本請用上方的版本列，確認後不可更改。" }),
      fold("兩個按鈕的差別", h("p", { text: "起訴狀 v1 已落地。可先「編輯為新版本」修改(原稿保留)，再選定要用的版本：" +
        "「確認並繼續」後，續跑從被告防禦分析開始，之後一律讀這一版；「到此結束」則案件停在起訴狀，可匯出。" })),
      blocked ? banner("bad", "✗", "此版本有 " + v.blocked_count + " 條引用未通過查證，不能確認。請先重新查證，或編輯移除該引用。") : null,
      noCf.length ? banner("warn", "!", [h("strong", { text: "這些新段落沒有〔CF…〕標記，不會進逐點表態" }),
        "(只提示，不阻擋)：" + noCf.map(function (t) { return "「" + (t.length > 40 ? t.slice(0, 40) + "…" : t) + "」"; }).join("、")]) : null,
      running ? banner("warn", "⏳", "此案件有執行進行中，結束後才能確認。") : null,
      h("div", { class: "controls" },
        h("button", { class: "btn primary", type: "button", disabled: busy || blocked ? true : null,
          onclick: function () { confirmGate(d, v, "continue"); }, text: "以此版本確認並繼續" }),
        h("button", { class: "btn", type: "button", disabled: busy || blocked ? true : null,
          onclick: function () { confirmGate(d, v, "finish"); }, text: "到此結束" }))]);
  }

  // 閱讀器版本列的名稱：律師看的是「初稿／修訂版／我改的版本」，編號只在同類有多份時才加
  function readerVersionName(x, vs) {
    var same = vs.filter(function (y) { return y.source === x.source; }).length > 1;
    var name = x.source === "system_revision" ? "修訂版(依診斷建議)" : x.source === "lawyer_edit" ? "律師修改版" : "初稿";
    return name + (same || x.source === "lawyer_edit" ? " #" + x.id : "");
  }
  function documentSwitch(d, locked) {
    var id = d.case.case_id, cur = pleadingSide(d);
    return h("div", { class: "seg document-switch", role: "group", "aria-label": "書狀種類" }, SIDES.map(function (side) {
      var has = versionsOf(d, side).length;
      return h("button", { type: "button", "aria-pressed": String(cur === side), disabled: locked ? true : null,
        onclick: function () {
          if (cur === side) return;
          state.pleadingSide[id] = side; delete state.pleadingSel[id]; delete state.pleadingNotice[id]; renderPanel();
        } }, DOCUMENT[side].label + (has ? "" : "・尚未產生"));
    }));
  }
  function pleadingPanel(d, opts) {
    var o = opts || {}, title = o.title || "訴狀骨架初稿";
    var id = d.case.case_id, side = pleadingSide(d), doc = docOf(d, side), vs = versionsOf(d, side);
    var lede = "須由執業律師審核修訂後方可使用，不得逕行送出；可編輯為新版本(原稿保留)。";
    var ledeMore = doc.lede + "可編輯為律師版本(原稿保留)，須由執業律師審核修訂、補正當事人資訊與證物清單後方可使用，不得逕行送出。";
    var ed = state.pleadingEdit[id];
    if (!vs.length) return [panelHead(title, null, lede), o.fixedSide ? null : documentSwitch(d, false), partyPleadingCard(d),
      emptyState([h("p", { text: "此案件尚未產生" + doc.label + "骨架。" }),
        d.gates ? h("p", { class: "detail-note", text: side === "defendant"
          ? "書狀交換流程：答辯狀在關卡 1 確認起訴狀之後的續跑才產生(或在跑完全程時產生)。系統不會拿另一方的書狀充數。"
          : "書狀交換流程：起訴狀 v1 在即時執行的第一段(P1)產生。" }) :
        h("p", { class: "detail-note", text: (side === "defendant"
          ? "答辯狀骨架於 2026-10-29 加入流程，之前跑完的案件只產生了原告起訴狀；之後的案件只產使用者選的書狀。"
          : "即時執行時只產使用者選的書狀；沒選起訴狀的案件就不會有。") +
          "系統不會拿另一方的書狀充數。已有該方 Stage 3 與查證結果的案件，可依 legal-debate 流程 Step 9C 只補產這一份，不必重跑整場攻防。" })]),
      pleadingRunCard(d, side, false), o.fixedSide ? null : roundDocsCard(d)];
    var v = selectedVersion(d), busy = state.pleadingBusy[id], gate = side === "plaintiff" ? complaintGate(d) : null;
    var exportUrl = API_BASE + "/api/cases/" + encodeURIComponent(id) + "/pleadings/" + v.id + "/export";
    var out = [
      panelHead(title, versionChip(v), o.reader ? (o.lede || "須由執業律師審核後使用。") : lede, o.reader ? null : ledeMore),
      o.fixedSide ? null : documentSwitch(d, !!ed),
      o.reader && vs.length < 2 ? null : h("div", { class: "version-bar", role: "group", "aria-label": doc.short + "版本" }, vs.map(function (x) {
        return h("button", { class: "btn small", type: "button", "aria-pressed": String(x.id === v.id), disabled: ed ? true : null,
          title: x.label, onclick: function () { state.pleadingSel[id] = x.id; renderPanel(); } },
          o.reader ? readerVersionName(x, vs) + (x.exportable ? "" : "・✗ 未放行") + (gate && gate.version_id === x.id ? (gate.by === "auto" ? "・流程採用" : "・律師確認版") : "") :
          x.label + (x.source === "system" ? (x.origin.kind === "live" ? "・⚡即時生成" : "・⏺錄製")
            : x.source === "system_revision" ? "・接在 #" + x.parent_id + " 之後" : "・基於 #" + x.parent_id) +
          (x.exportable ? "・✓" : "・✗ 未放行") + (gate && gate.version_id === x.id ? "・關卡 1 採用" : ""));
      })),
      state.pleadingNotice[id] || null,
    ];
    if (ed) { out.push(pleadingEditor(d, ed)); return out; }
    if (o.reader) return readerBody(d, out, v, doc, busy, exportUrl, o);
    out.push(gateCard(d, v));
    var note = systemMade(v) ? splitDraftNote(v.draft_text).note : null;
    var okN = v.citation_check.length - v.blocked_count;
    out.push(
      v.lint_warnings && v.lint_warnings.length ? banner("warn", "!", [h("strong", { text: "書狀正文含模擬流程用語" }),
        "：" + v.lint_warnings.map(function (w) { return w.word + "×" + w.count; }).join("、") + "。不阻擋匯出，請律師確認是否要刪改。"]) : null,
      h("div", { class: "controls" },
        chip(v.blocked_count ? "bad" : "ok", v.blocked_count ? "✗ " + v.blocked_count + " 條引用未通過" : "✓ 引用 " + okN + " / " + v.citation_check.length + " 通過"),
        h("button", { class: "btn", type: "button", disabled: busy ? true : null, text: "✎ 編輯為新版本",
          onclick: function () { delete state.pleadingNotice[id]; state.pleadingEdit[id] = { parentId: v.id, text: editableText(v), busy: false, error: null }; renderPanel(); } }),
        v.blocked_count ? h("button", { class: "btn", type: "button", disabled: busy ? true : null, onclick: function () { reverifyVersion(d, v); },
          text: busy ? "查證中…" : "重新查證未通過的引用(" + v.blocked_count + " 條)" }) : null,
        v.exportable ? h("a", { class: "btn primary", href: exportUrl, download: "" }, "匯出" + doc.short + " .txt")
          : h("button", { class: "btn primary", type: "button", disabled: true, text: "匯出" + doc.short + " .txt" }),
        v.exportable ? null : h("span", { class: "detail-note", text: "有 " + v.blocked_count + " 條引用未通過查證，未放行，不能匯出。" })),
      isV2(d) ? null : pleadingRunCard(d, side, true),
      v.diff ? diffToggle(d, v) : null,
      v.diff && state.diffOn[id] ? diffBlock(v.diff) : pleadingDoc(v));
    // 正文之後：未通過的引用先列；通過的引用、版本來源、當事人資料、系統備註收在下面
    var failedC = v.citation_check.filter(function (c) { return c.gate !== "pass"; });
    var passedC = v.citation_check.filter(function (c) { return c.gate === "pass"; });
    out.push(card("此版本的引用查證狀態", [
      h("div", { style: "margin-bottom:10px" }, chip(v.blocked_count || !v.citation_check.length ? (v.blocked_count ? "bad" : "neutral") : "ok",
        (v.blocked_count ? "✗ " : "✓ ") + okN + " / " + v.citation_check.length + " 條已查證通過")),
      failedC.map(function (c) { return pleadingCiteRow(c, v.source === "lawyer_edit"); }),
      passedC.length ? fold("已通過的 " + passedC.length + " 條引用", passedC.map(function (c) { return pleadingCiteRow(c, v.source === "lawyer_edit"); })) : null,
      h("p", { class: "detail-note", text: v.source === "lawyer_edit"
        ? "存檔時由版本文字重新找出引用並逐條查證；重新查證只處理未通過者。"
        : "由草稿文字重新找出其中的法條與裁判字號，對照目前的查證紀錄。" })]));
    out.push(fold("版本來源與系統備註", [versionBanner(v, d), partyPleadingCard(d),
      note ? card("系統補充說明(供律師參考，非訴狀正文)", paragraphs(note)) : null]));
    if (!o.fixedSide) out.push(roundDocsCard(d));
    return out;
  }

  // 閱讀器版面(v2 起訴狀、答辯狀分頁):正文為主體，右側是關卡與引用查證狀態，操作列在下方
  function readerBody(d, out, v, doc, busy, exportUrl, o) {
    var id = d.case.case_id, note = systemMade(v) ? splitDraftNote(v.draft_text).note : null;
    var okN = v.citation_check.length - v.blocked_count;
    var failedC = v.citation_check.filter(function (c) { return c.gate !== "pass"; });
    if (o.noHead) out.shift();
    var side = h("aside", { class: "reader-side", "aria-label": "引用查證與關卡" },
      gateCard(d, v),
      h("section", { class: "card" },
        h("div", { class: "card-header" }, h("span", { class: "card-title", text: "引用查證" }),
          chip(v.blocked_count ? "bad" : v.citation_check.length ? "ok" : "neutral", (v.blocked_count ? "✗ " : "✓ ") + okN + " / " + v.citation_check.length + " 通過")),
        h("div", { class: "cite-list" }, v.citation_check.length ? v.citation_check.map(function (c) {
          var ok = c.gate === "pass";
          return h("div", { class: "cite-row " + (ok ? "ok" : "bad") },
            h("span", { class: "cite-row-mark", "aria-hidden": "true", text: ok ? "✓" : "✗" }),
            h("span", { class: "cite-row-text", text: c.citation_text }),
            h("span", { class: "sr-only", text: ok ? "已查證" : "未通過" }),
            c.primary_source_url ? h("a", { href: c.primary_source_url, target: "_blank", rel: "noopener noreferrer", text: "官方" }) : null);
        }) : h("p", { class: "detail-note", text: "這份書狀沒有引用。" }))),
      h("div", { class: "reader-actions" },
        v.exportable ? h("a", { class: "btn primary", href: exportUrl, download: "" }, "匯出" + doc.short + " .txt")
          : h("button", { class: "btn primary", type: "button", disabled: true, text: "匯出" + doc.short + " .txt(未放行)" }),
        h("button", { class: "btn", type: "button", disabled: busy ? true : null, text: "✎ 編輯為新版本",
          onclick: function () { delete state.pleadingNotice[id]; state.pleadingEdit[id] = { parentId: v.id, text: editableText(v), busy: false, error: null }; renderPanel(); } }),
        v.blocked_count ? h("button", { class: "btn", type: "button", disabled: busy ? true : null, onclick: function () { reverifyVersion(d, v); },
          text: busy ? "查證中…" : "重新查證未通過的引用(" + v.blocked_count + " 條)" }) : null));
    out.push(
      v.lint_warnings && v.lint_warnings.length ? banner("warn", "!", [h("strong", { text: "書狀正文含模擬流程用語" }),
        "：" + v.lint_warnings.map(function (w) { return w.word + "×" + w.count; }).join("、") + "。不阻擋匯出，請律師確認是否要刪改。"]) : null,
      v.diff ? diffToggle(d, v) : null,
      h("div", { class: "reader" }, h("div", { class: "reader-main" }, v.diff && state.diffOn[id] ? diffBlock(v.diff) : pleadingDoc(v)), side),
      failedC.length ? card("未通過的引用", failedC.map(function (c) { return pleadingCiteRow(c, v.source === "lawyer_edit"); })) : null,
      fold("版本來源與系統備註", [versionBanner(v, d), partyPleadingCard(d),
        note ? card("系統補充說明(供律師參考，非訴狀正文)", paragraphs(note)) : null]));
    return out;
  }

  function partyPleadingCard(d) {
    var checks = d.party_checks || {}, items = SIDES.filter(function (side) { return checks[side]; });
    if (!items.length) return null;
    var bad = items.reduce(function (all, side) {
      return all.concat((checks[side].warnings || []).filter(function (w) { return w.level === "bad"; }).map(function (w) {
        var sentence = w.message.match(/^[^。！？]*[。！？]/);
        return SIDE[side].label + "：" + (sentence ? sentence[0] : w.message);
      }));
    }, []);
    return card("當事人資料（依商工登記帶入）", [
      bad.length ? banner("bad", "✗", "尚有 " + bad.length + " 項重大程序警示，正式列載前請先處理：" + bad.join("；")) : null,
      items.map(function (side) {
        var r = checks[side];
        if (r.entity_type === "branch" || r.query_status === "failed" || r.basic_data_available === false) return h("div", { class: "party-pleading-row" },
          h("strong", { text: SIDE[side].label }),
          h("p", { class: "detail-note", text: r.entity_type === "branch" ?
            "此統編為分公司；本功能未查詢分公司登記資料，請改以總公司統編查核。" :
            "商工基本資料未取得，當事人欄位未自動帶入。" }), partySourceFooter(r));
        return h("div", { class: "party-pleading-row" },
          h("strong", { text: SIDE[side].label }),
          partyFact("名稱", r.name), partyFact("統編", r.ban),
          partyFact("法定代理人", partyRepresentativeText(r)),
          partyFact("地址", r.address),
          chip(r.query_status === "ok" ? "ok" : "warn", (r.query_status === "ok" ? "✓ 已比對商工登記" : r.via === "recorded" ? "⏺ 錄製的查詢結果，非本次即時查詢" : "◐ 查核未完整") + "（查詢時間 " + fmtTime(r.fetched_at) + "）"),
          partySourceFooter(r));
      }),
      h("p", { class: "detail-note", text: "書狀本文未依本卡自動改寫；正式書狀請以本卡資料填寫當事人欄。" })]);
  }

  // ───────────── 建立新案件 ─────────────
  function openCreate(prefill) {
    state.creating = Object.assign({ case_id: "", case_type: "", facts_summary: "", claims: "", claim_amount: "",
      evidence: [], responses: [], known_gaps: "",
      p_name: "", p_ban: "", d_name: "", d_ban: "", busy: false, error: null, step: null }, prefill || {});
    state.caseId = null; state.detail = null;
    try { history.replaceState(null, "", "#/new"); } catch (e) { /* file:// 等環境略過 */ }
    renderAll();
  }
  function formField(f, key, label, opts) {
    var o = opts || {};
    var input = h(o.multiline ? "textarea" : "input", { id: "f-" + key, rows: o.rows, maxlength: o.max, placeholder: o.placeholder,
      inputmode: o.inputmode, value: o.multiline ? null : f[key], disabled: f.busy ? true : null,
      oninput: function (e) { f[key] = e.target.value; } });
    if (o.multiline) input.value = f[key];
    return h("label", { class: "form-field" + (o.wide ? " wide" : ""), for: "f-" + key },
      h("span", { class: "field-label", text: label + (o.optional ? "(選填)" : "") }), input,
      o.hint ? h("span", { class: "detail-note", text: o.hint }) : null);
  }
  var EVIDENCE_TYPES = [["contract", "契約或協議"], ["bank_record", "匯款或帳務"], ["chat_log", "對話紀錄"], ["letter", "存證信函"],
    ["other_document", "其他文書"], ["non_document", "非文書"]];
  function rowInput(row, key, label, opts) {
    var o = opts || {}, f = state.creating;
    return h("label", { class: "form-field" + (o.wide ? " wide" : "") },
      h("span", { class: "field-label", text: label }),
      h("input", { type: o.type || "text", maxlength: o.max, placeholder: o.placeholder, value: row[key] || "",
        disabled: f.busy ? true : null, oninput: function (e) { row[key] = e.target.value; } }));
  }
  function rowRemove(list, index, label) {
    return h("button", { class: "btn small", type: "button", disabled: state.creating.busy ? true : null, text: "移除" + label,
      onclick: function () { list.splice(index, 1); renderPanel(); } });
  }
  function evidenceRows(f) {
    return [
      f.evidence.map(function (row, i) {
        return h("div", { class: "input-row" },
          h("div", { class: "input-row-head" }, h("strong", { text: "甲證" + (i + 1) }), rowRemove(f.evidence, i, "此證據")),
          h("div", { class: "form-grid" },
            h("label", { class: "form-field" }, h("span", { class: "field-label", text: "類型" }),
              h("select", { disabled: f.busy ? true : null, onchange: function (e) { row.type = e.target.value; } },
                EVIDENCE_TYPES.map(function (t) { return h("option", { value: t[0], selected: row.type === t[0] ? true : null, text: t[1] }); }))),
            rowInput(row, "date", "日期(選填)", { type: "date" }),
            rowInput(row, "description", "證據內容", { wide: true, max: 2000, placeholder: "例：原告匯款 100 萬元至被告帳戶的匯款單" }),
            rowInput(row, "proves", "待證事實(選填)", { wide: true, max: 1000, placeholder: "例：金錢交付" })));
      }),
      h("button", { class: "btn small", type: "button", disabled: f.busy ? true : null, text: "＋ 新增證據",
        onclick: function () { f.evidence.push({ type: "other_document", date: "", description: "", proves: "" }); renderPanel(); } }),
    ];
  }
  function responseRows(f) {
    return [
      f.responses.map(function (row, i) {
        return h("div", { class: "input-row" },
          h("div", { class: "input-row-head" }, h("strong", { text: "第 " + (i + 1) + " 則" }), rowRemove(f.responses, i, "此則")),
          h("div", { class: "form-grid" },
            rowInput(row, "source", "來源", { max: 100, placeholder: "例：存證信函回函、LINE、調解" }),
            rowInput(row, "date", "日期(選填)", { type: "date" }),
            rowInput(row, "text", "對方說了什麼", { wide: true, max: 5000 })));
      }),
      h("button", { class: "btn small", type: "button", disabled: f.busy ? true : null, text: "＋ 新增對方反應",
        onclick: function () { f.responses.push({ source: "", date: "", text: "" }); renderPanel(); } }),
    ];
  }
  function createPanel(f) {
    return [
      panelHead("建立新案件", null, "目前只支援代理原告。輸入的文字原樣寫入本機資料庫，系統不會補寫案情；正式使用時請以律師掌握的完整卷證為準。"),
      h("form", { class: "card form-card", onsubmit: function (e) { e.preventDefault(); submitCreate(f); } },
        h("div", { class: "form-grid" },
          formField(f, "case_type", "案由", { max: 60, placeholder: "例：買賣價金、侵權行為損害賠償" }),
          formField(f, "case_id", "案件 ID", { optional: true, max: 64, placeholder: "留空自動產生(ui-日期-序號)",
            hint: "只能用英數字、點、底線、連字號" }),
          formField(f, "facts_summary", "我方主張的事實經過", { multiline: true, rows: 9, max: 20000, wide: true,
            hint: "時間、金額、契約與往來經過等，以你實際掌握者為限。模擬被告讀不到這段，只讀得到起訴狀寫進去的內容" }),
          formField(f, "claims", "請求／訴之聲明", { multiline: true, rows: 3, max: 5000, wide: true }),
          formField(f, "claim_amount", "請求金額(新臺幣元)", { optional: true, max: 15, inputmode: "numeric", placeholder: "例：1000000",
            hint: "非金錢請求或未定可留空，只用來提示程序類型" }),
          formField(f, "p_name", "原告名稱", { max: 100 }),
          formField(f, "p_ban", "原告統一編號", { optional: true, max: 12, inputmode: "numeric", placeholder: "8 位數字" }),
          formField(f, "d_name", "被告名稱", { max: 100 }),
          formField(f, "d_ban", "被告統一編號", { optional: true, max: 12, inputmode: "numeric", placeholder: "8 位數字" }),
          h("div", { class: "form-field wide" }, h("span", { class: "field-label", text: "證據清單(選填，依序編為甲證 1、甲證 2…)" }), evidenceRows(f)),
          h("div", { class: "form-field wide" }, h("span", { class: "field-label", text: "對方已知反應(選填，例如 LINE、存證信函、調解時的說法)" }), responseRows(f)),
          formField(f, "known_gaps", "已知缺口", { optional: true, multiline: true, rows: 3, max: 5000, wide: true,
            hint: "一行一項。只給律師與原告方，模擬被告讀不到" })),
        f.error ? banner("bad", "✗", "建立失敗：" + f.error) : null,
        f.step ? banner("warn", "⏱", f.step) : null,
        h("div", { class: "controls" },
          h("button", { class: "btn primary", type: "submit", disabled: f.busy ? true : null, text: f.busy ? "處理中…" : "建立案件" }),
          h("button", { class: "btn", type: "button", disabled: f.busy ? true : null, text: "取消",
            onclick: function () {
              state.creating = null;
              if (state.cases.length) selectCase(state.cases[0].case_id, "overview"); else renderAll();
            } }))),
    ];
  }
  async function submitCreate(f) {
    var missing = [["case_type", "案由"], ["facts_summary", "案件事實"], ["claims", "請求"], ["p_name", "原告名稱"], ["d_name", "被告名稱"]]
      .filter(function (k) { return !f[k[0]].trim(); }).map(function (k) { return k[1]; });
    if (missing.length) { f.error = "請填寫：" + missing.join("、"); renderPanel(); return; }
    var amount = f.claim_amount.replace(/[,，\s]/g, "");
    if (amount && !/^[0-9]+$/.test(amount)) { f.error = "請求金額只能填整數，或留空"; renderPanel(); return; }
    if (f.evidence.some(function (row) { return !row.description.trim(); })) { f.error = "有證據沒有寫內容；不需要的請移除"; renderPanel(); return; }
    if (f.responses.some(function (row) { return !row.text.trim(); })) { f.error = "有對方反應沒有寫內容；不需要的請移除"; renderPanel(); return; }
    f.busy = true; f.error = null; f.step = "寫入資料庫…"; renderPanel();
    var created;
    try {
      created = await api("/api/cases", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
        case_id: f.case_id.trim() || null, case_type: f.case_type, facts_summary: f.facts_summary, claims: f.claims,
        claim_amount: amount ? Number(amount) : null,
        evidence: f.evidence.map(function (row, i) {
          return { id: "甲證" + (i + 1), type: row.type, date: row.date || null, description: row.description, proves: row.proves || null };
        }),
        opponent_known_responses: f.responses.map(function (row) { return { source: row.source || null, date: row.date || null, text: row.text }; }),
        known_gaps: f.known_gaps.split(/\r?\n/).map(function (s) { return s.trim(); }).filter(Boolean),
        plaintiff: { name: f.p_name, ban: f.p_ban.trim() || null }, defendant: { name: f.d_name, ban: f.d_ban.trim() || null } }) });
    } catch (e) {
      f.busy = false; f.step = null; f.error = e.message; renderPanel(); return;
    }
    var notices = [{ cls: "ok", icon: "✓", text: "案件 " + created.case_id + " 已建立並寫入資料庫。" }];
    for (var i = 0; i < SIDES.length; i++) {
      var role = SIDES[i], p = created.parties[role];
      if (!p.ban) continue;
      f.step = "查核" + SIDE[role].label + "商工登記(統編 " + p.ban + ")…"; renderPanel();
      try {
        var r = await api("/api/party-check", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ban: p.ban, input_name: p.name, case_id: created.case_id, role: role }) });
        notices.push(r.query_status === "failed"
          ? { cls: "bad", icon: "✗", text: SIDE[role].label + "商工查核未完成(" + ((r.errors[0] || {}).error || "連線失敗") + ")；可到「起訴前檢查」分頁重試。" }
          : { cls: (r.warnings || []).length ? "warn" : "ok", icon: (r.warnings || []).length ? "!" : "✓",
            text: SIDE[role].label + "商工查核：" + (r.name || "已查詢") + (r.via === "recorded" ? "(本次即時查詢失敗，顯示錄製的查詢結果)" : "") +
              ((r.warnings || []).length ? "，警示 " + r.warnings.length + " 項，已轉成起訴審查事項" : "，無規則警示") });
      } catch (e) {
        notices.push({ cls: "bad", icon: "✗", text: SIDE[role].label + "商工查核失敗：" + e.message + "；可到「起訴前檢查」分頁重試。" });
      }
    }
    state.caseNotices[created.case_id] = notices;
    await refreshCases();
    await selectCase(created.case_id, "overview");
  }
  function renderSidebarNote() {
    var hl = liveInfo();
    document.getElementById("sidebar-note").textContent = hl.enabled
      ? "即時執行已啟用：建立案件後可由本機 Claude Code 跑完整攻防(模型 " + hl.model + ")。錄製案件照常重播。"
      : "即時執行停用：" + hl.reason + "。錄製案件照常重播。";
  }
  async function refreshCases() {
    try { state.cases = (await api("/api/cases")).cases; renderCaseList(); } catch (e) { /* 保留舊清單 */ }
  }

  // ───────────── 即時執行(Claude Code) ─────────────
  function liveLog(runId) {
    if (!state.liveLogs[runId]) state.liveLogs[runId] = { events: [], since: 0, loaded: false, error: null };
    return state.liveLogs[runId];
  }
  async function loadRunLog(runId) {
    var lr = liveLog(runId);
    lr.loaded = true;
    try { var r = await api("/api/runs/" + runId); lr.events = r.events; lr.since = r.event_count; }
    catch (e) { lr.error = e.message; }
    if (state.tab === "overview") renderPanel();
  }
  function ensurePolling() {
    if (!state.pollTimer) state.pollTimer = setInterval(pollRun, 3000);
  }
  async function pollRun() {
    var active = liveInfo().active_run;
    if (!active) { clearInterval(state.pollTimer); state.pollTimer = null; return; }
    var lr = liveLog(active.id);
    try {
      var r = await api("/api/runs/" + active.id + "?since=" + lr.since);
      lr.events = lr.events.concat(r.events).slice(-400); lr.since = r.event_count; lr.loaded = true; lr.error = null;
      var landed = r.events.some(function (e) { return e.kind === "landed" || e.kind === "error"; });
      if (!r.active) {
        state.health = await api("/api/health");
        renderSidebarNote();
        lr.loaded = false;  // 結束後改以存檔的完整紀錄為準
        await refreshCases();
      }
      if (state.caseId === active.case_id) {
        if (landed || !r.active) await reloadDetailQuietly();
        if (state.tab === "overview" || landed || !r.active) renderPanel();
      }
    } catch (e) { lr.error = e.message; }
  }
  // mode:full(新案件完整流程) / resume(續跑) / pleadings(只補產書狀，Step 9C);documents:使用者選的書狀
  // 書狀交換流程(protocol v2)不選書狀，改選停止點：stopAfter="complaint" 只跑到起訴狀 v1(停在關卡 1)，null 跑完全程
  var STOP_NAME = { complaint: "起訴狀 v1", answer: "模擬答辯狀", issue_sheet: "爭點整理表" };
  var STOP_CHIP = { complaint: "只產起訴狀(停在關卡 1)", answer: "跑到模擬答辯狀", issue_sheet: "跑到爭點整理表" };
  function v2RunConfirm(d, resume, stopAfter) {
    var hl = liveInfo(), head = "即將在這台電腦以你的 Claude 帳號啟動 Claude Code(模型 " + hl.model + ")，";
    var cap = "每次上限 " + hl.budget_usd + " 美元，超過即中止；訂閱帳號會占用 Claude 用量額度，與其他 Claude Code 使用共用。";
    var from = resume ? "從「" + d.resume.from_label + "」續跑，已落地的" + d.resume.landed.join("、") + "不會重做，也不會被覆寫或刪除。" : "";
    if (stopAfter === "complaint") {
      return head + (from || "") + "只跑到起訴狀 v1(原告請求權基礎檢驗 → 起訴狀 → 引用查證)，落地後停在關卡 1 等你確認。\n\n" +
        "・2026-11-02 實跑一次(單次，不是平均)：5 分 12 秒、估算 1.15 美元。\n・" + cap + "\n\n確定開始？";
    }
    var gate = complaintGate(d);
    var target = stopAfter ? "跑到" + STOP_NAME[stopAfter] + "落地後停止。" : "跑完全程(到起訴狀 v2)。";
    return head + (from || "") + target + "\n\n" +
      (gate ? "・起訴狀以關卡 1 採用的" + (gate.source === "lawyer_edit" ? "律師編輯版" : "系統原稿") + " #" + gate.version_id + "為準。\n"
        : "・關卡 1 自動通過：起訴狀 v1 不經律師確認就往下跑，紀錄會標「未經律師確認」。要先確認，請改按「只產起訴狀」。\n") +
      "・模擬被告只讀關卡 1 採用的起訴狀，讀不到事實經過全文。\n" +
      "・時間與花費依跑到哪一步而定。" + cap + "\n\n確定開始？";
  }
  async function startRun(d, mode, documents, stopAfter) {
    var hl = liveInfo(), id = d.case.case_id, pleadings = mode === "pleadings", resume = mode === "resume";
    var v2 = d.case.protocol === "v2";
    var docs = docsText(documents);
    var ok = window.confirm(v2 ? v2RunConfirm(d, resume, stopAfter) : pleadings
      ? "即將在這台電腦以你的 Claude 帳號啟動 Claude Code(模型 " + hl.model + ")，只產生" + docs + "骨架(legal-debate Step 9C)，不重跑攻防。\n\n" +
        "・只補產書狀的時間與花費尚未實測(訂閱帳號會占用 Claude 用量額度，與其他 Claude Code 使用共用)；每次上限 " + hl.budget_usd + " 美元，超過即中止。\n" +
        "・執行中可取消；既有的攻防、評估與其他書狀不會被更動。\n\n確定開始？"
      : resume
      ? "即將在這台電腦以你的 Claude 帳號啟動 Claude Code(模型 " + hl.model + ")，從「" + d.resume.from_label + "」續跑，書狀只產生：" + docs + "。\n\n" +
        "・已落地的" + d.resume.landed.join("、") + "不會重做，也不會被覆寫或刪除。\n" +
        "・費用視剩下的階段與書狀份數而定(整件約 2.5–3.3 美元，實測時只產一份起訴狀)；每次上限 " + hl.budget_usd + " 美元，超過即中止。訂閱帳號會占用 Claude 用量額度。\n\n確定續跑？"
      : "即將在這台電腦以你的 Claude 帳號啟動 Claude Code(模型 " + hl.model + ")，跑完整攻防流程，書狀只產生：" + docs + "。\n\n" +
        "・實測一件約 11–15 分鐘、估算約 2.5–3.3 美元(實測時只產一份起訴狀；選兩份會再增加，尚未實測；訂閱帳號會占用 Claude 用量額度，與其他 Claude Code 使用共用)；每次上限 " + hl.budget_usd + " 美元，超過即中止。\n" +
        "・執行中可取消；已落地的階段會保留，之後只能從尚未落地的階段續跑，不能整件重跑。沒選的書狀之後可在「訴狀骨架」分頁補產。\n\n確定開始？");
    if (!ok) return;
    state.liveBusy[id] = true; delete state.caseNotices[id]; delete state.pleadingNotice[id]; renderPanel();
    try {
      var r = await api("/api/cases/" + encodeURIComponent(id) + "/runs" + (resume ? "?resume=true" : ""), { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(v2 ? { kind: "full", stop_after: stopAfter || null } : { kind: pleadings ? "pleadings" : "full", documents: documents }) });
      var lr = liveLog(r.run.id);
      lr.events = r.events; lr.since = r.event_count; lr.loaded = true;
      state.health = await api("/api/health");
      ensurePolling();
      await refreshCases();
      await reloadDetailQuietly();
    } catch (e) {
      if (pleadings) state.pleadingNotice[id] = banner("bad", "✗", "無法開始補產" + docs + "：" + e.message);
      else state.caseNotices[id] = [{ cls: "bad", icon: "✗", text: "無法開始即時執行：" + e.message }];
    }
    state.liveBusy[id] = false;
    if (state.caseId === id) renderPanel();
  }
  async function cancelRun(run) {
    if (!window.confirm("確定取消執行 #" + run.id + "？已落地的階段會保留，之後只能從尚未落地的階段續跑。")) return;
    state.liveBusy[run.case_id] = true; renderPanel();
    try { await api("/api/runs/" + run.id + "/cancel", { method: "POST" }); }
    catch (e) { liveLog(run.id).error = "取消失敗：" + e.message; }
    state.liveBusy[run.case_id] = false;
    await pollRun();
    await reloadDetailQuietly();
    renderPanel();
  }
  function elapsed(run) {
    var end = run.ended_at ? Date.parse(run.ended_at) : Date.now();
    var min = Math.max(0, Math.round((end - Date.parse(run.started_at)) / 60000));
    return min < 60 ? min + " 分" : Math.floor(min / 60) + " 小時 " + (min % 60) + " 分";
  }
  // 訂閱額度(rate_limit_event):5 小時與 7 天視窗；API 金鑰登入時沒有這項資料
  var QUOTA_LABEL = { five_hour: "5 小時", seven_day: "7 天" };
  function localTime(iso) {
    var t = Date.parse(iso);
    return isNaN(t) ? "—" : new Date(t).toLocaleString("zh-TW", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
  }
  function quotaPct(x) { return x == null ? "?" : Math.round(x * 100) + "%"; }
  function quotaLine(windows) {
    return Object.keys(QUOTA_LABEL).filter(function (k) { return windows[k]; }).map(function (k) {
      var w = windows[k];
      return QUOTA_LABEL[k] + " " + (w.start != null && w.start !== w.end ? quotaPct(w.start) + " → " : "") + quotaPct(w.end) +
        (w.resets_at ? "(" + localTime(w.resets_at) + " 重置)" : "");
    }).join("・");
  }
  function quotaExpired(w) { return w.resets_at && Date.parse(w.resets_at) <= Date.now(); }
  // 上次已知的額度(某次執行結束時的值)：已過重置時間的視窗不再提醒，改說明數值已過期
  function knownQuota(q, warnAt) {
    var keys = Object.keys(QUOTA_LABEL).filter(function (k) { return q.windows[k]; });
    var hot = keys.filter(function (k) { return q.windows[k].end >= warnAt && !quotaExpired(q.windows[k]); });
    var expired = keys.filter(function (k) { return quotaExpired(q.windows[k]); });
    return [
      hot.length ? banner("warn", "!", hot.map(function (k) {
        return "訂閱帳號的 " + QUOTA_LABEL[k] + "額度在上次執行結束時已用 " + quotaPct(q.windows[k].end) +
          (q.windows[k].resets_at ? "，" + localTime(q.windows[k].resets_at) + " 重置" : "");
      }).join("；") + "。額度與這個帳號的其他 Claude 使用共用，用完時執行會中途失敗(已落地的階段保留)。") : null,
      h("p", { class: "detail-note", text: "上次已知的訂閱額度(" + localTime(q.as_of) + " 執行 #" + q.run_id + " 結束時，不是即時值)：" +
        quotaLine(q.windows) + (expired.length ? "。" + expired.map(function (k) { return QUOTA_LABEL[k]; }).join("、") +
        "視窗已過重置時間，實際用量應已重置" : "") })];
  }
  // 流程不完整且有分類器中止：最可能的原因就是分類器(Claude Code 自己回報完成，沒有其他明確錯誤)
  function stoppedByClassifier(run) { return run.status === "incomplete" && (run.safety_stops || []).length > 0; }
  function runLabel(run) {
    return RUN_STATUS[run.status].label + (stoppedByClassifier(run) ? "(安全分類器中止 " + run.safety_stops.length + " 次)" : "");
  }
  function safetyStopBanner(run) {
    var stops = run.safety_stops || [];
    if (!stops.length) return null;
    if (stoppedByClassifier(run)) {
      return banner("bad", "!", [h("strong", { text: "流程沒跑完的可能原因：安全分類器中止 " + stops.length + " 次" }),
        "：" + stops.map(function (s) { return s.who; }).join("、") + " 的回覆被 Anthropic 安全分類器中止，之後的階段沒有落地。" +
        "這不是程式或 API 錯誤，是根據執行紀錄推斷的原因，請以下方執行紀錄核對。依官方文件，這類中止照樣計費。"]);
    }
    var who = stops.map(function (s) { return s.who; }).join("、");
    var subagentOnly = stops.every(function (s) { return s.who !== "主 agent"; });
    var tail = run.status === "succeeded" ? (subagentOnly ? "依 SKILL.md，被中止的輸出不得落地、應另開 subagent 以同一份範本重派；請以執行紀錄與最後回覆核對。" : "") :
      run.status === "incomplete" ? "流程可能因此沒跑完，請以執行紀錄核對。" : "";
    return banner("warn", "!", [h("strong", { text: "安全分類器中止 " + stops.length + " 次" }),
      "：" + who + " 的回覆被 Anthropic 安全分類器中止。這不是程式或 API 錯誤。" + tail +
      "依官方文件，這類中止照樣計費。"]);
  }
  function fmtTokens(n) { return n >= 10000 ? (n / 10000).toFixed(n >= 1000000 ? 0 : 1) + " 萬" : String(n); }
  function tokenTotal(t) { return t.input_tokens + t.cache_read_input_tokens + t.cache_creation_input_tokens + t.output_tokens; }
  // 整次執行(含 subagent)的 token 數，取自 Claude Code 回報的累計值
  function tokenLine(t) {
    return "token 用量(含 subagent)：合計 " + fmtTokens(tokenTotal(t)) + "・輸入 " + fmtTokens(t.input_tokens) +
      "・快取讀取 " + fmtTokens(t.cache_read_input_tokens) + "・快取寫入 " + fmtTokens(t.cache_creation_input_tokens) +
      "・輸出 " + fmtTokens(t.output_tokens) + (Object.keys(t.by_model || {}).length > 1 ? "(" + Object.keys(t.by_model).join("、") + ")" : "");
  }
  function runReviewWarningCount(run, d) {
    return d.arguments.filter(function (a) {
      return a.origin.kind === "live" && a.origin.run_id === run.id && a.review_warning_count;
    }).length;
  }
  function runView(run, d) {
    var st = RUN_STATUS[run.status], lr = liveLog(run.id);
    var reviewCount = run.kind === "pleadings" ? null : runReviewWarningCount(run, d);
    if (!lr.loaded && run.status !== "running") loadRunLog(run.id);
    var events = lr.events;
    var row = function (e) {
      return h("div", { class: "run-event " + e.kind }, h("span", { class: "run-mark", "aria-hidden": "true", text: EVENT_MARK[e.kind] || "·" }),
        e.subagent ? chip("neutral", "subagent") : null, h("span", { class: "run-text", text: e.text }));
    };
    return h("div", { class: "run-view" },
      h("div", { class: "run-head" }, chip(st.cls, runLabel(run)), h("strong", { text: "執行 #" + run.id + (run.resume_from ? "(從" + run.resume_from + "續跑)" : "") }),
        run.kind === "pleadings" ? chip("neutral", "只補產" + docsText(run.documents) + "(Step 9C)")
          : run.stop_after ? chip("neutral", STOP_CHIP[run.stop_after] || run.stop_after)
          // 沒有停止點的 v2 執行不加標籤:W3 之前的執行(例如 W2 實跑)也是空值，當時是在指示裡另外寫明只跑到起訴狀
          : d.case.protocol === "v2" ? null
          : run.documents ? chip("neutral", "書狀：" + docsText(run.documents)) : null,
        h("span", { class: "detail-note", text: "開始 " + fmtTime(run.started_at) + "・經過 " + elapsed(run) + "・模型 " + run.model +
          (run.cost_usd != null ? "・估算花費 " + run.cost_usd.toFixed(2) + " 美元" : "") + (run.exit_code != null ? "・結束碼 " + run.exit_code : "") }),
        run.status === "running" ? h("button", { class: "btn small", type: "button", disabled: state.liveBusy[run.case_id] ? true : null,
          onclick: function () { cancelRun(run); }, text: "取消執行" }) : null),
      run.status === "running" ? h("div", { class: "chip-row" }, d.progress.map(function (s) {
        return chip(s.state === "done" ? "ok" : s.state === "partial" ? "warn" : "neutral", (s.state === "done" ? "✓ " : s.state === "partial" ? "◐ " : "· ") + s.label);
      })) : null,
      reviewCount === null ? null : reviewCount ? banner("warn", "!", "公開論證疑似含自我檢討:" + reviewCount + " 則。請查看攻防分頁逐則確認。") :
        h("p", { class: "detail-note", text: "公開論證疑似含自我檢討:0 則" }),
      stoppedByClassifier(run) ? safetyStopBanner(run) : null,
      run.error ? banner(run.status === "cancelled" ? "warn" : "bad", run.status === "cancelled" ? "!" : "✗", run.error) : null,
      stoppedByClassifier(run) ? null : safetyStopBanner(run),
      run.quota ? h("p", { class: "detail-note", text: "訂閱額度(本次執行開始 → 結束)：" + quotaLine(run.quota) }) : null,
      run.tokens ? h("p", { class: "detail-note", text: tokenLine(run.tokens) }) :
        run.status !== "running" ? h("p", { class: "detail-note", text: "token 用量：Claude Code 沒有回報 token 數，不估算。" }) : null,
      lr.error ? banner("warn", "!", "讀取執行紀錄失敗：" + lr.error) : null,
      events.length ? h("div", { class: "run-log", role: "log", "aria-label": "執行紀錄" }, events.slice(-30).map(row)) :
        h("p", { class: "detail-note", text: run.status === "running" ? "等待 Claude Code 輸出…" : "沒有可顯示的執行紀錄。" }),
      events.length > 30 ? fold("展開全部執行紀錄(" + events.length + " 則)", events.map(row)) : null,
      run.log_path ? h("p", { class: "detail-note", text: "完整原始輸出(stream-json)：" + run.log_path }) : null);
  }
  function liveRunCard(d) {
    if (d.case.source !== "database") return null;
    var hl = liveInfo(), runs = (d.live_runs || []).filter(function (r) { return r.kind !== "pleadings"; }), latest = runs[runs.length - 1];
    var hasRecords = d.stats.arguments || d.stats.questions || d.verdict || (d.pleading_versions || []).length;
    if (!latest && hasRecords) return null;  // 錄製案件：不提供重跑
    var body = [], rp = d.resume;
    if (latest) body.push(runView(latest, d));
    if (d.case.protocol === "v2" && (!latest || latest.status !== "running")) {
      body.push(v2RunControls(d, hl, rp, hasRecords));
      return card("即時執行(Claude Code)", body, latest ? chip(RUN_STATUS[latest.status].cls, runLabel(latest)) : null);
    }
    if (!latest || latest.status !== "running") {
      if (hasRecords && !(rp && rp.possible)) {
        body.push(h("p", { class: "detail-note", text: "此案件已有落地紀錄，不能整件重跑(落地紀錄不可覆寫)。" +
            (rp && rp.reason ? rp.reason + "。" : "") + "要用同樣內容再模擬一次，請另建案件。" }),
          h("button", { class: "btn small", type: "button", text: "以此案件內容建立新案件", onclick: function () { openCreate(prefillFrom(d)); } }));
      } else if (!hl.enabled) {
        body.push(banner("warn", "!", "即時執行停用：" + hl.reason));
      } else if (hl.auth && hl.auth.checked && !hl.auth.logged_in) {
        body.push(banner("bad", "✗", [h("strong", { text: "無法執行" }), "：" + hl.auth.detail + "。登入後重新整理本頁。"]));
      } else if (hl.active_run) {
        body.push(banner("warn", "⏳", "目前已有執行進行中(案件 " + hl.active_run.case_id + "，執行 #" + hl.active_run.id + ")，同一時間只能跑一件。"));
      } else if (hasRecords) {
        if (hl.quota) body.push(knownQuota(hl.quota, hl.quota_warn_at));
        body.push(h("p", { class: "detail-note", text: "資料庫已落地：" + rp.landed.join("、") + "。可從「" + rp.from_label + "」續跑：" +
            "已落地的紀錄不會重做，也不會被覆寫或刪除，Claude Code 會讀取這些紀錄接著跑剩下的階段。" +
            (rp.missing_sides.length ? "此階段只補" + rp.missing_sides.map(function (x) { return SIDE[x].label; }).join("、") + "一方。" : "") +
            (rp.landed.indexOf("法官訊問") >= 0 ? "法官訊問中「無爭議事項」當初沒有存進資料庫，續跑時無法取得，評估會照實註明。" : "") +
            "每次上限 " + hl.budget_usd + " 美元。" }),
          documentChooser(d),
          h("button", { class: "btn primary", type: "button", disabled: state.liveBusy[d.case.case_id] || !chosenDocs(d) ? true : null,
            onclick: function () { startRun(d, "resume", chosenDocs(d)); } }, h("span", { class: "ico", "aria-hidden": "true", text: "▶" }),
            state.liveBusy[d.case.case_id] ? "啟動中…" : "從「" + rp.from_label + "」續跑"),
          h("button", { class: "btn small", type: "button", text: "或以此案件內容建立新案件", onclick: function () { openCreate(prefillFrom(d)); } }));
      } else {
        if (hl.quota) body.push(knownQuota(hl.quota, hl.quota_warn_at));
        body.push(h("p", { class: "detail-note", text: "按下後，後端在這台電腦以你的 Claude 帳號啟動 Claude Code(無互動模式，模型 " + hl.model +
            ")，依 legal-debate 流程跑完：起訴審查 → Stage 1 → 法官訊問 → Stage 2 → Stage 3 → 機械彙整 → 爭點評估 → 引用查證 → 你選的書狀骨架。" +
            "只允許它執行 python main.py 指令、讀取專案檔案、派出 subagent。實測一件約 11–15 分鐘、估算約 2.5–3.3 美元(實測時只產一份起訴狀；選兩份會再增加，尚未實測；訂閱帳號會占用用量額度)，每次上限 " + hl.budget_usd + " 美元。" }),
          documentChooser(d),
          h("button", { class: "btn primary", type: "button", disabled: state.liveBusy[d.case.case_id] || !chosenDocs(d) ? true : null,
            onclick: function () { startRun(d, "full", chosenDocs(d)); } }, h("span", { class: "ico", "aria-hidden": "true", text: "▶" }),
            state.liveBusy[d.case.case_id] ? "啟動中…" : "開始即時執行"));
      }
    }
    return card("即時執行(Claude Code)", body, latest ? chip(RUN_STATUS[latest.status].cls, runLabel(latest)) : null);
  }
  // 書狀交換流程的執行按鈕：新案件或還沒過關卡 1 的續跑，可選「只產起訴狀」或「跑完全程」；關卡 1 等待中時引導去確認
  function v2RunControls(d, hl, rp, hasRecords) {
    var id = d.case.case_id, busy = state.liveBusy[id];
    var runBtn = function (mode, stopAfter, primary, label) {
      return h("button", { class: "btn" + (primary ? " primary" : ""), type: "button", disabled: busy ? true : null,
        onclick: function () { startRun(d, mode, null, stopAfter); } },
        h("span", { class: "ico", "aria-hidden": "true", text: "▶" }), busy ? "啟動中…" : label);
    };
    var gate = complaintGate(d);
    if (rp && rp.gate_pending) {
      return [banner("warn", "⏸", [h("strong", { text: "停在關卡 1" }), "：起訴狀 v1 已落地，等你在「起訴狀(P1)」分頁選定版本，確認並繼續，或到此結束。確認前不能續跑。"]),
        h("button", { class: "btn primary", type: "button", text: "前往起訴狀分頁確認", onclick: function () { switchTab("complaint"); } })];
    }
    if (hasRecords && !(rp && rp.possible)) {
      return [h("p", { class: "detail-note", text: (rp && rp.reason ? rp.reason + "。" : "") +
          "落地紀錄不可覆寫，不能整件重跑；要用同樣內容再模擬一次，請另建案件。" }),
        h("button", { class: "btn small", type: "button", text: "以此案件內容建立新案件", onclick: function () { openCreate(prefillFrom(d)); } })];
    }
    if (!hl.enabled) return banner("warn", "!", "即時執行停用：" + hl.reason);
    if (hl.auth && hl.auth.checked && !hl.auth.logged_in) return banner("bad", "✗", [h("strong", { text: "無法執行" }), "：" + hl.auth.detail + "。登入後重新整理本頁。"]);
    if (hl.active_run) return banner("warn", "⏳", "目前已有執行進行中(案件 " + hl.active_run.case_id + "，執行 #" + hl.active_run.id + ")，同一時間只能跑一件。");
    var out = [hl.quota ? knownQuota(hl.quota, hl.quota_warn_at) : null];
    if (hasRecords) {
      out.push(h("p", { class: "detail-note", text: "資料庫已落地：" + rp.landed.join("、") + "。可從「" + rp.from_label + "」續跑；已落地的紀錄不會重做，也不會被覆寫或刪除。" +
        (gate ? "起訴狀以關卡 1 採用的 #" + gate.version_id + "為準。" : "") + "每次上限 " + hl.budget_usd + " 美元。" }));
      // 停止點照後端續跑計畫給的 stop_after_options(已依落地進度過濾)
      var stops = rp.stop_after_options || [];
      out.push(h("div", { class: "controls" },
        stops.map(function (stop, i) {
          return runBtn("resume", stop, i === 0, stop === "complaint" ? "續跑到起訴狀(停在關卡 1)" : "續跑到" + STOP_NAME[stop]);
        }),
        runBtn("resume", null, !stops.length, stops.indexOf("complaint") >= 0 ? "續跑全程(關卡 1 自動通過)"
          : stops.length ? "續跑全程" : "從「" + rp.from_label + "」續跑")));
      return out;
    }
    out.push(h("p", { class: "detail-note", text: "書狀交換流程：先由原告方檢驗請求權基礎、寫起訴狀 v1(事實逐點對應、引用查證)，在關卡 1 停下來讓你確認或修改，" +
        "確認後再續跑模擬答辯與攻防。只允許 Claude Code 執行 python main.py 指令、讀取專案檔案、派出 subagent；每次上限 " + hl.budget_usd + " 美元(訂閱帳號會占用用量額度)。" }),
      h("p", { class: "detail-note", text: "「跑到模擬答辯狀」「跑到爭點整理表」「跑完全程」都不停在關卡 1，起訴狀不經確認就往下跑，紀錄標「未經律師確認」；只適合事先跑好示範案。" }),
      h("div", { class: "controls" }, runBtn("full", "complaint", true, "只產起訴狀(停在關卡 1)"),
        runBtn("full", "answer", false, "跑到模擬答辯狀"),
        runBtn("full", "issue_sheet", false, "跑到爭點整理表"),
        runBtn("full", null, false, "跑完全程(關卡 1 自動通過)")));
    return out;
  }
  // 書狀由使用者選(控制花費)：起訴狀、答辯狀或兩份。沒有預選，選了才能開始
  var DOC_CHOICES = [
    { key: "plaintiff", label: "只產起訴狀(原告)", docs: ["plaintiff"] },
    { key: "defendant", label: "只產答辯狀(被告)", docs: ["defendant"] },
    { key: "both", label: "兩份都產", docs: ["plaintiff", "defendant"] },
  ];
  function docsText(documents) {
    return (documents || []).map(function (s) { return DOCUMENT[s].short + "(" + SIDE[s].label + ")"; }).join("、");
  }
  function chosenDocs(d) {
    var key = state.docChoice[d.case.case_id];
    var c = DOC_CHOICES.filter(function (x) { return x.key === key; })[0];
    return c ? c.docs : null;
  }
  function documentChooser(d) {
    var id = d.case.case_id, cur = state.docChoice[id];
    return h("div", { class: "doc-chooser" },
      h("p", { class: "detail-note", text: "要產生哪一份書狀？每多一份就多一份撰狀與查證的花費；沒選的那份之後可在「訴狀骨架」分頁單獨補產。" }),
      h("div", { class: "seg", role: "group", "aria-label": "要產生的書狀" }, DOC_CHOICES.map(function (c) {
        return h("button", { type: "button", "aria-pressed": String(cur === c.key), disabled: state.liveBusy[id] ? true : null,
          onclick: function () { state.docChoice[id] = c.key; renderPanel(); } }, c.label);
      })),
      cur ? null : h("p", { class: "detail-note", text: "請先選擇要產生的書狀。" }));
  }
  // 只補產某一方的書狀(legal-debate Step 9C):已有該方 Stage 3 的案件，不重跑攻防
  function pleadingRunCard(d, side, has) {
    if (d.case.source !== "database" || d.case.protocol === "v2") return null;  // 補產(Step 9C)只有舊流程
    var doc = DOCUMENT[side];
    var hl = liveInfo(), runs = (d.live_runs || []).filter(function (r) {
      return r.kind === "pleadings" && (r.documents || []).indexOf(side) >= 0;
    });
    var latest = runs[runs.length - 1], body = [];
    if (latest) body.push(runView(latest, d));
    if (!has && (!latest || latest.status !== "running")) {
      var ready = d.arguments.some(function (a) { return a.side === side && a.stage === 3; });
      if (!ready) body.push(h("p", { class: "detail-note", text: "此案件還沒有" + SIDE[side].label + " Stage 3，不能只產" + doc.short + "；須先跑完攻防。" }));
      else if (!hl.enabled) body.push(banner("warn", "!", "即時執行停用：" + hl.reason));
      else if (hl.auth && hl.auth.checked && !hl.auth.logged_in) body.push(banner("bad", "✗", [h("strong", { text: "無法執行" }), "：" + hl.auth.detail + "。登入後重新整理本頁。"]));
      else if (hl.active_run) body.push(banner("warn", "⏳", "目前已有執行進行中(案件 " + hl.active_run.case_id + "，執行 #" + hl.active_run.id + ")，同一時間只能跑一件。"));
      else {
        if (hl.quota) body.push(knownQuota(hl.quota, hl.quota_warn_at));
        body.push(h("p", { class: "detail-note", text: "按下後，後端在這台電腦以你的 Claude 帳號啟動 Claude Code(無互動模式，模型 " + hl.model +
            ")，只跑 legal-debate 流程 Step 9C：讀取資料庫中" + SIDE[side].label + "方 Stage 3 與引用查證結果，草擬並落地" + doc.short + "骨架；不重跑攻防，既有的攻防、評估與其他書狀不會被更動。" +
            "只補產一份書狀的時間與花費尚未實測；每次上限 " + hl.budget_usd + " 美元(訂閱帳號會占用用量額度)。" }),
          h("button", { class: "btn primary", type: "button", disabled: state.liveBusy[d.case.case_id] ? true : null,
            onclick: function () { startRun(d, "pleadings", [side]); } }, h("span", { class: "ico", "aria-hidden": "true", text: "▶" }),
            state.liveBusy[d.case.case_id] ? "啟動中…" : "只產生" + doc.short + "(即時執行)"));
      }
    }
    if (!body.length) return null;
    return card("只產" + doc.short + "(Claude Code 即時執行)", body, latest ? chip(RUN_STATUS[latest.status].cls, runLabel(latest)) : null);
  }
  function prefillFrom(d) {
    var p = d.case.parties || {}, pl = p.plaintiff || {}, df = p.defendant || {};
    return { case_type: d.case.case_type || "", facts_summary: d.case.facts_summary || "", claims: d.case.claims || "",
      claim_amount: d.case.claim_amount == null ? "" : String(d.case.claim_amount),
      evidence: (d.case.evidence || []).map(function (e) { return { type: e.type || "other_document", date: e.date || "", description: e.description, proves: e.proves || "" }; }),
      responses: (d.case.opponent_known_responses || []).map(function (r) { return { source: r.source || "", date: r.date || "", text: r.text }; }),
      known_gaps: (d.case.known_gaps || []).join("\n"),
      p_name: pl.name || "", p_ban: pl.ban || "", d_name: df.name || "", d_ban: df.ban || "" };
  }

  // ───────────── 右側資訊欄 ─────────────
  function renderDetail() {
    var box = document.getElementById("detail");
    box.replaceChildren();
    var d = state.detail;
    if (state.creating) {
      box.append(h("div", { class: "detail-section" }, h("div", { class: "detail-section-title", text: "建立案件須知" }),
        h("p", { class: "detail-note", text: "事實經過只寫你實際掌握的內容；系統與 AI 都不會替你補寫案情。建立後會顯示程序類型、調解與時效提示，只是提示，不阻擋後續流程。" }),
        h("p", { class: "detail-note", text: "統一編號選填。填了會在建立後立即查核經濟部商工登記，查核結果轉成起訴審查補正事項，在 Stage 1 之前交給雙方。自然人或沒有統編的一方不查。" }),
        h("p", { class: "detail-note", text: "建立後可在案件總覽按「即時執行」，由本機 Claude Code 跑完整攻防。" })));
      return;
    }
    if (!d) return;
    var mark = { done: "✓", partial: "◐", ready: "▶", pending: "·" };
    box.append(
      // v2 總覽已有進度軌，右側不再重複；其他分頁留著當定位用
      isV2(d) && state.tab === "overview" ? document.createComment("") : h("div", { class: "detail-section" }, h("div", { class: "detail-section-title", text: "流程進度" }),
        h("ul", { class: "steps" }, d.progress.map(function (s) {
          return h("li", { class: "step " + s.state }, h("span", { class: "step-dot", "aria-hidden": "true", text: mark[s.state] }),
            h("span", { class: "step-label", text: s.label }), h("span", { class: "step-detail", text: s.detail }));
        }))),
      h("div", { class: "detail-section" }, h("div", { class: "detail-section-title", text: "案件摘要" }),
        meta("案件 ID", d.case.case_id), meta("案由", d.case.case_type || "—"),
        meta("落地時間", fmtTime(d.case.created_at)),
        meta("引用查證", d.stats.citations ? d.stats.citations_published + "/" + d.stats.citations + " 已查證通過" : "—"),
        h("p", { class: "detail-note", text: partySummary(d) })),
      h("p", { class: "detail-note detail-disclaimer", text: DISCLAIMER }),
      techDetails(d));
  }
  var DISCLAIMER = "研究原型，非法律意見，書狀須由執業律師審核。";
  // 技術細節：舊流程放右側欄；新流程(沒有右側欄)放在總覽的「完整案件輸入與技術細節」裡
  function techDetails(d) {
    var hl = state.health;
    return h("details", { class: "detail-section detail-tech" }, h("summary", { class: "detail-section-title", text: "技術細節(資料來源、即時執行、限制)" }),
        h("p", { class: "detail-note", text: "案件與論證：本機資料庫。" +
          (hl && hl.database.seeded_from_fixture ? "本次啟動時資料庫為空，已自動匯入示範案例存檔。" : "") }),
        hl ? h("p", { class: "detail-note", text: "判決預先內容 " + hl.corpus.judgments + " 份；檢索快取：判決 " +
          (hl.retrieval_cache ? hl.retrieval_cache.judgments : 0) + " 份、條文 " + (hl.retrieval_cache ? hl.retrieval_cache.statutes : 0) + " 條。" }) : null,
        h("p", { class: "detail-note", text: "查證權威來源：法規＝法務部全國法規資料庫(7 天內快取)；判決＝快取與預先內容 → 司法院裁判書查詢系統。" }),
        meta("論證／訊問", d.stats.arguments + " 筆／" + d.stats.questions + " 則"),
        d.live_runs && d.live_runs.length ? d.live_runs.map(function (r) {
          return meta("執行 #" + r.id + (r.kind === "pleadings" ? "(只補產" + docsText(r.documents) + ")" : ""), runLabel(r) + (r.cost_usd != null ? "・約 " + r.cost_usd.toFixed(2) + " 美元" : "") +
            (r.tokens ? "・" + fmtTokens(tokenTotal(r.tokens)) + " token" : "") +
            ((r.safety_stops || []).length && !stoppedByClassifier(r) ? "・安全分類器中止 " + r.safety_stops.length + " 次" : "") +
            (r.kind === "pleadings" ? "" : "・公開論證疑似含自我檢討:" + runReviewWarningCount(r, d) + " 則"));
        }) : null,
        h("p", { class: "detail-note", text: "標示「⚡ 本次即時生成」者由本機 Claude Code 經 UI 執行產生；標示「⏺ 錄製紀錄」者是過去產生後落地的紀錄重播。引用查證僅確認條文／字號存在，未比對判決全文是否支持該論點。" }));
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
    if (state.creating) { add(panel, createPanel(state.creating)); return; }
    if (state.loading || !d) { panel.append(emptyState("載入中…")); return; }
    try {
      // v2 的起訴狀、答辯狀分頁共用訴狀畫面，各自固定一方
      if (isV2(d) && (state.tab === "complaint" || state.tab === "answer")) state.pleadingSide[d.case.case_id] = state.tab === "complaint" ? "plaintiff" : "defendant";
      var view = { overview: overviewPanel, parties: partiesPanel, debate: debatePanel, aggregate: aggregatePanel, verify: verifyPanel, verdict: verdictPanel, pleading: pleadingPanel,
        complaint: complaintTabPanel, answer: answerPanel, sheet: sheetPanel, rounds: roundsPanel, diagnosis: diagnosisPanel }[state.tab];
      add(panel, view(d));
      panel.append(stepNav());
      // 新流程沒有右側欄(見 renderAll)，免責聲明放在每頁底部
      if (isV2(d)) panel.append(h("p", { class: "detail-note panel-disclaimer", text: DISCLAIMER }));
    } catch (e) {
      panel.append(banner("bad", "✗", [h("strong", { text: "畫面繪製失敗" }), "：" + e.message]));
    }
    panel.scrollTop = top;
  }

  // 分頁間逐步前進:上一步/下一步(鍵盤 ← →)，順序照目前流程的分頁列
  function stepNav() {
    var tabs = tabsNow(), i = tabs.map(function (t) { return t.key; }).indexOf(state.tab);
    var go = function (to, label, cls) {
      return to ? h("button", { class: "btn " + cls, type: "button", onclick: function () { switchTab(to.key); } }, label + to.label) : h("span");
    };
    return h("nav", { class: "step-nav", "aria-label": "分頁前後步驟" },
      go(tabs[i - 1], "← 上一步:", ""), h("span", { class: "step-pos", text: (i + 1) + " / " + tabs.length }), go(tabs[i + 1], "下一步:", "primary"), null);
  }
  function stepBy(n) {
    var tabs = tabsNow(), i = tabs.map(function (t) { return t.key; }).indexOf(state.tab), to = tabs[i + n];
    if (to) switchTab(to.key);
  }
  // 專注模式:隱藏案件清單與右側詳情、放大字級，供投影或逐步示範;偏好存在 localStorage(讀寫失敗照常運作)
  var FOCUS_KEY = "legaldebate-focus";
  function setFocus(on, save) {
    document.body.classList.toggle("focus", !!on);
    var btn = document.getElementById("focus-btn");
    if (btn) { btn.setAttribute("aria-pressed", String(!!on)); btn.textContent = on ? "離開專注模式" : "專注模式"; }
    if (save) { try { localStorage.setItem(FOCUS_KEY, on ? "1" : "0"); } catch (e) { /* 不記憶 */ } }
  }
  function onKey(e) {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    var t = e.target, tag = t && t.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (t && t.isContentEditable)) return;
    if (state.creating || !state.detail) return;
    if (e.key === "ArrowRight") { stepBy(1); e.preventDefault(); }
    else if (e.key === "ArrowLeft") { stepBy(-1); e.preventDefault(); }
    else if (e.key === "f" || e.key === "F") { setFocus(!document.body.classList.contains("focus"), true); }
  }

  function renderAll() { renderCaseList(); renderTopbar(); renderTabs(); renderDetail(); renderPanel(); }

  function setHash() { try { history.replaceState(null, "", "#/" + encodeURIComponent(state.caseId || "") + "/" + state.tab); } catch (e) { /* file:// 等環境略過 */ } }

  function switchTab(key) { state.tab = normalizeTab(key); setHash(); renderTabs(); renderPanel(); document.getElementById("panel").scrollTop = 0; }

  async function selectCase(caseId, tab) {
    state.caseId = caseId; state.tab = normalizeTab(tab || state.tab); state.loading = true; state.error = null; state.detail = null;
    state.creating = null;
    setHash(); renderAll();
    try {
      var d = await api("/api/cases/" + encodeURIComponent(caseId));
      if (state.caseId !== caseId) return;
      state.detail = d;
      state.tab = normalizeTab(state.tab);
    } catch (e) { state.error = e.message; }
    state.loading = false;
    setHash();
    renderAll();
  }

  function exportCase() {
    var d = state.detail;
    if (!d) return;
    var run = state.runs[d.case.case_id] || {};
    var kind = d.provenance.kind;
    var payload = {
      exported_at: new Date().toISOString(),
      note: (kind === "live_generated" ? "論證由 UI 觸發本機 Claude Code 即時產生後落地資料庫(見 live_runs)" :
        kind === "mixed" ? "論證部分由 UI 即時執行產生、部分為錄製紀錄(逐筆見 origin)" :
          "資料庫已落地的錄製紀錄(論證由 Claude Code subagent 產生，非即時生成)") + "，以及本次工作階段的機械執行結果。",
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
      tab: m && m[2] ? m[2] : "overview" };  // 合不合法等案件載入後由 normalizeTab 判斷
  }

  // 瀏覽器上一頁/下一頁只改變網址片段(不會整頁重新載入)，需另外監聽並同步畫面。
  window.addEventListener("hashchange", function () {
    if (location.hash === "#/new") { if (!state.creating) openCreate(); return; }
    var h = parseHash();
    if (!h.caseId || h.caseId === state.caseId) { if (h.tab !== state.tab) switchTab(h.tab); return; }
    selectCase(h.caseId, h.tab);
  });

  async function init() {
    updateThemeBtn();
    document.getElementById("theme-toggle").addEventListener("click", function () { setTheme(currentTheme() === "light" ? "dark" : "light"); });
    document.getElementById("export-btn").addEventListener("click", exportCase);
    var focusOn = false;
    try { focusOn = localStorage.getItem(FOCUS_KEY) === "1"; } catch (e) { /* 預設關 */ }
    // demo 用：網址帶 ?demo=1 或 ?focus=1 直接進專注模式(不寫入記憶)
    if (/[?&](demo|focus)=1\b/.test(location.search)) focusOn = true;
    setFocus(focusOn, false);
    document.getElementById("focus-btn").addEventListener("click", function () { setFocus(!document.body.classList.contains("focus"), true); });
    document.addEventListener("keydown", onKey);
    document.getElementById("new-case-btn").addEventListener("click", function () { openCreate(); });
    renderTabs();
    try {
      state.health = await api("/api/health");
      state.cases = (await api("/api/cases")).cases;
    } catch (e) {
      state.error = "無法連線後端：" + e.message;
      renderAll();
      return;
    }
    renderSidebarNote();
    if (liveInfo().active_run) ensurePolling();
    if (location.hash === "#/new") { openCreate(); return; }
    var h = parseHash();
    var pick = state.cases.some(function (c) { return c.case_id === h.caseId; }) ? h.caseId : (state.cases[0] && state.cases[0].case_id);
    if (!pick) { openCreate(); return; }
    await selectCase(pick, h.tab);
  }

  init();
})();
