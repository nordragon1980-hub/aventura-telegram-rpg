const telegram = window.Telegram && window.Telegram.WebApp;
if (telegram) {
  telegram.ready();
  telegram.expand();
}

const elements = {
  viewport: document.getElementById("mapViewport"),
  cityMap: document.getElementById("cityMap"),
  markers: document.getElementById("missionMarkers"),
  mapStatus: document.getElementById("mapStatus"),
  backdrop: document.getElementById("modalBackdrop"),
  panel: document.getElementById("missionPanel"),
  turnTitle: document.getElementById("turnTitle"),
  type: document.getElementById("missionType"),
  title: document.getElementById("missionTitle"),
  difficulty: document.getElementById("missionDifficulty"),
  participants: document.getElementById("missionParticipants"),
  description: document.getElementById("missionDescription"),
  joinHint: document.getElementById("joinHint"),
  close: document.getElementById("closePanel"),
};

let selectedMarker = null;

function telegramInitData() {
  if (telegram && telegram.initData) {
    return telegram.initData;
  }
  const launchParams = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  return launchParams.get("tgWebAppData") || "";
}

function missionTypeLabel(mission) {
  if (mission.type === "boss" && mission.subtype === "phased") {
    return "!!! БОСС !!!";
  }
  if (mission.type === "deadly_trial") {
    return "Смертельное испытание";
  }
  return "Миссия";
}

function showMission(mission, marker) {
  if (selectedMarker) {
    selectedMarker.classList.remove("is-selected");
  }
  selectedMarker = marker;
  marker.classList.add("is-selected");
  elements.type.textContent = missionTypeLabel(mission);
  elements.panel.classList.toggle("boss", mission.type === "boss");
  elements.title.textContent = mission.title;
  elements.difficulty.textContent = `Сложность: ${mission.difficulty}`;
  elements.participants.textContent =
    `Участники: ${mission.participants_count}/${mission.participants_limit}`;
  elements.description.textContent = mission.description;
  elements.joinHint.textContent = `Вступить через бота: /join ${mission.id}`;
  elements.backdrop.hidden = false;
  elements.close.focus();
}

function closeMission() {
  elements.backdrop.hidden = true;
  elements.panel.classList.remove("boss");
  if (selectedMarker) {
    selectedMarker.classList.remove("is-selected");
    selectedMarker.focus();
    selectedMarker = null;
  }
}

function centerMap(missions) {
  const focus = missions.length
    ? missions.reduce(
        (total, mission) => ({ x: total.x + mission.x, y: total.y + mission.y }),
        { x: 0, y: 0 },
      )
    : { x: 50, y: 53 };
  const x = missions.length ? focus.x / missions.length : focus.x;
  const y = missions.length ? focus.y / missions.length : focus.y;
  elements.viewport.scrollTo({
    left: (elements.cityMap.scrollWidth * x) / 100 - elements.viewport.clientWidth / 2,
    top: (elements.cityMap.scrollHeight * y) / 100 - elements.viewport.clientHeight / 2,
  });
}

function renderState(state) {
  elements.turnTitle.textContent = state.turn ? state.turn.title : "Нет открытого хода";
  elements.markers.replaceChildren();
  if (!state.missions.length) {
    elements.mapStatus.textContent = "На карте сейчас нет открытых миссий.";
    elements.mapStatus.hidden = false;
    requestAnimationFrame(() => centerMap([]));
    return;
  }
  elements.mapStatus.hidden = true;
  state.missions.forEach((mission) => {
    const marker = document.createElement("button");
    marker.type = "button";
    marker.className = "marker marker-pin-layout";
    const pin = document.createElement("span");
    pin.className = "marker-pin";
    const number = document.createElement("span");
    number.className = "marker-number";
    if (mission.type === "boss") {
      marker.classList.add("boss");
    } else if (mission.type === "deadly_trial") {
      marker.classList.add("danger");
    }
    number.textContent = mission.type === "boss" ? `БОСС ${mission.id}` : String(mission.id);
    pin.appendChild(number);
    marker.appendChild(pin);
    marker.style.left = `${mission.x}%`;
    marker.style.top = `${mission.y}%`;
    marker.setAttribute("aria-label", `Миссия ${mission.id}: ${mission.title}`);
    marker.addEventListener("click", () => showMission(mission, marker));
    elements.markers.appendChild(marker);
  });
  requestAnimationFrame(() => centerMap(state.missions));
}

async function loadState() {
  const initData = telegramInitData();
  const query = initData ? `?init_data=${encodeURIComponent(initData)}` : "";
  try {
    const response = await fetch(`/api/tanellorn/state${query}`);
    if (response.status === 403) {
      throw new Error("Доступ мастера не подтвержден. Открой карту из свежей кнопки бота.");
    }
    if (!response.ok) {
      throw new Error("Карта сейчас недоступна.");
    }
    renderState(await response.json());
  } catch (error) {
    elements.mapStatus.textContent = error.message;
    elements.mapStatus.hidden = false;
  }
}

elements.close.addEventListener("click", closeMission);
elements.backdrop.addEventListener("click", (event) => {
  if (event.target === elements.backdrop) {
    closeMission();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !elements.backdrop.hidden) {
    closeMission();
  }
});

loadState();
