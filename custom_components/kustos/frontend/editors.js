/* Editor subpages (Automations-Editor-Stil): centered column of section
   cards, save pill bottom right. Render functions + form field helpers.
   `ctx` is the panel component. */
import { esc, icon } from "./styles.js";
import {
  ALARM_TYPES, ALARM_TYPE_LABELS, ALL_MODES, BLOCK_LABELS, MODE_LABELS,
} from "./views.js";

export const ROLES = ["inactive", "instant", "delayed", "follower"];
export const ROLE_LABELS = {
  inactive: "inaktiv", instant: "sofort", delayed: "verzögert", follower: "Folgezone",
};
export const BLOCK_DEFAULTS = {
  flash_lights: { type: "flash_lights", targets: [], color_rgb: [255, 0, 0],
                  brightness_pct: 100, period_s: 2.0, fade_s: 0.4, non_color_behavior: "off" },
  lights_on:    { type: "lights_on", targets: [], brightness_pct: 100, refresh_interval_s: 0 },
  sound:        { type: "sound", targets: [], retrigger_interval_s: 30, max_duration_s: 180 },
  announce_loop:{ type: "announce_loop", notify_service: "notify.", message: "",
                  interval_s: 15, media_targets: [], volume_pct: 80, volume_fallback_pct: 30 },
  notify:       { type: "notify", service: "persistent_notification.create", title: "", message: "" },
  lock:         { type: "lock", targets: [], action: "lock" },
};

export const EDITOR_TITLES = {
  panel: ["Neuer Bereich", "Bereich bearbeiten"],
  zone: ["Neue Zone", "Zone bearbeiten"],
  profile: ["Neues Profil", "Profil bearbeiten"],
  user: ["Neuer Benutzer", "Benutzer bearbeiten"],
  person: ["Neue Person", "Person bearbeiten"],
  rule: ["Neue Regel", "Regel bearbeiten"],
};

/* ---------- form helpers ---------- */

export const textField = (id, label, value, opts = {}) => `
  <div class="field"><label for="${id}">${label}</label>
    <input type="${opts.type || "text"}" id="${id}" value="${esc(value ?? "")}"
      ${opts.list ? `list="${opts.list}"` : ""} ${opts.step ? `step="${opts.step}"` : ""}
      placeholder="${esc(opts.placeholder || "")}"></div>`;

export const numField = (id, label, value, placeholder = "") =>
  textField(id, label, value ?? "", { type: "number", step: "0.1", placeholder });

export const selectField = (id, label, options, selected) => `
  <div class="field"><label for="${id}">${label}</label>
    <select id="${id}">${options.map(([v, text]) =>
      `<option value="${esc(v)}" ${String(v) === String(selected) ? "selected" : ""}>${esc(text)}</option>`).join("")}
    </select></div>`;

export const switchRow = (id, label, checked, secondary = "", cls = "") => `
  <div class="switch-row">
    <span class="body"><div>${label}</div>
      ${secondary ? `<div class="secondary">${secondary}</div>` : ""}</span>
    <label class="switch"><input type="checkbox" id="${id}" class="${cls}" ${checked ? "checked" : ""}>
      <span class="track"></span></label>
  </div>`;

const checkChip = (cls, value, label, checked) => `
  <label style="display:inline-flex;align-items:center;gap:6px;margin:4px 12px 4px 0;">
    <input type="checkbox" class="${cls}" value="${esc(value)}" ${checked ? "checked" : ""}> ${esc(label)}
  </label>`;

const card = (title, content, hint = "") => `
  <div class="card"><div class="card-header">${title}
    ${hint ? `<span class="hint">${hint}</span>` : ""}</div>
  <div class="card-content">${content}</div></div>`;

/* ---------- editors ---------- */

export function renderEditor(ctx) {
  const { kind, draft } = ctx._edit;
  const body = {
    panel: panelEditor, zone: zoneEditor, profile: profileEditor,
    user: userEditor, person: personEditor, rule: ruleEditor,
  }[kind](ctx, draft);
  return `<div class="cards">${body}</div>
    <button class="fab" data-action="save-${kind}" data-id="${draft.id || ""}"
      ${ctx._edit.panelId ? `data-panel="${ctx._edit.panelId}"` : ""}>
      ${icon("save", 20)} Speichern</button>`;
}

function panelEditor(ctx, doc) {
  const areas = Object.values(ctx._hass.areas || {})
    .map((a) => `<option value="${esc(a.area_id)}">`).join("");
  const modes = ALL_MODES.map((m) => {
    const cfg = (doc.modes || {})[m] || {};
    return `<div style="margin-bottom:8px;">
      ${switchRow(`mode-${m}`, `<b>${MODE_LABELS[m]}</b>`, cfg.enabled)}
      <div class="form-grid">
        ${numField(`exit-${m}`, "Exit-Delay s", cfg.exit_delay_s, "Standard")}
        ${numField(`entry-${m}`, "Entry-Delay s", cfg.entry_delay_s, "Standard")}
        ${numField(`trig-${m}`, "Alarmdauer s", cfg.trigger_time_s, "Standard")}
      </div></div>`;
  }).join("");
  const opts = doc.options || {};
  const profileOptions = (sel) => [["", "kein Profil"],
    ...(ctx._data.profiles || []).map((pr) => [pr.id, pr.name])];
  const assignments = `<div class="form-grid">${ALARM_TYPES.map((t) =>
    selectField(`prof-${t}`, ALARM_TYPE_LABELS[t],
      profileOptions(), ((doc.alarm_types || {})[t] || {}).profile_id || "")).join("")}</div>`;
  return `
    ${card("Bereich", `<div class="form">
      ${textField("f-area", "Home-Assistant-Bereich (area_id)", doc.scope?.area_id, { list: "dl-areas" })}
      <datalist id="dl-areas">${areas}</datalist></div>`)}
    ${card("Modi", modes, "Zeiten leer = zentrale Standardwerte")}
    ${card("Optionen", `
      ${switchRow("f-codearm", "Code zum Scharfschalten", opts.code_arm_required)}
      ${switchRow("f-codedisarm", "Code zum Entschärfen", opts.code_disarm_required !== false)}
      ${switchRow("f-rearm", "Nach Ablauf der Alarmdauer wieder scharf",
        opts.rearm_after_trigger !== false, "offene Zonen werden dabei sichtbar überbrückt")}`)}
    ${card("Reaktionsprofile je Alarmtyp", assignments)}`;
}

function zoneEditor(ctx, doc) {
  const panelDoc = (ctx._data.panels || []).find((p) => p.id === ctx._edit.panelId);
  const enabledModes = Object.entries(panelDoc?.modes || {})
    .filter(([, c]) => c.enabled).map(([m]) => m);
  const roles = `<div class="form-grid">${(enabledModes.length ? enabledModes : ["armed_away"])
    .map((m) => selectField(`role-${m}`, MODE_LABELS[m],
      ROLES.map((r) => [r, ROLE_LABELS[r]]), (doc.modes || {})[m] || "inactive")).join("")}</div>`;
  const o = doc.options || {};
  return `
    ${card("Zone", `<div class="form">
      ${textField("z-entity", "Entität", doc.entity_id, { list: "dl-zone-entities" })}
      ${ctx._datalist("dl-zone-entities", ["binary_sensor", "input_boolean", "switch", "sensor"])}
      ${textField("z-name", "Name (optional)", doc.name)}
      ${selectField("z-type", "Alarmtyp", ALARM_TYPES.map((t) => [t, ALARM_TYPE_LABELS[t]]),
        doc.alarm_type || "burglary")}</div>`,
      "Feuer/Wasser/CO/Sabotage sind automatisch 24/7 scharf")}
    ${card("Rolle je Modus", roles)}
    ${card("Optionen", `
      ${switchRow("z-exitok", "Darf beim Verlassen offen sein", o.use_exit_delay)}
      ${switchRow("z-armclose", "Schließen beendet das Exit-Delay", o.arm_after_closing)}
      ${switchRow("z-allowopen", "Darf offen bleiben", o.allow_open, "blockiert nie; erst erneutes Öffnen löst aus")}
      ${switchRow("z-bypass", "Offen = automatisch überbrücken", o.auto_bypass)}
      ${switchRow("z-unavail", "Ausfall löst Alarm aus", o.trigger_when_unavailable)}
      <div style="margin-top:12px;">${selectField("z-unavailpol", "Verhalten bei totem Sensor",
        [["ignore", "ignorieren"], ["block_arm", "Scharfschalten blockieren"],
         ["auto_bypass", "sichtbar überbrücken"]], o.unavailable_policy || "ignore")}</div>`)}`;
}

function blockFields(ctx, b, i, j) {
  const id = (f) => `b-${i}-${j}-${f}`;
  const list = (f, label, dl) => textField(id(f), label,
    Array.isArray(b[f]) ? b[f].join(", ") : b[f], { list: dl });
  const num = (f, label) => numField(id(f), label, b[f]);
  const txt = (f, label) => textField(id(f), label, b[f]);
  switch (b.type) {
    case "flash_lights": {
      const hex = "#" + (b.color_rgb || [255, 0, 0])
        .map((c) => c.toString(16).padStart(2, "0")).join("");
      return `<div class="form-grid">
        ${list("targets", "Ziele (Komma-Liste)", "dl-lights")}
        <div class="field"><label>Farbe</label>
          <input type="color" id="${id("color")}" value="${hex}" style="height:24px;padding:0;border:none;background:transparent;"></div>
        ${num("brightness_pct", "Helligkeit %")} ${num("period_s", "Periode s")}
        ${num("fade_s", "Fade s")}
        ${selectField(id("ncb"), "Nicht-farbfähige Ziele",
          [["off", "ausschalten"], ["hard_blink", "hart mitblinken"], ["ignore", "unverändert"]],
          b.non_color_behavior)}</div>`;
    }
    case "lights_on":
      return `<div class="form-grid">${list("targets", "Ziele", "dl-lights")}
        ${num("brightness_pct", "Helligkeit %")}
        ${num("refresh_interval_s", "Refresh s (0 = aus)")}</div>`;
    case "sound":
      return `<div class="form-grid">${list("targets", "Ziele", "dl-sound")}
        ${num("retrigger_interval_s", "Nachtrigger s")}
        ${num("max_duration_s", "Maximaldauer s (Pflicht)")}</div>`;
    case "announce_loop":
      return `<div class="form-grid">${txt("notify_service", "Notify-Service")}
        ${txt("message", "Ansagetext")} ${num("interval_s", "Intervall s")}
        ${list("media_targets", "Player", "dl-media")}
        ${num("volume_pct", "Lautstärke %")} ${num("volume_fallback_pct", "Fallback %")}</div>`;
    case "notify":
      return `<div class="form-grid">${txt("service", "Service")}
        ${txt("title", "Titel")} ${txt("message", "Text")}</div>`;
    case "lock":
      return `<div class="form-grid">${list("targets", "Schlösser", "dl-locks")}
        ${selectField(id("action"), "Aktion",
          [["lock", "verriegeln"], ["unlock", "öffnen (nur Feuer/CO wirksam)"]], b.action)}</div>`;
  }
  return "";
}

function profileEditor(ctx, doc) {
  const stages = (doc.stages || []).map((s, i) => {
    const blocks = s.blocks.map((b, j) => `
      <fieldset class="block"><legend>${BLOCK_LABELS[b.type]}
        <button class="icon-btn" style="width:32px;height:32px;vertical-align:middle;"
          title="Entfernen" data-action="del-block" data-i="${i}" data-j="${j}">${icon("close", 18)}</button></legend>
        ${blockFields(ctx, b, i, j)}</fieldset>`).join("");
    return card(`Stufe ${i + 1}`, `
      <div class="form">${numField(`stage-${i}-dur`, "Dauer s (leer = bis Alarmende)", s.duration_s)}</div>
      <div style="margin-top:12px;">${blocks}</div>
      <div style="display:flex;gap:8px;align-items:center;margin-top:8px;">
        ${selectField(`stage-${i}-newblock`, "Baustein-Typ",
          Object.keys(BLOCK_DEFAULTS).map((t) => [t, BLOCK_LABELS[t]]), "flash_lights")}
        <button class="btn" data-action="add-block" data-i="${i}">${icon("plus", 18)} Baustein</button>
      </div>`,
      `<button class="btn danger" data-action="del-stage" data-i="${i}">Stufe entfernen</button>`);
  }).join("");
  return `
    ${ctx._datalist("dl-lights", ["light", "switch"])}
    ${ctx._datalist("dl-sound", ["siren", "switch", "input_boolean", "button", "input_button"])}
    ${ctx._datalist("dl-media", ["media_player"])}
    ${ctx._datalist("dl-locks", ["lock"])}
    ${card("Profil", `<div class="form">${textField("p-name", "Name", doc.name)}</div>`,
      "Stufen laufen als Zeitachse ab Alarmbeginn")}
    ${stages}
    <div><button class="btn outlined" data-action="add-stage">${icon("plus", 18)} Stufe hinzufügen</button></div>`;
}

function userEditor(ctx, doc) {
  const r = doc.rights || {};
  const panelChecks = (ctx._data.panels || []).map((p) =>
    checkChip("u-panel", p.id, ctx._panelName(p.id),
      r.panels && r.panels.includes(p.id))).join("");
  return `
    ${card("Benutzer", `<div class="form">${textField("u-name", "Name", doc.name)}</div>
      ${switchRow("u-enabled", "Aktiv", doc.enabled !== false)}`)}
    ${card("Rechte", `
      ${switchRow("u-arm", "Darf scharfschalten", r.can_arm !== false)}
      ${switchRow("u-disarm", "Darf entschärfen", r.can_disarm !== false)}
      ${switchRow("u-allpanels", "Alle Bereiche", r.panels == null)}
      <div style="margin-top:8px;">${panelChecks}</div>`,
      "PIN und Duress-PIN setzt du in der Liste am Benutzer")}`;
}

function personEditor(ctx, doc) {
  return `
    ${ctx._datalist("dl-trackers", ["person", "device_tracker"])}
    ${ctx._datalist("dl-distance", ["sensor", "input_number"])}
    ${card("Person", `<div class="form">
      ${textField("pe-name", "Name", doc.name)}
      ${textField("pe-tracker", "Tracker-Entität (home/not_home)", doc.tracker_entity, { list: "dl-trackers" })}
      ${textField("pe-dist", "Distanz-Entität (optional)", doc.distance_entity, { list: "dl-distance" })}
      ${numField("pe-threshold", "Weg-Schwelle in Metern", doc.away_confirm_distance_m, "Standard")}
    </div>`, "ohne Distanzquelle zählt anhaltendes not_home")}`;
}

function ruleEditor(ctx, doc) {
  const arm = doc.arm || {};
  const personChecks = (ctx._data.persons || []).map((p) =>
    checkChip("r-person", p.id, p.name, doc.persons && doc.persons.includes(p.id))).join("");
  return `
    ${card("Regel", `<div class="form">${textField("r-name", "Name", doc.name)}</div>
      ${switchRow("r-enabled", "Aktiv", doc.enabled !== false)}`)}
    ${card("Scharfschalten", `<div class="form-grid">
      ${selectField("r-panel", "Bereich",
        [["master", "Gesamtsystem"], ...(ctx._data.panels || []).map((p) => [p.id, ctx._panelName(p.id)])],
        doc.panel_id || "master")}
      ${selectField("r-mode", "Modus", ALL_MODES.map((m) => [m, MODE_LABELS[m]]), arm.mode || "armed_away")}
      ${selectField("r-exec", "Ausführung",
        [["prewarn", "mit Vorwarnung"], ["immediate", "sofort"]], arm.execution || "prewarn")}
      ${numField("r-prewarn", "Vorwarnzeit s", arm.prewarn_s, "Standard")}</div>`)}
    ${card("Rückkehr", switchRow("r-return", "Bei Ankunft entschärfen",
      doc.return_action?.disarm !== false,
      "nur nach bestätigter Abwesenheit im selben Trip; nie während Alarm oder Eintrittsverzögerung"))}
    ${card("Personen", `${switchRow("r-allpersons", "Alle Personen", doc.persons == null)}
      <div style="margin-top:8px;">${personChecks || '<span class="muted">Noch keine Personen angelegt.</span>'}</div>`)}`;
}
