/* Editor subpages: centered column of section cards, save pill bottom right.
   Every value that exists in the system is PICKED, never typed (entity
   picker with search and friendly names, like the automation editor). */
import { esc, icon } from "./styles.js";
import {
  ALARM_TYPES, ALARM_TYPE_LABELS, ALL_MODES, BLOCK_LABELS, MODE_LABELS,
} from "./views.js";

export const SENSOR_TYPE_LABELS = {
  opening: "Öffnung (Tür/Fenster)", motion: "Bewegung", tilt: "Neigung (Kippfenster)",
  vibration: "Erschütterung", glass: "Glasbruch", generic: "Allgemein",
};
export const BLOCK_DESCRIPTIONS = {
  flash_lights: "Farbfähige Lampen blinken in der Alarmfarbe, Zustände werden exakt wiederhergestellt",
  lights_on: "Lampen dauerhaft an, optional zyklisch nachgeschaltet (Flutlichter)",
  sound: "Sirenen, Schalter oder Taster mit Nachtrigger (z.B. Rauchmelder-Testknopf)",
  announce_loop: "Wiederkehrende Sprachansage über einen Notify-Service, mit Lautstärke-Restore",
  notify: "Einmalige Benachrichtigung beim Start der Stufe",
  lock: "Türschlösser verriegeln oder (bei Feuer/CO) öffnen",
};

export const ROLES = ["inactive", "instant", "delayed", "follower"];
export const ROLE_LABELS = {
  inactive: "inaktiv", instant: "sofort", delayed: "verzögert", follower: "Folgezone",
};
export const BLOCK_DEFAULTS = {
  flash_lights: { type: "flash_lights", targets: [], color_rgb: [255, 0, 0],
                  brightness_pct: 100, period_s: 2.0, fade_s: 0.4, non_color_behavior: "off" },
  lights_on:    { type: "lights_on", targets: [], brightness_pct: 100, refresh_interval_s: 0 },
  sound:        { type: "sound", targets: [], retrigger_interval_s: 30, max_duration_s: 180 },
  announce_loop:{ type: "announce_loop", notify_service: "", message: "",
                  interval_s: 15, media_targets: [], volume_pct: 80, volume_fallback_pct: 30 },
  notify:       { type: "notify", service: "persistent_notification.create", title: "", message: "" },
  lock:         { type: "lock", targets: [], action: "lock" },
};

export const EDITOR_TITLES = {
  settings: ["Einstellungen", "Einstellungen"],
  group: ["Neue Bereichsgruppe", "Bereichsgruppe bearbeiten"],
  panel: ["Neuer Bereich", "Bereich bearbeiten"],
  zone: ["Neuer Sensor", "Sensor bearbeiten"],
  profile: ["Neues Profil", "Profil bearbeiten"],
  member: ["", "Person bearbeiten"],
  rule: ["Neue Regel", "Regel bearbeiten"],
};

/* ---------- basic fields ---------- */

export const textField = (id, label, value, opts = {}) => `
  <div class="field"><label for="${id}">${label}</label>
    <input type="${opts.type || "text"}" id="${id}" value="${esc(value ?? "")}"
      ${opts.step ? `step="${opts.step}"` : ""} placeholder="${esc(opts.placeholder || "")}"></div>`;

export const numField = (id, label, value, placeholder = "") =>
  textField(id, label, value ?? "", { type: "number", step: "0.1", placeholder });

export const selectField = (id, label, options, selected, opts = {}) => `
  <div class="field ${opts.disabled ? "disabled" : ""}"><label for="${id}">${label}</label>
    <select id="${id}" ${opts.disabled ? "disabled" : ""}>${options.map(([v, text]) =>
      `<option value="${esc(v)}" ${String(v) === String(selected) ? "selected" : ""}>${esc(text)}</option>`).join("")}
    </select></div>`;

export const switchRow = (id, label, checked, secondary = "") => `
  <div class="switch-row">
    <span class="body"><div>${label}</div>
      ${secondary ? `<div class="secondary">${secondary}</div>` : ""}</span>
    <label class="switch"><input type="checkbox" id="${id}" ${checked ? "checked" : ""}>
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

/* ---------- picker field ---------- */

const displayName = (ctx, kind, value) => {
  if (kind === "area") return ctx._areaName(value);
  if (kind === "entity") return ctx._friendly(value);
  return value;
};

export function pickerValueHTML(ctx, values, multi, kind, placeholder) {
  let inner;
  if (!values.length) {
    inner = `<span class="ph">${esc(placeholder)}</span>`;
  } else if (multi) {
    inner = `<span class="chips">${values.map((v) => `
      <span class="chip-item">${esc(displayName(ctx, kind, v))}
        <button class="chip-x" title="Entfernen" data-action="chip-del"
          data-value="${esc(v)}">${icon("close", 14)}</button></span>`).join("")}</span>`;
  } else {
    const v = values[0];
    const name = displayName(ctx, kind, v);
    inner = `<span>${esc(name)}</span>${name !== v ? `<span class="vd-sec">${esc(v)}</span>` : ""}`;
  }
  return `${inner}<span class="chev">${icon("chevron-right", 20)}</span>`;
}

export function pickerField(ctx, id, label, value, opts = {}) {
  const multi = !!opts.multi;
  const values = Array.isArray(value) ? value : (value ? [value] : []);
  const placeholder = opts.placeholder || "Auswählen";
  return `
    <div class="field picker-field" data-action="pick" data-input="${id}"
         data-kind="${opts.kind || "entity"}" data-domains="${(opts.domains || []).join(",")}"
         data-multi="${multi ? 1 : 0}" data-label="${esc(label)}"
         data-placeholder="${esc(placeholder)}">
      <label>${label}</label>
      <input type="hidden" id="${id}" value="${esc(values.join(","))}">
      <span class="value-display" id="${id}-display">${pickerValueHTML(ctx, values, multi, opts.kind || "entity", placeholder)}</span>
    </div>`;
}

/* ---------- editors ---------- */

export function renderEditor(ctx) {
  const { kind, draft } = ctx._edit;
  const body = {
    panel: panelEditor, zone: zoneEditor, profile: profileEditor,
    member: memberEditor, rule: ruleEditor, settings: settingsEditor,
    group: groupEditor,
  }[kind](ctx, draft);
  return `<div class="cards">${body}</div>
    <div class="fab-row">
      <button class="fab-secondary ${ctx._dirty ? "" : "hidden"}" data-action="discard">
        ${icon("close", 20)} Verwerfen</button>
      <button class="fab" data-action="save-${kind}" data-id="${draft.id || ""}"
        ${ctx._edit.panelId ? `data-panel="${ctx._edit.panelId}"` : ""}>
        ${icon("save", 20)} Speichern</button>
    </div>`;
}

function panelEditor(ctx, doc) {
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
  const profileOptions = () => [["", "kein Profil"],
    ...(ctx._data.profiles || []).map((pr) => [pr.id, pr.name])];
  const assignments = `<div class="form-grid">${ALARM_TYPES.map((t) =>
    selectField(`prof-${t}`, ALARM_TYPE_LABELS[t],
      profileOptions(), ((doc.alarm_types || {})[t] || {}).profile_id || "")).join("")}</div>`;
  const scopeType = doc.scope?.type === "custom" ? "custom" : "area";
  return `
    ${card("Bereich", `<div class="form">
      ${selectField("f-scopetype", "Art des Bereichs",
        [["area", "Home-Assistant-Bereich"], ["custom", "Individuell (nur Kustos)"]], scopeType)}
      ${pickerField(ctx, "f-area", "Home-Assistant-Bereich", doc.scope?.area_id, { kind: "area" })}
      ${textField("f-cname", "Eigener Name (bei Individuell)", doc.scope?.name)}
    </div>`, "es gilt das Feld passend zur gewählten Art")}
    ${card("Modi", modes, "Zeiten leer = zentrale Standardwerte")}
    ${card("Optionen", `
      ${switchRow("f-codearm", "Code zum Scharfschalten", opts.code_arm_required)}
      ${switchRow("f-codedisarm", "Code zum Entschärfen", opts.code_disarm_required !== false)}
      ${switchRow("f-rearm", "Nach Ablauf der Alarmdauer wieder scharf",
        opts.rearm_after_trigger !== false, "offene Sensoren werden dabei sichtbar überbrückt")}`)}
    ${card("Reaktionsprofile je Alarmtyp", assignments)}`;
}

function zoneEditor(ctx, doc) {
  const panelDoc = (ctx._data.panels || []).find((p) => p.id === ctx._edit.panelId);
  const enabledModes = Object.entries(panelDoc?.modes || {})
    .filter(([, c]) => c.enabled).map(([m]) => m);
  // Alle Modi zeigen; im Bereich nicht aktivierte ausgegraut (User-Feedback).
  const hasDisabled = ALL_MODES.some((m) => !enabledModes.includes(m));
  const roles = `<div class="form-grid">${ALL_MODES.map((m) => {
    const enabled = enabledModes.includes(m);
    return selectField(`role-${m}`, MODE_LABELS[m],
      ROLES.map((r) => [r, ROLE_LABELS[r]]), (doc.modes || {})[m] || "inactive",
      { disabled: !enabled });
  }).join("")}</div>
  ${hasDisabled ? `<p class="muted" style="margin:10px 0 0;">Ausgegraute Modi sind in diesem Bereich nicht aktiviert (Bereich bearbeiten, Karte Modi).</p>` : ""}
  <div class="muted" style="margin-top:12px; line-height:1.8;">
    <b>sofort</b>: löst ohne Karenz aus (Fenster, Glasbruch)<br>
    <b>verzögert</b>: startet die Eintrittsverzögerung zum Entschärfen (Haustür)<br>
    <b>Folgezone</b>: wie sofort, folgt aber einer bereits laufenden Eintrittsverzögerung, statt selbst auszulösen (Flur hinter der Haustür)<br>
    <b>inaktiv</b>: in diesem Modus nicht überwacht
  </div>`;
  const o = doc.options || {};
  return `
    ${card("Sensor", `<div class="form">
      ${pickerField(ctx, "z-entity", "Entität", doc.entity_id,
        { domains: ["binary_sensor", "input_boolean", "switch", "sensor"] })}
      ${textField("z-name", "Name (optional)", doc.name)}
      ${selectField("z-type", "Alarmtyp", ALARM_TYPES.map((t) => [t, ALARM_TYPE_LABELS[t]]),
        doc.alarm_type || "burglary")}
      <div class="muted" id="z-type-hint"></div>
      ${selectField("z-sensortype", "Sensortyp",
        Object.entries(SENSOR_TYPE_LABELS), doc.sensor_type || "opening")}
      <div id="st-tilt" class="${(doc.sensor_type || "opening") === "tilt" ? "" : "hidden"}">
        <div class="form-grid">
          ${numField("z-tiltmin", "Gekippt ab (Sensorwert)", (doc.evaluation || {}).tilt_min)}
          ${numField("z-openmin", "Offen ab (Sensorwert)", (doc.evaluation || {}).open_min)}
        </div>
        ${switchRow("z-tiltarm", "Scharfschalten bei gekipptem Fenster erlaubt",
          (doc.evaluation || {}).arm_allowed_when_tilted !== false,
          "gekippt löst nie aus; Alarm erst ab dem Offen-Wert")}
        <p class="muted">Ohne Werte gilt: binärer Kipp-Sensor, an = gekippt (löst nie selbst aus).</p>
      </div>
      <div id="st-vibration" class="${(doc.sensor_type || "opening") === "vibration" ? "" : "hidden"}">
        <div class="form-grid">
          ${numField("z-tripcount", "Auslösungen bis Alarm", (doc.evaluation || {}).trip_count ?? 1)}
          ${numField("z-tripwindow", "Zeitfenster s", (doc.evaluation || {}).trip_window_s ?? 30)}
        </div>
        <p class="muted">Erst die eingestellte Anzahl Impulse innerhalb des Fensters löst aus (Fehlalarm-Schutz).</p>
      </div></div>`,
      "Feuer/Wasser/CO/Sabotage sind automatisch 24/7 scharf")}
    ${card("Rolle je Modus", roles, "steuert, wann dieser Sensor überwacht wird")}
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
  const pick = (f, label, domains) => pickerField(ctx, id(f), label, b[f] || [],
    { domains, multi: true });
  const num = (f, label) => numField(id(f), label, b[f]);
  const txt = (f, label) => textField(id(f), label, b[f]);
  switch (b.type) {
    case "flash_lights": {
      const hex = "#" + (b.color_rgb || [255, 0, 0])
        .map((c) => c.toString(16).padStart(2, "0")).join("");
      return `${pick("targets", "Lampen", ["light", "switch"])}
        <div class="form-grid" style="margin-top:12px;">
        <div class="field"><label>Farbe</label>
          <input type="color" id="${id("color")}" value="${hex}" style="height:24px;padding:0;border:none;background:transparent;"></div>
        ${num("brightness_pct", "Helligkeit %")} ${num("period_s", "Periode s")}
        ${num("fade_s", "Fade s")}
        ${selectField(id("ncb"), "Nicht-farbfähige Lampen",
          [["off", "ausschalten"], ["hard_blink", "hart mitblinken"], ["ignore", "unverändert"]],
          b.non_color_behavior)}</div>`;
    }
    case "lights_on":
      return `${pick("targets", "Lampen", ["light", "switch"])}
        <div class="form-grid" style="margin-top:12px;">${num("brightness_pct", "Helligkeit %")}
        ${num("refresh_interval_s", "Refresh s (0 = aus)")}</div>`;
    case "sound":
      return `${pick("targets", "Alarmgeber", ["siren", "switch", "input_boolean", "button", "input_button"])}
        <div class="form-grid" style="margin-top:12px;">${num("retrigger_interval_s", "Nachtrigger s")}
        ${num("max_duration_s", "Maximaldauer s (Pflicht)")}</div>`;
    case "announce_loop":
      return `${pickerField(ctx, id("notify_service"), "Notify-Service", b.notify_service, { kind: "service" })}
        <div class="form" style="margin-top:12px;">${txt("message", "Ansagetext")}</div>
        ${pick("media_targets", "Player (Lautstärke)", ["media_player"])}
        <div class="form-grid" style="margin-top:12px;">${num("interval_s", "Intervall s")}
        ${num("volume_pct", "Lautstärke %")} ${num("volume_fallback_pct", "Fallback %")}</div>`;
    case "notify":
      return `${pickerField(ctx, id("service"), "Service", b.service, { kind: "service" })}
        <div class="form-grid" style="margin-top:12px;">${txt("title", "Titel")} ${txt("message", "Text")}</div>`;
    case "lock":
      return `${pick("targets", "Schlösser", ["lock"])}
        <div class="form-grid" style="margin-top:12px;">${selectField(id("action"), "Aktion",
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
      <div style="margin-top:8px;">
        <button class="btn" data-action="add-block" data-i="${i}">${icon("plus", 18)} Baustein hinzufügen</button>
      </div>`,
      `<button class="btn danger" data-action="del-stage" data-i="${i}">Stufe entfernen</button>`);
  }).join("");
  return `
    ${card("Profil", `<div class="form">${textField("p-name", "Name", doc.name)}</div>`,
      "Stufen laufen als Zeitachse ab Alarmbeginn")}
    ${stages}
    <div><button class="btn outlined" data-action="add-stage">${icon("plus", 18)} Stufe hinzufügen</button></div>`;
}

function memberEditor(ctx, draft) {
  const u = draft.user;
  const p = draft.person || {};
  const r = u.rights || {};
  const panelChecks = (ctx._data.panels || []).map((pl) =>
    checkChip("u-panel", pl.id, ctx._panelName(pl.id),
      r.panels && r.panels.includes(pl.id))).join("");
  return `
    ${card(esc(u.name), switchRow("u-enabled", "Aktiv", u.enabled !== false,
      "kommt automatisch aus Home Assistant"),
      esc(u.person_entity || ""))}
    ${card("Zugang", `
      ${switchRow("u-arm", "Darf scharfschalten", r.can_arm !== false)}
      ${switchRow("u-disarm", "Darf entschärfen", r.can_disarm !== false)}
      ${switchRow("u-allpanels", "Alle Bereiche", r.panels == null)}
      <div style="margin-top:8px;">${panelChecks}</div>`,
      "PIN und Duress-PIN setzt du in der Personen-Liste")}
    ${card("Anwesenheit", `<div class="form">
      ${pickerField(ctx, "pe-dist", "Distanz-Entität (optional)", p.distance_entity,
        { domains: ["sensor", "input_number", "number"] })}
      ${numField("pe-threshold", "Weg-Schwelle in Metern", p.away_confirm_distance_m, "Standard")}
    </div>`, "ohne Distanzquelle zählt anhaltendes not_home")}`;
}

function groupEditor(ctx, doc) {
  const checks = (ctx._data.panels || []).map((p) =>
    checkChip("g-panel", p.id, ctx._panelName(p.id),
      (doc.panel_ids || []).includes(p.id))).join("");
  return `
    ${card("Bereichsgruppe", `<div class="form">${textField("g-name", "Name", doc.name)}</div>`,
      "schaltet als Einheit; die Gesamtheit aller Sensoren zählt")}
    ${card("Mitglieder", checks || '<span class="muted">Noch keine Bereiche angelegt.</span>')}`;
}

function ruleEditor(ctx, doc) {
  const arm = doc.arm || {};
  const personChecks = (ctx._data.persons || [])
    .filter((p) => p.person_entity)
    .map((p) => checkChip("r-person", p.id, p.name,
      doc.persons && doc.persons.includes(p.id))).join("");
  return `
    ${card("Regel", `<div class="form">${textField("r-name", "Name", doc.name)}</div>
      ${switchRow("r-enabled", "Aktiv", doc.enabled !== false)}`)}
    ${card("Scharfschalten", `<div class="form-grid">
      ${selectField("r-panel", "Bereich",
        [["master", "Gesamtsystem"],
         ...(ctx._data.panels || []).map((p) => [p.id, ctx._panelName(p.id)]),
         ...((ctx._data.state.groups || []).map((g) => [g.group_id, `Gruppe: ${g.name}`]))],
        doc.panel_id || "master")}
      ${selectField("r-mode", "Modus", ALL_MODES.map((m) => [m, MODE_LABELS[m]]), arm.mode || "armed_away")}
      ${selectField("r-exec", "Ausführung",
        [["prewarn", "mit Vorwarnung"], ["immediate", "sofort"]], arm.execution || "prewarn")}
      ${numField("r-prewarn", "Vorwarnzeit s", arm.prewarn_s, "Standard")}</div>`)}
    ${card("Rückkehr", switchRow("r-return", "Bei Ankunft entschärfen",
      doc.return_action?.disarm !== false,
      "nur nach bestätigter Abwesenheit im selben Trip; nie während Alarm oder Eintrittsverzögerung"))}
    ${card("Personen", `${switchRow("r-allpersons", "Alle Personen", doc.persons == null)}
      <div style="margin-top:8px;">${personChecks || '<span class="muted">Keine HA-Personen gefunden.</span>'}</div>`)}`;
}


function settingsEditor(ctx, draft) {
  const d = draft;
  const prio = d.engine.alarm_type_priority.map((t, i) => `
    <div class="row"><span class="body"><div class="primary">${i + 1}. ${ALARM_TYPE_LABELS[t] || t}</div></span>
      <span class="meta">
        <button class="icon-btn" title="Hoch" data-action="prio-up" data-i="${i}" ${i === 0 ? "disabled" : ""}>${icon("arrow-up", 20)}</button>
        <button class="icon-btn" title="Runter" data-action="prio-down" data-i="${i}" ${i === d.engine.alarm_type_priority.length - 1 ? "disabled" : ""}>${icon("arrow-down", 20)}</button>
      </span></div>`).join("");
  const lifeSafety = ALARM_TYPES.map((t) =>
    `<label style="display:inline-flex;align-items:center;gap:6px;margin:4px 12px 4px 0;">
      <input type="checkbox" class="ls-type" value="${t}"
        ${d.engine.life_safety_unlock_types.includes(t) ? "checked" : ""}> ${ALARM_TYPE_LABELS[t]}
    </label>`).join("");
  return `
    ${card("Standard-Zeiten", `<div class="form-grid">
      ${numField("s-exit", "Exit-Delay s", d.defaults.exit_delay_s)}
      ${numField("s-entry", "Entry-Delay s", d.defaults.entry_delay_s)}
      ${numField("s-trigger", "Alarmdauer s (0 = bis Quittierung)", d.defaults.trigger_time_s)}
      ${numField("s-debounce", "Kontakt-Entprellung s", d.defaults.debounce_s)}
      ${numField("s-walk", "Walk-Test-Timeout s", d.defaults.walk_test_timeout_s)}
    </div>`, "gelten, wo ein Bereich nichts Eigenes setzt")}
    ${card("Sicherheit", `
      ${switchRow("s-ack", "Alarme müssen quittiert werden", d.security.require_explicit_ack,
        "Alarmspeicher bleibt bis zur Quittierung sichtbar")}
      ${switchRow("s-disack", "Entschärfen quittiert automatisch mit", d.security.disarm_acknowledges)}`)}
    ${card("Anwesenheit", `<div class="form-grid">
      ${numField("s-away", "Weg-Schwelle m", d.presence.away_confirm_distance_m)}
      ${numField("s-minaway", "Mindest-Abwesenheit s (ohne Distanzquelle)", d.presence.min_away_duration_s)}
      ${numField("s-prewarn", "Vorwarnzeit vor Auto-Scharf s", d.presence.prewarn_s)}
    </div>`, "pro Person und Regel übersteuerbar")}
    ${card("Alarmtyp-Priorität", `<div class="rows">${prio}</div>`,
      "wer bei Konflikten dieselben Geräte gewinnt")}
    ${card("Türen öffnen erlaubt bei", lifeSafety,
      "Schloss-Baustein 'öffnen' wirkt nur für diese Alarmtypen")}
    ${card("Erweitert", `<div class="form-grid">
      ${numField("s-retry", "Restore-Nachversuch-Fenster s", d.engine.restore_retry_window_s)}
      ${numField("s-audit", "Protokoll-Abfragelimit", d.audit.query_limit)}
      ${numField("s-save", "Laufzeit-Speicherverzögerung s", d.storage.runtime_save_delay_s)}
    </div>`)}`;
}
