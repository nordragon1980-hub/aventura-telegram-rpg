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
  feedback: document.getElementById("missionFeedback"),
  joinButton: document.getElementById("joinMissionButton"),
  actionForm: document.getElementById("actionForm"),
  actionText: document.getElementById("actionText"),
  actionCount: document.getElementById("actionCount"),
  close: document.getElementById("closePanel"),
  heroButton: document.getElementById("heroButton"),
  mapHintsButton: document.getElementById("mapHintsButton"),
  hotspots: document.getElementById("mapHotspots"),
  hintMarkers: document.getElementById("mapHintMarkers"),
  infoBackdrop: document.getElementById("infoBackdrop"),
  infoIcon: document.getElementById("infoIcon"),
  infoTitle: document.getElementById("infoTitle"),
  infoContent: document.getElementById("infoContent"),
  closeInfo: document.getElementById("closeInfo"),
};

let selectedMarker = null;
let selectedMission = null;
let playerState = null;
let mapHintsVisible = false;

const tanellornLore = window.TANELLORN_LORE || { locations: {}, npcs: {} };

const serviceIcons = {
  guild: "/static/tanellorn/icons/guild.png",
  shop: "/static/tanellorn/icons/shop.png",
  tavern: "/static/tanellorn/icons/tavern.png",
  craft: "/static/tanellorn/icons/alchemy.png",
  market: "/static/tanellorn/icons/auction.png",
};

const districtHotspots = [
  { loreId: "alchemical_industrial_quarter", x: 11.14, y: 23.62, w: 35, h: 30, hintLabel: "Алхим. район" },
  { loreId: "high_mage_tower_district", x: 54.95, y: 22.81, w: 22, h: 25, hintLabel: "Маг. квартал" },
  { loreId: "temple_district_cthulhu", x: 71.95, y: 21.68, w: 22, h: 28, hintLabel: "Храм. квартал" },
  { loreId: "depths_district", x: 87.3, y: 16.36, w: 20, h: 30, hintLabel: "Район Глубин" },
  { loreId: "carnival_opera_quarter", x: 67, y: 51.81, w: 22, h: 22, hintLabel: "Маски/карнавал" },
  { loreId: "market_food_quarter", x: 82.92, y: 80.88, w: 30, h: 25, hintLabel: "Рынок/еда" },
  { loreId: "lower_water_gate", x: 49.45, y: 93.37, w: 18, h: 10, hintLabel: "Водные ворота" },
];

const functionalHotspots = [
  { loreId: "guild_manor", x: 21.05, y: 64.42, w: 16, h: 13, id: "guild", action: "guild", hintLabel: "Гильдия" },
  { loreId: "magic_item_shop", x: 8.63, y: 56.5, w: 13, h: 16, id: "shop", action: "shop", hintLabel: "Лавка" },
  { loreId: "trebuchet_tavern", x: 37.21, y: 68.94, w: 13, h: 12, id: "tavern", action: "tavern", hintLabel: "Таверна" },
  { loreId: "alchemists_cauldrons", x: 18.61, y: 41.02, w: 19, h: 16, id: "craft", action: "craft", hintLabel: "Алхимия/крафт" },
  { loreId: "auction_house", x: 63.12, y: 69.32, w: 11, h: 12, id: "market", action: "market", hintLabel: "Аукцион" },
];

const locationHotspots = [
  { loreId: "golem_factory", x: 21.29, y: 27.81, w: 11, h: 14, hintLabel: "Фабрика големов" },
  { loreId: "alchemical_rocket", x: 39.01, y: 20.37, w: 12, h: 17, hintLabel: "Ракета" },
  { loreId: "high_mage_tower", x: 54.92, y: 11.85, w: 11, h: 14, hintLabel: "Башня магов" },
  { loreId: "library_magical_grimoires", x: 51.36, y: 31.51, w: 14, h: 11, hintLabel: "Библиотека" },
  { loreId: "temple_cthulhu", x: 72.07, y: 14.12, w: 16, h: 17, hintLabel: "Храм Ктулху" },
  { loreId: "depths", x: 93.21, y: 21.21, w: 13, h: 15, hintLabel: "Глубины" },
  { loreId: "wallenstein_manor", x: 93.62, y: 46.2, w: 12, h: 13, hintLabel: "Особняк" },
  { loreId: "knight_tournament_arena", x: 27.05, y: 50.59, w: 12, h: 13, hintLabel: "Арена" },
  { loreId: "masks_opera_house", x: 64.41, y: 44.09, w: 13, h: 13, hintLabel: "Опера Масок" },
  { loreId: "carnival_plaza", x: 62.82, y: 58.07, w: 14, h: 12, hintLabel: "Карнавал" },
  { loreId: "living_gingerbread_bakery", x: 84.73, y: 60.18, w: 12, h: 12, hintLabel: "Пекарня" },
  { loreId: "hells_kitchen", x: 93.25, y: 64, w: 13, h: 16, hintLabel: "Адская кухня" },
  { loreId: "grand_bazaar", x: 60.62, y: 77.8, w: 13, h: 12, hintLabel: "Базар" },
  { loreId: "cascade_fountain", x: 49.41, y: 80.54, w: 11, h: 12, hintLabel: "Фонтан" },
  { loreId: "troll_bridge", x: 69.08, y: 84.65, w: 14, h: 12, hintLabel: "Троллий мост" },
  { loreId: "magic_portal_arch", x: 32.97, y: 91.48, w: 12, h: 12, hintLabel: "Портал" },
  { loreId: "crossroads", x: 49.82, y: 56.52, w: 14, h: 14, hintLabel: "Перекрестки" },
];

const npcHotspots = [
  { loreId: "mira_belozlatka", x: 13.2, y: 68.52, w: 3, h: 4, hintLabel: "Мира" },
  { loreId: "bruh_tihiy", x: 36.39, y: 43.22, w: 3, h: 4, hintLabel: "Брух" },
  { loreId: "pips_mednaya_pugovitsa", x: 17.64, y: 73.78, w: 3, h: 4, hintLabel: "Пипс" },
  { loreId: "riksa_flamberg", x: 17.13, y: 50.26, w: 3, h: 4, hintLabel: "Рикса" },
  { loreId: "varg_rzhavy_bok", x: 54.83, y: 39.52, w: 3, h: 4, hintLabel: "Варг" },
  { loreId: "noks_bezlikiy", x: 41.69, y: 31.28, w: 4, h: 5, hintLabel: "Нокс" },
  { loreId: "hadj_burkun", x: 30.38, y: 22.03, w: 4, h: 5, hintLabel: "Хадж-Буркун" },
  { loreId: "shmyg_i_gryz", x: 39.15, y: 55.86, w: 4, h: 5, hintLabel: "Шмыг и Грыз" },
  { loreId: "edwin_krivokolpak", x: 43.89, y: 47.69, w: 4, h: 5, hintLabel: "Эдвин" },
  { loreId: "kostik_pylny", x: 28.14, y: 73.27, w: 4, h: 5, hintLabel: "Костик" },
  { loreId: "bazil_goryachaya_lopatka", x: 73.07, y: 56.2, w: 4, h: 5, hintLabel: "Базиль" },
  { loreId: "avrelian_svetly_gvozd", x: 39.52, y: 62.13, w: 4, h: 5, hintLabel: "Аврелиан" },
  { loreId: "klepp_mednoshum", x: 39.59, y: 27.64, w: 4, h: 5, hintLabel: "Клёпп" },
  { loreId: "lukreciya_maskarina", x: 56.9, y: 50.41, w: 4, h: 5, hintLabel: "Лукреция" },
  { loreId: "tiko_i_lana", x: 52.45, y: 66.89, w: 4, h: 5, hintLabel: "Тико и Лана" },
  { loreId: "severin_morn", x: 89.2, y: 34.41, w: 4, h: 5, hintLabel: "Северин" },
  { loreId: "mostoboy_urr", x: 71.07, y: 92.52, w: 4, h: 5, hintLabel: "Урр" },
  { loreId: "elianna_pylcekrylaya", x: 74.32, y: 70.42, w: 4, h: 5, hintLabel: "Элианна" },
];

function telegramInitData() {
  if (telegram && telegram.initData) {
    return telegram.initData;
  }
  const launchParams = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  return launchParams.get("tgWebAppData") || "";
}

function authQuery() {
  const source = new URLSearchParams(window.location.search);
  const query = new URLSearchParams();
  const initData = telegramInitData();
  if (initData) {
    query.set("init_data", initData);
  }
  if (source.has("admin_user_id")) {
    query.set("admin_user_id", source.get("admin_user_id"));
  }
  if (source.has("admin_signature")) {
    query.set("admin_signature", source.get("admin_signature"));
  }
  if (source.has("admin_expires")) {
    query.set("admin_expires", source.get("admin_expires"));
  }
  return query.toString();
}

async function apiFetch(path, options = {}) {
  const suffix = authQuery();
  const response = await fetch(`${path}${suffix ? `?${suffix}` : ""}`, options);
  let payload = null;
  try {
    payload = await response.json();
  } catch (_error) {
    payload = {};
  }
  if (!response.ok) {
    throw new Error(payload.detail || "Запрос не выполнен.");
  }
  return payload;
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

function setFeedback(text = "", error = false) {
  elements.feedback.hidden = !text;
  elements.feedback.textContent = text;
  elements.feedback.classList.toggle("error", error);
}

function updateMissionControls(mission) {
  const current = playerState && playerState.current_mission;
  const joinedHere = current && current.id === mission.id;
  elements.actionForm.hidden = !joinedHere;
  elements.joinButton.hidden = Boolean(joinedHere);
  if (joinedHere) {
    elements.actionText.value = current.action_text || "";
    elements.actionCount.textContent = `${elements.actionText.value.length} / 3000`;
    return;
  }
  elements.joinButton.textContent = current ? "Сменить миссию" : "Присоединиться";
}

function showMission(mission, marker) {
  if (selectedMarker) {
    selectedMarker.classList.remove("is-selected");
  }
  selectedMarker = marker;
  selectedMission = mission;
  marker.classList.add("is-selected");
  elements.type.textContent = missionTypeLabel(mission);
  elements.panel.classList.toggle("boss", mission.type === "boss");
  elements.title.textContent = mission.title;
  elements.difficulty.textContent = `Опасность: ${mission.difficulty_label || "неизвестно"}`;
  elements.participants.textContent =
    `Участники: ${mission.participants_count}/${mission.participants_limit}`;
  elements.description.textContent = mission.description;
  setFeedback();
  updateMissionControls(mission);
  elements.backdrop.hidden = false;
  elements.close.focus();
}

function closeMission() {
  elements.backdrop.hidden = true;
  elements.panel.classList.remove("boss");
  setFeedback();
  if (selectedMarker) {
    selectedMarker.classList.remove("is-selected");
    selectedMarker.focus();
  }
  selectedMarker = null;
  selectedMission = null;
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

function renderState(state, preservePosition = false) {
  elements.turnTitle.textContent = state.turn ? state.turn.title : "Нет открытого хода";
  elements.markers.replaceChildren();
  if (!state.missions.length) {
    elements.mapStatus.textContent = "На карте сейчас нет открытых миссий.";
    elements.mapStatus.hidden = false;
    if (!preservePosition) {
      requestAnimationFrame(() => centerMap([]));
    }
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
    marker.dataset.missionId = String(mission.id);
    marker.setAttribute("aria-label", `Миссия ${mission.id}: ${mission.title}`);
    marker.addEventListener("click", () => showMission(mission, marker));
    elements.markers.appendChild(marker);
  });
  if (!preservePosition) {
    requestAnimationFrame(() => centerMap(state.missions));
  }
}

function renderPlayerButton() {
  const character = playerState && playerState.character;
  if (!character) {
    elements.heroButton.hidden = true;
    return;
  }
  elements.heroButton.hidden = false;
  elements.heroButton.textContent = `${character.name} · ур. ${character.level}`;
}

function textElement(tagName, text, className = "") {
  const element = document.createElement(tagName);
  element.textContent = text;
  if (className) {
    element.className = className;
  }
  return element;
}

function openInfo(title, icon = "") {
  elements.infoTitle.textContent = title;
  elements.infoIcon.hidden = !icon;
  if (icon) {
    elements.infoIcon.src = icon;
  } else {
    elements.infoIcon.removeAttribute("src");
  }
  elements.infoContent.replaceChildren();
  elements.infoBackdrop.hidden = false;
  elements.closeInfo.focus();
}

function closeInfo() {
  elements.infoBackdrop.hidden = true;
}

function createHotspot({ title, x, y, w = 4, h = 4, onClick, className = "" }) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `map-hotspot ${className}`.trim();
  button.style.left = `${x}%`;
  button.style.top = `${y}%`;
  button.style.width = `${w}%`;
  button.style.height = `${h}%`;
  button.setAttribute("aria-label", title);
  button.title = title;
  button.addEventListener("click", onClick);
  elements.hotspots.appendChild(button);
  return button;
}

function locationLore(loreId) {
  return tanellornLore.locations[loreId] || null;
}

function npcLore(loreId) {
  return tanellornLore.npcs[loreId] || null;
}

function locationTitle(loreId, fallback = "Локация") {
  const lore = locationLore(loreId);
  return lore ? lore.title : fallback;
}

function appendLocationIntro(loreId) {
  const lore = locationLore(loreId);
  if (!lore) {
    return;
  }
  elements.infoContent.appendChild(textElement("p", lore.description, "hero-summary"));
  if (lore.role) {
    addInfoSection("Интерактивная роль");
    elements.infoContent.appendChild(textElement("p", lore.role));
  }
}

function allHintHotspots() {
  return [...districtHotspots, ...functionalHotspots, ...locationHotspots, ...npcHotspots];
}

function renderMapHintMarkers() {
  elements.hintMarkers.replaceChildren();
  allHintHotspots().forEach((hotspot, index) => {
    const hint = document.createElement("div");
    hint.className = "map-hint";
    hint.style.left = `${hotspot.x}%`;
    hint.style.top = `${hotspot.y}%`;
    hint.title = hotspot.hintLabel || locationTitle(hotspot.loreId);
    const pin = document.createElement("div");
    pin.className = "map-hint-pin";
    const number = document.createElement("span");
    number.className = "map-hint-number";
    number.textContent = String(index + 1);
    const label = document.createElement("span");
    label.className = "map-hint-label";
    label.textContent = hotspot.hintLabel || hint.title;
    pin.appendChild(number);
    hint.appendChild(pin);
    hint.appendChild(label);
    elements.hintMarkers.appendChild(hint);
  });
}

function setMapHintsVisible(visible) {
  mapHintsVisible = visible;
  elements.hintMarkers.hidden = !visible;
  elements.mapHintsButton.setAttribute("aria-pressed", visible ? "true" : "false");
  elements.mapHintsButton.textContent = visible ? "Скрыть подсказки" : "Подсказки";
}

function renderMapHotspots() {
  elements.hotspots.replaceChildren();
  districtHotspots.forEach((hotspot) => {
    createHotspot({
      ...hotspot,
      title: locationTitle(hotspot.loreId),
      onClick: () => showLocation(hotspot.loreId),
    });
  });
  functionalHotspots.forEach((hotspot) => {
    const actions = {
      guild: showRoster,
      shop: showShop,
      tavern: showTavern,
      craft: showCraft,
      market: showMarket,
    };
    createHotspot({
      ...hotspot,
      title: locationTitle(hotspot.loreId, hotspot.id),
      onClick: actions[hotspot.action],
    });
  });
  locationHotspots.forEach((location) => {
    createHotspot({
      ...location,
      title: locationTitle(location.loreId),
      onClick: () => showLocation(location.loreId),
    });
  });
  npcHotspots.forEach((npc) => {
    const lore = npcLore(npc.loreId);
    createHotspot({
      title: lore ? lore.name : "Персонаж",
      x: npc.x,
      y: npc.y,
      w: npc.w || 4,
      h: npc.h || 5,
      onClick: () => showNpc(npc.loreId),
    });
  });
  const freeButton = document.createElement("button");
  freeButton.type = "button";
  freeButton.className = "free-action-marker";
  freeButton.setAttribute("aria-label", "Свободный ход");
  freeButton.title = "Свободный ход";
  freeButton.textContent = "✦";
  freeButton.addEventListener("click", showFreeAction);
  elements.hotspots.appendChild(freeButton);
}

function addInfoSection(title) {
  elements.infoContent.appendChild(textElement("h3", title, "info-section"));
}

function addAssets(title, assets) {
  addInfoSection(title);
  const list = document.createElement("div");
  list.className = "asset-list";
  if (!assets.length) {
    list.appendChild(textElement("p", "Нет", "muted"));
  }
  assets.forEach((asset) => {
    const cooldown = asset.cooldown_remaining ? ` · восстановление через ${asset.cooldown_remaining} ход.` : "";
    list.appendChild(textElement("div", `${asset.name} · ур. ${asset.level}${cooldown}`, "asset-row"));
  });
  elements.infoContent.appendChild(list);
}

function showHero() {
  const character = playerState && playerState.character;
  if (!character) {
    return;
  }
  openInfo(character.name);
  elements.infoContent.appendChild(
    textElement("p", `${character.race} · ур. ${character.level} · ${character.gold} дублонов`, "hero-summary"),
  );
  elements.infoContent.appendChild(textElement("p", character.description || "Описание не указано."));
  addInfoSection("Характеристики");
  const stats = document.createElement("div");
  stats.className = "stat-grid";
  Object.entries(character.stats).forEach(([name, value]) => {
    stats.appendChild(textElement("div", `${name}: ${value}`));
  });
  elements.infoContent.appendChild(stats);
  addAssets("Предметы", character.assets.inventory || []);
  addAssets("Заклинания", character.assets.spells || []);
  addAssets("Питомцы", character.assets.pets || []);
  addAssets("Спутники", character.assets.companions || []);
  addAssets("Маунты", character.assets.mounts || []);
  const result = playerState.latest_result;
  if (result) {
    addInfoSection("Последний результат");
    elements.infoContent.appendChild(textElement("p", `${result.mission_title} · ${result.status || ""}`));
    elements.infoContent.appendChild(textElement("p", result.public_summary || "Результат обработан."));
  }
}

function resultChangeText(change) {
  const field = change.field;
  const delta = Number(change.delta || 0);
  const signed = delta >= 0 ? `+${delta}` : String(delta);
  if (field === "level") return `Уровень героя: ${signed}`;
  if (field === "gold") return `Золото: ${signed}`;
  if (field === "stat") return `${change.stat || change.name || "Характеристика"}: ${signed}`;
  const values = {
    inventory: ["Предмет", change.item || change.value],
    spells: ["Заклинание", change.spell || change.value],
    pet: ["Питомец", change.pet || change.value],
    companion: ["Спутник", change.companion || change.value],
    mount: ["Маунт", change.mount || change.value],
  };
  if (values[field]) {
    const [label, value] = values[field];
    return `${label}: ${(value && value.name) || "получен"}`;
  }
  return change.reason || "Изменение героя";
}

function showResult() {
  const result = playerState && playerState.latest_result;
  if (!result) {
    return;
  }
  openInfo("Итоги хода");
  elements.infoContent.appendChild(textElement("p", `${result.turn_title} · ${result.mission_title}`, "hero-summary"));
  elements.infoContent.appendChild(textElement("p", result.public_summary || "Общий итог миссии опубликован."));
  const personal = result.player_result;
  if (personal) {
    addInfoSection("Личный результат");
    if (personal.message) {
      elements.infoContent.appendChild(textElement("p", personal.message));
    }
    const changes = Array.isArray(personal.changes) ? personal.changes : [];
    const list = document.createElement("div");
    list.className = "asset-list";
    if (!changes.length) {
      list.appendChild(textElement("p", "Изменений нет.", "muted"));
    }
    changes.forEach((change) => list.appendChild(textElement("div", resultChangeText(change), "asset-row")));
    elements.infoContent.appendChild(list);
  }
}

function showLocation(loreId) {
  const lore = locationLore(loreId);
  openInfo(lore ? lore.title : "Локация");
  appendLocationIntro(loreId);
}

function showNpc(loreId) {
  const lore = npcLore(loreId);
  openInfo(lore ? lore.name : "Персонаж");
  if (lore && lore.subtitle) {
    elements.infoContent.appendChild(textElement("p", lore.subtitle, "hero-summary"));
  }
  if (lore && lore.description) {
    elements.infoContent.appendChild(textElement("p", lore.description));
  }
  if (lore && lore.about) {
    addInfoSection("О персонаже");
    elements.infoContent.appendChild(textElement("p", lore.about));
  }
  const value = 0;
  const meter = document.createElement("div");
  meter.className = "reputation-meter";
  meter.appendChild(textElement("p", `Репутация с персонажем: ${value}`, "muted"));
  const track = document.createElement("div");
  track.className = "reputation-track";
  const fill = document.createElement("div");
  fill.className = "reputation-fill";
  fill.style.width = `${50 + value / 2}%`;
  track.appendChild(fill);
  meter.appendChild(track);
  elements.infoContent.appendChild(meter);
}

function renderFreeAction(message = "", isError = false) {
  openInfo("Свободный ход");
  if (message) {
    serviceMessage(message, isError);
  }
  elements.infoContent.appendChild(
    textElement(
      "p",
      "Свободный ход заменяет участие в обычной миссии текущего хода и попадет в export для обработки результата.",
      "hero-summary",
    ),
  );
  const form = document.createElement("form");
  form.className = "action-form";
  const label = textElement("label", "Что делает герой", "field-label");
  label.htmlFor = "freeActionText";
  const textarea = document.createElement("textarea");
  textarea.id = "freeActionText";
  textarea.minLength = 120;
  textarea.maxLength = 3000;
  textarea.rows = 6;
  textarea.value = (playerState && playerState.current_free_action && playerState.current_free_action.action_text) || "";
  const footer = document.createElement("div");
  footer.className = "action-footer";
  const count = textElement("span", `${textarea.value.length} / 3000`, "character-count");
  const submit = textElement("button", "Отправить свободный ход", "command-button");
  submit.type = "submit";
  textarea.addEventListener("input", () => {
    count.textContent = `${textarea.value.length} / 3000`;
  });
  footer.appendChild(count);
  footer.appendChild(submit);
  form.appendChild(label);
  form.appendChild(textarea);
  form.appendChild(footer);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    try {
      const response = await apiFetch("/api/tanellorn/free-action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action_text: textarea.value }),
      });
      playerState = response.player;
      renderPlayerButton();
      renderFreeAction(response.message);
    } catch (error) {
      renderFreeAction(error.message, true);
    } finally {
      submit.disabled = false;
    }
  });
  elements.infoContent.appendChild(form);
}

function showFreeAction() {
  renderFreeAction();
}

function actionButton(label, handler) {
  const button = textElement("button", label, "command-button small-action");
  button.type = "button";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await handler();
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

async function refreshPlayerData() {
  playerState = await apiFetch("/api/tanellorn/me");
  renderPlayerButton();
}

function serviceMessage(text, error = false) {
  const message = textElement("p", text, `feedback service-feedback${error ? " error" : ""}`);
  elements.infoContent.appendChild(message);
}

function assetLabel(asset) {
  const cooldown = asset.cooldown_remaining ? ` · КД ${asset.cooldown_remaining}` : "";
  return `${asset.name} · ур. ${asset.level}${cooldown}`;
}

function renderShop(shop, message = "", isError = false) {
  openInfo("Лавка", serviceIcons.shop);
  appendLocationIntro("magic_item_shop");
  elements.infoContent.appendChild(textElement("p", `${shop.gold} дублонов`, "hero-summary"));
  if (message) {
    serviceMessage(message, isError);
  }
  addInfoSection("На прилавке");
  const catalog = document.createElement("div");
  catalog.className = "asset-list";
  shop.items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "shop-row";
    row.appendChild(textElement("div", `${item.name} · ур. ${item.level} · ${item.price} дубл.`, "row-text"));
    const endpoint = item.can_buy_back ? "buyback" : "buy";
    const label = item.can_buy_back ? "Выкупить" : "Купить";
    row.appendChild(actionButton(label, async () => {
      try {
        const response = await apiFetch(`/api/tanellorn/shop/${item.id}/${endpoint}`, { method: "POST" });
        await refreshPlayerData();
        renderShop(response.shop, response.message);
      } catch (error) {
        renderShop(shop, error.message, true);
      }
    }));
    catalog.appendChild(row);
  });
  if (!shop.items.length) {
    catalog.appendChild(textElement("p", "Прилавок пуст.", "muted"));
  }
  elements.infoContent.appendChild(catalog);
  addInfoSection("Продать");
  const sellables = document.createElement("div");
  sellables.className = "asset-list";
  appendSaleControls(sellables, shop, renderShop);
  if (!sellables.childElementCount) {
    sellables.appendChild(textElement("p", "Нет активов для продажи.", "muted"));
  }
  elements.infoContent.appendChild(sellables);
  elements.infoContent.appendChild(textElement("p", "Спутники доступны для обмена, но не продаются в лавке.", "muted"));
}

async function showShop() {
  try {
    renderShop(await apiFetch("/api/tanellorn/shop"));
  } catch (error) {
    openInfo("Лавка", serviceIcons.shop);
    serviceMessage(error.message, true);
  }
}

function renderTavern(shop, message = "", isError = false) {
  const tavern = shop.tavern;
  openInfo("Таверна", serviceIcons.tavern);
  appendLocationIntro("trebuchet_tavern");
  elements.infoContent.appendChild(textElement("p", `${shop.gold} дублонов`, "hero-summary"));
  if (message) {
    serviceMessage(message, isError);
  }
  if (!tavern.available) {
    elements.infoContent.appendChild(textElement("p", "Все твои активы готовы. Отдых сейчас не нужен."));
    return;
  }
  elements.infoContent.appendChild(
    textElement("p", `Платный отдых восстановит ${tavern.asset_count} активов за ${tavern.price} дублонов.`),
  );
  const list = document.createElement("div");
  list.className = "asset-list";
  tavern.assets.forEach((asset) => list.appendChild(textElement("div", assetLabel(asset), "asset-row")));
  elements.infoContent.appendChild(list);
  elements.infoContent.appendChild(actionButton("Отдохнуть", async () => {
    try {
      const response = await apiFetch("/api/tanellorn/tavern/rest", { method: "POST" });
      await refreshPlayerData();
      renderTavern(response.shop, response.message);
    } catch (error) {
      renderTavern(shop, error.message, true);
    }
  }));
}

async function showTavern() {
  try {
    renderTavern(await apiFetch("/api/tanellorn/shop"));
  } catch (error) {
    openInfo("Таверна", serviceIcons.tavern);
    serviceMessage(error.message, true);
  }
}

function craftOption(asset) {
  const option = document.createElement("option");
  option.value = asset.token;
  option.textContent = assetLabel(asset);
  return option;
}

function renderCraftConfirmation(craft, base, material) {
  openInfo("Подтверждение крафта", serviceIcons.craft);
  const box = document.createElement("div");
  box.className = "confirm-box";
  box.appendChild(textElement("p", `Основа: ${assetLabel(base)}`));
  box.appendChild(textElement("p", `Материал: ${assetLabel(material)}`));
  box.appendChild(textElement("p", "Оба актива будут потрачены.", "muted"));
  const actions = document.createElement("div");
  actions.className = "inline-actions";
  actions.appendChild(actionButton("Подтвердить", async () => {
    try {
      const response = await apiFetch("/api/tanellorn/craft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ base_token: base.token, material_token: material.token }),
      });
      await refreshPlayerData();
      renderCraft(response.craft, response.message);
    } catch (error) {
      renderCraft(craft, error.message, true);
    }
  }));
  actions.appendChild(actionButton("Назад", async () => renderCraft(craft)));
  box.appendChild(actions);
  elements.infoContent.appendChild(box);
}

function renderCraft(craft, message = "", isError = false) {
  openInfo("Алхимическая мастерская", serviceIcons.craft);
  appendLocationIntro("alchemists_cauldrons");
  if (message) {
    serviceMessage(message, isError);
  }
  if (craft.request) {
    elements.infoContent.appendChild(textElement("p", "Крафт текущего хода принят.", "hero-summary"));
    elements.infoContent.appendChild(textElement("div", `Основа: ${assetLabel(craft.request.base)}`, "asset-row"));
    elements.infoContent.appendChild(textElement("div", `Материал: ${assetLabel(craft.request.material)}`, "asset-row"));
    elements.infoContent.appendChild(textElement("p", "Результат появится после обработки хода.", "muted"));
    return;
  }
  if (craft.assets.length < 2) {
    elements.infoContent.appendChild(textElement("p", "Для крафта нужны минимум два актива."));
    return;
  }
  const form = document.createElement("form");
  form.className = "craft-form";
  const baseLabel = textElement("label", "Основа", "field-label");
  const baseSelect = document.createElement("select");
  const materialLabel = textElement("label", "Материал", "field-label");
  const materialSelect = document.createElement("select");
  baseSelect.id = "craftBase";
  materialSelect.id = "craftMaterial";
  baseLabel.htmlFor = baseSelect.id;
  materialLabel.htmlFor = materialSelect.id;
  craft.assets.forEach((asset) => {
    baseSelect.appendChild(craftOption(asset));
    materialSelect.appendChild(craftOption(asset));
  });
  materialSelect.value = craft.assets[1].token;
  form.appendChild(baseLabel);
  form.appendChild(baseSelect);
  form.appendChild(materialLabel);
  form.appendChild(materialSelect);
  const startButton = textElement("button", "Выбрать", "command-button");
  startButton.type = "submit";
  form.appendChild(startButton);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (baseSelect.value === materialSelect.value) {
      renderCraft(craft, "Основа и материал должны быть разными.", true);
      return;
    }
    const base = craft.assets.find((asset) => asset.token === baseSelect.value);
    const material = craft.assets.find((asset) => asset.token === materialSelect.value);
    renderCraftConfirmation(craft, base, material);
  });
  elements.infoContent.appendChild(form);
}

async function showCraft() {
  try {
    renderCraft(await apiFetch("/api/tanellorn/craft"));
  } catch (error) {
    openInfo("Алхимическая мастерская", serviceIcons.craft);
    serviceMessage(error.message, true);
  }
}

function appendSaleControls(container, shop, rerender) {
  const saleTypes = [
    ["inventory", "item"],
    ["pets", "pet"],
    ["mounts", "mount"],
  ];
  saleTypes.forEach(([collection, assetType]) => {
    (shop.sellables[collection] || []).forEach((asset) => {
      const row = document.createElement("div");
      row.className = "sell-row";
      row.appendChild(textElement("div", assetLabel(asset), "row-text"));
      const token = assetType === "item" ? asset.uid : asset.name;
      row.appendChild(actionButton("Продать", async () => {
        try {
          const response = await apiFetch("/api/tanellorn/shop/sell", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ asset_type: assetType, token }),
          });
          await refreshPlayerData();
          rerender(response.shop, response.message);
        } catch (error) {
          rerender(shop, error.message, true);
        }
      }));
      container.appendChild(row);
    });
  });
}

function renderMarket(shop, message = "", isError = false) {
  openInfo("Аукцион", serviceIcons.market);
  appendLocationIntro("auction_house");
  elements.infoContent.appendChild(textElement("p", `${shop.gold} дублонов`, "hero-summary"));
  if (message) {
    serviceMessage(message, isError);
  }
  addInfoSection("Лоты игроков");
  const listingBox = document.createElement("div");
  listingBox.className = "asset-list";
  const listings = shop.items.filter((item) => item.source === "player_sale");
  listings.forEach((item) => {
    const row = document.createElement("div");
    row.className = "shop-row";
    row.appendChild(textElement("div", `${item.name} · ур. ${item.level} · ${item.price} дубл.`, "row-text"));
    const endpoint = item.can_buy_back ? "buyback" : "buy";
    row.appendChild(actionButton(item.can_buy_back ? "Снять" : "Купить", async () => {
      try {
        const response = await apiFetch(`/api/tanellorn/shop/${item.id}/${endpoint}`, { method: "POST" });
        await refreshPlayerData();
        renderMarket(response.shop, response.message);
      } catch (error) {
        renderMarket(shop, error.message, true);
      }
    }));
    listingBox.appendChild(row);
  });
  if (!listings.length) {
    listingBox.appendChild(textElement("p", "Лотов игроков пока нет.", "muted"));
  }
  elements.infoContent.appendChild(listingBox);
  addInfoSection("Выставить на продажу");
  const sellables = document.createElement("div");
  sellables.className = "asset-list";
  appendSaleControls(sellables, shop, renderMarket);
  if (!sellables.childElementCount) {
    sellables.appendChild(textElement("p", "Нет активов для продажи.", "muted"));
  }
  elements.infoContent.appendChild(sellables);
  elements.infoContent.appendChild(textElement("p", "Спутники не выставляются на продажу.", "muted"));
}

async function showMarket() {
  try {
    renderMarket(await apiFetch("/api/tanellorn/shop"));
  } catch (error) {
    openInfo("Аукцион", serviceIcons.market);
    serviceMessage(error.message, true);
  }
}

async function showRoster() {
  try {
    const payload = await apiFetch("/api/tanellorn/roster");
    openInfo("Гильдия Авентура", serviceIcons.guild);
    appendLocationIntro("guild_manor");
    const list = document.createElement("div");
    list.className = "roster-list";
    payload.heroes.forEach((hero) => {
      const row = document.createElement("div");
      row.className = "roster-row";
      row.appendChild(textElement("strong", `${hero.name} · ур. ${hero.level}`));
      row.appendChild(textElement("div", hero.race || "Раса не указана", "muted"));
      list.appendChild(row);
    });
    if (!payload.heroes.length) {
      list.appendChild(textElement("p", "В гильдии пока нет героев.", "muted"));
    }
    elements.infoContent.appendChild(list);
  } catch (error) {
    elements.mapStatus.textContent = error.message;
    elements.mapStatus.hidden = false;
  }
}

async function loadState() {
  try {
    const [state, player] = await Promise.all([
      apiFetch("/api/tanellorn/state"),
      apiFetch("/api/tanellorn/me"),
    ]);
    playerState = player;
    renderPlayerButton();
    renderMapHotspots();
    renderMapHintMarkers();
    setMapHintsVisible(mapHintsVisible);
    renderState(state);
  } catch (error) {
    elements.mapStatus.textContent = error.message;
    elements.mapStatus.hidden = false;
  }
}

async function refreshAfterWrite(message) {
  const previousMissionId = selectedMission && selectedMission.id;
  const [state, player] = await Promise.all([
    apiFetch("/api/tanellorn/state"),
    apiFetch("/api/tanellorn/me"),
  ]);
  playerState = player;
  renderPlayerButton();
  renderState(state, true);
  const mission = state.missions.find((candidate) => candidate.id === previousMissionId);
  const marker = elements.markers.querySelector(`[data-mission-id="${previousMissionId}"]`);
  if (mission && marker) {
    selectedMarker = marker;
    selectedMarker.classList.add("is-selected");
    selectedMission = mission;
    elements.participants.textContent =
      `Участники: ${mission.participants_count}/${mission.participants_limit}`;
    updateMissionControls(mission);
    setFeedback(message);
  }
}

elements.joinButton.addEventListener("click", async () => {
  if (!selectedMission) {
    return;
  }
  elements.joinButton.disabled = true;
  try {
    const payload = await apiFetch(`/api/tanellorn/missions/${selectedMission.id}/join`, { method: "POST" });
    const suffix = payload.action_cleared ? " Предыдущий отправленный ход удален." : "";
    await refreshAfterWrite(`${payload.message}${suffix}`);
  } catch (error) {
    setFeedback(error.message, true);
  } finally {
    elements.joinButton.disabled = false;
  }
});

elements.actionText.addEventListener("input", () => {
  elements.actionCount.textContent = `${elements.actionText.value.length} / 3000`;
});

elements.actionForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submitButton = elements.actionForm.querySelector("button[type='submit']");
  submitButton.disabled = true;
  try {
    const payload = await apiFetch("/api/tanellorn/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action_text: elements.actionText.value }),
    });
    await refreshAfterWrite(`${payload.message} Его можно заменить до дедлайна.`);
  } catch (error) {
    setFeedback(error.message, true);
  } finally {
    submitButton.disabled = false;
  }
});

elements.close.addEventListener("click", closeMission);
elements.backdrop.addEventListener("click", (event) => {
  if (event.target === elements.backdrop) {
    closeMission();
  }
});
elements.heroButton.addEventListener("click", showHero);
elements.mapHintsButton.addEventListener("click", () => setMapHintsVisible(!mapHintsVisible));
elements.closeInfo.addEventListener("click", closeInfo);
elements.infoBackdrop.addEventListener("click", (event) => {
  if (event.target === elements.infoBackdrop) {
    closeInfo();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !elements.backdrop.hidden) {
    closeMission();
  } else if (event.key === "Escape" && !elements.infoBackdrop.hidden) {
    closeInfo();
  }
});

loadState();
