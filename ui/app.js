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
    { key: "parties", label: "當事人查核" },
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
    pleadingSel: {}, pleadingEdit: {}, pleadingBusy: {}, pleadingNotice: {},
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
          c.arguments ? chip("neutral", "論證 " + c.arguments) : null,
          c.last_run_status ? chip(RUN_STATUS[c.last_run_status].cls, c.last_run_status === "succeeded" ? "⚡ 即時生成" : RUN_STATUS[c.last_run_status].label)
            : c.created_via === "ui" ? chip("neutral", "UI 建立") : null)));
    });
  }

  function renderTopbar() {
    var d = state.detail;
    if (state.creating) {
      document.getElementById("topbar-id").textContent = "新案件";
      document.getElementById("topbar-title").textContent = "建立新案件";
      document.getElementById("topbar-sub").textContent = "輸入案件事實與雙方當事人，寫入本機資料庫";
      document.getElementById("export-btn").disabled = true;
      return;
    }
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
    if (state.creating) return;
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
    pieces.push(partySourceFooter(result));
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
    return card(SIDE[role].label + "查核", [
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
      p.busy ? banner("warn", "⏱", "查詢中…") : null,
      partyResultBlock(result, d)]);
  }
  function partiesPanel(d) {
    var checks = d.party_checks || {};
    return [panelHead("當事人查核", chip("ok", "⚡ 即時執行"),
      "以統一編號查詢經濟部商工登記，確認當事人名稱、法定代理人、公司狀態與管轄法院。本分頁為即時查詢，不呼叫 AI。"),
      banner("warn", "!", "查核結果僅反映商工登記公示資料，不代表該公司涉入本案；登記為查詢當下的狀態。"),
      h("div", { class: "party-grid" }, SIDES.map(function (side) { return partyCard(d, side); })),
      d.procedural_issues && d.procedural_issues.issues.length ? banner("rec", "→", [
        h("strong", { text: "這些警示已轉成 " + d.procedural_issues.issues.length + " 項起訴審查命補正事項" }),
        "：當事人能力與法定代理屬法院應依職權調查的事項，系統依固定規則把警示轉成命補正事項，在 Stage 1 之前交給雙方，並寫入爭點評估的機械錨點。 ",
        h("button", { class: "btn small", type: "button", onclick: function () { switchTab("debate"); }, text: "到攻防過程查看" })]) : null,
      SIDES.map(function (side) { var r = partyState(d.case.case_id, side).result || checks[side];
        return r && r.query_status !== "failed" && r.entity_type !== "not_found" && r.entity_type !== "branch" && r.address ? partyJurisdiction(r, side) : null; })];
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
        originChip(a.origin),
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
      h("div", { class: "judge-band-title" }, chip("judge", "法官"), "訊問 — 基於雙方 Stage 1，共 " + d.questions.length + " 則", provChip(d.questions)),
      d.questions.map(function (q) {
        return h("div", { class: "judge-q" },
          h("div", { class: "judge-q-head" }, sideChip(q.target_side, "問" + SIDE[q.target_side].label + "(第 " + q.seq + " 則)"),
            /^官方事實層/.test(q.based_on || "") ? chip("judge", "補正追問・依商工登記") : null,
            h("span", { class: "arg-time", text: "落地 " + fmtTime(q.created_at) })),
          h("div", { class: "judge-q-text prewrap", text: q.question_text }),
          h("div", { class: "judge-q-basis" }, h("b", { text: "訊問依據(based_on，須回溯至具體論點)：" }), q.based_on));
      }));
  }

  // ───────────── 官方事實層 → 起訴審查命補正事項 ─────────────
  // 事項本身由後端規則依最新商工查核產生(非錄製內容)；錄製的攻防有沒有回應，只看原告 Stage 1 的
  // 「程序補正(<id>)」標記與法官追問 based_on 的事項代號，不判斷補正內容是否足夠。
  function proceduralCoverageBanner(p) {
    var c = p.coverage;
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
          issue.cured_in_stage1 ? chip("ok", "✓ 原告 Stage 1 已回應補正") : chip("warn", "錄製的 Stage 1 未回應"),
        withCoverage && followed.length ? chip("judge", "法官第 " + followed.join("、") + " 則訊問追問") : null),
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
      h("p", { class: "detail-note", text: "實務上法院收狀後先審查當事人能力與法定代理權，有欠缺而可以補正者，審判長定期間命補正，逾期未補正以裁定駁回(民事訴訟法第249條第1項)；但法院須依職權調查實際代表權，不得僅憑登記認定(參最高法院115年度台抗字第105號裁定)。系統依「當事人查核」分頁的最新結果，以固定規則產生下列事項，在 Stage 1 之前交給雙方；原告在 Stage 1 補正，法官只就補正不足者追問。本區文字由規則即時產生，不是錄製的 AI 內容。" }),
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
    var pi = r.procedural_issues;
    if (pi) out.push(card("程序事項(官方事實層)", [
      h("p", { class: "detail-note", text: "依案件最新的商工查核結果，以固定規則轉換，與弱點、立場位移一起寫入評估錨點；法官評估須先處理 ✗ 等級的程序事項。" }),
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
    var head = panelHead("法官爭點強弱評估", v ? originChip(v.origin) : null,
      "評估的用途是協助律師決定訴狀火力與蒐證優先順序，不是預測法院會怎麼判。以下為法官角色落地的原文。");
    if (!v) return [head, emptyState("此案件尚未落地爭點強弱評估。")];
    var risk = v.risk_map || {};
    var list = function (items) { return h("ul", { class: "risk-list" }, (items || []).map(function (t) { return h("li", { text: t }); })); };
    var out = [head,
      card("評估結論", paragraphs(delabelJargon(v.verdict_main_text)), chip("neutral", "落地 " + fmtTime(v.created_at))),
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
      c === "included" ? banner("ok", "✓", "本評估落地時，機械錨點已含下列程序事項，法官角色須先處理程序再談實體。")
        : c === "not_included" ? banner("warn", "!", [h("strong", { text: "本評估錄製於程序事項串接之前" }),
          "：落地時的機械錨點沒有程序事項，上方評估文字未處理下列風險。下列內容由規則依最新商工查核即時產生，不是法官角色的評估。"]) : null,
      p.issues.map(function (i) { return procIssueItem(i, d, false); })]);
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
  // 【…】不在此清理：錄製評估用它標爭點標題，即時生成的訴狀用它寫舉證缺口與待調閱證據(含引用)，都是實質內容。
  var TEXT_JARGON = [
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
      .replace(/【(?:骨架版聲明|本稿產出說明)[^】]*】/g, "")  // 附註區塊的標頭，畫面另有標題
      .replace(/^-{2,}\s*$/gm, "")
      .split("\n").map(function (l) { return l.replace(/^[-•]\s*/, "").trim(); })
      .filter(function (l) { return l && l !== "。" && !/^骨架版[,，]?.*潤飾[。.]?$/.test(l); })
      .join("\n\n").replace(/\n{3,}/g, "\n\n").trim();
  }

  // 版本：系統產生版(流程經查證閘門落地，原稿不改寫)與律師編輯版(UI 另存的新版本)。
  // 預設顯示最新的系統產生版，錄製案件的重播畫面因此不受律師編輯影響。
  function selectedVersion(d) {
    var vs = d.pleading_versions || [];
    var sel = vs.filter(function (v) { return v.id === state.pleadingSel[d.case.case_id]; })[0];
    if (sel) return sel;
    var sys = vs.filter(function (v) { return v.source === "system"; });
    return sys[sys.length - 1] || vs[vs.length - 1];
  }
  function versionChip(v) {
    return v.source === "lawyer_edit" ? chip("judge", "✎ 律師編輯版", { title: "律師在 UI 編輯後另存的版本" }) : originChip(v.origin);
  }
  function splitDraftNote(text) {
    var noteIdx = text.search(/-{2,}\s*\n\s*(?=【)|【(?:骨架版聲明|本稿產出說明)/);
    return noteIdx >= 0 ? { body: text.slice(0, noteIdx), note: cleanDraftNote(text.slice(noteIdx)) } : { body: text, note: null };
  }
  function editableText(v) {
    return v.source === "system" ? delabelJargon(splitDraftNote(v.draft_text).body).trim() : v.draft_text;
  }
  function pleadingDoc(v) {
    var system = v.source === "system";
    var lines = (system ? delabelJargon(splitDraftNote(v.draft_text).body) : v.draft_text).replace(/^\s+|\s+$/g, "").split("\n");
    // 標題是第一個不是整行【…】的行；之前的整行【…】(如即時生成稿開頭的骨架版說明)照原文列在標題上方
    var titleIdx = 0;
    while (titleIdx < lines.length - 1 && (!lines[titleIdx].trim() || /^【[^】]*】$/.test(lines[titleIdx].trim()))) titleIdx++;
    return h("div", { class: "pleading-doc" },
      lines.map(function (ln, i) {
        if (i < titleIdx) return ln.trim() ? h("div", { class: "pl-line", text: ln }) : null;
        if (i === titleIdx) return [
          h("div", { class: "pl-title", text: ln.replace(/[（(][\s\S]*[）)]\s*$/, "").trim() || "民事起訴狀" }),
          h("div", { class: "pl-subtitle", text: system ? "骨架版初稿．尚未經法律用語潤飾．須經律師審核後使用" : "律師編輯版．須經律師審核後使用" }),
        ];
        var headLine = /^(訴之聲明|事實及理由|證物名稱及件數|為.*事：)/.test(ln);
        if (!ln.trim()) return h("div", { class: "pl-gap", "aria-hidden": "true" });
        return h("div", { class: "pl-line" + (headLine ? " pl-head" : ""), text: ln });
      }));
  }
  function versionBanner(v, d) {
    if (v.source === "lawyer_edit") {
      return banner("rec", "✎", [h("strong", { text: "律師編輯版" }), "：於 " + fmtTime(v.generated_at) + " 存檔，基於 #" + v.parent_id +
        "。原稿 #" + v.parent_id + " 保留不動；本版的引用在存檔時逐條查證，結果列於下方。"]);
    }
    var live = v.origin && v.origin.kind === "live";
    var sysCount = (d.pleading_versions || []).filter(function (x) { return x.source === "system"; }).length;
    return banner(live ? "ok" : "rec", live ? "⚡" : "⏺", [h("strong", { text: live ? "系統產生版・本次即時生成" : "系統產生版・錄製紀錄" }),
      "：草稿產生於 " + fmtTime(v.generated_at) + (live ? "(UI 執行 #" + v.origin.run_id + ")" : "") +
      (sysCount > 1 ? "；此案件共有 " + sysCount + " 份系統草稿" : "") + "。"]);
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
    return card("編輯為新版本(基於 #" + ed.parentId + ")", [
      h("p", { class: "detail-note", text: "存檔時原稿保留不動，另存為「律師編輯版」新版本。新增或改動的引用會當場重新查證(判例先比對本地語料庫再查司法院；法條查全國法規資料庫)；未通過者照實標示，該版本不能匯出。" }),
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

  function pleadingPanel(d) {
    var vs = d.pleading_versions || [], id = d.case.case_id;
    var lede = "骨架版：僅套用司法院官方起訴狀結構，直接帶入系統攻防結果原文，尚未經法律用語潤飾。可編輯為律師版本(原稿保留)，須由執業律師審核修訂、補正當事人資訊與證物清單後方可使用，不得逕行送出。";
    if (!vs.length) return [panelHead("訴狀骨架初稿", null, lede), partyPleadingCard(d), emptyState("此案件尚未落地訴狀草稿。")];
    var v = selectedVersion(d), ed = state.pleadingEdit[id], busy = state.pleadingBusy[id];
    var exportUrl = API_BASE + "/api/cases/" + encodeURIComponent(id) + "/pleadings/" + v.id + "/export";
    var out = [
      panelHead("訴狀骨架初稿", versionChip(v), lede),
      h("div", { class: "version-bar", role: "group", "aria-label": "訴狀版本" }, vs.map(function (x) {
        return h("button", { class: "btn small", type: "button", "aria-pressed": String(x.id === v.id), disabled: ed ? true : null,
          onclick: function () { state.pleadingSel[id] = x.id; renderPanel(); } },
          x.label + (x.source === "system" ? (x.origin.kind === "live" ? "・⚡即時生成" : "・⏺錄製") : "・基於 #" + x.parent_id) +
          (x.exportable ? "・✓" : "・✗ 未放行"));
      })),
      state.pleadingNotice[id] || null,
    ];
    if (ed) { out.push(pleadingEditor(d, ed)); return out; }
    var note = v.source === "system" ? splitDraftNote(v.draft_text).note : null;
    out.push(versionBanner(v, d),
      h("div", { class: "controls" },
        h("button", { class: "btn", type: "button", disabled: busy ? true : null, text: "✎ 編輯為新版本",
          onclick: function () { delete state.pleadingNotice[id]; state.pleadingEdit[id] = { parentId: v.id, text: editableText(v), busy: false, error: null }; renderPanel(); } }),
        v.blocked_count ? h("button", { class: "btn", type: "button", disabled: busy ? true : null, onclick: function () { reverifyVersion(d, v); },
          text: busy ? "查證中…" : "重新查證未通過的引用(" + v.blocked_count + " 條)" }) : null,
        v.exportable ? h("a", { class: "btn primary", href: exportUrl, download: "" }, "匯出 .txt")
          : h("button", { class: "btn primary", type: "button", disabled: true, text: "匯出 .txt" }),
        v.exportable ? null : h("span", { class: "detail-note", text: "有 " + v.blocked_count + " 條引用未通過查證，未放行，不能匯出。" })),
      partyPleadingCard(d),
      pleadingDoc(v),
      note ? card("系統補充說明(供律師參考，非訴狀正文)", paragraphs(note)) : null);
    var okN = v.citation_check.length - v.blocked_count;
    out.push(card("此版本的引用查證狀態", [
      h("div", { style: "margin-bottom:10px" }, chip(v.blocked_count || !v.citation_check.length ? (v.blocked_count ? "bad" : "neutral") : "ok",
        (v.blocked_count ? "✗ " : "✓ ") + okN + " / " + v.citation_check.length + " 條已查證通過")),
      v.citation_check.map(function (c) { return pleadingCiteRow(c, v.source === "lawyer_edit"); }),
      h("p", { class: "detail-note", text: v.source === "lawyer_edit"
        ? "存檔時由版本文字重新找出引用並逐條查證；重新查證只處理未通過者。"
        : "由草稿文字重新找出其中的法條與裁判字號，對照目前的查證紀錄。" })]));
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
    state.creating = Object.assign({ case_id: "", case_type: "", facts_summary: "", claims: "",
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
  function createPanel(f) {
    return [
      panelHead("建立新案件", null, "輸入的文字原樣寫入本機資料庫，作為三角色攻防的唯一案件輸入。系統不會補寫案情；正式使用時請以律師掌握的完整卷證為準。"),
      h("form", { class: "card form-card", onsubmit: function (e) { e.preventDefault(); submitCreate(f); } },
        h("div", { class: "form-grid" },
          formField(f, "case_type", "案由", { max: 60, placeholder: "例：買賣價金、侵權行為損害賠償" }),
          formField(f, "case_id", "案件 ID", { optional: true, max: 64, placeholder: "留空自動產生(ui-日期-序號)",
            hint: "只能用英數字、點、底線、連字號" }),
          formField(f, "facts_summary", "案件事實", { multiline: true, rows: 9, max: 20000, wide: true,
            hint: "時間、金額、契約與往來經過等，以你實際掌握者為限" }),
          formField(f, "claims", "請求／訴之聲明", { multiline: true, rows: 3, max: 5000, wide: true }),
          formField(f, "p_name", "原告名稱", { max: 100 }),
          formField(f, "p_ban", "原告統一編號", { optional: true, max: 12, inputmode: "numeric", placeholder: "8 位數字" }),
          formField(f, "d_name", "被告名稱", { max: 100 }),
          formField(f, "d_ban", "被告統一編號", { optional: true, max: 12, inputmode: "numeric", placeholder: "8 位數字" })),
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
    f.busy = true; f.error = null; f.step = "寫入資料庫…"; renderPanel();
    var created;
    try {
      created = await api("/api/cases", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
        case_id: f.case_id.trim() || null, case_type: f.case_type, facts_summary: f.facts_summary, claims: f.claims,
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
          ? { cls: "bad", icon: "✗", text: SIDE[role].label + "商工查核未完成(" + ((r.errors[0] || {}).error || "連線失敗") + ")；可到「當事人查核」分頁重試。" }
          : { cls: (r.warnings || []).length ? "warn" : "ok", icon: (r.warnings || []).length ? "!" : "✓",
            text: SIDE[role].label + "商工查核：" + (r.name || "已查詢") + (r.via === "recorded" ? "(本次即時查詢失敗，顯示錄製的查詢結果)" : "") +
              ((r.warnings || []).length ? "，警示 " + r.warnings.length + " 項，已轉成起訴審查事項" : "，無規則警示") });
      } catch (e) {
        notices.push({ cls: "bad", icon: "✗", text: SIDE[role].label + "商工查核失敗：" + e.message + "；可到「當事人查核」分頁重試。" });
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
  async function startRun(d) {
    var hl = liveInfo(), id = d.case.case_id;
    var ok = window.confirm("即將在這台電腦以你的 Claude 帳號啟動 Claude Code(模型 " + hl.model + ")，跑完整攻防流程。\n\n" +
      "・實測一件約 11–15 分鐘、估算約 2.5–3.3 美元(訂閱帳號會占用 Claude 用量額度，與其他 Claude Code 使用共用)；每次上限 " + hl.budget_usd + " 美元，超過即中止。\n" +
      "・執行中可取消；已落地的階段會保留，同一案件之後不能重跑。\n\n確定開始？");
    if (!ok) return;
    state.liveBusy[id] = true; delete state.caseNotices[id]; renderPanel();
    try {
      var r = await api("/api/cases/" + encodeURIComponent(id) + "/runs", { method: "POST" });
      var lr = liveLog(r.run.id);
      lr.events = r.events; lr.since = r.event_count; lr.loaded = true;
      state.health = await api("/api/health");
      ensurePolling();
      await refreshCases();
      await reloadDetailQuietly();
    } catch (e) {
      state.caseNotices[id] = [{ cls: "bad", icon: "✗", text: "無法開始即時執行：" + e.message }];
    }
    state.liveBusy[id] = false;
    if (state.caseId === id) renderPanel();
  }
  async function cancelRun(run) {
    if (!window.confirm("確定取消執行 #" + run.id + "？已落地的階段會保留，此案件之後不能重跑。")) return;
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
  function runView(run, d) {
    var st = RUN_STATUS[run.status], lr = liveLog(run.id);
    if (!lr.loaded && run.status !== "running") loadRunLog(run.id);
    var events = lr.events;
    var row = function (e) {
      return h("div", { class: "run-event " + e.kind }, h("span", { class: "run-mark", "aria-hidden": "true", text: EVENT_MARK[e.kind] || "·" }),
        e.subagent ? chip("neutral", "subagent") : null, h("span", { class: "run-text", text: e.text }));
    };
    return h("div", { class: "run-view" },
      h("div", { class: "run-head" }, chip(st.cls, runLabel(run)), h("strong", { text: "執行 #" + run.id }),
        h("span", { class: "detail-note", text: "開始 " + fmtTime(run.started_at) + "・經過 " + elapsed(run) + "・模型 " + run.model +
          (run.cost_usd != null ? "・估算花費 " + run.cost_usd.toFixed(2) + " 美元" : "") + (run.exit_code != null ? "・結束碼 " + run.exit_code : "") }),
        run.status === "running" ? h("button", { class: "btn small", type: "button", disabled: state.liveBusy[run.case_id] ? true : null,
          onclick: function () { cancelRun(run); }, text: "取消執行" }) : null),
      run.status === "running" ? h("div", { class: "chip-row" }, d.progress.map(function (s) {
        return chip(s.state === "done" ? "ok" : s.state === "partial" ? "warn" : "neutral", (s.state === "done" ? "✓ " : s.state === "partial" ? "◐ " : "· ") + s.label);
      })) : null,
      stoppedByClassifier(run) ? safetyStopBanner(run) : null,
      run.error ? banner(run.status === "cancelled" ? "warn" : "bad", run.status === "cancelled" ? "!" : "✗", run.error) : null,
      stoppedByClassifier(run) ? null : safetyStopBanner(run),
      run.quota ? h("p", { class: "detail-note", text: "訂閱額度(本次執行開始 → 結束)：" + quotaLine(run.quota) }) : null,
      lr.error ? banner("warn", "!", "讀取執行紀錄失敗：" + lr.error) : null,
      events.length ? h("div", { class: "run-log", role: "log", "aria-label": "執行紀錄" }, events.slice(-30).map(row)) :
        h("p", { class: "detail-note", text: run.status === "running" ? "等待 Claude Code 輸出…" : "沒有可顯示的執行紀錄。" }),
      events.length > 30 ? fold("展開全部執行紀錄(" + events.length + " 則)", events.map(row)) : null,
      run.log_path ? h("p", { class: "detail-note", text: "完整原始輸出(stream-json)：" + run.log_path }) : null);
  }
  function liveRunCard(d) {
    if (d.case.source !== "database") return null;
    var hl = liveInfo(), runs = d.live_runs || [], latest = runs[runs.length - 1];
    var hasRecords = d.stats.arguments || d.stats.questions || d.verdict || d.pleading;
    if (!latest && hasRecords) return null;  // 錄製案件：不提供重跑
    var body = [];
    if (latest) body.push(runView(latest, d));
    if (!latest || latest.status !== "running") {
      if (hasRecords) {
        body.push(h("p", { class: "detail-note", text: "此案件已有落地紀錄，不能重跑(落地紀錄不可覆寫)。要用同樣內容再模擬一次，請另建案件。" }),
          h("button", { class: "btn small", type: "button", text: "以此案件內容建立新案件", onclick: function () { openCreate(prefillFrom(d)); } }));
      } else if (!hl.enabled) {
        body.push(banner("warn", "!", "即時執行停用：" + hl.reason));
      } else if (hl.auth && hl.auth.checked && !hl.auth.logged_in) {
        body.push(banner("bad", "✗", [h("strong", { text: "無法執行" }), "：" + hl.auth.detail + "。登入後重新整理本頁。"]));
      } else if (hl.active_run) {
        body.push(banner("warn", "⏳", "目前已有執行進行中(案件 " + hl.active_run.case_id + "，執行 #" + hl.active_run.id + ")，同一時間只能跑一件。"));
      } else {
        if (hl.quota) body.push(knownQuota(hl.quota, hl.quota_warn_at));
        body.push(h("p", { class: "detail-note", text: "按下後，後端在這台電腦以你的 Claude 帳號啟動 Claude Code(無互動模式，模型 " + hl.model +
            ")，依 legal-debate 流程跑完：起訴審查 → Stage 1 → 法官訊問 → Stage 2 → Stage 3 → 機械彙整 → 爭點評估 → 引用查證 → 訴狀骨架。" +
            "只允許它執行 python main.py 指令、讀取專案檔案、派出 subagent。實測一件約 11–15 分鐘、估算約 2.5–3.3 美元(訂閱帳號會占用用量額度)，每次上限 " + hl.budget_usd + " 美元。" }),
          h("button", { class: "btn primary", type: "button", disabled: state.liveBusy[d.case.case_id] ? true : null,
            onclick: function () { startRun(d); } }, h("span", { class: "ico", "aria-hidden": "true", text: "▶" }),
            state.liveBusy[d.case.case_id] ? "啟動中…" : "開始即時執行"));
      }
    }
    return card("即時執行(Claude Code)", body, latest ? chip(RUN_STATUS[latest.status].cls, runLabel(latest)) : null);
  }
  function prefillFrom(d) {
    var p = d.case.parties || {}, pl = p.plaintiff || {}, df = p.defendant || {};
    return { case_type: d.case.case_type || "", facts_summary: d.case.facts_summary || "", claims: d.case.claims || "",
      p_name: pl.name || "", p_ban: pl.ban || "", d_name: df.name || "", d_ban: df.ban || "" };
  }

  // ───────────── 右側資訊欄 ─────────────
  function renderDetail() {
    var box = document.getElementById("detail");
    box.replaceChildren();
    var d = state.detail;
    if (state.creating) {
      box.append(h("div", { class: "detail-section" }, h("div", { class: "detail-section-title", text: "建立案件須知" }),
        h("p", { class: "detail-note", text: "案件事實只寫你實際掌握的內容；系統與 AI 都不會替你補寫案情。" }),
        h("p", { class: "detail-note", text: "統一編號選填。填了會在建立後立即查核經濟部商工登記，查核結果轉成起訴審查補正事項，在 Stage 1 之前交給雙方。自然人或沒有統編的一方不查。" }),
        h("p", { class: "detail-note", text: "建立後可在案件總覽按「即時執行」，由本機 Claude Code 跑完整攻防。" })));
      return;
    }
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
        meta("引用查證", d.stats.citations ? d.stats.citations_published + "/" + d.stats.citations + " 已查證通過" : "—"),
        h("p", { class: "detail-note", text: partySummary(d) })),
      h("div", { class: "detail-section" }, h("div", { class: "detail-section-title", text: "資料來源" }),
        h("p", { class: "detail-note", text: "案件與論證：本機資料庫。" +
          (hl && hl.database.seeded_from_fixture ? "本次啟動時資料庫為空，已自動匯入示範案例存檔。" : "") }),
        hl ? h("p", { class: "detail-note", text: "本地語料庫：最高法院判決 " + hl.corpus.judgments + " 份、法典 " + hl.corpus.statutes + " 部。" }) : null,
        h("p", { class: "detail-note", text: "查證權威來源：法規＝法務部全國法規資料庫；判決＝本地語料庫 → 司法院裁判書查詢系統。" })),
      d.live_runs && d.live_runs.length ? h("div", { class: "detail-section" }, h("div", { class: "detail-section-title", text: "即時執行" }),
        d.live_runs.map(function (r) {
          return meta("執行 #" + r.id, runLabel(r) + (r.cost_usd != null ? "・約 " + r.cost_usd.toFixed(2) + " 美元" : "") +
            ((r.safety_stops || []).length && !stoppedByClassifier(r) ? "・安全分類器中止 " + r.safety_stops.length + " 次" : ""));
        })) : null,
      h("div", { class: "detail-section" }, h("div", { class: "detail-section-title", text: "限制" }),
        h("p", { class: "detail-note", text: "標示「⚡ 本次即時生成」者由本機 Claude Code 經 UI 執行產生；標示「⏺ 錄製紀錄」者是過去產生後落地的紀錄重播。引用查證僅確認條文／字號存在，未比對判決全文是否支持該論點。研究原型，非法律意見，訴狀須由律師審核。" })));
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
      var view = { overview: overviewPanel, parties: partiesPanel, debate: debatePanel, aggregate: aggregatePanel, verify: verifyPanel, verdict: verdictPanel, pleading: pleadingPanel }[state.tab];
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
    state.creating = null;
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
      tab: m && TABS.some(function (t) { return t.key === m[2]; }) ? m[2] : "overview" };
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
