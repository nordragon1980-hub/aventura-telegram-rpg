const telegram = window.Telegram && window.Telegram.WebApp;
if (telegram) {
  telegram.ready();
  telegram.expand();
}

const elements = {
  markers: document.getElementById("missionMarkers"),
  mapStatus: document.getElementById("mapStatus"),
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
  elements.title.textContent = mission.title;
  elements.difficulty.textContent = `Сложность: ${mission.difficulty}`;
  elements.participants.textContent =
    `Участники: ${mission.participants_count}/${mission.participants_limit}`;
  elements.description.textContent = mission.description;
  elements.joinHint.textContent =
    `Для вступления пока используй в боте: /join ${mission.id}`;
  elements.panel.hidden = false;
}

function renderState(state) {
  elements.turnTitle.textContent = state.turn ? state.turn.title : "Нет открытого хода";
  elements.markers.replaceChildren();
  if (!state.missions.length) {
    elements.mapStatus.textContent = "На карте сейчас нет открытых миссий.";
    elements.mapStatus.hidden = false;
    return;
  }
  elements.mapStatus.hidden = true;
  state.missions.forEach((mission) => {
    const marker = document.createElement("button");
    marker.type = "button";
    marker.className = "marker";
    if (mission.type === "boss") {
      marker.classList.add("boss");
    }
    marker.textContent = String(mission.id);
    marker.style.left = `${mission.x}%`;
    marker.style.top = `${mission.y}%`;
    marker.setAttribute("aria-label", `Миссия ${mission.id}: ${mission.title}`);
    marker.addEventListener("click", () => showMission(mission, marker));
    elements.markers.appendChild(marker);
  });
}

async function loadState() {
  const initData = telegram ? telegram.initData : "";
  const query = initData ? `?init_data=${encodeURIComponent(initData)}` : "";
  try {
    const response = await fetch(`/api/tanellorn/state${query}`);
    if (response.status === 403) {
      throw new Error("Карта пока доступна только мастеру.");
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

elements.close.addEventListener("click", () => {
  elements.panel.hidden = true;
  if (selectedMarker) {
    selectedMarker.classList.remove("is-selected");
    selectedMarker = null;
  }
});

loadState();
