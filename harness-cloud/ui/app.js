/* Harness Cloud — интерфейс. Все кнопки связаны с обработчиками ниже. */
(function () {
  "use strict";

  // ---------- иконки ----------
  const ICONS = {
    cloud: '<path d="M7 18a4.5 4.5 0 0 1-.5-9A6 6 0 0 1 18 9.5a4 4 0 0 1 .5 8H7z"/>',
    "cloud-down": '<path d="M7 18a4.5 4.5 0 0 1-.5-9A6 6 0 0 1 18 9.5a4 4 0 0 1 .5 8H7z"/><path d="M12 11v6M9.5 14.5 12 17l2.5-2.5"/>',
    home: '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1"/><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    type: '<path d="M4 6h16M4 12h16M4 18h10"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    gamepad: '<path d="M7 16a3 3 0 0 1-3-3v-2a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3v2a3 3 0 0 1-3 3 2.5 2.5 0 0 1-2-1l-1-1h-2l-1 1a2.5 2.5 0 0 1-2 1z"/><path d="M6 10h4M8 8v4M15 11h.01M17 13h.01"/>',
    grid: '<rect x="4" y="4" width="6" height="6" rx="1.5"/><rect x="14" y="4" width="6" height="6" rx="1.5"/><rect x="4" y="14" width="6" height="6" rx="1.5"/><rect x="14" y="14" width="6" height="6" rx="1.5"/>',
    wand: '<path d="M4 20L16 8M14 6l4 4M18 3v3M16.5 4.5h3M20 13v2M19 14h2"/>',
    play: '<path d="M7 5l12 7-12 7z"/>',
    pause: '<path d="M8 5h3v14H8zM13 5h3v14h-3z"/>',
    chev: '<path d="M6 9l6 6 6-6"/>',
    "chev-r": '<path d="M9 6l6 6-6 6"/>',
    "chev-l": '<path d="M15 6l-6 6 6 6"/>',
    vol: '<path d="M4 9v6h4l5 4V5L8 9z"/><path d="M16 9a4 4 0 0 1 0 6"/>',
    fs: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    bars: '<path d="M5 20V10M12 20V4M19 20v-7"/>',
    download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
    dots: '<path d="M5 12h.01M12 12h.01M19 12h.01" stroke-width="3"/>',
    scissors: '<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><path d="M8 8l12 10M8 16L20 6"/>',
    doc: '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M10 13h6M10 17h6"/>',
    copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5h10"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    check: '<path d="M5 12l5 5 9-10"/>',
    star: '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
  };
  function iconSvg(name) {
    const inner = ICONS[name];
    if (!inner) return "";
    return `<svg viewBox="0 0 24 24" aria-hidden="true">${inner}</svg>`;
  }
  function paintIcons(root) {
    (root || document).querySelectorAll("[data-icon]").forEach((el) => {
      if (!el.querySelector("svg")) el.innerHTML = iconSvg(el.dataset.icon);
    });
  }

  // ---------- утилиты ----------
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtTime = (s) => {
    s = Math.max(0, Math.floor(s || 0));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  };
  const isEditable = (el) => el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
  const URL_RE = /^https?:\/\/[^\s]+$/i;

  function toast(msg, kind) {
    const box = $("toasts");
    const t = document.createElement("div");
    t.className = "toast " + (kind || "");
    t.textContent = msg;
    box.appendChild(t);
    setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 300); }, 3800);
  }

  async function api(path, opts) {
    const o = Object.assign({ headers: {} }, opts || {});
    if (o.body && !(o.body instanceof FormData) && typeof o.body !== "string") {
      o.headers["Content-Type"] = "application/json";
      o.body = JSON.stringify(o.body);
    }
    const res = await fetch(path, o);
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (_) {}
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    const ct = res.headers.get("content-type") || "";
    return ct.includes("application/json") ? res.json() : res;
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise((resolve, reject) => {
      const ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      const ok = document.execCommand("copy");
      ta.remove();
      ok ? resolve() : reject(new Error("copy failed"));
    });
  }

  function downloadUrl(url) {
    const a = document.createElement("a");
    a.href = url; a.download = ""; document.body.appendChild(a); a.click(); a.remove();
  }

  // ---------- состояние ----------
  const state = {
    meta: null,
    settings: null,
    contentType: "podcast",
    pid: localStorage.getItem("hc_project") || null,
    project: null,
    selected: null,         // index выбранного клипа
    pollTimer: null,
    lastStatus: null,
  };

  // ---------- тема ----------
  function applyTheme(theme, persist) {
    document.documentElement.dataset.theme = theme;
    $("themeDark").checked = theme === "dark";
    $("themeLight").checked = theme === "light";
    $("setTheme").value = theme;
    localStorage.setItem("hc_theme", theme);
    if (persist && state.settings) {
      state.settings.theme = theme;
      api("/api/settings", { method: "PUT", body: { theme } }).catch(() => {});
    }
  }
  $("themeDark").addEventListener("change", () => applyTheme("dark", true));
  $("themeLight").addEventListener("change", () => applyTheme("light", true));

  // ---------- навигация ----------
  function showView(name) {
    document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
    document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
    if (name === "history") loadHistory();
  }
  document.querySelectorAll(".nav-item").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));

  // ---------- источник ----------
  function parseUrls(text) {
    return text.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);
  }
  function refreshUrlHint() {
    const urls = parseUrls($("urlInput").value);
    const bad = urls.filter((u) => !URL_RE.test(u));
    $("urlInput").classList.toggle("invalid", bad.length > 0);
    $("urlHint").textContent = !urls.length
      ? "Можно вставить несколько ссылок: по одной в строке или через пробел"
      : bad.length ? `Не похоже на ссылку: ${bad[0].slice(0, 60)}`
      : `Ссылок в очереди: ${urls.length}`;
  }
  $("urlInput").addEventListener("input", refreshUrlHint);
  $("urlInput").addEventListener("keydown", (e) => { if (e.key === "Enter") startProcessing(); });
  $("clearUrl").addEventListener("click", () => { $("urlInput").value = ""; refreshUrlHint(); $("urlInput").focus(); });
  $("loadBtn").addEventListener("click", async () => {
    if (!$("urlInput").value.trim()) {
      try {
        const txt = (await navigator.clipboard.readText()).trim();
        if (txt) $("urlInput").value = txt;
      } catch (_) { toast("Вставьте ссылку в поле (Ctrl+V)", "err"); }
    }
    refreshUrlHint();
    const urls = parseUrls($("urlInput").value);
    if (!urls.length) return toast("Вставьте ссылку на видео", "err");
    if (urls.some((u) => !URL_RE.test(u))) return toast("Проверьте ссылки: должны начинаться с https://", "err");
    toast(`Ссылок принято: ${urls.length}. Нажмите «Начать обработку»`, "ok");
  });

  // ---------- тип контента ----------
  function setContentType(t) {
    state.contentType = t;
    document.querySelectorAll("#contentChips .chip").forEach((c) => c.classList.toggle("active", c.dataset.type === t));
    $("typeHint").textContent = t === "game"
      ? "Режим «Стрим / Игра»: субтитры и хук не добавляются, клипы режутся по динамике и ключевым словам."
      : "";
  }
  document.querySelectorAll("#contentChips .chip").forEach((c) => c.addEventListener("click", () => setContentType(c.dataset.type)));

  // ---------- расширенные настройки ----------
  $("advToggle").addEventListener("click", () => {
    const panel = $("advPanel");
    panel.hidden = !panel.hidden;
    $("advToggle").lastElementChild.style.transform = panel.hidden ? "" : "rotate(180deg)";
  });

  function fillSelect(sel, items) {
    sel.innerHTML = Object.entries(items).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("");
  }

  // ---------- дроп-зона и файл ----------
  const dz = $("dropzone");
  dz.addEventListener("click", () => $("fileInput").click());
  dz.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("fileInput").click(); } });
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
  ["dragleave", "dragend"].forEach((ev) => dz.addEventListener(ev, () => dz.classList.remove("over")));
  dz.addEventListener("drop", (e) => {
    e.preventDefault(); dz.classList.remove("over");
    const f = e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) uploadFile(f);
  });
  $("fileInput").addEventListener("change", (e) => { const f = e.target.files[0]; if (f) uploadFile(f); e.target.value = ""; });

  async function uploadFile(file) {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("content_type", state.contentType);
    fd.append("clip_count", $("clipCount").value);
    fd.append("subtitle_style", $("subStyle").value);
    fd.append("whisper_model", $("whisperModel").value);
    fd.append("export_preset", $("exportPreset").value);
    toast(`Загрузка файла «${file.name}»…`);
    try {
      const r = await api("/api/projects/upload", { method: "POST", body: fd });
      afterCreate(r.ids);
    } catch (e) { toast(e.message, "err"); }
  }

  // ---------- старт обработки ----------
  async function startProcessing() {
    const urls = parseUrls($("urlInput").value);
    if (!urls.length) return toast("Вставьте ссылку или перетащите файл", "err");
    if (urls.some((u) => !URL_RE.test(u))) return toast("Проверьте ссылки: должны начинаться с https://", "err");
    if (state.settings && state.settings.notify && "Notification" in window && Notification.permission === "default") {
      try { Notification.requestPermission(); } catch (_) {}
    }
    try {
      const r = await api("/api/projects", { method: "POST", body: {
        urls, content_type: state.contentType,
        clip_count: Number($("clipCount").value),
        subtitle_style: $("subStyle").value,
        whisper_model: $("whisperModel").value,
        export_preset: $("exportPreset").value,
      }});
      afterCreate(r.ids);
    } catch (e) { toast(e.message, "err"); }
  }
  $("startBtn").addEventListener("click", startProcessing);

  function afterCreate(ids) {
    toast(ids.length > 1 ? `В очереди ${ids.length} проекта` : "Проект поставлен в очередь", "ok");
    setCurrent(ids[0]);
    $("urlInput").value = "";
    refreshUrlHint();
    showView("home");
  }

  function setCurrent(pid) {
    state.pid = pid;
    state.selected = null;
    state.lastStatus = null;
    localStorage.setItem("hc_project", pid);
    startPolling();
  }

  // ---------- опрос состояния ----------
  function startPolling() {
    clearTimeout(state.pollTimer);
    pollOnce();
  }
  async function pollOnce() {
    if (!state.pid) { renderProject(null); return; }
    try {
      const p = await api("/api/projects/" + encodeURIComponent(state.pid));
      state.project = p;
      renderProject(p);
      const live = p.status === "running" || p.status === "queued";
      if (live) state.pollTimer = setTimeout(pollOnce, 1000);
      else if (state.lastStatus && state.lastStatus !== p.status) onFinished(p);
      state.lastStatus = p.status;
    } catch (e) {
      state.pid = null;
      localStorage.removeItem("hc_project");
      renderProject(null);
    }
  }

  function onFinished(p) {
    const ready = (p.clips || []).filter((c) => c.status === "done").length;
    if (p.status === "done") {
      toast(`Готово! Найдено ${ready} клипов`, "ok");
      if (state.settings && state.settings.notify && "Notification" in window && Notification.permission === "granted") {
        new Notification("Harness Cloud", { body: `Обработка завершена: ${ready} клипов` });
      }
    } else if (p.status === "error") toast("Ошибка: " + (p.error || "см. детали"), "err");
    else if (p.status === "cancelled") toast("Обработка отменена");
  }

  const STEP_NAMES = { source: "загрузка видео", audio: "извлечение аудио", transcribe: "транскрибация",
    analyze: "поиск моментов", clips: "рендер клипов" };

  // ---------- рендер проекта ----------
  function renderProject(p) {
    const phoneEmpty = $("phoneEmpty");
    if (!p) {
      $("statusLine").className = "status";
      $("statusText").textContent = "Нет проекта";
      $("progressWrap").hidden = true;
      $("warnBox").hidden = true;
      $("zipBtn").disabled = true;
      $("clipList").innerHTML = '<div class="empty">Запустите обработку, и здесь появятся клипы</div>';
      $("clipPos").textContent = "—";
      return;
    }
    const clips = p.clips || [];
    const ready = clips.filter((c) => c.status === "done" && c.file).length;
    const cls = { running: "run", queued: "run", done: "ok", error: "err", cancelled: "" }[p.status] || "";
    $("statusLine").className = "status " + cls;
    let text;
    if (p.status === "done") text = `Готово! Найдено ${ready} клипов`;
    else if (p.status === "error") text = "Ошибка на шаге: " + (STEP_NAMES[p.failed_step] || "—");
    else if (p.status === "cancelled") text = "Отменено";
    else if (p.status === "queued") text = "В очереди…";
    else text = p.stage || "Обработка…";
    $("statusText").textContent = text;

    const live = p.status === "running" || p.status === "queued";
    $("progressWrap").hidden = !live;
    $("progressBar").style.width = Math.round((p.progress || 0) * 100) + "%";
    $("zipBtn").disabled = ready === 0;

    const warns = [...(p.warnings || [])];
    if (p.status === "error" && p.error) warns.unshift(p.error);
    $("warnBox").hidden = warns.length === 0;
    $("warnBox").className = "warn" + (p.status === "error" ? " err-box" : "");
    $("warnBox").innerHTML = warns.map((w) => `<div>• ${esc(w)}</div>`).join("");

    renderClipList(p);

    if (state.selected == null) {
      const first = clips.find((c) => c.status === "done" && c.file);
      if (first) selectClip(first.index, false);
    } else {
      const cur = clips.find((c) => c.index === state.selected);
      if (cur && cur.file && !$("player").src.endsWith(`/clips/${cur.index}/video`)) selectClip(cur.index, false);
      else if (cur) refreshSidePanel(cur);
    }
    if (!clips.length) phoneEmpty.classList.remove("hide");
    drawTimeline();
  }

  function clipTitle(c) {
    return c.hook || (c.text ? c.text.split(" ").slice(0, 7).join(" ") : c.description) || `Клип ${c.index}`;
  }

  function renderClipList(p) {
    const list = $("clipList");
    const clips = p.clips || [];
    if (!clips.length) {
      list.innerHTML = p.status === "error" || p.status === "cancelled"
        ? '<div class="empty">Клипов пока нет. Нажмите «Повторить» в меню ⋯ или запустите заново.</div>'
        : '<div class="empty">Клипы появятся здесь после анализа видео</div>';
      return;
    }
    list.innerHTML = clips.map((c) => {
      const done = c.status === "done" && c.file;
      const thumb = done
        ? `<img src="/api/projects/${encodeURIComponent(p.id)}/clips/${c.index}/thumb?v=${c.updated || c.index}" alt="">`
        : `<div class="ph">${c.status === "error" ? "Ошибка" : "Ожидание"}</div>`;
      let overlay = "";
      if (c.status === "processing") overlay = '<div class="clip-state"><div class="spinner"></div>Рендер…</div>';
      else if (c.status === "queued" && !done) overlay = '<div class="clip-state">В очереди</div>';
      return `
        <div class="clip-card ${c.index === state.selected ? "active" : ""} ${c.status === "processing" ? "processing" : ""} ${c.status === "queued" ? "queued" : ""}" data-idx="${c.index}" tabindex="0" role="button" aria-label="Клип ${c.index}">
          <div class="clip-thumb">${thumb}
            <span class="rank">${c.index}</span>
            <span class="score"><span data-icon="star"></span>${c.score}%</span>
            <span class="dur">0:30</span>
            ${overlay}
          </div>
          <div class="clip-title">${esc(clipTitle(c))}</div>
          ${c.status === "error" ? `<div class="clip-err">${esc((c.error || "").slice(0, 120))}</div>` : ""}
        </div>`;
    }).join("");
    paintIcons(list);
    list.querySelectorAll(".clip-card").forEach((el) => {
      el.addEventListener("click", () => selectClip(Number(el.dataset.idx), true));
      el.addEventListener("keydown", (e) => { if (e.key === "Enter") selectClip(Number(el.dataset.idx), true); });
    });
  }

  // ---------- выбор клипа и плеер ----------
  function currentClips() { return (state.project && state.project.clips) || []; }

  function selectClip(idx, userAction) {
    const clip = currentClips().find((c) => c.index === idx);
    if (!clip) return;
    state.selected = idx;
    const pos = currentClips().findIndex((c) => c.index === idx) + 1;
    $("clipPos").textContent = `${pos} / ${currentClips().length}`;
    document.querySelectorAll(".clip-card").forEach((el) => el.classList.toggle("active", Number(el.dataset.idx) === idx));
    const player = $("player");
    if (clip.file) {
      const src = `/api/projects/${encodeURIComponent(state.pid)}/clips/${idx}/video`;
      if (!player.src.endsWith(src)) {
        player.src = src;
        player.load();
      }
      $("phoneEmpty").classList.add("hide");
    } else {
      $("phoneEmpty").classList.remove("hide");
    }
    refreshSidePanel(clip);
    drawTimeline();
    if (userAction) player.play().catch(() => {});
  }

  function refreshSidePanel(clip) {
    const shift = Number(clip.shift || 0);
    const trim = $("trim");
    trim.disabled = !clip.file;
    trim.value = shift;
    $("trimLbl").textContent = `${fmtTime(0)} — ${fmtTime(30)}` + (shift ? `  ·  сдвиг ${shift > 0 ? "+" : ""}${shift.toFixed(1)} с` : "");
    $("trimApply").disabled = !clip.file;
    $("trimReset").disabled = !clip.file;
    $("dlOne").disabled = !clip.file;
    $("descText").textContent = clip.description || clip.reason || "—";
    $("tags").innerHTML = (clip.hashtags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("");
    $("copyDesc").dataset.text = [clip.description || "", (clip.hashtags || []).join(" ")].join("\n\n").trim();
  }

  // Предпросмотр: управление
  const player = $("player");
  function togglePlay() {
    if (!player.src) return;
    if (player.paused) player.play().catch(() => {}); else player.pause();
  }
  function syncPlayBtn() {
    $("playBtn").innerHTML = iconSvg(player.paused ? "play" : "pause");
  }
  $("playBtn").addEventListener("click", togglePlay);
  player.addEventListener("play", syncPlayBtn);
  player.addEventListener("pause", syncPlayBtn);
  player.addEventListener("ended", syncPlayBtn);
  player.addEventListener("timeupdate", () => {
    const d = player.duration || 30;
    const pct = (player.currentTime / d) * 100;
    $("seek").value = pct;
    $("seek").style.setProperty("--p", pct + "%");
    $("timeLbl").textContent = `${fmtTime(player.currentTime)} / ${fmtTime(d)}`;
  });
  $("seek").addEventListener("input", (e) => {
    if (player.duration) player.currentTime = (Number(e.target.value) / 100) * player.duration;
  });
  $("muteBtn").addEventListener("click", () => {
    player.muted = !player.muted;
    $("muteBtn").innerHTML = iconSvg(player.muted ? "x" : "vol");
    toast(player.muted ? "Звук выключен" : "Звук включён");
  });
  $("fsBtn").addEventListener("click", () => {
    if (player.requestFullscreen) player.requestFullscreen().catch(() => toast("Полноэкранный режим недоступен", "err"));
  });
  function step(dir) {
    const list = currentClips().filter((c) => c.file);
    if (!list.length) return;
    const i = list.findIndex((c) => c.index === state.selected);
    const next = list[(i + dir + list.length) % list.length];
    selectClip(next.index, false);
  }
  $("prevClip").addEventListener("click", () => step(-1));
  $("nextClip").addEventListener("click", () => step(1));

  // Ручная подрезка: сдвиг начала ±3 с, длина 30 с
  $("trim").addEventListener("input", (e) => {
    const v = Number(e.target.value);
    $("trimLbl").textContent = `${fmtTime(0)} — ${fmtTime(30)}  ·  сдвиг ${v > 0 ? "+" : ""}${v.toFixed(1)} с`;
  });
  $("trimApply").addEventListener("click", async () => {
    const clip = currentClips().find((c) => c.index === state.selected);
    if (!clip) return;
    try {
      await api(`/api/projects/${encodeURIComponent(state.pid)}/clips/${clip.index}/shift`, {
        method: "POST", body: { shift: Number($("trim").value) } });
      toast("Клип перерезается с новым началом");
      startPolling();
    } catch (e) { toast(e.message, "err"); }
  });
  $("trimReset").addEventListener("click", async () => {
    const clip = currentClips().find((c) => c.index === state.selected);
    if (!clip) return;
    $("trim").value = 0;
    try {
      await api(`/api/projects/${encodeURIComponent(state.pid)}/clips/${clip.index}/shift`, {
        method: "POST", body: { shift: 0 } });
      toast("Начало клипа возвращено");
      startPolling();
    } catch (e) { toast(e.message, "err"); }
  });

  // Описание и хештеги
  $("descToggle").addEventListener("click", () => {
    const body = $("descBody");
    body.hidden = !body.hidden;
    $("descToggle").classList.toggle("open", !body.hidden);
  });
  $("copyDesc").addEventListener("click", async () => {
    try { await copyText($("copyDesc").dataset.text || ""); toast("Описание и хештеги скопированы", "ok"); }
    catch (_) { toast("Не удалось скопировать", "err"); }
  });
  $("dlOne").addEventListener("click", () => {
    if (!state.pid || state.selected == null) return;
    downloadUrl(`/api/projects/${encodeURIComponent(state.pid)}/clips/${state.selected}/download`);
  });
  $("zipBtn").addEventListener("click", () => {
    if (!state.pid) return;
    const clips = currentClips();
    const notReady = clips.filter((c) => !(c.status === "done" && c.file)).length;
    if (notReady) toast(`В архив войдут только готовые клипы: ещё ${notReady} в обработке`, "err");
    else toast("Архив готовится, загрузка начнётся сразу после сборки");
    downloadUrl(`/api/projects/${encodeURIComponent(state.pid)}/zip`);
  });

  // Таймлайн: сила момента по всему видео + окна клипов
  function drawTimeline() {
    const cv = $("timeline");
    const ctx = cv.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const w = cv.clientWidth, h = cv.clientHeight;
    cv.width = w * dpr; cv.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const p = state.project;
    const clips = (p && p.clips) || [];
    const dur = (p && (p.duration || p.timeline_seconds)) || 0;
    const line = clips.length ? clips[0].timeline : null;
    if (!line || !dur) {
      ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--text-3");
      ctx.font = "12px sans-serif";
      ctx.fillText("Таймлайн появится после анализа", 10, h / 2 + 4);
      return;
    }
    const n = line.length;
    const bw = w / n;
    ctx.fillStyle = "rgba(167,139,250,.35)";
    line.forEach((v, i) => { const bh = Math.max(2, v * (h - 8)); ctx.fillRect(i * bw, h - bh - 4, Math.max(bw - 0.5, 0.5), bh); });
    clips.forEach((c) => {
      const x0 = (c.start / dur) * w, x1 = (c.end / dur) * w;
      ctx.fillStyle = c.index === state.selected ? "rgba(139,92,246,.45)" : "rgba(255,255,255,.12)";
      ctx.fillRect(x0, 0, Math.max(x1 - x0, 2), h);
      ctx.fillStyle = c.index === state.selected ? "#c4b5fd" : "rgba(255,255,255,.5)";
      ctx.font = "bold 10px sans-serif";
      ctx.fillText(String(c.index), x0 + 3, 12);
    });
  }
  $("timeline").addEventListener("click", (e) => {
    const p = state.project; if (!p || !p.clips) return;
    const dur = p.duration || p.timeline_seconds || 1;
    const rect = e.target.getBoundingClientRect();
    const t = ((e.clientX - rect.left) / rect.width) * dur;
    const hit = p.clips.reduce((best, c) => {
      const mid = (c.start + c.end) / 2;
      return !best || Math.abs(mid - t) < Math.abs((best.start + best.end) / 2 - t) ? c : best;
    }, null);
    if (hit && hit.file) selectClip(hit.index, false);
  });
  window.addEventListener("resize", drawTimeline);

  // ---------- меню ⋯ ----------
  $("moreBtn").addEventListener("click", (e) => { e.stopPropagation(); $("moreMenu").hidden = !$("moreMenu").hidden; });
  document.addEventListener("click", (e) => { if (!e.target.closest(".menu-wrap")) $("moreMenu").hidden = true; });
  $("moreMenu").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => menuAction(b.dataset.act)));

  async function menuAction(act) {
    $("moreMenu").hidden = true;
    if (act === "copyall") {
      const texts = currentClips().filter((c) => c.file).map((c) =>
        `Клип ${c.index}: ${c.description || ""}\n${(c.hashtags || []).join(" ")}`);
      if (!texts.length) return toast("Нет готовых клипов", "err");
      try { await copyText(texts.join("\n\n")); toast("Описания всех клипов скопированы", "ok"); }
      catch (_) { toast("Не удалось скопировать", "err"); }
    } else if (act === "retry") {
      if (!state.pid) return toast("Нет проекта", "err");
      try { await api(`/api/projects/${state.pid}/retry`, { method: "POST" }); toast("Повтор с последнего шага"); startPolling(); }
      catch (e) { toast(e.message, "err"); }
    } else if (act === "cancel") {
      if (!state.pid) return toast("Нет проекта", "err");
      await api(`/api/projects/${state.pid}/cancel`, { method: "POST" }).catch(() => {});
      toast("Отмена запрошена");
      startPolling();
    } else if (act === "delete") {
      if (!state.pid) return toast("Нет проекта", "err");
      if (!confirm("Удалить проект вместе с клипами?")) return;
      await deleteProject(state.pid);
    }
  }

  async function deleteProject(pid) {
    try {
      await api(`/api/projects/${encodeURIComponent(pid)}`, { method: "DELETE" });
      toast("Проект удалён");
      if (state.pid === pid) {
        state.pid = null; state.project = null; state.selected = null;
        localStorage.removeItem("hc_project");
        $("player").removeAttribute("src"); $("player").load();
        renderProject(null);
      }
      if (document.getElementById("view-history").classList.contains("active")) loadHistory();
    } catch (e) { toast(e.message, "err"); }
  }

  // ---------- стиль и пресет без повторной транскрибации ----------
  $("subStyle").addEventListener("change", async () => {
    const p = state.project;
    if (!p || !state.pid || !(p.clips || []).length) return;
    if (p.status === "running" || p.status === "queued") {
      toast("Дождитесь окончания обработки, потом смените стиль", "err");
      $("subStyle").value = (p.options && p.options.subtitle_style) || $("subStyle").value;
      return;
    }
    try {
      await api(`/api/projects/${state.pid}/restyle`, { method: "POST", body: { subtitle_style: $("subStyle").value } });
      toast("Перерендер клипов с новым стилем субтитров");
      startPolling();
    } catch (e) { toast(e.message, "err"); }
  });

  // ---------- история ----------
  async function loadHistory() {
    const box = $("historyList");
    try {
      const items = await api("/api/projects");
      if (!items.length) { box.innerHTML = '<div class="empty">Проектов пока нет</div>'; return; }
      box.innerHTML = items.map((p) => {
        const when = new Date((p.created || 0) * 1000).toLocaleString("ru-RU");
        const title = (p.source || "").length > 80 ? p.source.slice(0, 80) + "…" : (p.source || "");
        const st = { done: "Готово", running: "Обработка", queued: "В очереди", error: "Ошибка", cancelled: "Отменено" }[p.status] || p.status;
        return `<div class="hist-item" data-pid="${esc(p.id)}">
          <div class="hist-main">
            <div class="hist-title">${esc(title)}</div>
            <div class="hist-meta">${esc(when)} · клипов: ${p.clip_count || 0} · ${esc(CONTENT_LABEL(p.content_type))}</div>
          </div>
          <span class="badge ${esc(p.status)}">${esc(st)}</span>
          <button class="btn btn-ghost btn-sm" data-open="${esc(p.id)}">Открыть</button>
          <button class="icon-btn" data-del="${esc(p.id)}" data-icon="x" title="Удалить"></button>
        </div>`;
      }).join("");
      paintIcons(box);
      box.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => {
        setCurrent(b.dataset.open); showView("home");
      }));
      box.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", () => {
        if (confirm("Удалить проект?")) deleteProject(b.dataset.del);
      }));
    } catch (e) { box.innerHTML = `<div class="empty">Не удалось загрузить историю: ${esc(e.message)}</div>`; }
  }
  function CONTENT_LABEL(t) {
    return (state.meta && state.meta.content_types[t]) || t;
  }

  // ---------- настройки ----------
  function fillSettingsForm() {
    const s = state.settings;
    $("setTheme").value = s.theme;
    $("setCount").value = String(s.clip_count);
    $("setStyle").value = s.subtitle_style;
    $("setModel").value = s.whisper_model;
    $("setPreset").value = s.export_preset;
    $("setNotify").checked = !!s.notify;
  }
  async function saveSettings() {
    const body = {
      theme: $("setTheme").value,
      clip_count: Number($("setCount").value),
      subtitle_style: $("setStyle").value,
      whisper_model: $("setModel").value,
      export_preset: $("setPreset").value,
      notify: $("setNotify").checked,
    };
    try {
      state.settings = await api("/api/settings", { method: "PUT", body });
      applyTheme(body.theme, false);
      applyFormDefaults();
      toast("Настройки сохранены", "ok");
    } catch (e) { toast(e.message, "err"); }
  }
  $("saveSettings").addEventListener("click", saveSettings);
  function applyFormDefaults() {
    const s = state.settings;
    $("clipCount").value = String(s.clip_count);
    $("subStyle").value = s.subtitle_style;
    $("whisperModel").value = s.whisper_model;
    $("exportPreset").value = s.export_preset;
  }

  // ---------- горячие клавиши ----------
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      saveSettings();
      return;
    }
    if (isEditable(e.target)) return;
    if (e.code === "Space" && !(e.target.tagName === "BUTTON")) {
      e.preventDefault(); togglePlay();
    } else if (e.key === "ArrowRight") step(1);
    else if (e.key === "ArrowLeft") step(-1);
  });

  // ---------- старт приложения ----------
  async function boot() {
    paintIcons(document);
    applyTheme(localStorage.getItem("hc_theme") || "dark", false);
    try {
      state.meta = await api("/api/meta");
      state.settings = await api("/api/settings");
    } catch (e) {
      toast("Сервер недоступен: " + e.message, "err");
      return;
    }
    fillSelect($("subStyle"), state.meta.subtitle_styles);
    fillSelect($("setStyle"), state.meta.subtitle_styles);
    const presets = Object.fromEntries(Object.entries(state.meta.presets).map(([k, v]) => [k, v.label]));
    fillSelect($("exportPreset"), presets);
    fillSelect($("setPreset"), presets);
    fillSettingsForm();
    applyFormDefaults();
    applyTheme(state.settings.theme || "dark", false);
    setContentType(state.contentType);
    $("aboutSub").textContent = `${state.meta.name} ${state.meta.version}`;
    $("aboutMeta").textContent = `Выход: ${state.meta.output.w}×${state.meta.output.h}, ${state.meta.output.fps} fps, H.264 + AAC. ` +
      `FFmpeg: ${state.meta.ffmpeg}`;
    refreshUrlHint();
    if (state.pid) startPolling(); else renderProject(null);
  }
  boot();
})();
