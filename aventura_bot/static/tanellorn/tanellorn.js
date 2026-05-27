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
  guildButton: document.getElementById("guildButton"),
  resultButton: document.getElementById("resultButton"),
  shopButton: document.getElementById("shopButton"),
  tavernButton: document.getElementById("tavernButton"),
  craftButton: document.getElementById("craftButton"),
  infoBackdrop: document.getElementById("infoBackdrop"),
  infoTitle: document.getElementById("infoTitle"),
  infoContent: document.getElementById("infoContent"),
  closeInfo: document.getElementById("closeInfo"),
};

let selectedMarker = null;
let selectedMission = null;
let playerState = null;

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
  elements.difficulty.textContent = `Сложность: ${mission.difficulty}`;
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
    elements.resultButton.hidden = true;
    return;
  }
  elements.heroButton.hidden = false;
  elements.heroButton.textContent = `${character.name} · ур. ${character.level}`;
  elements.resultButton.hidden = !playerState.latest_result;
}

function textElement(tagName, text, className = "") {
  const element = document.createElement(tagName);
  element.textContent = text;
  if (className) {
    element.className = className;
  }
  return element;
}

function openInfo(title) {
  elements.infoTitle.textContent = title;
  elements.infoContent.replaceChildren();
  elements.infoBackdrop.hidden = false;
  elements.closeInfo.focus();
}

function closeInfo() {
  elements.infoBackdrop.hidden = true;
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
  openInfo("Лавка");
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
          renderShop(response.shop, response.message);
        } catch (error) {
          renderShop(shop, error.message, true);
        }
      }));
      sellables.appendChild(row);
    });
  });
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
    openInfo("Лавка");
    serviceMessage(error.message, true);
  }
}

function renderTavern(shop, message = "", isError = false) {
  const tavern = shop.tavern;
  openInfo("Таверна");
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
    openInfo("Таверна");
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
  openInfo("Подтверждение крафта");
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
  openInfo("Алхимическая мастерская");
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
    openInfo("Алхимическая мастерская");
    serviceMessage(error.message, true);
  }
}

async function showRoster() {
  try {
    const payload = await apiFetch("/api/tanellorn/roster");
    openInfo("Гильдия Авентура");
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
elements.guildButton.addEventListener("click", showRoster);
elements.resultButton.addEventListener("click", showResult);
elements.shopButton.addEventListener("click", showShop);
elements.tavernButton.addEventListener("click", showTavern);
elements.craftButton.addEventListener("click", showCraft);
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
