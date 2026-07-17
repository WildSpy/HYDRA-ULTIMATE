"use strict";
/* HYDRA Web Panel — SPA (vanilla, без сборки). */

// ─── Состояние / утилиты ──────────────────────────────────────────────────
const TOKEN_KEY = "hydra_token";
let TOKEN = localStorage.getItem(TOKEN_KEY) || "";
let ME = "";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function fmtBytes(n) {
  n = Number(n) || 0; const u = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]; let i = 0;
  while (Math.abs(n) >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
}
function fmtDate(s) { if (!s) return "∞"; const d = new Date(s); return isNaN(d) ? s : d.toLocaleDateString("ru-RU"); }

async function api(method, path, body) {
  const opt = { method, headers: {} };
  if (TOKEN) opt.headers["Authorization"] = "Bearer " + TOKEN;
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt);
  let data = null;
  try { data = await r.json(); } catch (e) { data = {}; }
  if (r.status === 401) { logout(true); throw { status: 401, error: "Требуется вход" }; }
  if (!r.ok) throw { status: r.status, error: (data && data.error) || ("Ошибка " + r.status) };
  return data;
}

// ─── Тосты ───────────────────────────────────────────────────────────────
function toast(msg, type = "ok", ms = 3500) {
  const t = document.createElement("div");
  t.className = "toast " + type; t.textContent = msg;
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), ms);
}

// ─── Фоновые задачи ─────────────────────────────────────────────────────
async function runTask(title, starter, onDone) {
  let res;
  try { res = await starter(); } catch (e) { toast(e.error || "Ошибка", "err"); return; }
  const id = res && res.task_id;
  if (!id) { if (onDone) onDone(res); return; }
  const modal = $("#task-modal"), log = $("#task-log"), st = $("#task-status");
  $("#task-title").textContent = title; log.textContent = ""; st.className = "task-status run"; st.textContent = "Выполняется…";
  modal.classList.remove("hidden");
  let done = false;
  while (!done) {
    await new Promise(r => setTimeout(r, 900));
    let task;
    try { task = await api("GET", "/api/tasks/" + id); } catch (e) { break; }
    log.textContent = (task.progress || []).join("\n"); log.scrollTop = log.scrollHeight;
    if (task.status !== "running") {
      done = true;
      if (task.status === "success") { st.className = "task-status ok"; st.textContent = "Готово ✓"; toast(title + ": готово", "ok"); }
      else { st.className = "task-status err"; st.textContent = "Ошибка: " + (task.error || ""); toast(title + ": ошибка", "err", 6000); }
      if (onDone) onDone(task);
    }
  }
}
$("#task-close").onclick = () => $("#task-modal").classList.add("hidden");

// ─── Аутентификация ─────────────────────────────────────────────────────
function showLogin() { $("#login").classList.remove("hidden"); $("#app").classList.add("hidden"); }
function showApp() { $("#login").classList.add("hidden"); $("#app").classList.remove("hidden"); }
function logout(silent) {
  TOKEN = ""; localStorage.removeItem(TOKEN_KEY);
  if (!silent) api("POST", "/api/logout").catch(() => { });
  showLogin();
}
$("#logout").onclick = () => logout();
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = $("#login-user").value.trim(), password = $("#login-pass").value;
  $("#login-error").textContent = "";
  try {
    const r = await fetch("/api/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });
    const d = await r.json();
    if (!r.ok) { $("#login-error").textContent = d.error || "Ошибка входа"; return; }
    TOKEN = d.token; localStorage.setItem(TOKEN_KEY, TOKEN); ME = d.username;
    boot();
  } catch (err) { $("#login-error").textContent = "Сеть недоступна"; }
});

// ─── Навигация / роутер ─────────────────────────────────────────────────
const NAV = [
  ["dashboard", "📊", "Дашборд"],
  ["core", "⚙️", "Ядро и система"],
  ["protocols", "🧩", "Протоколы"],
  ["users", "👥", "Пользователи"],
  ["monitoring", "📈", "Мониторинг"],
  ["security", "🔒", "Безопасность"],
  ["network", "🌐", "Сетевые службы"],
  ["telegram", "🤖", "Telegram-боты"],
  ["subscriptions", "🔗", "Подписки"],
  ["diagnostics", "🛠️", "Диагностика"],
];
let CURRENT = "dashboard";

function buildNav() {
  $("#nav").innerHTML = NAV.map(([id, ico, label]) =>
    `<button class="nav-item" data-route="${id}"><span class="ico">${ico}</span>${label}</button>`).join("");
  $$("#nav .nav-item").forEach(b => b.onclick = () => { location.hash = b.dataset.route; });
}
function setActive() {
  $$("#nav .nav-item").forEach(b => b.classList.toggle("active", b.dataset.route === CURRENT));
  const item = NAV.find(n => n[0] === CURRENT);
  $("#crumb").textContent = item ? item[2] : "";
}
async function route() {
  const r = (location.hash.replace("#", "") || "dashboard").split("/")[0];
  CURRENT = NAV.some(n => n[0] === r) ? r : "dashboard";
  setActive();
  const view = $("#view");
  view.innerHTML = `<div class="empty"><span class="spinner"></span> Загрузка…</div>`;
  try { await VIEWS[CURRENT](view); }
  catch (e) { view.innerHTML = `<div class="empty">Ошибка загрузки: ${esc(e.error || e.message || e)}</div>`; }
}
window.addEventListener("hashchange", route);
$("#refresh").onclick = route;

// ─── Общие рендер-хелперы ────────────────────────────────────────────────
function badge(on, textOn = "вкл", textOff = "выкл") {
  return `<span class="badge ${on ? "on" : "off"}">${on ? textOn : textOff}</span>`;
}
function stateDot(p) {
  const cls = p.running ? "on" : (p.installed ? "warn" : "off");
  return `<span class="dot ${cls}"></span>`;
}
function card(title, inner) { return `<div class="card"><h3>${title}</h3>${inner}</div>`; }

// Простая модалка с произвольным содержимым
function openModal(title, html) {
  const m = $("#task-modal"); $("#task-title").textContent = title;
  $("#task-log").textContent = ""; $("#task-status").textContent = "";
  $("#task-status").className = "task-status";
  // используем отдельный контейнер: заменяем лог на html
  $("#task-log").innerHTML = html; $("#task-log").style.whiteSpace = "normal";
  m.classList.remove("hidden");
}

// ═══════════════════════════════════════════════════════════════════════════
//  VIEWS
// ═══════════════════════════════════════════════════════════════════════════
const VIEWS = {};

// ── Дашборд ────────────────────────────────────────────────────────────────
VIEWS.dashboard = async (view) => {
  const d = await api("GET", "/api/dashboard");
  const sb = d.singbox, c = d.counts, sys = d.system || {};
  const pct = (v) => (v == null ? "—" : v + "%");
  view.innerHTML = `
    <div class="grid grid-3">
      ${card("Sing-Box", `<div class="stat"><div class="num">${sb.running ? "🟢" : "🔴"}</div>
        <div class="lbl">${sb.installed ? esc(sb.version || "установлен") : "не установлен"} · ${sb.running ? "запущен" : "остановлен"}</div></div>`)}
      ${card("Пользователи", `<div class="stat"><div class="num">${c.users.active}/${c.users.total}</div><div class="lbl">активных / всего</div></div>`)}
      ${card("Транспорты", `<div class="stat"><div class="num">${c.transports.active}/${c.transports.total}</div><div class="lbl">включено</div></div>`)}
      ${card("Службы", `<div class="stat"><div class="num">${c.enhancements.active}/${c.enhancements.total}</div><div class="lbl">DNSCrypt/WARP</div></div>`)}
      ${card("Безопасность", `<div class="stat"><div class="num">${c.security.active}/${c.security.total}</div><div class="lbl">fail2ban/honeypot/ipban</div></div>`)}
      ${card("CPU / RAM", `<div class="stat"><div class="num">${pct(sys.cpu_percent)}</div><div class="lbl">RAM: ${pct(sys.mem_percent)}${sys.mem_total ? " (" + fmtBytes(sys.mem_used) + "/" + fmtBytes(sys.mem_total) + ")" : ""}</div></div>`)}
    </div>
    <div class="section-title">Сеть</div>
    <div class="tbl-wrap"><table>
      <tr><td>Публичный IP</td><td class="code">${esc(d.network.public_ip || "—")}</td></tr>
      <tr><td>Домен</td><td>${esc(d.network.domain || "—")}</td></tr>
      <tr><td>Домен подписок</td><td>${esc(d.network.sub_domain || "—")}</td></tr>
    </table></div>
    <div class="section-title">Статус протоколов</div>
    <div class="tbl-wrap"><table><thead><tr><th>Плагин</th><th>Установлен</th><th>Включён</th><th>Запущен</th><th>Порт</th></tr></thead><tbody>
      ${Object.entries(d.protocols).map(([n, s]) => `<tr><td><b>${esc(n)}</b></td>
        <td>${badge(s.installed, "да", "нет")}</td><td>${badge(s.enabled)}</td>
        <td>${badge(s.running, "да", "нет")}</td><td>${s.port || "—"}</td></tr>`).join("")}
    </tbody></table></div>`;
};

// ── Ядро ─────────────────────────────────────────────────────────────────
VIEWS.core = async (view) => {
  const [s, panel] = await Promise.all([
    api("GET", "/api/system"),
    api("GET", "/api/system/panel").catch(() => ({ version: "?" })),
  ]);
  view.innerHTML = `
    <div class="grid grid-2">
      ${card("Веб-панель", `
        <p>Версия: <b>${esc(panel.version)}</b></p>
        <p class="muted">Источник: ${esc(panel.repo || "")} (${esc(panel.branch || "main")})</p>
        <p class="muted">Каталог: <span class="code">${esc(panel.install_dir || "")}</span></p>
        <div class="btn-row"><button class="btn" id="c-panel-update">⬆ Обновить панель</button></div>`)}
      ${card("Sing-Box", `
        <p>Статус: ${badge(s.running, "запущен", "остановлен")} ${badge(s.installed, "установлен", "нет")}</p>
        <p class="muted">Версия: ${esc(s.version || "—")}</p>
        <p class="muted">Конфиг: <span class="code">${esc(s.config_path)}</span></p>
        <div class="btn-row">
          <button class="btn" id="c-install">${s.installed ? "Переустановить" : "Установить"}</button>
          <button class="btn-ghost" id="c-start">Запустить</button>
          <button class="btn-ghost" id="c-stop">Остановить</button>
          <button class="btn-ghost" id="c-restart">Перезапустить</button>
        </div>`)}
      ${card("Конфигурация", `
        <p class="muted">Пересобрать и применить конфигурацию Sing-Box, nftables и мультиплексора.</p>
        <div class="btn-row"><button class="btn" id="c-apply">Применить конфиг</button></div>`)}
    </div>`;
  $("#c-install").onclick = () => runTask("Установка Sing-Box", () => api("POST", "/api/system/singbox/install", { force: s.installed }), route);
  $("#c-start").onclick = async () => { await api("POST", "/api/system/singbox/start"); toast("Запущено"); route(); };
  $("#c-stop").onclick = async () => { await api("POST", "/api/system/singbox/stop"); toast("Остановлено"); route(); };
  $("#c-restart").onclick = async () => { await api("POST", "/api/system/singbox/restart"); toast("Перезапущено"); route(); };
  $("#c-apply").onclick = () => runTask("Применение конфигурации", () => api("POST", "/api/system/apply"), route);
  $("#c-panel-update").onclick = () => {
    if (!confirm("Скачать свежую версию панели из форка и перезапустить службу?")) return;
    runTask("Обновление панели", () => api("POST", "/api/system/panel/update"), (task) => {
      const r = task.result || {};
      if (r.new_version) toast(`Панель обновлена: ${r.old_version} → ${r.new_version}. Переподключение…`, "ok", 8000);
      waitForReconnect();
    });
  };
};

// После обновления служба перезапускается — ждём, пока API снова ответит, и перезагружаем UI.
async function waitForReconnect() {
  const st = $("#task-status");
  for (let i = 0; i < 40; i++) {
    await new Promise(r => setTimeout(r, 1500));
    try {
      await api("GET", "/api/session");
      if (st) { st.className = "task-status ok"; st.textContent = "Панель перезапущена — обновляю…"; }
      setTimeout(() => location.reload(), 800);
      return;
    } catch (e) { /* ещё поднимается */ }
  }
}

// ── Протоколы ──────────────────────────────────────────────────────────────
function protoCard(p) {
  return `<div class="card"><div class="spread">
      <div><b>${stateDot(p)} ${esc(p.name)}</b> <span class="tag">${esc(p.category)}</span></div>
      ${badge(p.enabled)}
    </div>
    <p class="muted" style="margin:8px 0">${esc(p.description || "")}</p>
    <div class="btn-row">
      ${p.installed
      ? (p.enabled ? `<button class="btn-warn btn-sm" data-act="disable" data-n="${p.name}">Выключить</button>`
        : `<button class="btn-green btn-sm" data-act="enable" data-n="${p.name}">Включить</button>`)
      : `<button class="btn btn-sm" data-act="install" data-n="${p.name}">Установить</button>`}
      ${p.installed ? `<button class="btn-ghost btn-sm" data-act="config" data-n="${p.name}">Настроить</button>` : ""}
      ${p.installed ? `<button class="btn-ghost btn-sm" data-act="reinstall" data-n="${p.name}">Переустановить</button>` : ""}
      ${p.installed ? `<button class="btn-danger btn-sm" data-act="uninstall" data-n="${p.name}">Удалить</button>` : ""}
    </div></div>`;
}
VIEWS.protocols = async (view) => {
  const d = await api("GET", "/api/protocols");
  view.innerHTML = `
    <div class="section-title">Транспорты</div><div class="grid grid-2">${d.transports.map(protoCard).join("")}</div>
    <div class="section-title">Сетевые службы</div><div class="grid grid-2">${d.enhancements.map(protoCard).join("")}</div>
    <div class="section-title">Безопасность</div><div class="grid grid-2">${d.security.map(protoCard).join("")}</div>`;
  $$("[data-act]", view).forEach(b => b.onclick = () => protoAction(b.dataset.act, b.dataset.n));
};
async function protoAction(act, name) {
  if (act === "config") return openProtoConfig(name);
  if (act === "uninstall" && !confirm(`Удалить плагин ${name}?`)) return;
  const titles = { install: "Установка", uninstall: "Удаление", enable: "Включение", disable: "Выключение", reinstall: "Переустановка" };
  runTask(`${titles[act]} ${name}`, () => api("POST", `/api/protocols/${name}/${act}`), () => VIEWS.protocols($("#view")));
}

// Настройка конкретного плагина (мастера)
async function openProtoConfig(name) {
  const wizards = {
    amneziawg: awgWizard, mieru: mieruWizard, naive: transportWizard,
    trusttunnel: transportWizard, telemt: telemtWizard, wdtt: wdttWizard,
  };
  const fn = wizards[name] || genericPluginConfig;
  await fn(name);
}
async function genericPluginConfig(name) {
  const p = await api("GET", "/api/protocols/" + name);
  openModal("Плагин: " + name, `
    <p>${esc(p.description || "")}</p>
    <p class="muted">Установлен: ${p.installed ? "да" : "нет"} · Включён: ${p.enabled ? "да" : "нет"} · Порт: ${p.port || "—"}</p>
    <div class="btn-row"><button class="btn btn-sm" id="w-clients">Показать клиентов</button>
      <button class="btn-ghost btn-sm" id="w-sync">Пересоздать конфиги</button></div>
    <div id="w-body"></div>`);
  $("#w-clients").onclick = async () => {
    const r = await api("GET", `/api/protocols/${name}/clients`);
    $("#w-body").innerHTML = clientsTable(r.clients);
  };
  $("#w-sync").onclick = () => runTask("Синхронизация конфигов", () => api("POST", `/api/protocols/${name}/sync`));
}
function clientsTable(rows) {
  if (!rows || !rows.length) return `<p class="muted">Нет подключённых клиентов.</p>`;
  const keys = Object.keys(rows[0]);
  return `<div class="tbl-wrap"><table><thead><tr>${keys.map(k => `<th>${esc(k)}</th>`).join("")}</tr></thead><tbody>
    ${rows.map(r => `<tr>${keys.map(k => `<td>${esc(r[k])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

async function transportWizard(name) {
  openModal("Транспорт: " + name, `
    <p class="muted">Выберите сетевой режим транспорта.</p>
    <div class="btn-row">
      <button class="btn btn-sm" data-m="tcp">HTTP/2 (TCP)</button>
      <button class="btn btn-sm" data-m="quic">QUIC (UDP)</button>
      <button class="btn btn-sm" data-m="both">HTTP/2 + QUIC</button>
    </div>`);
  $$("#task-log [data-m]").forEach(b => b.onclick = () =>
    runTask("Смена транспорта", () => api("POST", `/api/plugins/${name}/transport`, { mode: b.dataset.m })));
}

async function mieruWizard() {
  const d = await api("GET", "/api/plugins/mieru/presets");
  openModal("Mieru — обфускация", `
    <p class="muted">Текущий пресет: <b>${esc(d.current || "—")}</b></p>
    <div class="field"><label>Пресет обфускации</label>
      <select class="input" id="mieru-preset">${d.presets.map(p =>
    `<option value="${esc(p.name || p)}">${esc(p.name || p)}${p.desc ? " — " + esc(p.desc) : ""}</option>`).join("")}</select></div>
    <button class="btn btn-sm" id="mieru-apply">Применить</button>`);
  $("#mieru-apply").onclick = () => runTask("Mieru пресет",
    () => api("POST", "/api/plugins/mieru/preset", { preset: $("#mieru-preset").value }));
}

async function awgWizard() {
  const [prof, opts] = await Promise.all([
    api("GET", "/api/plugins/amneziawg/profiles"),
    api("GET", "/api/plugins/amneziawg/obfuscation/options"),
  ]);
  const strategies = opts.strategies || [];
  const carriers = opts.carriers || [];
  openModal("AmneziaWG", `
    <div class="section-title">Профили</div>
    <div class="tbl-wrap"><table><thead><tr><th>Профиль</th><th>Интерфейс</th><th>Порт</th><th>Пресет</th></tr></thead><tbody>
      ${(prof.profiles || []).map(p => `<tr><td>${esc(p.label || p.name)}</td><td>${esc(p.interface || "")}</td>
        <td>${esc(p.port || "")}</td><td>${esc(p.preset || "")}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">Нет профилей</td></tr>`}
    </tbody></table></div>
    <div class="section-title">Обфускация</div>
    <div class="inline">
      <div class="field"><label>Профиль</label><select class="input" id="awg-prof">
        <option value="desktop">desktop</option><option value="mobile">mobile</option></select></div>
      <div class="field"><label>Стратегия</label><select class="input" id="awg-strat">
        ${strategies.map(s => `<option value="${esc(s.id || s.name || s)}">${esc(s.name || s.id || s)}</option>`).join("")}</select></div>
      <div class="field"><label>Оператор (моб.)</label><select class="input" id="awg-carrier">
        <option value="">— generic —</option>
        ${carriers.map(c => `<option value="${esc(c.id || c.name || c)}">${esc(c.name || c.id || c)}</option>`).join("")}</select></div>
      <button class="btn btn-sm" id="awg-preview">Предпросмотр</button>
      <button class="btn-green btn-sm" id="awg-rotate">Ротировать</button>
    </div>
    <pre id="awg-params" class="code" style="margin-top:10px;display:none"></pre>
    <div class="section-title">Профили и тюнинг</div>
    <div class="inline">
      <button class="btn-ghost btn-sm" id="awg-addmob">➕ Добавить мобильный профиль</button>
      <button class="btn-ghost btn-sm" id="awg-delmob">🗑 Удалить мобильный профиль</button>
      <button class="btn-ghost btn-sm" id="awg-tune">⚙️ Оптимизация VPS</button>
    </div>`);
  $("#awg-preview").onclick = async () => {
    const r = await api("POST", "/api/plugins/amneziawg/obfuscation/preview",
      { strategy: $("#awg-strat").value, carrier: $("#awg-carrier").value || null });
    const el = $("#awg-params"); el.style.display = "block"; el.textContent = JSON.stringify(r.params, null, 2);
  };
  $("#awg-rotate").onclick = () => runTask("Ротация обфускации", () =>
    api("POST", "/api/plugins/amneziawg/obfuscation/rotate",
      { profile: $("#awg-prof").value, strategy: $("#awg-strat").value, carrier: $("#awg-carrier").value || "" }));
  $("#awg-addmob").onclick = () => runTask("Добавление профиля", () =>
    api("POST", "/api/plugins/amneziawg/profiles",
      { name: "mobile", strategy: $("#awg-strat").value, carrier: $("#awg-carrier").value || "" }));
  $("#awg-delmob").onclick = () => runTask("Удаление профиля", () => api("DELETE", "/api/plugins/amneziawg/profiles/mobile"));
  $("#awg-tune").onclick = () => runTask("Оптимизация VPS", () => api("POST", "/api/plugins/amneziawg/tune"));
}

async function telemtWizard() {
  const d = await api("GET", "/api/plugins/telemt/config");
  const cfg = d.config || {};
  openModal("Telemt (MTProto)", `
    <p class="muted">Параметры конфигурации. Изменённые поля будут применены к сервису telemt.</p>
    <div class="field"><label>TLS-домен маскировки</label><input class="input" id="tm-domain" value="${esc(cfg.tls_domain || "")}"></div>
    <div class="inline">
      <div class="field"><label>Порт</label><input class="input" id="tm-port" value="${esc(cfg.port || "")}" style="width:120px"></div>
      <div class="field"><label>IP-режим</label><select class="input" id="tm-ip">
        ${["ipv4", "ipv6", "dual"].map(m => `<option ${cfg.ip_mode === m ? "selected" : ""}>${m}</option>`).join("")}</select></div>
    </div>
    <div class="btn-row">
      <button class="btn btn-sm" id="tm-save">Сохранить и применить</button>
      <button class="btn-ghost btn-sm" id="tm-restart">Перезапустить сервис</button>
    </div>
    <details style="margin-top:10px"><summary class="muted">Полный JSON config</summary>
      <textarea class="input" id="tm-json" style="min-height:160px">${esc(JSON.stringify(cfg, null, 2))}</textarea>
      <button class="btn-ghost btn-sm" id="tm-savejson" style="margin-top:8px">Сохранить JSON</button></details>`);
  $("#tm-save").onclick = () => runTask("Telemt reconfigure", () => api("PUT", "/api/plugins/telemt/config",
    { config: { tls_domain: $("#tm-domain").value, port: Number($("#tm-port").value) || cfg.port, ip_mode: $("#tm-ip").value } }));
  $("#tm-restart").onclick = () => api("POST", "/api/plugins/telemt/restart").then(() => toast("Перезапущено"));
  $("#tm-savejson").onclick = () => {
    let obj; try { obj = JSON.parse($("#tm-json").value); } catch (e) { return toast("Некорректный JSON", "err"); }
    runTask("Telemt reconfigure", () => api("PUT", "/api/plugins/telemt/config", { config: obj }));
  };
}

async function wdttWizard() {
  const d = await api("GET", "/api/plugins/wdtt/passwords");
  openModal("qWDTT — пароли", `
    <div class="inline">
      <div class="field"><label>Дней</label><input class="input" id="wd-days" value="30" style="width:90px"></div>
      <div class="field"><label>Устройств</label><input class="input" id="wd-dev" value="1" style="width:90px"></div>
      <div class="field"><label>VK хеш</label><input class="input" id="wd-vk" placeholder="необяз."></div>
      <button class="btn btn-sm" id="wd-create">Создать пароль</button>
    </div>
    <div class="btn-row"><button class="btn-ghost btn-sm" id="wd-main">Главная ссылка</button>
      <button class="btn-ghost btn-sm" id="wd-restart">Перезапустить</button></div>
    <div id="wd-list"></div>`);
  const renderList = (rows) => {
    $("#wd-list").innerHTML = `<div class="tbl-wrap"><table><thead><tr><th>Пароль</th><th>Устройств</th><th>Действует до</th><th></th></tr></thead><tbody>
      ${(rows || []).map(p => `<tr><td class="code">${esc(p.password)}</td><td>${p.max_devices}</td>
        <td>${p.expires_at ? new Date(p.expires_at * 1000).toLocaleDateString("ru-RU") : "—"}</td>
        <td><button class="btn-danger btn-sm" data-del="${esc(p.password)}">Удалить</button></td></tr>`).join("")
      || `<tr><td colspan="4" class="muted">Нет паролей</td></tr>`}</tbody></table></div>`;
    $$("#wd-list [data-del]").forEach(b => b.onclick = async () => {
      await api("DELETE", "/api/plugins/wdtt/passwords/" + encodeURIComponent(b.dataset.del)); toast("Удалено");
      const r = await api("GET", "/api/plugins/wdtt/passwords"); renderList(r.passwords);
    });
  };
  renderList(d.passwords);
  $("#wd-create").onclick = async () => {
    const r = await api("POST", "/api/plugins/wdtt/passwords",
      { days: Number($("#wd-days").value), max_devices: Number($("#wd-dev").value), vk_hash: $("#wd-vk").value });
    toast("Пароль создан"); prompt("Ссылка для клиента:", r.link);
    const l = await api("GET", "/api/plugins/wdtt/passwords"); renderList(l.passwords);
  };
  $("#wd-main").onclick = async () => { const r = await api("GET", "/api/plugins/wdtt/main-link"); prompt("Главная ссылка:", r.link); };
  $("#wd-restart").onclick = () => api("POST", "/api/plugins/wdtt/restart").then(() => toast("Перезапущено"));
}

// ── Пользователи ─────────────────────────────────────────────────────────
VIEWS.users = async (view) => {
  const d = await api("GET", "/api/users");
  view.innerHTML = `
    <div class="inline" style="margin-bottom:14px">
      <div class="field"><label>Новый пользователь (email/имя)</label><input class="input" id="u-email" placeholder="user@example.com"></div>
      <button class="btn" id="u-add">➕ Добавить</button>
    </div>
    <div class="tbl-wrap"><table><thead><tr><th>Пользователь</th><th>Трафик</th><th>Лимит</th><th>Действует до</th><th>Статус</th><th></th></tr></thead><tbody>
    ${d.users.map(u => {
      const used = fmtBytes(u.traffic_used_bytes);
      const lim = u.traffic_limit_gb ? u.traffic_limit_gb + " GiB" : "∞";
      const pctv = u.traffic_limit_bytes ? Math.min(100, u.traffic_used_bytes / u.traffic_limit_bytes * 100) : 0;
      const barcls = pctv >= 100 ? "err" : (pctv >= 80 ? "warn" : "");
      return `<tr>
        <td><b>${esc(u.email)}</b></td>
        <td>${used}${u.traffic_limit_bytes ? `<div class="bar" style="width:90px;margin-top:4px"><i class="${barcls}" style="width:${pctv}%"></i></div>` : ""}</td>
        <td>${lim}</td><td>${fmtDate(u.expiry_date)}</td>
        <td>${u.blocked ? '<span class="badge err">заблокирован</span>' : '<span class="badge on">активен</span>'}</td>
        <td class="flexrow">
          <button class="btn-ghost btn-sm" data-cfg="${esc(u.email)}">Конфиги</button>
          <button class="btn-ghost btn-sm" data-edit="${esc(u.email)}">✎</button>
          <button class="btn-warn btn-sm" data-block="${esc(u.email)}">${u.blocked ? "Разбл." : "Блок"}</button>
          <button class="btn-danger btn-sm" data-del="${esc(u.email)}">✕</button>
        </td></tr>`;
    }).join("") || `<tr><td colspan="6" class="empty">Пользователей нет</td></tr>`}
    </tbody></table></div>`;
  // Перерисовка списка с обработкой ошибки (чтобы список всегда обновлялся).
  const reload = async () => { try { await VIEWS.users(view); } catch (e) { toast("Не удалось обновить список: " + (e.error || e), "err"); } };
  $("#u-add").onclick = async () => {
    const email = $("#u-email").value.trim(); if (!email) return;
    const btn = $("#u-add"); btn.disabled = true;
    try { await api("POST", "/api/users", { email }); toast("Добавлен"); await reload(); }
    catch (e) { toast(e.error || "Ошибка добавления", "err"); btn.disabled = false; }
  };
  $$("[data-del]", view).forEach(b => b.onclick = async () => {
    if (!confirm("Удалить " + b.dataset.del + "?")) return;
    b.disabled = true;
    try { await api("DELETE", "/api/users/" + encodeURIComponent(b.dataset.del)); toast("Удалён"); await reload(); }
    catch (e) { toast(e.error || "Ошибка удаления", "err"); b.disabled = false; }
  });
  $$("[data-block]", view).forEach(b => b.onclick = async () => {
    const u = d.users.find(x => x.email === b.dataset.block);
    b.disabled = true;
    try {
      await api("POST", `/api/users/${encodeURIComponent(b.dataset.block)}/${u.blocked ? "unblock" : "block"}`);
      toast("Готово"); await reload();
    } catch (e) { toast(e.error || "Ошибка", "err"); b.disabled = false; }
  });
  $$("[data-edit]", view).forEach(b => b.onclick = () => editUser(d.users.find(x => x.email === b.dataset.edit), view));
  $$("[data-cfg]", view).forEach(b => b.onclick = () => showConfigs(b.dataset.cfg));
};
function editUser(u, view) {
  openModal("Пользователь: " + u.email, `
    <div class="field"><label>Лимит трафика (GiB, 0 = ∞)</label><input class="input" id="e-lim" value="${u.traffic_limit_gb || 0}"></div>
    <div class="field"><label>Действует до (YYYY-MM-DD, пусто = ∞)</label><input class="input" id="e-exp" value="${esc((u.expiry_date || "").split("T")[0])}"></div>
    <label class="flexrow"><input type="checkbox" id="e-unblock"> авто-разблокировать</label>
    <div class="btn-row"><button class="btn btn-sm" id="e-save">Сохранить</button></div>`);
  $("#e-save").onclick = async () => {
    const au = $("#e-unblock").checked;
    try {
      await api("PUT", `/api/users/${encodeURIComponent(u.email)}/limit`, { traffic_limit_gb: Number($("#e-lim").value), auto_unblock: au });
      await api("PUT", `/api/users/${encodeURIComponent(u.email)}/expiry`, { expiry_date: $("#e-exp").value, auto_unblock: au });
      toast("Сохранено"); $("#task-modal").classList.add("hidden");
      try { await VIEWS.users(view); } catch (e) { toast("Не удалось обновить список", "err"); }
    } catch (e) { toast(e.error || "Ошибка сохранения", "err"); }
  };
}
async function showConfigs(email) {
  const d = await api("GET", "/api/users/" + encodeURIComponent(email) + "/configs");
  let html = `<div class="field"><label>Ссылка подписки</label>
    <div class="flexrow"><span class="code" style="flex:1">${esc(d.subscription_url || "—")}</span>
    <button class="btn-ghost btn-sm" data-qr="${esc(d.subscription_url || "")}">QR</button></div></div>`;
  html += (d.protocols || []).map(p => `
    <div class="section-title">${esc(p.name)}</div>
    ${(p.links || []).map(l => `<div class="flexrow" style="margin-bottom:6px">
      <span class="code" style="flex:1">${esc(l)}</span>
      <button class="btn-ghost btn-sm" data-copy="${esc(l)}">Копир.</button>
      <button class="btn-ghost btn-sm" data-qr="${esc(l)}">QR</button></div>`).join("")}
    ${p.config ? `<details><summary class="muted">config</summary><pre class="code">${esc(p.config)}</pre></details>` : ""}`).join("");
  html += `<div id="qr-box" class="qr" style="margin-top:12px"></div>`;
  openModal("Конфиги: " + email, html);
  $$("#task-log [data-copy]").forEach(b => b.onclick = () => { navigator.clipboard.writeText(b.dataset.copy); toast("Скопировано"); });
  $$("#task-log [data-qr]").forEach(b => b.onclick = async () => {
    if (!b.dataset.qr) return;
    try { const r = await api("GET", "/api/qr?text=" + encodeURIComponent(b.dataset.qr)); $("#qr-box").innerHTML = r.svg; }
    catch (e) { toast(e.error || "QR недоступен", "err"); }
  });
}

// ── Мониторинг ─────────────────────────────────────────────────────────────
VIEWS.monitoring = async (view) => {
  view.innerHTML = tabsBar(["traffic", "connections", "system", "logs", "sync", "clash"],
    ["Трафик", "Подключения", "Система", "Логи", "Sync-агент", "Clash API"], "mon");
  const body = document.createElement("div"); body.id = "tabbody"; view.appendChild(body);
  wireTabs(view, "mon", (t) => monTab(t, body), "traffic");
};
async function monTab(t, body) {
  body.innerHTML = `<div class="empty"><span class="spinner"></span></div>`;
  if (t === "traffic") {
    const d = await api("GET", "/api/monitoring/traffic");
    body.innerHTML = `<div class="section-title">По протоколам</div><div class="tbl-wrap"><table><tbody>
      ${Object.entries(d.protocol_totals || {}).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${fmtBytes(v)}</td></tr>`).join("") || `<tr><td class="muted">Нет данных</td></tr>`}
      </tbody></table></div>
      <div class="section-title">По пользователям</div><div class="tbl-wrap"><table><thead><tr><th>Пользователь</th><th>Трафик</th><th>Лимит</th></tr></thead><tbody>
      ${d.users.map(u => `<tr><td>${esc(u.email)}</td><td>${fmtBytes(u.traffic_used_bytes)}</td><td>${u.traffic_limit_gb ? u.traffic_limit_gb + " GiB" : "∞"}</td></tr>`).join("")}
      </tbody></table></div>`;
  } else if (t === "connections") {
    const d = await api("GET", "/api/monitoring/connections");
    if (!d.clash_api_enabled) { body.innerHTML = `<div class="empty">Clash API выключен — включите его во вкладке «Clash API».</div>`; return; }
    body.innerHTML = `<p class="muted">Демон свежий: ${d.daemon_fresh ? "да" : "нет"}</p>` + clientsTable(d.connections);
  } else if (t === "system") {
    const d = await api("GET", "/api/monitoring/system"); const s = d.system;
    body.innerHTML = `<div class="grid grid-3">
      ${card("CPU", `<div class="stat"><div class="num">${s.cpu_percent == null ? "—" : s.cpu_percent + "%"}</div></div>`)}
      ${card("RAM", `<div class="stat"><div class="num">${s.mem_percent == null ? "—" : s.mem_percent + "%"}</div><div class="lbl">${s.mem_total ? fmtBytes(s.mem_used) + " / " + fmtBytes(s.mem_total) : ""}</div></div>`)}
      ${card("Диск", `<div class="stat"><div class="num">${s.disk_percent == null ? "—" : s.disk_percent + "%"}</div></div>`)}</div>`;
  } else if (t === "logs") {
    const d = await api("GET", "/api/monitoring/logs");
    body.innerHTML = `<div class="inline"><div class="field"><label>Лог</label><select class="input" id="log-sel">
      ${d.logs.map(l => `<option value="${l.key}" ${l.exists ? "" : "disabled"}>${esc(l.key)} ${l.exists ? "(" + fmtBytes(l.size) + ")" : "— нет"}</option>`).join("")}</select></div>
      <button class="btn btn-sm" id="log-load">Показать</button></div><pre id="log-out" class="task-log" style="max-height:420px;margin-top:12px"></pre>`;
    $("#log-load").onclick = async () => {
      const r = await api("GET", "/api/monitoring/logs/" + $("#log-sel").value + "?lines=300");
      $("#log-out").textContent = (r.lines || []).join("\n") || "(пусто)";
    };
  } else if (t === "sync") {
    const d = await api("GET", "/api/monitoring/sync-agent");
    body.innerHTML = `<p>Таймер (5 мин): ${badge(d.timer_active, "активен", "выключен")}</p>
      <p class="muted">Последняя запись: ${esc(d.last_log || "—")}</p>
      <div class="btn-row"><button class="btn btn-sm" id="sy-run">Запустить сейчас</button>
        <button class="btn-green btn-sm" id="sy-on">Включить таймер</button>
        <button class="btn-warn btn-sm" id="sy-off">Выключить таймер</button></div>`;
    $("#sy-run").onclick = () => runTask("Синхронизация", () => api("POST", "/api/monitoring/sync-agent/run"));
    $("#sy-on").onclick = async () => { await api("POST", "/api/monitoring/sync-agent/timer/enable"); toast("Таймер включён"); monTab("sync", body); };
    $("#sy-off").onclick = async () => { await api("POST", "/api/monitoring/sync-agent/timer/disable"); toast("Таймер выключен"); monTab("sync", body); };
  } else if (t === "clash") {
    const d = await api("GET", "/api/monitoring/clash-api");
    body.innerHTML = `<p>Clash API: ${badge(d.enabled)} · Демон: ${badge(d.daemon_active, "активен", "нет")}</p>
      <div class="inline">
        <div class="field"><label>Порт</label><input class="input" id="cl-port" value="${d.port}" style="width:120px"></div>
        <div class="field"><label>Секрет</label><input class="input" id="cl-secret" placeholder="${d.secret_set ? "•••• (задан)" : "не задан"}"></div>
      </div>
      <div class="btn-row"><button class="btn btn-sm" id="cl-toggle">${d.enabled ? "Выключить" : "Включить"}</button>
        <button class="btn-ghost btn-sm" id="cl-save">Сохранить порт/секрет</button></div>`;
    $("#cl-toggle").onclick = () => runTask("Clash API", () => api("PUT", "/api/monitoring/clash-api", { enabled: !d.enabled }), () => monTab("clash", body));
    $("#cl-save").onclick = () => runTask("Clash API", () => api("PUT", "/api/monitoring/clash-api",
      { port: Number($("#cl-port").value), secret: $("#cl-secret").value }), () => monTab("clash", body));
  }
}

// ── Безопасность ────────────────────────────────────────────────────────────
VIEWS.security = async (view) => {
  view.innerHTML = `<div class="btn-row">
      <button class="btn-green btn-sm" id="sec-all-on">Включить всё</button>
      <button class="btn-warn btn-sm" id="sec-all-off">Выключить всё</button></div>` +
    tabsBar(["fail2ban", "ipban", "honeypot"], ["Fail2ban", "IPBan", "Honeypot"], "sec");
  const body = document.createElement("div"); body.id = "secbody"; view.appendChild(body);
  $("#sec-all-on").onclick = () => runTask("Включение безопасности", () => api("POST", "/api/security/toggle-all", { enable: true }));
  $("#sec-all-off").onclick = () => runTask("Выключение безопасности", () => api("POST", "/api/security/toggle-all", { enable: false }));
  wireTabs(view, "sec", (t) => secTab(t, body), "fail2ban");
};
async function secTab(t, body) {
  body.innerHTML = `<div class="empty"><span class="spinner"></span></div>`;
  if (t === "fail2ban") {
    const d = await api("GET", "/api/security/fail2ban");
    body.innerHTML = `<p>Установлен: ${badge(d.installed, "да", "нет")} · Активен: ${badge(d.active, "да", "нет")}</p>
      <div class="inline">
        <div class="field"><label>Забанить (IP/CIDR/ASN, через пробел)</label><input class="input" id="f2b-ban" style="min-width:280px"></div>
        <button class="btn btn-sm" id="f2b-ban-btn">Забанить</button>
        <div class="field"><label>Разбанить IP</label><input class="input" id="f2b-unban"></div>
        <button class="btn-ghost btn-sm" id="f2b-unban-btn">Разбанить</button>
      </div>
      <div class="section-title">Джейлы</div><div class="tbl-wrap"><table><thead><tr><th>Джейл</th><th>Вкл</th><th>bantime</th><th>findtime</th><th>maxretry</th><th></th></tr></thead><tbody>
      ${Object.entries(d.jails || {}).map(([n, j]) => `<tr>
        <td>${esc(n)}</td><td>${badge(j.enabled === "true")}</td>
        <td><input class="input" style="width:90px" value="${esc(j.bantime)}" data-jf="bantime" data-jn="${n}"></td>
        <td><input class="input" style="width:90px" value="${esc(j.findtime)}" data-jf="findtime" data-jn="${n}"></td>
        <td><input class="input" style="width:70px" value="${esc(j.maxretry)}" data-jf="maxretry" data-jn="${n}"></td>
        <td><button class="btn-ghost btn-sm" data-jsave="${n}">Сохранить</button></td></tr>`).join("")}
      </tbody></table></div>
      <div class="section-title">Забаненные</div>
      <div class="tbl-wrap"><table><tbody>${Object.entries(d.banned || {}).map(([j, info]) =>
      `<tr><td>${esc(j)}</td><td>${esc(JSON.stringify(info))}</td></tr>`).join("") || `<tr><td class="muted">—</td></tr>`}</tbody></table></div>
      <div class="btn-row"><button class="btn-ghost btn-sm" id="f2b-restore">Восстановить дефолты</button>
        <button class="btn-ghost btn-sm" id="f2b-hist">История банов</button></div>`;
    $("#f2b-ban-btn").onclick = async () => { const r = await api("POST", "/api/security/fail2ban/ban", { targets: $("#f2b-ban").value }); toast(`Забанено: ${r.banned}`); };
    $("#f2b-unban-btn").onclick = async () => { const r = await api("POST", "/api/security/fail2ban/unban", { ips: $("#f2b-unban").value }); toast(`Разбанено: ${r.unbanned}`); };
    $$("[data-jsave]", body).forEach(b => b.onclick = () => {
      const n = b.dataset.jsave, payload = {};
      $$(`[data-jn="${n}"]`, body).forEach(i => payload[i.dataset.jf] = i.value);
      runTask("Настройка джейла", () => api("PUT", "/api/security/fail2ban/jail/" + n, payload), () => secTab("fail2ban", body));
    });
    $("#f2b-restore").onclick = () => runTask("Восстановление", () => api("POST", "/api/security/fail2ban/restore-defaults"), () => secTab("fail2ban", body));
    $("#f2b-hist").onclick = async () => { const r = await api("GET", "/api/security/fail2ban/history"); openModal("История банов", `<pre class="code">${esc(JSON.stringify(r.history, null, 2))}</pre>`); };
  } else if (t === "ipban") {
    const d = await api("GET", "/api/security/ipban");
    body.innerHTML = `<p class="muted">Забанено записей: ${d.count}</p>
      <div class="inline"><div class="field"><label>Забанить (IP/CIDR/range/ASN)</label><input class="input" id="ip-ban"></div>
        <div class="field"><label>Комментарий</label><input class="input" id="ip-com"></div>
        <button class="btn btn-sm" id="ip-ban-btn">Забанить</button>
        <button class="btn-warn btn-sm" id="ip-flush">Снять все</button></div>
      <div class="tbl-wrap"><table><thead><tr><th>Запись</th><th>Комментарий</th><th></th></tr></thead><tbody>
      ${(d.banned || []).map(e => `<tr><td class="code">${esc(e.display || e.cidr || e.ip || JSON.stringify(e))}</td>
        <td>${esc(e.comment || "")}</td><td><button class="btn-danger btn-sm" data-unban="${esc(e.display || e.cidr || e.ip)}">✕</button></td></tr>`).join("")
      || `<tr><td colspan="3" class="muted">Нет записей</td></tr>`}</tbody></table></div>`;
    $("#ip-ban-btn").onclick = async () => { await api("POST", "/api/security/ipban/ban", { target: $("#ip-ban").value, comment: $("#ip-com").value }); toast("Забанено"); secTab("ipban", body); };
    $("#ip-flush").onclick = async () => { if (!confirm("Снять ВСЕ баны?")) return; await api("POST", "/api/security/ipban/flush"); toast("Очищено"); secTab("ipban", body); };
    $$("[data-unban]", body).forEach(b => b.onclick = async () => { await api("DELETE", "/api/security/ipban/ban/" + encodeURIComponent(b.dataset.unban)); toast("Разбанено"); secTab("ipban", body); });
  } else if (t === "honeypot") {
    const d = await api("GET", "/api/security/honeypot");
    body.innerHTML = `<p>Запущен: ${badge(d.running, "да", "нет")} · Порт: ${esc(d.port)}</p>
      <div class="inline"><div class="field"><label>Порт</label><input class="input" id="hp-port" value="${esc(d.port)}" style="width:120px"></div>
        <button class="btn btn-sm" id="hp-port-btn">Изменить порт</button></div>
      <div class="section-title">Whitelist</div>
      <div class="inline"><div class="field"><label>IP/CIDR</label><input class="input" id="hp-wl"></div>
        <button class="btn-ghost btn-sm" id="hp-wl-add">Добавить</button></div>
      <div class="tbl-wrap"><table><tbody>${(d.whitelist || []).map(w => `<tr><td class="code">${esc(w)}</td>
        <td><button class="btn-ghost btn-sm" data-wlrm="${esc(w)}">✕</button></td></tr>`).join("")}</tbody></table></div>
      <div class="section-title">Пойманные IP</div>
      <div class="tbl-wrap"><table><tbody>${(d.banned || []).map(ip => `<tr><td class="code">${esc(ip)}</td>
        <td><button class="btn-ghost btn-sm" data-hpunban="${esc(ip)}">Разбанить</button></td></tr>`).join("") || `<tr><td class="muted">—</td></tr>`}</tbody></table></div>`;
    $("#hp-port-btn").onclick = async () => { await api("PUT", "/api/security/honeypot/port", { port: Number($("#hp-port").value) }); toast("Порт изменён"); secTab("honeypot", body); };
    $("#hp-wl-add").onclick = async () => { await api("POST", "/api/security/honeypot/whitelist", { action: "add", value: $("#hp-wl").value }); toast("Добавлено"); secTab("honeypot", body); };
    $$("[data-wlrm]", body).forEach(b => b.onclick = async () => { await api("POST", "/api/security/honeypot/whitelist", { action: "remove", value: b.dataset.wlrm }); secTab("honeypot", body); });
    $$("[data-hpunban]", body).forEach(b => b.onclick = async () => { await api("DELETE", "/api/security/honeypot/ban/" + encodeURIComponent(b.dataset.hpunban)); toast("Разбанено"); secTab("honeypot", body); });
  }
}

// ── Сетевые службы ──────────────────────────────────────────────────────────
VIEWS.network = async (view) => {
  view.innerHTML = tabsBar(["dnscrypt", "warp"], ["DNSCrypt", "WARP"], "net");
  const body = document.createElement("div"); body.id = "netbody"; view.appendChild(body);
  wireTabs(view, "net", (t) => netTab(t, body), "dnscrypt");
};
async function netTab(t, body) {
  body.innerHTML = `<div class="empty"><span class="spinner"></span></div>`;
  if (t === "dnscrypt") {
    const d = await api("GET", "/api/network/dnscrypt");
    body.innerHTML = `<p>Статус: ${badge(d.status.enabled)} · Запущен: ${badge(d.status.running, "да", "нет")}</p>
      <div class="field"><label>Текущие резолверы</label><textarea class="input" id="dc-names">${esc((d.server_names || []).join("\n"))}</textarea></div>
      <div class="btn-row"><button class="btn-ghost btn-sm" id="dc-measure">Измерить задержки</button>
        <button class="btn btn-sm" id="dc-apply">Применить резолверы</button></div>
      <div id="dc-res"></div>`;
    $("#dc-measure").onclick = () => runTask("Измерение резолверов", () => api("POST", "/api/network/dnscrypt/resolvers/measure"), (task) => {
      const r = task.result || {}; $("#dc-res").innerHTML = `<div class="tbl-wrap"><table><thead><tr><th>Резолвер</th><th>RTT, мс</th></tr></thead><tbody>
        ${(r.resolvers || []).map(x => `<tr><td>${esc(x.name)}</td><td>${x.rtt_ms}</td></tr>`).join("")}</tbody></table></div>`;
    });
    $("#dc-apply").onclick = async () => { await api("PUT", "/api/network/dnscrypt/resolvers", { server_names: $("#dc-names").value.split(/\s+/).filter(Boolean) }); toast("Применено"); };
  } else if (t === "warp") {
    const d = await api("GET", "/api/network/warp");
    const targetSel = (key, cur) => `<select class="input" data-route="${esc(key)}">
      ${["none", ...d.destinations].map(x => `<option ${x === cur ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>`;
    body.innerHTML = `<p>Статус: ${badge(d.status.enabled)} · Профилей релеев: ${(d.profiles || []).length}</p>
      <div class="btn-row"><button class="btn-ghost btn-sm" id="warp-ext">Обновить внешние списки</button></div>
      <div class="section-title">Локальные списки</div>
      <div class="inline"><div class="field"><label>Новый список</label><input class="input" id="warp-newlist"></div>
        <button class="btn btn-sm" id="warp-addlist">Создать</button></div>
      <div class="tbl-wrap"><table><thead><tr><th>Список</th><th>Домены/IP</th><th>Маршрут</th><th></th></tr></thead><tbody>
      ${Object.entries(d.local_lists || {}).map(([n, v]) => `<tr><td><b>${esc(n)}</b></td>
        <td>${(v.domains || []).length} / ${(v.ips || []).length}</td>
        <td>${targetSel("local:" + n, d.list_targets["local:" + n] || "none")}</td>
        <td><button class="btn-ghost btn-sm" data-editlist="${esc(n)}">✎</button>
          ${n === "default" ? "" : `<button class="btn-danger btn-sm" data-dellist="${esc(n)}">✕</button>`}</td></tr>`).join("")}
      </tbody></table></div>
      <div class="section-title">Внешние источники</div>
      <div class="tbl-wrap"><table><thead><tr><th>Источник</th><th>Описание</th><th>Маршрут</th></tr></thead><tbody>
      ${Object.entries(d.external_lists || {}).map(([k, v]) => `<tr><td><b>${esc(v.name)}</b></td>
        <td class="muted">${esc(v.desc || "")}</td><td>${targetSel("ext:" + k, d.list_targets["ext:" + k] || "none")}</td></tr>`).join("")}
      </tbody></table></div>`;
    $("#warp-ext").onclick = () => runTask("Обновление списков WARP", () => api("POST", "/api/network/warp/external/update"));
    $("#warp-addlist").onclick = async () => { await api("POST", "/api/network/warp/local-lists", { name: $("#warp-newlist").value }); toast("Создан"); netTab("warp", body); };
    $$("[data-route]", body).forEach(s => s.onchange = () => runTask("Маршрутизация WARP",
      () => api("PUT", "/api/network/warp/routing", { key: s.dataset.route, target: s.value })));
    $$("[data-dellist]", body).forEach(b => b.onclick = async () => { if (!confirm("Удалить список?")) return; await api("DELETE", "/api/network/warp/local-lists/" + b.dataset.dellist); toast("Удалён"); netTab("warp", body); });
    $$("[data-editlist]", body).forEach(b => b.onclick = () => editWarpList(b.dataset.editlist, d.local_lists[b.dataset.editlist], body));
  }
}
function editWarpList(name, val, body) {
  openModal("Список WARP: " + name, `
    <div class="field"><label>Домены (по одному в строке)</label><textarea class="input" id="wl-dom">${esc((val.domains || []).join("\n"))}</textarea></div>
    <div class="field"><label>IP/CIDR (по одному в строке)</label><textarea class="input" id="wl-ip">${esc((val.ips || []).join("\n"))}</textarea></div>
    <button class="btn btn-sm" id="wl-save">Сохранить</button>`);
  $("#wl-save").onclick = async () => {
    await api("PUT", "/api/network/warp/local-lists/" + name, {
      domains: $("#wl-dom").value.split(/\s+/).filter(Boolean),
      ips: $("#wl-ip").value.split(/\s+/).filter(Boolean),
    });
    toast("Сохранено"); $("#task-modal").classList.add("hidden"); netTab("warp", body);
  };
}

// ── Telegram ────────────────────────────────────────────────────────────────
VIEWS.telegram = async (view) => {
  const d = await api("GET", "/api/telegram");
  view.innerHTML = `<div class="grid grid-2">
    ${card("Токены", `
      <div class="field"><label>Admin-токен ${d.admin_token_set ? "(" + esc(d.admin_token_masked) + ")" : ""}</label><input class="input" id="tg-at" placeholder="изменить…"></div>
      <div class="field"><label>Admin Chat ID</label><input class="input" id="tg-cid" value="${esc(d.admin_chat_id)}"></div>
      <div class="field"><label>Client-токен ${d.bot_token_set ? "(" + esc(d.bot_token_masked) + ")" : ""}</label><input class="input" id="tg-bt" placeholder="изменить…"></div>
      <button class="btn btn-sm" id="tg-save">Сохранить</button>`)}
    ${card("Боты", `
      <p>Admin-бот: ${badge(d.admin_running, "запущен", "остановлен")}</p>
      <p>Client-бот: ${badge(d.client_running, "запущен", "остановлен")}</p>
      <div class="btn-row">
        <button class="btn-green btn-sm" id="tg-admin-start">Запустить admin</button>
        <button class="btn-green btn-sm" id="tg-client-start">Запустить client</button>
        <button class="btn-warn btn-sm" id="tg-stop">Остановить всех</button></div>`)}
  </div>`;
  $("#tg-save").onclick = async () => {
    const payload = { admin_chat_id: $("#tg-cid").value };
    if ($("#tg-at").value) payload.admin_token = $("#tg-at").value;
    if ($("#tg-bt").value) payload.bot_token = $("#tg-bt").value;
    await api("PUT", "/api/telegram", payload); toast("Сохранено"); VIEWS.telegram(view);
  };
  $("#tg-admin-start").onclick = async () => { try { await api("POST", "/api/telegram/admin/start"); toast("Запущен"); VIEWS.telegram(view); } catch (e) { toast(e.error, "err"); } };
  $("#tg-client-start").onclick = async () => { try { await api("POST", "/api/telegram/client/start"); toast("Запущен"); VIEWS.telegram(view); } catch (e) { toast(e.error, "err"); } };
  $("#tg-stop").onclick = async () => { await api("POST", "/api/telegram/stop"); toast("Остановлены"); VIEWS.telegram(view); };
};

// ── Подписки ────────────────────────────────────────────────────────────────
VIEWS.subscriptions = async (view) => {
  const d = await api("GET", "/api/subscriptions");
  view.innerHTML = card("Сервер подписок (hydra-sub, :9443)", `
    <p>Статус: ${badge(d.running, "активен", "остановлен")}</p>
    <p class="muted">Сертификат: ${d.cert_present ? esc(d.cert) : "отсутствует (нужен для HTTPS)"}</p>
    <div class="field"><label>Домен подписок</label><input class="input" id="sub-domain" value="${esc(d.sub_domain)}" placeholder="sub.example.com"></div>
    <div class="btn-row">
      <button class="btn-green btn-sm" id="sub-start">Запустить</button>
      <button class="btn-warn btn-sm" id="sub-stop">Остановить</button>
      <button class="btn-ghost btn-sm" id="sub-restart">Перезапустить</button>
      <button class="btn-ghost btn-sm" id="sub-savedomain">Сохранить домен</button>
      <button class="btn btn-sm" id="sub-cert">Выпустить SSL (certbot)</button>
    </div>`);
  $("#sub-start").onclick = async () => { try { await api("POST", "/api/subscriptions/start"); toast("Запущен"); VIEWS.subscriptions(view); } catch (e) { toast(e.error, "err"); } };
  $("#sub-stop").onclick = async () => { await api("POST", "/api/subscriptions/stop"); toast("Остановлен"); VIEWS.subscriptions(view); };
  $("#sub-restart").onclick = async () => { try { await api("POST", "/api/subscriptions/restart"); toast("Перезапущен"); } catch (e) { toast(e.error, "err"); } };
  $("#sub-savedomain").onclick = async () => { await api("PUT", "/api/subscriptions/domain", { sub_domain: $("#sub-domain").value }); toast("Сохранено"); VIEWS.subscriptions(view); };
  $("#sub-cert").onclick = () => runTask("Выпуск сертификата", () => api("POST", "/api/subscriptions/certbot"), () => VIEWS.subscriptions(view));
};

// ── Диагностика ─────────────────────────────────────────────────────────────
VIEWS.diagnostics = async (view) => {
  view.innerHTML = `<div class="grid grid-3">
    ${diagCard("geoip", "GeoIP и сервисы", "IP, ASN, стриминги/ИИ")}
    ${diagCard("censorcheck", "Geoblock", "Доступ к медиа", { mode: "geoblock" })}
    ${diagCard("censorcheck-dpi", "DPI (РФ)", "Блокировки в РФ", { mode: "dpi", ep: "censorcheck" })}
    ${diagCard("tspu", "ТСПУ-радар", "RIPE Atlas, порт 443")}
    ${diagCard("speedtest", "Speedtest", "HTTP скорость")}
    ${diagCard("cpu", "CPU (sysbench)", "Производительность CPU")}
    ${diagCard("report", "Полный отчёт", "Markdown-отчёт")}
  </div><div id="diag-out" style="margin-top:16px"></div>`;
  $$("[data-diag]", view).forEach(b => b.onclick = () => {
    const ep = b.dataset.ep || b.dataset.diag; const mode = b.dataset.mode;
    runTask("Диагностика: " + b.dataset.diag, () => api("POST", "/api/diagnostics/" + ep, mode ? { mode } : undefined),
      (task) => { $("#diag-out").innerHTML = `<pre class="task-log" style="max-height:460px">${esc(typeof task.result === "string" ? task.result : JSON.stringify(task.result, null, 2))}</pre>`; });
  });
};
function diagCard(id, title, desc, opts = {}) {
  return `<div class="card"><b>${esc(title)}</b><p class="muted" style="margin:8px 0">${esc(desc)}</p>
    <button class="btn btn-sm" data-diag="${id}" ${opts.ep ? `data-ep="${opts.ep}"` : ""} ${opts.mode ? `data-mode="${opts.mode}"` : ""}>Запустить</button></div>`;
}

// ── Табы (общий помощник) ───────────────────────────────────────────────────
function tabsBar(ids, labels, ns) {
  return `<div class="btn-row" data-tabs="${ns}">${ids.map((id, i) =>
    `<button class="btn-ghost btn-sm" data-tab="${id}">${esc(labels[i])}</button>`).join("")}</div>`;
}
function wireTabs(view, ns, render, first) {
  const btns = $$(`[data-tabs="${ns}"] [data-tab]`, view);
  const activate = (t) => { btns.forEach(b => b.classList.toggle("btn", b.dataset.tab === t)); render(t); };
  btns.forEach(b => b.onclick = () => activate(b.dataset.tab));
  activate(first);
}

// ─── Boot ────────────────────────────────────────────────────────────────
async function boot() {
  buildNav();
  try {
    const s = await api("GET", "/api/session");
    ME = s.username; $("#whoami").textContent = "👤 " + ME;
    $("#panel-host").textContent = location.host;
    api("GET", "/api/system/panel").then(p => {
      $("#panel-host").textContent = location.host + " · v" + p.version;
    }).catch(() => { });
    showApp();
    if (!location.hash) location.hash = "dashboard";
    route();
  } catch (e) { showLogin(); }
}
boot();
