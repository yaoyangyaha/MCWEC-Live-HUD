const rows = document.getElementById("rows");
const statusEl = document.getElementById("status");
const titleEl = document.getElementById("title");
const logoImageEl = document.getElementById("logoImage");
const logoMarkEl = document.getElementById("logoMark");
const sessionEl = document.getElementById("session");
const trackEl = document.getElementById("track");
const remainingLapsEl = document.getElementById("remainingLaps");
const leaderNameEl = document.getElementById("leaderName");
const leaderSubEl = document.getElementById("leaderSub");
const flagBannerEl = document.getElementById("flagBanner");
const flagLabelEl = document.getElementById("flagLabel");
const flagMessageEl = document.getElementById("flagMessage");
const centerBannerEl = document.getElementById("centerBanner");
const centerBannerTagEl = document.getElementById("centerBannerTag");
const centerBannerTitleEl = document.getElementById("centerBannerTitle");
const centerBannerMessageEl = document.getElementById("centerBannerMessage");
const noticeStackEl = document.getElementById("noticeStack");
const eventCountEl = document.getElementById("eventCount");
const updatedAtEl = document.getElementById("updatedAt");
let latestState = null;
let greenBannerTimer = null;
let lastBannerMode = "";

const FLAG_CLASS_MAP = {
  green: "flag-green",
  yellow: "flag-yellow",
  red: "flag-red",
  sc: "flag-sc",
  safety_car: "flag-sc",
  vsc: "flag-vsc",
  virtual_safety_car: "flag-vsc"
};

function formatMs(value) {
  if (value === null || value === undefined) {
    return "--";
  }
  const totalMs = Number(value);
  const minutes = Math.floor(totalMs / 60000);
  const seconds = Math.floor((totalMs % 60000) / 1000);
  const milliseconds = totalMs % 1000;
  return `${minutes}:${String(seconds).padStart(2, "0")}.${String(milliseconds).padStart(3, "0")}`;
}

function formatGap(driver) {
  if (driver.position === 1) {
    return "LEADER";
  }
  if (driver.gap_to_leader_ms === null || driver.gap_to_leader_ms === undefined) {
    return "+1L";
  }
  return `+${(driver.gap_to_leader_ms / 1000).toFixed(3)}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderFlag(state) {
  const flagClass = FLAG_CLASS_MAP[state.flag_state] || "flag-green";
  flagBannerEl.className = `flag-banner ${flagClass}`;
  flagLabelEl.textContent = state.flag_label || "GREEN FLAG";
  flagMessageEl.textContent = state.flag_message || "Track clear";

  const bannerMode = state.final_lap_active ? "final-lap" : (state.flag_state || "green");
  centerBannerEl.className = `center-banner ${flagClass}`;
  centerBannerTagEl.textContent = state.final_lap_active ? "Race Status" : "Race Control";
  centerBannerTitleEl.textContent = state.final_lap_active ? "FINAL LAP" : (state.flag_label || "GREEN FLAG");
  centerBannerMessageEl.textContent = state.final_lap_active
    ? `${state.leader || "Leader"} is on the final lap`
    : (state.flag_message || "Track clear");

  if (greenBannerTimer) {
    window.clearTimeout(greenBannerTimer);
    greenBannerTimer = null;
  }

  const greenVisibleUntil = (state.flag_changed_at_ms || 0) + 10000;
  const greenShouldShow = state.flag_state === "green" && Date.now() < greenVisibleUntil;
  const shouldShow = state.final_lap_active || state.flag_state !== "green" || greenShouldShow;

  if (state.flag_state === "green" && !greenShouldShow) {
    flagBannerEl.classList.add("hidden");
  } else {
    flagBannerEl.classList.remove("hidden");
  }

  if (shouldShow) {
    centerBannerEl.classList.remove("hidden");
  } else {
    centerBannerEl.classList.add("hidden");
  }

  if (shouldShow && bannerMode !== lastBannerMode) {
    centerBannerEl.classList.remove("banner-green-enter", "banner-alert", "banner-scan");
    void centerBannerEl.offsetWidth;

    if (state.final_lap_active || state.flag_state === "red") {
      centerBannerEl.classList.add("banner-alert", "banner-scan");
    } else if (state.flag_state === "sc" || state.flag_state === "safety_car" || state.flag_state === "vsc" || state.flag_state === "virtual_safety_car") {
      centerBannerEl.classList.add("banner-alert", "banner-scan");
    } else if (state.flag_state === "yellow") {
      centerBannerEl.classList.add("banner-alert");
    } else if (state.flag_state === "green") {
      centerBannerEl.classList.add("banner-green-enter");
    }
  }

  if (!state.final_lap_active && state.flag_state === "green" && greenShouldShow) {
    greenBannerTimer = window.setTimeout(() => {
      if (latestState) {
        renderFlag(latestState);
      }
    }, Math.max(greenVisibleUntil - Date.now(), 0) + 10);
  }

  lastBannerMode = shouldShow ? bannerMode : "";
}

function renderNotices(state) {
  const notices = state.notices || [];
  noticeStackEl.innerHTML = notices.slice(0, 3).map((notice) => `
    <div class="notice-card accent-${escapeHtml(notice.accent || "neutral")}">
      <div class="notice-title">${escapeHtml(notice.title)}</div>
      <div class="notice-message">${escapeHtml(notice.message)}</div>
    </div>
  `).join("");
}

function render(state) {
  latestState = state;
  const globalBestLap = state.global_best_lap_ms ?? null;

  titleEl.textContent = state.title;
  if (state.logo_url) {
    logoImageEl.src = state.logo_url;
    logoImageEl.classList.remove("hidden");
    logoMarkEl.classList.add("hidden");
  } else {
    logoImageEl.removeAttribute("src");
    logoImageEl.classList.add("hidden");
    logoMarkEl.classList.remove("hidden");
  }
  sessionEl.textContent = state.session;
  trackEl.textContent = state.track_name;
  remainingLapsEl.textContent = state.final_lap_active ? "FL" : (state.remaining_laps ?? "--");
  eventCountEl.textContent = state.total_events;
  updatedAtEl.textContent = state.updated_at_ms
    ? new Date(state.updated_at_ms).toLocaleTimeString()
    : "-";

  renderFlag(state);
  renderNotices(state);

  const leader = state.drivers[0];
  leaderNameEl.textContent = leader ? leader.player : "Waiting...";
  leaderSubEl.textContent = leader
    ? `${state.final_lap_active ? "FINAL LAP" : `Lap ${leader.lap}/${state.total_laps || "--"}`}  BEST ${formatMs(leader.best_lap_ms)}`
    : "等待过线事件";

  rows.innerHTML = state.drivers.map((driver) => {
    const fastest = driver.best_lap_ms !== null && driver.best_lap_ms === globalBestLap;
    return `
      <div class="board-row ${driver.position === 1 ? "top" : ""} ${driver.in_pit ? "pit" : ""} ${fastest ? "fastest" : ""}">
        <div class="position-pill">${driver.position}</div>
        <div class="driver-cell">
          <div class="driver-name">${escapeHtml(driver.player)}</div>
          <div class="driver-source">
            <span>LAST ${formatMs(driver.lap_time_ms)}</span>
            <span class="${fastest ? "best-lap-chip" : ""}">BEST ${formatMs(driver.best_lap_ms)}</span>
            ${driver.in_pit ? '<span class="pit-chip">PIT</span>' : ""}
          </div>
        </div>
        <div class="board-stat">${driver.lap}</div>
        <div class="board-gap ${driver.position === 1 ? "top" : (fastest ? "best" : "")}">${driver.in_pit ? "PIT" : formatGap(driver)}</div>
      </div>
    `;
  }).join("");
}

function connect() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${window.location.host}/ws/hud`);

  ws.addEventListener("open", () => {
    statusEl.textContent = "Connected";
  });

  ws.addEventListener("message", (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "state") {
      render(payload.payload);
    }
  });

  ws.addEventListener("close", () => {
    statusEl.textContent = "Reconnecting...";
    window.setTimeout(connect, 1500);
  });
}

fetch("/api/state")
  .then((response) => response.json())
  .then((state) => render(state))
  .catch(() => {});

connect();
