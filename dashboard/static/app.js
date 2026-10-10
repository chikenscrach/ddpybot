"use strict";

const $ = (selector) => document.querySelector(selector);
const state = {
  view: "overview",
  session: null,
  overview: null,
  music: null,
  settings: null,
  dirty: false,
  busy: false,
  polling: false,
};
const titles = {
  overview: "總覽",
  ping: "Ping 分析",
  music: "音樂播放",
  settings: "設定",
};
const statusNames = {
  idle: "待命",
  playing: "播放中",
  paused: "已暫停",
  downloading: "下載中",
  stopped: "已停止",
  disconnected: "已離線",
};
const number = (n) => Number(n || 0).toLocaleString("zh-TW");
const duration = (n) =>
  `${Math.floor(Math.max(0, n || 0) / 60)}:${String(Math.floor(Math.max(0, n || 0) % 60)).padStart(2, "0")}`;
const bytes = (n) => `${((n || 0) / 1048576).toFixed(1)} MB`;
const dateTime = (n) =>
  n
    ? new Intl.DateTimeFormat("zh-TW", {
        timeZone: "Asia/Taipei",
        dateStyle: "short",
        timeStyle: "short",
      }).format(new Date(n * 1000))
    : "無時間紀錄";
function el(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}
function replace(selector, ...items) {
  $(selector).replaceChildren(...items);
}
function notice(text, failure = false) {
  const box = $("#notice");
  box.textContent = text;
  box.classList.toggle("failure", failure);
  box.hidden = !text;
}
function safeUrl(raw) {
  try {
    const url = new URL(raw);
    return url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}
function online(ok) {
  $("#connection-dot").classList.toggle("offline", !ok);
  $("#connection-text").textContent = ok ? "已連線" : "連線中斷";
  if (ok)
    $("#updated-at").textContent = new Date().toLocaleTimeString("zh-TW", {
      hour12: false,
    });
}

async function api(path, options = {}) {
  const headers = { ...options.headers };
  if (options.body) headers["Content-Type"] = "application/json";
  if (options.method && options.method !== "GET")
    headers["X-CSRF-Token"] = state.session?.csrf_token || "";
  const response = await fetch(path, {
    ...options,
    headers,
    credentials: "same-origin",
    cache: "no-store",
    signal: AbortSignal.timeout(30000),
  });
  const data = await response
    .json()
    .catch(() => ({ error: "伺服器回傳格式錯誤。" }));
  if (!response.ok) {
    if (response.status === 401 && state.session) {
      state.session = null;
      $("#console").hidden = true;
      $("#login").hidden = false;
      $("#login-error").textContent = "登入已到期，請重新登入。";
    }
    const error = new Error(data.error || `操作失敗（${response.status}）`);
    error.status = response.status;
    throw error;
  }
  online(true);
  return data;
}

function confirmAction(title, message) {
  const dialog = $("#confirm-dialog");
  $("#confirm-title").textContent = title;
  $("#confirm-message").textContent = message;
  return new Promise((resolve) => {
    let accepted = false;
    $("#confirm-ok").onclick = () => {
      accepted = true;
      dialog.close();
    };
    $("#confirm-cancel").onclick = () => dialog.close();
    dialog.onclose = () => resolve(accepted);
    dialog.showModal();
  });
}

function metric(label, value, unit, detail) {
  const box = el("div", "metric");
  const val = el("div", "metric-value", value);
  val.append(el("span", "metric-unit", unit));
  box.append(
    el("div", "metric-label", label),
    val,
    el("p", "metric-detail", detail),
  );
  return box;
}

function updateGuildOptions(guilds) {
  for (const id of ["#music-guild", "#ping-guild"]) {
    const select = $(id);
    const selected = select.value;
    const ids = guilds.map((g) => g.id).join(",");
    if (select.dataset.ids === ids) continue;
    select.dataset.ids = ids;
    select.replaceChildren();
    if (id === "#ping-guild") select.add(new Option("全部伺服器", ""));
    guilds.forEach((g) => select.add(new Option(g.name, g.id)));
    if ([...select.options].some((o) => o.value === selected))
      select.value = selected;
  }
}

async function loadOverview() {
  const data = await api("/api/overview");
  state.overview = data;
  updateGuildOptions(data.guilds);
  $("#connection-text").textContent = data.ready ? "Bot 已就緒" : "Bot 連線中";
  replace(
    "#metrics",
    metric("Gateway 延遲", data.latency_ms ?? "—", "ms", "Discord 即時連線"),
    metric(
      "持續運行",
      Math.floor(data.uptime_seconds / 3600),
      "小時",
      `${Math.floor(data.uptime_seconds / 60) % 60} 分鐘 · 自本次啟動`,
    ),
    metric(
      "程序記憶體",
      (data.memory_bytes / 1048576).toFixed(0),
      "MB",
      `CPU ${data.cpu_percent.toFixed(1)}%`,
    ),
    metric(
      "歷來標記",
      data.ping_total === null ? "—" : number(data.ping_total),
      "次",
      `${data.active_players} 個語音連線`,
    ),
  );
  $("#guild-count").textContent = number(data.guilds.length);
  const guildNodes = data.guilds.map((g) => {
    const row = el("div", "guild-row");
    const icon = el("div", "guild-icon", g.name.slice(0, 1));
    if (safeUrl(g.icon)) {
      const img = el("img");
      img.src = g.icon;
      img.alt = "";
      icon.replaceChildren(img);
    }
    const info = el("div");
    info.append(
      el("strong", "", g.name),
      el("p", "small muted", `${number(g.member_count)} 位成員`),
    );
    row.append(icon, info, el("span", "status-dot"));
    return row;
  });
  replace(
    "#guild-list",
    ...(guildNodes.length
      ? guildNodes
      : [el("div", "empty", "Bot 尚未加入伺服器。")]),
  );
  replace("#modules", ...data.cogs.map((name) => el("span", "tag", name)));
  $("#cache-size").textContent = data.cache
    ? bytes(data.cache.bytes)
    : "音樂模組未載入";
  $("#cache-meter").style.width =
    `${data.cache ? Math.min(100, (data.cache.bytes / data.cache.max_bytes) * 100) : 0}%`;
  $("#cache-detail").textContent = data.cache
    ? `${number(data.cache.files)} 個音檔 · ${data.cache.pinned_files} 個使用中 / 上限 ${bytes(data.cache.max_bytes)}`
    : "";
  $("#clear-cache").disabled = !data.cache || state.busy;
}

function pingQuery() {
  return new URLSearchParams({
    start: $("#ping-start").value,
    end: $("#ping-end").value,
    source: "scheduled",
    guild_id: $("#ping-guild").value,
  });
}
function table(headers, rows) {
  if (!rows.length) return el("div", "empty", "這個區間沒有紀錄。");
  const result = el("table");
  const head = el("thead");
  const tr = el("tr");
  headers.forEach((h) => tr.append(el("th", "", h)));
  head.append(tr);
  const body = el("tbody");
  rows.forEach((row) => {
    const item = el("tr");
    row.forEach((value) => item.append(el("td", "", value)));
    body.append(item);
  });
  result.append(head, body);
  return result;
}
function leaders(rows) {
  if (!rows.length) return [el("div", "empty", "尚無標記紀錄。")];
  return rows.map((row, i) => {
    const line = el("div", "leader-row");
    const count = el("span", "leader-score", number(row.count));
    count.append(el("small", "", "次"));
    line.append(
      el("span", "rank", String(i + 1).padStart(2, "0")),
      el("span", "leader-name", row.name),
      count,
    );
    return line;
  });
}
async function loadPing() {
  const query = pingQuery();
  const data = await api(`/api/ping?${query}`);
  $("#export-ping").href = `/api/ping/export?${query}`;
  $("#history-note").textContent =
    `明細自 ${dateTime(data.history_started_at)} 開始記錄（起始日可能不完整）。升級前 ${number(data.legacy_total)} 次只保留在歷來累計；更早日期沒有可分析的明細。`;
  replace(
    "#ping-metrics",
    metric(
      "區間標記",
      number(data.period_total),
      "次",
      `${data.start} — ${data.end}`,
    ),
    metric("被標記成員", number(data.unique_users), "人", "目前篩選區間"),
    metric(
      "歷來總數",
      number(data.lifetime_total),
      "次",
      "所有伺服器，包含舊資料",
    ),
    metric("舊資料累計", number(data.legacy_total), "次", "沒有逐次明細的紀錄"),
  );
  replace("#period-leaders", ...leaders(data.leaders));
  replace("#lifetime-leaders", ...leaders(data.lifetime_leaders));
  replace(
    "#ping-events",
    table(
      ["時間（台北）", "成員", "伺服器 ID"],
      data.events.map((r) => [
        dateTime(r.event_at),
        r.name,
        r.guild_id || "未知",
      ]),
    ),
  );
}

function renderMusic(data) {
  state.music = data;
  const song = data?.current;
  $("#music-status").textContent = statusNames[data?.status] || "待命";
  $("#music-channel").textContent = data?.voice_channel_id
    ? `♫ ${data.voice_channel_name || data.voice_channel_id}`
    : "尚未加入語音頻道";
  $("#song-title").textContent = song?.title || "等待下一首好歌";
  $("#song-requester").textContent = song
    ? `點歌者 · ${song.requester_name || song.requester_id || "未知"}`
    : "在 Discord 使用 /play 開始播放。";
  const imageUrl = safeUrl(song?.thumbnail);
  const currentImage = $("#album img");
  if (imageUrl) {
    if (!currentImage || currentImage.src !== imageUrl) {
      currentImage?.remove();
      const img = el("img");
      img.src = imageUrl;
      img.alt = "";
      img.onerror = () => img.remove();
      $("#album").append(img);
    }
  } else currentImage?.remove();
  $("#song-elapsed").textContent = duration(data?.elapsed_seconds);
  $("#song-duration").textContent = duration(song?.duration);
  $("#song-progress").style.width =
    `${song?.duration ? Math.min(100, (data.elapsed_seconds / song.duration) * 100) : 0}%`;
  $("#pause-music").textContent =
    data?.status === "paused" ? "繼續播放" : "暫停";
  $("#pause-music").disabled =
    state.busy || !["playing", "paused"].includes(data?.status);
  document.querySelectorAll("[data-action]").forEach((button) => {
    button.disabled =
      state.busy ||
      !data?.session_id ||
      (button.dataset.action === "skip" && !song);
  });
  $("#loop-mode").value = data?.loop_mode || "off";
  $("#loop-mode").disabled = state.busy || (!song && !data?.queue.length);
  $("#queue-count").textContent = data?.queue.length || 0;
  const queue = (data?.queue || []).map((s, i) => {
    const row = el("div", "queue-row");
    const info = el("div", "queue-song");
    info.append(
      el("strong", "", s.title),
      el(
        "small",
        "",
        `點歌者 · ${s.requester_name || s.requester_id || "未知"}`,
      ),
    );
    row.append(
      el("span", "rank", String(i + 1).padStart(2, "0")),
      info,
      el("span", "queue-duration", duration(s.duration)),
    );
    return row;
  });
  replace(
    "#queue-list",
    ...(queue.length
      ? queue
      : [el("div", "empty", "待播清單目前是空的。\n下一首，交給你。")]),
  );
}
async function loadMusic() {
  const guild = $("#music-guild").value;
  if (!guild) {
    renderMusic(null);
    return;
  }
  const data = await api(`/api/music/${encodeURIComponent(guild)}`);
  if ($("#music-guild").value === guild) renderMusic(data);
}
async function controlMusic(action, mode) {
  if (state.busy || !state.music?.session_id) return;
  const data = state.music;
  const guild = data.guild_id;
  if (
    ["stop", "leave"].includes(action) &&
    !(await confirmAction(
      action === "stop" ? "停止並清空待播清單？" : "離開語音頻道？",
      "目前播放會停止，待播清單與循環模式會重設。",
    ))
  )
    return;
  state.busy = true;
  renderMusic(state.music);
  try {
    await api(`/api/music/${guild}/control`, {
      method: "POST",
      body: JSON.stringify({
        action,
        session_id: data.session_id,
        generation: data.generation,
        ...(mode ? { mode } : {}),
      }),
    });
    notice("音樂操作已完成。");
  } catch (error) {
    notice(error.message, true);
  } finally {
    state.busy = false;
    await loadMusic().catch((error) => notice(error.message, true));
  }
}

const settingsGroups = [
  [
    "基本設定",
    "GENERAL",
    [
      [
        "DAILY_CHANNEL_ID",
        "每日標記頻道 ID",
        "id",
        "留空停用每日排程；排程固定為台北時間 00:00。",
      ],
      [
        "moderator_ids",
        "Bot 管理員 ID",
        "ids",
        "每行一個 ID。這份清單不會授予 dashboard 存取權。",
      ],
    ],
  ],
  [
    "AI 對話",
    "AI PROVIDER",
    [
      [
        "AI_PROVIDER",
        "供應商",
        "provider",
        "請先在 .env 設定對應供應商的 API Key。",
      ],
      ["OPENROUTER_MODEL", "OpenRouter 模型", "text", "輸入完整模型名稱。"],
      ["GROQ_MODEL", "Groq 模型", "text", "輸入完整模型名稱。"],
    ],
  ],
  [
    "播放與佇列",
    "MUSIC",
    [
      ["MUSIC.max_duration_seconds", "單曲長度上限（秒）", "number", ""],
      [
        "MUSIC.max_queue_size",
        "待播歌曲上限",
        "number",
        "每個伺服器共用這項限制。",
      ],
      ["MUSIC.max_playlist_items", "單次播放清單上限", "number", ""],
      [
        "MUSIC.empty_channel_grace_seconds",
        "空頻道離開等待（秒）",
        "number",
        "可設為 0。",
      ],
    ],
  ],
  [
    "快取管理",
    "CACHE",
    [
      ["MUSIC.max_cache_mb", "快取容量上限（MB）", "number", ""],
      [
        "MUSIC.max_file_mb",
        "單檔大小上限（MB）",
        "number",
        "不可大於快取容量上限。",
      ],
      [
        "MUSIC.cache_ttl_hours",
        "未使用音檔保存（小時）",
        "decimal",
        "可設為 0。",
      ],
      ["MUSIC.cleanup_interval_seconds", "自動清理間隔（秒）", "number", ""],
      [
        "MUSIC.auto_cleanup",
        "啟用自動清理",
        "boolean",
        "關閉後可在總覽手動清理。",
      ],
    ],
  ],
  [
    "進階音樂設定",
    "ADVANCED",
    [
      [
        "MUSIC.cache_dir",
        "快取目錄",
        "text",
        "使用專用目錄；相對路徑以專案根目錄為準。",
      ],
      ["MUSIC.download_timeout_seconds", "下載逾時（秒）", "number", ""],
      ["MUSIC.ffmpeg_executable", "FFmpeg 執行檔", "text", ""],
      ["MUSIC.js_runtime", "JavaScript runtime", "text", ""],
      [
        "MUSIC.cookies_file",
        "YouTube cookies 檔案路徑",
        "optional",
        "留空停用。此處僅設定路徑，不傳送檔案內容。",
      ],
      [
        "MUSIC.youtube_player_client",
        "YouTube client",
        "optional",
        "留空使用預設值。",
      ],
      [
        "MUSIC.pot_provider_url",
        "PO Token provider URL",
        "optional",
        "選填；填寫時須啟用下方外掛並安裝 provider。",
      ],
      ["MUSIC.allow_ytdlp_plugins", "允許 yt-dlp 外掛", "boolean", ""],
    ],
  ],
];
const fieldDefinitions = settingsGroups.flatMap((g) => g[2]);
function getValue(object, path) {
  return path.split(".").reduce((value, key) => value?.[key], object);
}
function setValue(object, path, value) {
  const parts = path.split(".");
  if (parts.length === 2) {
    object[parts[0]] ||= {};
    object[parts[0]][parts[1]] = value;
  } else object[path] = value;
}
function fieldId(path) {
  return `setting-${path.replaceAll(".", "-")}`;
}
function renderSettings(data) {
  state.settings = data;
  state.dirty = false;
  const sections = settingsGroups.map(([title, eyebrow, fields]) => {
    const section = el("section", "panel settings-section");
    const heading = el("div", "panel-heading");
    const text = el("div");
    text.append(el("p", "eyebrow", eyebrow), el("h2", "", title));
    heading.append(text);
    const grid = el("div", "settings-grid");
    fields.forEach(([path, label, kind, hint]) => {
      const wrapper = el(
        "label",
        `settings-field${kind === "boolean" ? " checkbox" : ""}`,
        label,
      );
      wrapper.htmlFor = fieldId(path);
      const input = el(
        kind === "ids" ? "textarea" : kind === "provider" ? "select" : "input",
      );
      input.id = fieldId(path);
      input.dataset.path = path;
      input.dataset.kind = kind;
      const value = getValue(data.values, path);
      if (kind === "provider")
        ["openrouter", "groq"].forEach((p) => input.add(new Option(p, p)));
      if (kind === "boolean") {
        input.type = "checkbox";
        input.checked = Boolean(value);
      } else {
        input.value = kind === "ids" ? (value || []).join("\n") : (value ?? "");
        if (["number", "decimal"].includes(kind)) {
          input.type = "number";
          input.min =
            path.endsWith("empty_channel_grace_seconds") || kind === "decimal"
              ? "0"
              : "1";
          input.step = kind === "decimal" ? "any" : "1";
          input.required = true;
        } else if (kind === "id") {
          input.type = "text";
          input.inputMode = "numeric";
          input.pattern = "[0-9]*";
        } else if (kind === "text") {
          input.type = "text";
          input.required = true;
        }
      }
      const active = getValue(data.active_values, path);
      let help = hint;
      if (JSON.stringify(active) !== JSON.stringify(value))
        help += ` 目前生效：${Array.isArray(active) ? active.join("、") : active === null ? "未設定" : active === true ? "開啟" : active === false ? "關閉" : active}`;
      wrapper.append(input, el("span", "hint", help));
      grid.append(wrapper);
    });
    section.append(heading, grid);
    return section;
  });
  replace("#settings-fields", ...sections);
  const pending = $("#pending-settings");
  pending.hidden = !data.pending_restart.length;
  if (data.pending_restart.length) {
    const tags = el("div", "tags");
    data.pending_restart.forEach((p) =>
      tags.append(
        el("span", "tag", fieldDefinitions.find((f) => f[0] === p)?.[1] || p),
      ),
    );
    pending.replaceChildren(
      el(
        "p",
        "",
        `${data.pending_restart.length} 項設定已儲存，等待重啟 Bot 生效。`,
      ),
      tags,
    );
  }
  $("#settings-status").textContent = data.pending_restart.length
    ? "已儲存 · 等待重啟生效"
    : "設定與目前運行狀態一致";
}
async function loadSettings() {
  renderSettings(await api("/api/settings"));
}
async function saveSettings(event) {
  event.preventDefault();
  const button = $("#save-settings");
  button.disabled = true;
  try {
    const values = {};
    document.querySelectorAll("[data-path]").forEach((input) => {
      let value = input.value.trim();
      const kind = input.dataset.kind;
      if (kind === "boolean") value = input.checked;
      else if (kind === "ids")
        value = value ? value.split(/[\s,，]+/).filter(Boolean) : [];
      else if (kind === "number" || kind === "decimal") value = Number(value);
      else if (kind === "optional" || kind === "id") value = value || null;
      setValue(values, input.dataset.path, value);
    });
    const result = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify({ values, revision: state.settings.revision }),
    });
    renderSettings(result);
    notice("設定已儲存。請在方便時重啟 Bot 套用變更。");
  } catch (error) {
    notice(
      error.status === 409
        ? "設定已被其他頁面或外部程式更新。請先保留你的修改，再重新讀取。"
        : error.message,
      true,
    );
  } finally {
    button.disabled = false;
  }
}

async function switchView(view) {
  if (
    state.view === "settings" &&
    state.dirty &&
    view !== "settings" &&
    !(await confirmAction(
      "離開設定頁？",
      "尚未儲存的變更會保留在這個頁面，重新載入網站則會失去變更。",
    ))
  )
    return;
  state.view = view;
  $("#page-title").textContent = titles[view];
  notice("");
  document
    .querySelectorAll(".view")
    .forEach((item) => (item.hidden = item.id !== `view-${view}`));
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
    if (button.dataset.view === view)
      button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  try {
    if (view === "overview") await loadOverview();
    if (view === "music") await loadMusic();
    if (view === "ping") await loadPing();
    if (view === "settings" && !state.dirty) await loadSettings();
  } catch (error) {
    notice(error.message, true);
  }
}

document
  .querySelectorAll("[data-view]")
  .forEach((button) =>
    button.addEventListener("click", () => switchView(button.dataset.view)),
  );
$("#ping-filter").addEventListener("submit", async (event) => {
  event.preventDefault();
  await loadPing().catch((error) => notice(error.message, true));
});
$("#music-guild").addEventListener("change", () => {
  renderMusic(null);
  loadMusic().catch((error) => notice(error.message, true));
});
$("#pause-music").addEventListener("click", () =>
  controlMusic(state.music?.status === "paused" ? "resume" : "pause"),
);
document
  .querySelectorAll("[data-action]")
  .forEach((button) =>
    button.addEventListener("click", () => controlMusic(button.dataset.action)),
  );
$("#loop-mode").addEventListener("change", (event) =>
  controlMusic("loop", event.target.value),
);
$("#settings-form").addEventListener("submit", saveSettings);
$("#settings-form").addEventListener("input", () => {
  state.dirty = true;
  $("#settings-status").textContent = "有尚未儲存的變更";
});
$("#reload-settings").addEventListener("click", async () => {
  if (
    !state.dirty ||
    (await confirmAction("重新讀取設定？", "尚未儲存的變更將被捨棄。"))
  )
    await loadSettings().catch((error) => notice(error.message, true));
});
$("#logout").addEventListener("click", async () => {
  if (
    state.dirty &&
    !(await confirmAction("登出？", "尚未儲存的設定將被捨棄。"))
  )
    return;
  try {
    await api("/auth/logout", { method: "POST" });
    state.dirty = false;
    location.assign("/");
  } catch (error) {
    notice(error.message, true);
  }
});
$("#clear-cache").addEventListener("click", async () => {
  if (
    state.busy ||
    !(await confirmAction(
      "清理未使用的快取？",
      "刪除未使用的已下載音檔；目前播放與預載中的檔案會保留。",
    ))
  )
    return;
  state.busy = true;
  $("#clear-cache").disabled = true;
  try {
    const result = await api("/api/cache/clear", {
      method: "POST",
      body: JSON.stringify({ confirm: true }),
    });
    notice(
      `已清理 ${result.removed_files} 個音檔，釋放 ${bytes(result.freed_bytes)}。`,
    );
  } catch (error) {
    notice(error.message, true);
  } finally {
    state.busy = false;
    await loadOverview().catch((error) => notice(error.message, true));
  }
});
window.addEventListener("beforeunload", (event) => {
  if (state.dirty) {
    event.preventDefault();
    event.returnValue = "";
  }
});

async function bootstrap() {
  const today = new Date();
  const taipei = new Date(today.getTime() + 8 * 3600000);
  $("#ping-end").value = taipei.toISOString().slice(0, 10);
  taipei.setUTCDate(taipei.getUTCDate() - 29);
  $("#ping-start").value = taipei.toISOString().slice(0, 10);
  try {
    state.session = await api("/api/session");
    $("#owner-name").textContent = state.session.user.name;
    $("#login").hidden = true;
    $("#console").hidden = false;
    await loadOverview();
  } catch (error) {
    if (![401, 403].includes(error.status))
      $("#login-error").textContent = error.message;
    else if (error.status === 403)
      $("#login-error").textContent = "這個管理空間僅限 Bot owner 存取。";
  }
}
let ticks = 0;
setInterval(async () => {
  if (!state.session || state.polling || state.busy || document.hidden) return;
  state.polling = true;
  try {
    if (state.view === "overview" || ++ticks % 5 === 0) await loadOverview();
    if (state.view === "music") await loadMusic();
  } catch (error) {
    online(false);
    if (error.status !== 401) notice(error.message, true);
  } finally {
    state.polling = false;
  }
}, 3000);
bootstrap();
