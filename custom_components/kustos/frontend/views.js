/* List views: Leitstand, Bereiche, Reaktionsprofile, Personen, Betrieb.
   Pure render functions; `ctx` is the panel component (data + helpers). */
import { esc, icon } from "./styles.js";

export const STATE_LABELS = {
  disarmed: "Unscharf", arming: "Wird scharf", armed: "Scharf",
  pending: "Eintrittsverzögerung", triggered: "ALARM",
};
export const MODE_LABELS = {
  armed_away: "Abwesend", armed_home: "Zuhause", armed_night: "Nacht",
  armed_vacation: "Urlaub", armed_custom_bypass: "Benutzerdefiniert",
};
export const ALL_MODES = Object.keys(MODE_LABELS);
export const PHASE_LABELS = {
  home: "zuhause", leaving: "verlässt gerade", confirmed_away: "bestätigt abwesend",
  returning: "auf dem Rückweg", untracked: "nicht verfolgbar", arrived: "angekommen",
};
export const ALARM_TYPES = ["burglary","fire","water","co","tamper","holdup","panic","technical"];
export const ALARM_TYPE_LABELS = {
  burglary: "Einbruch", fire: "Feuer", water: "Wasser", co: "CO",
  tamper: "Sabotage", holdup: "Überfall (still)", panic: "Panik", technical: "Technik",
};
export const BLOCK_LABELS = {
  flash_lights: "Licht blinken", lights_on: "Licht an", sound: "Alarmgeber",
  announce_loop: "Ansage-Loop", notify: "Benachrichtigung", lock: "Schloss",
};

const rowActions = (edit, del) => `
  <span class="meta">
    <button class="icon-btn" title="Bearbeiten" data-action="${edit.action}" ${edit.attrs}>${icon("pencil", 20)}</button>
    <button class="icon-btn" title="Löschen" data-action="${del.action}" ${del.attrs}>${icon("delete", 20)}</button>
  </span>`;

const listRow = (iconName, primary, secondary, meta = "") => `
  <div class="row">
    <span class="leading">${icon(iconName, 22)}</span>
    <span class="body"><div class="primary">${primary}</div>
      ${secondary ? `<div class="secondary">${secondary}</div>` : ""}</span>
    ${meta}
  </div>`;

/* ------------------------------------------------------------------ */

export function renderLeitstand(ctx) {
  const { state } = ctx._data;
  const master = state.master;
  const cards = state.panels.map((p) => {
    const zones = (ctx._data.zones || []).filter((z) => z.panel_id === p.panel_id);
    const walk = (state.walk_tests || {})[p.panel_id];
    const svcBtn = (svc, label, cls = "") =>
      `<button class="btn ${cls}" data-action="service" data-service="${svc}" data-panel="${p.panel_id}">${label}</button>`;
    const memory = p.alarm_memory.length
      ? `<p class="muted">Alarmspeicher: ${p.alarm_memory
          .map((m) => `${esc(m.entity_id)} (${ALARM_TYPE_LABELS[m.alarm_type] || m.alarm_type})`).join(", ")}</p>` : "";
    const bypassed = p.bypassed_zones.length
      ? `<p class="muted">Überbrückt: ${p.bypassed_zones.map((z) => esc(ctx._zoneName(z))).join(", ")}</p>` : "";
    return `
      <div class="card">
        <div class="card-header">${esc(ctx._areaName(p.area_id) || p.panel_id)}
          ${walk ? `<span class="chip">Walk-Test läuft</span>` : ""}</div>
        <div class="card-content">
          <div class="big-state ${p.state}">${STATE_LABELS[p.state] || p.state}
            ${p.arm_mode ? `<span class="chip">${MODE_LABELS[p.arm_mode] || p.arm_mode}</span>` : ""}
            ${p.ends_at ? `<span class="chip" data-ends-at="${p.ends_at}"></span>` : ""}</div>
          <p class="muted">${zones.length} Sensor(en)${p.active_alarm_types.length
            ? ` | aktiv: ${p.active_alarm_types.map((t) => ALARM_TYPE_LABELS[t] || t).join(", ")}` : ""}</p>
          ${bypassed}${memory}
        </div>
        <div class="card-actions">
          ${svcBtn("alarm_arm_away","Abwesend")}${svcBtn("alarm_arm_home","Zuhause")}
          ${svcBtn("alarm_arm_night","Nacht")}${svcBtn("alarm_disarm","Unscharf")}
          ${svcBtn("acknowledge","Quittieren")}
        </div>
      </div>`;
  });
  const presence = state.presence || [];
  const presenceCard = presence.length ? `
    <div class="card"><div class="card-header">Anwesenheit</div>
      <div class="rows">${presence.map((p) =>
        listRow("account", esc(p.name),
          `${PHASE_LABELS[p.phase] || p.phase}${p.trip_id ? ` | Trip ${p.trip_id.slice(-6)}` : ""}`)).join("")}
      </div></div>` : "";
  const groupCards = (state.groups || []).map((g) => `
    <div class="card"><div class="card-header">${esc(g.name)}
        <span class="hint">Gruppe</span></div>
      <div class="card-content"><div class="big-state ${g.state}">
        ${STATE_LABELS[g.state] || g.state}
        ${g.arm_mode ? `<span class="chip">${MODE_LABELS[g.arm_mode] || g.arm_mode}</span>` : ""}</div>
      <p class="muted">${g.panel_ids.map((pid) => esc(ctx._panelName(pid))).join(", ")}</p></div>
      <div class="card-actions">
        <button class="btn" data-action="service" data-service="alarm_arm_away" data-panel="${g.group_id}">Abwesend</button>
        <button class="btn" data-action="service" data-service="alarm_arm_night" data-panel="${g.group_id}">Nacht</button>
        <button class="btn" data-action="service" data-service="alarm_disarm" data-panel="${g.group_id}">Unscharf</button>
      </div></div>`).join("");
  return `<div class="cards">
    <div class="card"><div class="card-header">Gesamtsystem</div>
      <div class="card-content"><div class="big-state ${master.state}">
        ${STATE_LABELS[master.state] || master.state}
        ${master.arm_mode ? `<span class="chip">${MODE_LABELS[master.arm_mode] || master.arm_mode}</span>` : ""}
      </div></div></div>
    ${cards.join("") || `<div class="card"><div class="empty">Noch keine Bereiche. Lege im Tab "Bereiche" den ersten an.</div></div>`}
    ${groupCards}
    ${presenceCard}</div>`;
}

/* ------------------------------------------------------------------ */

export function renderBereiche(ctx) {
  const cards = (ctx._data.panels || []).map((p) => {
    const zones = (ctx._data.zones || []).filter((z) => z.panel_id === p.id);
    const modes = Object.entries(p.modes).filter(([, c]) => c.enabled)
      .map(([m]) => MODE_LABELS[m] || m).join(", ");
    const zoneRows = zones.map((z) => listRow(
      "shield",
      esc(z.name || ctx._friendly(z.entity_id)),
      `${esc(z.entity_id)} | ${ALARM_TYPE_LABELS[z.alarm_type] || z.alarm_type} | ${
        Object.entries(z.modes).map(([m, r]) => `${MODE_LABELS[m] || m}: ${r}`).join(", ") || "keine Rolle"}`,
      rowActions(
        { action: "edit-zone", attrs: `data-id="${z.id}" data-panel="${p.id}"` },
        { action: "del-zone", attrs: `data-id="${z.id}"` })
    )).join("");
    return `
      <div class="card">
        <div class="card-header">${esc(p.scope.type === "custom" ? p.scope.name : (ctx._areaName(p.scope.area_id) || p.scope.type))}
          <span class="hint">${modes || "keine Modi aktiviert"}</span></div>
        ${zones.length ? `<div class="rows">${zoneRows}</div>`
          : `<div class="empty">Keine Sensoren in diesem Bereich.</div>`}
        <div class="card-actions">
          <button class="btn" data-action="new-zone" data-panel="${p.id}">${icon("plus",18)} Sensor</button>
          <button class="btn" data-action="edit-panel" data-id="${p.id}">${icon("pencil",18)} Bereich</button>
          <button class="btn danger" data-action="del-panel" data-id="${p.id}">${icon("delete",18)} Löschen</button>
        </div>
      </div>`;
  });
  const groups = (ctx._data.state.groups || []).map((g) => listRow("shield",
    esc(g.name),
    `${g.panel_ids.map((pid) => esc(ctx._panelName(pid))).join(", ") || "keine Mitglieder"}`,
    rowActions(
      { action: "edit-group", attrs: `data-id="${g.group_id}"` },
      { action: "del-group", attrs: `data-id="${g.group_id}"` })
  )).join("");
  return `<div class="cards">${cards.join("") ||
    `<div class="card"><div class="empty">Noch keine Bereiche angelegt.</div></div>`}
    <div class="card"><div class="card-header">Bereichsgruppen
        <span class="hint">schalten als Einheit, die Gesamtheit der Sensoren zählt</span></div>
      ${groups ? `<div class="rows">${groups}</div>`
        : `<div class="empty">Noch keine Gruppen.</div>`}
      <div class="card-actions"><button class="btn" data-action="new-group">${icon("plus",18)} Gruppe</button></div>
    </div></div>
    <button class="fab" data-action="new-panel">${icon("plus",20)} Bereich anlegen</button>`;
}

/* ------------------------------------------------------------------ */

export function renderProfile(ctx) {
  const cards = (ctx._data.profiles || []).map((prof) => {
    const stages = prof.stages.map((s, i) => {
      const blocks = s.blocks.map((b) => {
        const targets = (b.targets || b.media_targets || [])
          .map((t) => ctx._friendly(t)).join(", ");
        return `${BLOCK_LABELS[b.type] || b.type}${targets ? ` → ${esc(targets)}` : ""}`;
      }).join(" · ") || "keine Bausteine";
      return listRow("bell", `Stufe ${i + 1} <span class="chip">${
        s.duration_s === null ? "bis Alarmende" : s.duration_s + " s"}</span>`, blocks);
    }).join("");
    return `<div class="card">
      <div class="card-header">${esc(prof.name)}</div>
      <div class="rows">${stages}</div>
      <div class="card-actions">
        <button class="btn" data-action="edit-profile" data-id="${prof.id}">${icon("pencil",18)} Bearbeiten</button>
        <button class="btn danger" data-action="del-profile" data-id="${prof.id}">${icon("delete",18)} Löschen</button>
      </div></div>`;
  });
  return `<div class="cards">${cards.join("") ||
    `<div class="card"><div class="empty">Noch keine Reaktionsprofile.</div></div>`}</div>
    <button class="fab" data-action="new-profile">${icon("plus",20)} Profil anlegen</button>`;
}

/* ------------------------------------------------------------------ */

export function renderPersonen(ctx) {
  const personByEntity = {};
  for (const p of (ctx._data.persons || [])) {
    if (p.person_entity) personByEntity[p.person_entity] = p;
  }
  const phases = {};
  for (const p of (ctx._data.state.presence || [])) phases[p.person_id] = p.phase;

  const members = (ctx._data.users || [])
    .filter((u) => u.person_entity)
    .map((u) => {
      const person = personByEntity[u.person_entity];
      const rights = [u.rights.can_arm ? "scharf" : null, u.rights.can_disarm ? "unscharf" : null]
        .filter(Boolean).join(" + ") || "keine Rechte";
      const panels = u.rights.panels === null ? "alle Bereiche"
        : u.rights.panels.map((p) => esc(ctx._panelName(p))).join(", ");
      const presence = person
        ? ` | ${PHASE_LABELS[phases[person.id]] || "-"}${person.distance_entity
            ? ` | Distanz: ${esc(ctx._friendly(person.distance_entity))}` : ""}`
        : "";
      return listRow("account",
        `${esc(u.name)}${u.enabled ? "" : ' <span class="chip">deaktiviert</span>'}`,
        `${rights} | ${panels}${presence}`,
        `<span class="meta">
          <button class="btn" data-action="set-pin" data-id="${u.id}" data-kind="normal">PIN</button>
          <button class="btn" data-action="set-pin" data-id="${u.id}" data-kind="duress">Duress</button>
          <button class="icon-btn" title="Bearbeiten" data-action="edit-member" data-id="${u.id}">${icon("pencil", 20)}</button>
        </span>`);
    }).join("");

  const rules = (ctx._data.rules || []).map((r) => listRow("cog",
    `${esc(r.name)}${r.enabled ? "" : ' <span class="chip">deaktiviert</span>'}`,
    `${r.panel_id === "master" ? "Gesamtsystem" : esc(ctx._panelName(r.panel_id))} | ${
      MODE_LABELS[r.arm.mode] || r.arm.mode}, ${r.arm.execution === "prewarn" ? "mit Vorwarnung" : "sofort"}${
      r.return_action.disarm ? " | entschärft bei Ankunft" : ""}`,
    rowActions(
      { action: "edit-rule", attrs: `data-id="${r.id}"` },
      { action: "del-rule", attrs: `data-id="${r.id}"` })
  )).join("");

  return `<div class="cards">
    <div class="card"><div class="card-header">Personen
        <span class="hint">kommen automatisch aus Home Assistant</span></div>
      ${members ? `<div class="rows">${members}</div>`
        : `<div class="empty">Keine HA-Personen gefunden. Lege Personen unter Einstellungen, Personen an.</div>`}
    </div>
    <div class="card"><div class="card-header">Automatik-Regeln</div>
      ${rules ? `<div class="rows">${rules}</div>` : `<div class="empty">Keine Regeln angelegt.</div>`}
      <div class="card-actions"><button class="btn" data-action="new-rule">${icon("plus", 18)} Regel</button></div>
    </div>
  </div>`;
}

/* ------------------------------------------------------------------ */

export function renderBetrieb(ctx) {
  const s = ctx._data.settings;
  const walk = (ctx._data.panels || []).map((p) => {
    const info = (ctx._data.state.walk_tests || {})[p.id];
    return listRow("shield",
      `Walk-Test: ${esc(p.scope.type === "custom" ? p.scope.name : (ctx._areaName(p.scope.area_id) || p.scope.type))}`,
      info
        ? `läuft, Ende <span data-ends-at="${info.ends_at}"></span> | getestet: ${
            info.tested.map((z) => esc(ctx._zoneName(z))).join(", ") || "noch kein Sensor"}`
        : "nicht aktiv",
      `<span class="meta"><button class="btn ${info ? "danger" : ""}" data-action="walk"
         data-walk="${info ? "stop" : "start"}" data-panel="${p.id}">
         ${info ? "Beenden" : "Starten"}</button></span>`);
  }).join("");
  const audit = (ctx._data.audit?.entries || []).map((e) => {
    const { ts, seq, kind, ...rest } = e;
    return listRow("bell", esc(kind),
      `${ts.slice(0, 19).replace("T", " ")} UTC | <code>${esc(JSON.stringify(rest))}</code>`);
  }).join("");
  return `<div class="cards">
    <div class="card"><div class="card-header">Walk-Test</div>
      ${walk ? `<div class="rows">${walk}</div>` : `<div class="empty">Keine Bereiche.</div>`}</div>
    <div class="card"><div class="card-header">Einstellungen
        <span class="hint">zentrale Defaults, wirken sofort</span></div>
      <div class="rows">
        ${listRow("cog", "Standard-Zeiten",
          `Exit ${s.defaults.exit_delay_s} s | Entry ${s.defaults.entry_delay_s} s | Alarmdauer ${
            s.defaults.trigger_time_s} s | Walk-Test ${s.defaults.walk_test_timeout_s} s`)}
        ${listRow("cog", "Anwesenheit",
          `Weg-Schwelle ${s.presence.away_confirm_distance_m} m | Mindest-Abwesenheit ${
            s.presence.min_away_duration_s} s | Vorwarnzeit ${s.presence.prewarn_s} s`)}
        ${listRow("cog", "Sicherheit",
          `Quittierungspflicht ${s.security.require_explicit_ack ? "an" : "aus"} | Entschärfen quittiert ${
            s.security.disarm_acknowledges ? "mit" : "nicht"}`)}
      </div>
      <div class="card-actions">
        <button class="btn" data-action="edit-settings">${icon("pencil",18)} Bearbeiten</button>
      </div></div>
    <div class="card"><div class="card-header">Protokoll
        <span class="hint">${ctx._data.audit?.month || ""}</span></div>
      ${audit ? `<div class="rows">${audit}</div>` : `<div class="empty">Noch keine Einträge.</div>`}</div>
  </div>`;
}
