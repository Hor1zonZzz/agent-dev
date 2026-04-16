(function () {
  "use strict";

  // ---------------- Glossary dialog ----------------

  function openGlossary() {
    const g = document.getElementById("glossary");
    if (!g) return;
    g.hidden = false;
    document.body.style.overflow = "hidden";
    const closeBtn = g.querySelector("[data-glossary-close]");
    if (closeBtn) closeBtn.focus();
  }

  function closeGlossary() {
    const g = document.getElementById("glossary");
    if (!g) return;
    g.hidden = true;
    document.body.style.overflow = "";
  }

  function initGlossary() {
    const g = document.getElementById("glossary");
    const toggle = document.getElementById("glossary-toggle");
    if (!g || !toggle) return;

    toggle.addEventListener("click", openGlossary);
    g.querySelectorAll("[data-glossary-close]").forEach((el) =>
      el.addEventListener("click", closeGlossary)
    );

    document.querySelectorAll(".inline-glossary-trigger").forEach((el) =>
      el.addEventListener("click", (evt) => {
        evt.preventDefault();
        openGlossary();
      })
    );

    document.addEventListener("keydown", (evt) => {
      const tag = (evt.target && evt.target.tagName) || "";
      const isInputLike = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
      if (evt.key === "Escape") {
        if (!g.hidden) closeGlossary();
      } else if ((evt.key === "?" || (evt.key === "/" && evt.shiftKey)) && !isInputLike) {
        evt.preventDefault();
        if (g.hidden) openGlossary();
        else closeGlossary();
      }
    });
  }

  // ---------------- Theme toggle ----------------

  function initThemeToggle() {
    const btn = document.getElementById("theme-toggle");
    if (!btn) return;
    btn.addEventListener("click", () => {
      const root = document.documentElement;
      const next = root.dataset.theme === "dark" ? "light" : "dark";
      if (next === "dark") {
        root.dataset.theme = "dark";
      } else {
        delete root.dataset.theme;
      }
      window.localStorage.setItem("trace-theme", next);
    });
  }

  // ---------------- Copy buttons ----------------

  function initCopyButtons(root) {
    (root || document).querySelectorAll(".copy-btn").forEach((btn) => {
      if (btn.dataset.copyBound) return;
      btn.dataset.copyBound = "1";
      btn.addEventListener("click", async (evt) => {
        evt.preventDefault();
        evt.stopPropagation();
        const target = btn.dataset.copyTarget;
        let text = "";
        if (target === "next-pre") {
          const details = btn.closest("details");
          const pre = details && details.querySelector("pre");
          text = pre ? pre.textContent : "";
        } else if (target && target.startsWith("#")) {
          const el = document.querySelector(target);
          text = el ? el.textContent : "";
        }
        if (!text) return;
        try {
          await navigator.clipboard.writeText(text);
          btn.classList.add("copied");
          const original = btn.textContent;
          btn.textContent = "copied";
          window.setTimeout(() => {
            btn.textContent = original;
            btn.classList.remove("copied");
          }, 1200);
        } catch (err) {
          /* ignore */
        }
      });
    });
  }

  // ---------------- Timeline filters ----------------

  function initTimelineFilters() {
    const panel = document.getElementById("timeline-filters");
    const timeline = document.getElementById("timeline");
    if (!panel || !timeline) return;

    const state = { lane: "__all__", status: "__all__", query: "" };

    function apply() {
      const items = timeline.querySelectorAll(".timeline-item");
      items.forEach((item) => {
        const laneOk = state.lane === "__all__" || item.dataset.lane === state.lane;
        const statusOk = state.status === "__all__" || item.dataset.status === state.status;
        const blob = item.dataset.searchBlob || "";
        const queryOk = !state.query || blob.includes(state.query);
        item.style.display = laneOk && statusOk && queryOk ? "" : "none";
      });

      // hide turn dividers whose items are all filtered out
      const dividers = timeline.querySelectorAll(".turn-divider");
      dividers.forEach((div) => {
        let next = div.nextElementSibling;
        let visibleBefore = false;
        while (next && !next.classList.contains("turn-divider")) {
          if (next.classList.contains("timeline-item") && next.style.display !== "none") {
            visibleBefore = true;
            break;
          }
          next = next.nextElementSibling;
        }
        div.style.display = visibleBefore ? "" : "none";
      });
    }

    panel.querySelectorAll("[data-filter-lane]").forEach((btn) => {
      btn.addEventListener("click", () => {
        panel.querySelectorAll("[data-filter-lane]").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        state.lane = btn.dataset.filterLane;
        apply();
      });
    });
    panel.querySelectorAll("[data-filter-status]").forEach((btn) => {
      btn.addEventListener("click", () => {
        panel.querySelectorAll("[data-filter-status]").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        state.status = btn.dataset.filterStatus;
        apply();
      });
    });
    const search = document.getElementById("timeline-search");
    if (search) {
      search.addEventListener("input", () => {
        state.query = search.value.trim().toLowerCase();
        apply();
      });
    }
  }

  // ---------------- Live indicator ----------------

  function setLive(state) {
    const el = document.getElementById("live-indicator");
    if (!el) return;
    el.dataset.state = state;
    const label = el.querySelector("[data-role=live-label]");
    if (label) label.textContent = state === "live" ? "live" : state;
  }

  // ---------------- Update banner ----------------

  function showUpdateBanner(text, onApply) {
    const banner = document.getElementById("update-banner");
    const label = document.getElementById("update-banner-text");
    const btn = document.getElementById("update-apply");
    if (!banner || !btn) return;
    if (label) label.textContent = text;
    banner.hidden = false;
    btn.onclick = () => {
      banner.hidden = true;
      onApply();
    };
  }

  function hideUpdateBanner() {
    const banner = document.getElementById("update-banner");
    if (banner) banner.hidden = true;
  }

  // ---------------- Runs list: delta refresh ----------------

  function updateRunCardInPlace(card, data) {
    if (data.status) {
      card.dataset.status = data.status;
      card.classList.remove("status-ok", "status-error", "status-info", "status-skipped");
      card.classList.add(`status-${data.status}`);
    }
    const countEl = card.querySelector("[data-role=event-count]");
    if (countEl && data.event_count !== undefined) countEl.textContent = data.event_count;
    const summaryEl = card.querySelector("[data-role=summary]");
    if (summaryEl && data.summary !== undefined) summaryEl.textContent = data.summary;
    card.classList.remove("flash");
    void card.offsetWidth;
    card.classList.add("flash");
  }

  async function refreshRunsList() {
    const list = document.getElementById("run-list");
    if (!list) return;
    try {
      const params = new URLSearchParams(window.location.search);
      const res = await fetch(`/api/runs?${params.toString()}`, { cache: "no-store" });
      if (!res.ok) return;
      const data = await res.json();
      const countEl = document.querySelector("[data-role=run-count]");
      if (countEl) countEl.textContent = data.count;
      const existingIds = new Set(
        Array.from(list.querySelectorAll(".run-card")).map((c) => c.dataset.runId)
      );
      const newIds = new Set(data.runs.map((r) => r.run_id));
      const hasNewRun = data.runs.some((r) => !existingIds.has(r.run_id));
      const hasRemovedRun = Array.from(existingIds).some((id) => !newIds.has(id));
      if (hasNewRun || hasRemovedRun) {
        showUpdateBanner(
          hasNewRun ? "发现新的 run" : "列表已变化",
          () => window.location.reload()
        );
      }
      // in-place update for existing
      data.runs.forEach((run) => {
        const card = list.querySelector(`.run-card[data-run-id="${run.run_id}"]`);
        if (card) updateRunCardInPlace(card, run);
      });
    } catch (err) {
      /* ignore */
    }
  }

  // ---------------- Run detail: delta refresh ----------------

  async function refreshRunDetail(runId) {
    const timeline = document.getElementById("timeline");
    if (!timeline) return;
    try {
      const res = await fetch(`/api/runs/${runId}`, { cache: "no-store" });
      if (!res.ok) return;
      const data = await res.json();

      // Preserve open <details> keyed by seq
      const openSeqs = new Set(
        Array.from(timeline.querySelectorAll(".timeline-item"))
          .filter((it) => {
            const det = it.querySelector(".payload-details");
            return det && det.open;
          })
          .map((it) => it.dataset.seq)
      );
      const knownSeqs = new Set(
        Array.from(timeline.querySelectorAll(".timeline-item")).map((it) => it.dataset.seq)
      );

      // Re-render timeline HTML from payload
      const html = renderTimelineHtml(data.timeline);
      timeline.innerHTML = html;

      // Re-apply open state and flash only new items
      timeline.querySelectorAll(".timeline-item").forEach((it) => {
        const seq = it.dataset.seq;
        const det = it.querySelector(".payload-details");
        if (openSeqs.has(seq) && det) det.open = true;
        if (!knownSeqs.has(seq)) {
          it.classList.add("flash");
        }
      });

      // Update summary numbers
      const map = {
        "[data-role=event-count]": data.run.event_count,
        "[data-role=timeline-count]": data.timeline.length,
        "[data-role=duration-label]": data.run.duration_label,
        "[data-role=finished-label]": data.run.finished_at_label,
      };
      Object.entries(map).forEach(([sel, val]) => {
        document.querySelectorAll(sel).forEach((el) => {
          if (val !== undefined && val !== null) el.textContent = val;
        });
      });
      const statusEl = document.querySelector(".hero-status[data-role=status]");
      if (statusEl) {
        statusEl.className = `status status-${data.run.status} hero-status`;
        statusEl.setAttribute("data-role", "status");
        statusEl.innerHTML =
          (data.run.is_running ? `<span class="pulse-dot"></span>` : "") +
          ` ${data.run.status}${data.run.is_running ? " · running" : ""}`;
      }

      initCopyButtons(timeline);
      // Re-apply active filters
      initTimelineFiltersReapply();
    } catch (err) {
      /* ignore */
    }
  }

  // Re-apply current filter state (reads chip state from DOM)
  function initTimelineFiltersReapply() {
    const panel = document.getElementById("timeline-filters");
    const timeline = document.getElementById("timeline");
    if (!panel || !timeline) return;
    const activeLane = panel.querySelector("[data-filter-lane].active");
    const activeStatus = panel.querySelector("[data-filter-status].active");
    const search = document.getElementById("timeline-search");
    const lane = activeLane ? activeLane.dataset.filterLane : "__all__";
    const status = activeStatus ? activeStatus.dataset.filterStatus : "__all__";
    const query = search ? search.value.trim().toLowerCase() : "";
    timeline.querySelectorAll(".timeline-item").forEach((item) => {
      const laneOk = lane === "__all__" || item.dataset.lane === lane;
      const statusOk = status === "__all__" || item.dataset.status === status;
      const blob = item.dataset.searchBlob || "";
      const queryOk = !query || blob.includes(query);
      item.style.display = laneOk && statusOk && queryOk ? "" : "none";
    });
  }

  // ---------------- Render helpers for delta timeline ----------------

  function esc(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderTimelineHtml(items) {
    let prevTurn = "\u0000";
    const parts = [];
    items.forEach((item) => {
      const turn = item.turn === null || item.turn === undefined ? "" : item.turn;
      if (turn !== "" && turn !== prevTurn) {
        parts.push(
          `<div class="turn-divider" data-turn="${esc(turn)}"><span class="turn-badge">turn ${esc(
            turn
          )}</span><span class="turn-line"></span></div>`
        );
      }
      prevTurn = turn;
      parts.push(renderTimelineItem(item));
    });
    return parts.join("");
  }

  function renderTimelineItem(item) {
    const s = item.surface || {};
    const turnTxt = item.turn === null || item.turn === undefined ? "" : item.turn;
    const blob = (item.type + " " + item.summary + " " + (s.tool_name || "")).toLowerCase();
    const head = `
      <div class="timeline-head">
        <div class="head-left">
          <span class="status status-${esc(item.status)}">${esc(item.status)}</span>
          <strong class="type-name">${esc(item.type)}</strong>
          <span class="lane-tag lane-${esc(item.lane)}">${esc(item.lane)}</span>
          ${turnTxt !== "" ? `<span class="chip chip-turn">T${esc(turnTxt)}</span>` : ""}
          ${item.pair_duration_label && item.pair_duration_ms > 0 ? `<span class="chip chip-duration">${esc(item.pair_duration_label)}</span>` : ""}
        </div>
        <div class="head-right">
          <span class="mono subtle">#${esc(item.seq)}</span>
          <span class="mono subtle">${esc(item.ts_short)}</span>
        </div>
      </div>`;

    let body = "";
    if (s.kind === "llm_exchange") {
      body = renderExchange(s);
    } else if (s.kind === "tool") {
      body = renderTool(s, item);
    } else {
      const summaryHtml = `<p class="summary-text">${esc(item.summary)}</p>`;
      body = summaryHtml;
    }

    const payloadJson = JSON.stringify(item.payload, null, 2);
    const rawJson = JSON.stringify(item.raw_events, null, 2);

    const details = `
      <details class="payload-details">
        <summary>
          <span class="summary-text-inline">payload${item.event_count > 1 ? ` · ${item.event_count} events` : ""}</span>
          <button type="button" class="copy-btn" data-copy-target="next-pre">copy</button>
        </summary>
        <div class="detail-stack">
          <pre class="data-block">${esc(payloadJson)}</pre>
          <pre class="data-block">${esc(rawJson)}</pre>
        </div>
      </details>`;

    return `
      <article class="timeline-item" id="ti-${esc(item.seq)}"
               data-seq="${esc(item.seq)}"
               data-lane="${esc(item.lane)}"
               data-status="${esc(item.status)}"
               data-turn="${esc(turnTxt)}"
               data-type="${esc(item.type)}"
               data-search-blob="${esc(blob)}">
        <div class="timeline-rail lane-bg-${esc(item.lane)}"></div>
        <div class="timeline-card status-${esc(item.status)}">
          ${head}
          ${body}
          ${details}
        </div>
      </article>`;
  }

  function renderExchange(s) {
    const reqParts = [`<span class="exchange-label">→ request</span>`];
    if (s.message_count !== null && s.message_count !== undefined)
      reqParts.push(`<span class="kv">messages <strong>${esc(s.message_count)}</strong></span>`);
    if (s.tool_count !== null && s.tool_count !== undefined)
      reqParts.push(`<span class="kv">tools <strong>${esc(s.tool_count)}</strong></span>`);
    if (s.last_message_role)
      reqParts.push(
        `<span class="chip chip-role role-${esc(s.last_message_role)}">${esc(s.last_message_role)}</span>`
      );

    const resParts = [`<span class="exchange-label">← response</span>`];
    if (s.tool_call_count)
      resParts.push(`<span class="kv">tool_calls <strong>${esc(s.tool_call_count)}</strong></span>`);
    else resParts.push(`<span class="chip chip-ghost">final</span>`);

    const toolRow =
      s.tool_call_names && s.tool_call_names.length
        ? `<div class="tool-call-row">${s.tool_call_names
            .map((n) => `<span class="chip chip-tool">⚙ ${esc(n)}</span>`)
            .join("")}</div>`
        : "";

    return `
      <div class="exchange">
        <div class="exchange-col exchange-req">
          <div class="exchange-col-head">${reqParts.join("")}</div>
          ${s.last_message_preview ? `<blockquote class="quote">${esc(s.last_message_preview)}</blockquote>` : ""}
        </div>
        <div class="exchange-col exchange-res">
          <div class="exchange-col-head">${resParts.join("")}</div>
          ${s.content_preview ? `<blockquote class="quote">${esc(s.content_preview)}</blockquote>` : ""}
          ${s.reasoning_preview ? `<details class="reasoning"><summary>reasoning</summary><blockquote class="quote subtle-quote">${esc(s.reasoning_preview)}</blockquote></details>` : ""}
          ${toolRow}
        </div>
      </div>`;
  }

  function renderTool(s, item) {
    const head = `<div class="tool-head"><span class="exchange-label">⚙ ${esc(
      s.tool_name || "tool"
    )}</span>${
      item.pair_duration_label && item.pair_duration_ms > 0
        ? `<span class="kv">duration <strong>${esc(item.pair_duration_label)}</strong></span>`
        : ""
    }</div>`;
    const args = s.arguments_preview
      ? `<div class="tool-section"><span class="exchange-label">args</span><pre class="data-block mini">${esc(s.arguments_preview)}</pre></div>`
      : "";
    const result = s.result_preview
      ? `<div class="tool-section"><span class="exchange-label">result</span><pre class="data-block mini">${esc(s.result_preview)}</pre></div>`
      : "";
    const err = s.error_message
      ? `<div class="tool-section"><span class="exchange-label err">error</span><pre class="data-block mini err">${esc(s.error_message)}</pre></div>`
      : "";
    return `<div class="tool-card">${head}${args}${result}${err}</div>`;
  }

  // ---------------- SSE dispatcher ----------------

  function initStream() {
    const streamUrl = document.body.dataset.streamUrl;
    if (!streamUrl) return;

    const runId = document.body.dataset.runId;
    const isRunList = !runId;

    setLive("live");
    const source = new EventSource(streamUrl);

    const refresh = isRunList ? refreshRunsList : () => refreshRunDetail(runId);
    let pending = false;
    let timer = null;
    const schedule = () => {
      if (pending) return;
      pending = true;
      timer = window.setTimeout(() => {
        pending = false;
        refresh();
      }, 250);
    };

    source.addEventListener("run_update", schedule);
    source.addEventListener("run_event", schedule);
    source.onmessage = schedule;
    source.onerror = () => {
      setLive("error");
      source.close();
      window.setTimeout(initStream, 1500);
    };

    window.addEventListener("beforeunload", () => {
      if (timer) window.clearTimeout(timer);
      source.close();
    });
  }

  // ---------------- Boot ----------------

  window.addEventListener("DOMContentLoaded", () => {
    initGlossary();
    initThemeToggle();
    initCopyButtons(document);
    initTimelineFilters();
    initStream();
  });
})();
