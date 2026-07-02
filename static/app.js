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
const rowElements = new Map();
const noticeElements = new Map();
const FLAG_BANNER_VISIBLE_MS = 10000;

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

function animateEntry(element, className) {
  element.classList.remove(className);
  void element.offsetWidth;
  element.classList.add(className);
  window.setTimeout(() => {
    element.classList.remove(className);
  }, 260);
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

  const greenVisibleUntil = (state.flag_changed_at_ms || 0) + FLAG_BANNER_VISIBLE_MS;
  const greenShouldShow = state.flag_state === "green" && Date.now() < greenVisibleUntil;
  const shouldShow = state.final_lap_active || state.flag_state !== "green" || greenShouldShow;
  const flagBannerVisibleUntil = (state.flag_changed_at_ms || 0) + FLAG_BANNER_VISIBLE_MS;
  const flagBannerShouldShow = Date.now() < flagBannerVisibleUntil;

  if (!flagBannerShouldShow) {
    flagBannerEl.classList.add("is-collapsed");
  } else {
    flagBannerEl.classList.remove("is-collapsed");
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

  if (flagBannerShouldShow || (!state.final_lap_active && state.flag_state === "green" && greenShouldShow)) {
    greenBannerTimer = window.setTimeout(() => {
      if (latestState) {
        renderFlag(latestState);
      }
    }, Math.max(Math.max(flagBannerVisibleUntil, greenVisibleUntil) - Date.now(), 0) + 10);
  }

  lastBannerMode = shouldShow ? bannerMode : "";
}

function renderNotices(state) {
  const notices = state.notices || [];
  const nextKeys = new Set();
  const fragment = document.createDocumentFragment();

  notices.slice(0, 3).forEach((notice) => {
    const key = `${notice.created_at_ms || 0}:${notice.title || ""}:${notice.message || ""}`;
    nextKeys.add(key);

    let card = noticeElements.get(key);
    if (!card) {
      card = document.createElement("div");
      card.innerHTML = '<div class="notice-title"></div><div class="notice-message"></div>';
      noticeElements.set(key, card);
      animateEntry(card, "enter");
    }

    card.className = `notice-card accent-${notice.accent || "neutral"}`;
    card.querySelector(".notice-title").textContent = notice.title || "";
    card.querySelector(".notice-message").textContent = notice.message || "";
    fragment.appendChild(card);
  });

  for (const [key, element] of noticeElements) {
    if (!nextKeys.has(key)) {
      noticeElements.delete(key);
      element.remove();
    }
  }

  noticeStackEl.replaceChildren(fragment);
}

function renderRows(state, globalBestLap) {
  const nextPlayers = new Set();
  const fragment = document.createDocumentFragment();

  state.drivers.forEach((driver) => {
    nextPlayers.add(driver.player);
    const fastest = driver.best_lap_ms !== null && driver.best_lap_ms === globalBestLap;
    let row = rowElements.get(driver.player);

    if (!row) {
      row = document.createElement("div");
      row.innerHTML = `
        <div class="position-pill"></div>
        <div class="driver-cell">
          <div class="driver-name"></div>
          <div class="driver-source">
            <span class="last-lap"></span>
            <span class="best-lap"></span>
            <span class="pit-chip hidden">PIT</span>
          </div>
        </div>
        <div class="board-stat"></div>
        <div class="board-gap"></div>
      `;
      rowElements.set(driver.player, row);
      animateEntry(row, "enter");
    }

    row.className = `board-row ${driver.position === 1 ? "top" : ""} ${driver.in_pit ? "pit" : ""} ${fastest ? "fastest" : ""}`.trim();
    row.querySelector(".position-pill").textContent = String(driver.position ?? "");
    row.querySelector(".driver-name").textContent = driver.player || "";
    row.querySelector(".last-lap").textContent = `LAST ${formatMs(driver.lap_time_ms)}`;

    const bestLapEl = row.querySelector(".best-lap");
    bestLapEl.textContent = `BEST ${formatMs(driver.best_lap_ms)}`;
    bestLapEl.className = fastest ? "best-lap-chip best-lap" : "best-lap";

    const pitChipEl = row.querySelector(".pit-chip");
    pitChipEl.className = driver.in_pit ? "pit-chip" : "pit-chip hidden";

    row.querySelector(".board-stat").textContent = String(driver.lap ?? "");

    const gapEl = row.querySelector(".board-gap");
    gapEl.textContent = driver.in_pit ? "PIT" : formatGap(driver);
    gapEl.className = `board-gap ${driver.position === 1 ? "top" : (fastest ? "best" : "")}`.trim();

    fragment.appendChild(row);
  });

  for (const [player, element] of rowElements) {
    if (!nextPlayers.has(player)) {
      rowElements.delete(player);
      element.remove();
    }
  }

  rows.replaceChildren(fragment);
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
  renderRows(state, globalBestLap);

  const leader = state.drivers[0];
  leaderNameEl.textContent = leader ? leader.player : "Waiting...";
  leaderSubEl.textContent = leader
    ? `${state.final_lap_active ? "FINAL LAP" : `Lap ${leader.lap}/${state.total_laps || "--"}`}  BEST ${formatMs(leader.best_lap_ms)}`
    : "Waiting for timing data";
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
