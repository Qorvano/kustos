/* Kustos sidebar panel: buildless vanilla web component.
   Read AND write: full CRUD for panels, zones, profiles, users, persons,
   rules plus settings editor. Deliberately plain; pretty comes later. */

const STATE_LABELS = {
  disarmed: "Unscharf", arming: "Wird scharf", armed: "Scharf",
  pending: "Eintrittsverzögerung", triggered: "ALARM",
};
const MODE_LABELS = {
  armed_away: "Abwesend", armed_home: "Zuhause", armed_night: "Nacht",
  armed_vacation: "Urlaub", armed_custom_bypass: "Benutzerdefiniert",
};
const ALL_MODES = Object.keys(MODE_LABELS);
const PHASE_LABELS = {
  home: "zuhause", leaving: "verlässt gerade", confirmed_away: "bestätigt abwesend",
  returning: "auf dem Rückweg", untracked: "nicht verfolgbar", arrived: "angekommen",
};
const ALARM_TYPES = ["burglary","fire","water","co","tamper","holdup","panic","technical"];
const ALARM_TYPE_LABELS = {
  burglary: "Einbruch", fire: "Feuer", water: "Wasser", co: "CO",
  tamper: "Sabotage", holdup: "Überfall (still)", panic: "Panik", technical: "Technik",
};
const ROLES = ["inactive","instant","delayed","follower"];
const BLOCK_LABELS = {
  flash_lights: "Licht blinken", lights_on: "Licht an", sound: "Alarmgeber",
  announce_loop: "Ansage-Loop", notify: "Benachrichtigung", lock: "Schloss",
};
const BLOCK_DEFAULTS = {
  flash_lights: { type: "flash_lights", targets: [], color_rgb: [255,0,0],
                  brightness_pct: 100, period_s: 2.0, fade_s: 0.4, non_color_behavior: "off" },
  lights_on:    { type: "lights_on", targets: [], brightness_pct: 100, refresh_interval_s: 0 },
  sound:        { type: "sound", targets: [], retrigger_interval_s: 30, max_duration_s: 180 },
  announce_loop:{ type: "announce_loop", notify_service: "notify.", message: "",
                  interval_s: 15, media_targets: [], volume_pct: 80, volume_fallback_pct: 30 },
  notify:       { type: "notify", service: "persistent_notification.create", title: "", message: "" },
  lock:         { type: "lock", targets: [], action: "lock" },
};

const esc = (v) => String(v ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
  .replace(/"/g, "&quot;");

class KustosPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "leitstand";
    this._data = {};
    this._edit = null; // {kind, id, draft, panelId}
    this._hass = null;
    this._tick = null;
    this._unsubs = [];
  }

  set hass(hass) {
    const first = this._hass === null;
    this._hass = hass;
    if (first) { this._refresh(); this._subscribe(); }
  }

  connectedCallback() {
    this._render();
    this._tick = setInterval(() => this._updateCountdowns(), 1000);
  }
  disconnectedCallback() {
    clearInterval(this._tick);
    for (const u of this._unsubs) u.then((x) => x()).catch(() => {});
    this._unsubs = [];
  }

  async _subscribe() {
    const conn = this._hass.connection;
    for (const evt of [
      "kustos_arming","kustos_armed","kustos_pending","kustos_triggered",
      "kustos_disarmed","kustos_arm_failed","kustos_acknowledged",
      "kustos_zone_bypassed","kustos_walk_test_zone","kustos_presence_phase",
      "kustos_auto_arm_pending","kustos_auto_armed","kustos_auto_disarmed",
    ]) {
      this._unsubs.push(conn.subscribeEvents(() => {
        if (!this._edit) this._refresh();  // never yank a form under the user
      }, evt));
    }
  }

  async _refresh() {
    if (!this._hass) return;
    const ws = (type, extra) => this._hass.callWS({ type, ...(extra || {}) });
    try {
      const [state, panels, zones, profiles, users, persons, rules, audit, settings] =
        await Promise.all([
          ws("kustos/state/list"), ws("kustos/panels/list"), ws("kustos/zones/list"),
          ws("kustos/profiles/list"), ws("kustos/users/list"),
          ws("kustos/persons/list"), ws("kustos/rules/list"),
          ws("kustos/audit/query", { limit: 50 }), ws("kustos/settings/get"),
        ]);
      this._data = { state, panels, zones, profiles, users, persons, rules, audit, settings };
    } catch (err) {
      this._data = { error: String(err.message || err) };
    }
    this._render();
  }

  async _ws(type, payload) {
    try {
      const result = await this._hass.callWS({ type, ...payload });
      return { ok: true, result };
    } catch (err) {
      alert("Fehler: " + (err.message || err));
      return { ok: false };
    }
  }

  // ------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------

  _panelEntity(panelId) {
    for (const [eid, st] of Object.entries(this._hass.states)) {
      if (eid.startsWith("alarm_control_panel.") && st.attributes.panel_id === panelId)
        return eid;
    }
    return null;
  }

  _panelName(panelId) {
    const doc = (this._data.panels || []).find((p) => p.id === panelId);
    return doc ? (doc.scope.area_id || doc.scope.type) : panelId;
  }
  _zoneName(zoneId) {
    const z = (this._data.zones || []).find((x) => x.id === zoneId);
    return z ? (z.name || z.entity_id) : zoneId;
  }

  _datalist(id, domains) {
    const options = Object.keys(this._hass.states)
      .filter((e) => domains.some((d) => e.startsWith(d + ".")))
      .sort()
      .map((e) => `<option value="${esc(e)}">`).join("");
    return `<datalist id="${id}">${options}</datalist>`;
  }

  _q(id) { return this.shadowRoot.getElementById(id); }
  _val(id) { return this._q(id) ? this._q(id).value.trim() : ""; }
  _num(id) { const v = this._val(id); return v === "" ? null : Number(v); }
  _chk(id) { return this._q(id) ? this._q(id).checked : false; }
  _list(id) {
    return this._val(id).split(",").map((s) => s.trim()).filter(Boolean);
  }

  _updateCountdowns() {
    for (const el of this.shadowRoot.querySelectorAll("[data-ends-at]")) {
      const remaining = Math.max(0,
        Math.round((new Date(el.dataset.endsAt) - Date.now()) / 1000));
      el.textContent = `noch ${remaining} s`;
    }
  }

  // ------------------------------------------------------------------
  // Rendering
  // ------------------------------------------------------------------

  _render() {
    const style = `
      :host { display:block; padding:16px; font-family: var(--paper-font-body1_-_font-family, sans-serif);
              color: var(--primary-text-color); background: var(--primary-background-color); min-height:100%; }
      h1 { font-size:1.4em; margin:0 0 12px; }
      h3 { margin:0 0 8px; } h4 { margin:12px 0 4px; }
      nav button { margin:0 8px 8px 0; padding:8px 16px; border:none; border-radius:4px;
                   background: var(--secondary-background-color); color: var(--primary-text-color); cursor:pointer; }
      nav button.active { background: var(--primary-color); color: var(--text-primary-color, #fff); }
      .card { background: var(--card-background-color); border-radius:8px; padding:16px;
              margin:12px 0; box-shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,.3)); }
      .state { font-weight:bold; }
      .state.triggered { color: var(--error-color, #d32f2f); }
      .state.pending, .state.arming { color: var(--warning-color, #f9a825); }
      .state.armed { color: var(--success-color, #2e7d32); }
      button { margin:4px 6px 0 0; padding:6px 12px; border:1px solid var(--divider-color);
               border-radius:4px; background: var(--secondary-background-color);
               color: var(--primary-text-color); cursor:pointer; }
      button.primary { background: var(--primary-color); color:#fff; border:none; }
      button.danger { color: var(--error-color, #d32f2f); }
      table { border-collapse:collapse; width:100%; }
      td, th { text-align:left; padding:4px 12px 4px 0; border-bottom:1px solid var(--divider-color);
               vertical-align:top; }
      .muted { color: var(--secondary-text-color); font-size:.9em; }
      .badge { display:inline-block; padding:2px 8px; border-radius:10px; font-size:.85em;
               background: var(--secondary-background-color); margin-left:6px; }
      input[type=text], input[type=number], select, textarea {
        background: var(--secondary-background-color); color: var(--primary-text-color);
        border:1px solid var(--divider-color); border-radius:4px; padding:5px 8px; margin:2px 4px 2px 0; }
      input[type=number] { width:90px; } input[type=text] { min-width:220px; }
      textarea { width:100%; min-height:180px; font-family:monospace; }
      label { margin-right:12px; white-space:nowrap; }
      fieldset { border:1px solid var(--divider-color); border-radius:6px; margin:8px 0; }
      code { font-size:.85em; }
    `;
    const tabs = ["leitstand","bereiche","profile","personen","betrieb"];
    const labels = { leitstand:"Leitstand", bereiche:"Bereiche", profile:"Reaktionsprofile",
                     personen:"Personen", betrieb:"Betrieb" };
    const nav = `<nav>${tabs.map((t) =>
      `<button class="${this._tab===t?"active":""}" data-action="tab" data-tab="${t}">${labels[t]}</button>`).join("")}</nav>`;
    let body;
    if (this._data.error) body = `<p>Fehler: ${esc(this._data.error)}</p>`;
    else if (!this._data.state) body = `<p class="muted">Lade Daten...</p>`;
    else body = this[`_render_${this._tab}`]();
    this.shadowRoot.innerHTML = `<style>${style}</style><h1>Kustos</h1>${nav}${body}`;
    for (const btn of this.shadowRoot.querySelectorAll("[data-action]")) {
      btn.onclick = (ev) => this._onAction(btn.dataset, ev);
    }
    this._updateCountdowns();
  }

  // ------------------------------------------------------------------
  // Leitstand
  // ------------------------------------------------------------------

  _render_leitstand() {
    const { state } = this._data;
    const master = state.master;
    const cards = state.panels.map((p) => {
      const zones = (this._data.zones || []).filter((z) => z.panel_id === p.panel_id);
      const walk = (state.walk_tests || {})[p.panel_id];
      const memory = p.alarm_memory.length
        ? `<p class="muted">Alarmspeicher: ${p.alarm_memory
            .map((m) => `${esc(m.entity_id)} (${m.alarm_type})`).join(", ")}</p>` : "";
      const bypassed = p.bypassed_zones.length
        ? `<p class="muted">Überbrückt: ${p.bypassed_zones.map((z) => esc(this._zoneName(z))).join(", ")}</p>` : "";
      const svcBtn = (svc, label) =>
        `<button data-action="service" data-service="${svc}" data-panel="${p.panel_id}">${label}</button>`;
      return `
        <div class="card">
          <h3>${esc(p.area_id || p.panel_id)}${walk ? '<span class="badge">Walk-Test läuft</span>' : ""}</h3>
          <p><span class="state ${p.state}">${STATE_LABELS[p.state] || p.state}</span>
             ${p.arm_mode ? `(${MODE_LABELS[p.arm_mode] || p.arm_mode})` : ""}
             ${p.ends_at ? `<span class="muted" data-ends-at="${p.ends_at}"></span>` : ""}</p>
          <p class="muted">${zones.length} Zone(n) | aktive Alarmtypen: ${p.active_alarm_types.join(", ") || "keine"}</p>
          ${bypassed}${memory}
          <div>${svcBtn("alarm_arm_away","Abwesend")}${svcBtn("alarm_arm_home","Zuhause")}
               ${svcBtn("alarm_arm_night","Nacht")}${svcBtn("alarm_disarm","Unscharf")}
               ${svcBtn("acknowledge","Quittieren")}</div>
        </div>`;
    });
    const presence = state.presence || [];
    const presenceCard = presence.length ? `
      <div class="card"><h3>Anwesenheit</h3><table>
        <tr><th>Person</th><th>Phase</th><th>Trip</th></tr>
        ${presence.map((p) => `<tr><td>${esc(p.name)}</td><td>${PHASE_LABELS[p.phase] || p.phase}</td>
          <td class="muted">${p.trip_id ? p.trip_id.slice(-6) : "-"}</td></tr>`).join("")}
      </table></div>` : "";
    return `
      <div class="card"><h3>Gesamtsystem</h3>
        <p><span class="state ${master.state}">${STATE_LABELS[master.state] || master.state}</span>
           ${master.arm_mode ? `(${MODE_LABELS[master.arm_mode] || master.arm_mode})` : ""}</p></div>
      ${cards.join("") || `<p class="muted">Noch keine Bereiche angelegt (Tab Bereiche).</p>`}
      ${presenceCard}`;
  }

  // ------------------------------------------------------------------
  // Bereiche (panels + zones, CRUD)
  // ------------------------------------------------------------------

  _panelForm(doc) {
    const areas = Object.values(this._hass.areas || {})
      .map((a) => `<option value="${esc(a.area_id)}">`).join("");
    const modes = ALL_MODES.map((m) => {
      const cfg = (doc.modes || {})[m] || {};
      const n = (f) => cfg[f] ?? "";
      return `<fieldset><label><input type="checkbox" id="mode-${m}" ${cfg.enabled ? "checked" : ""}>
        <b>${MODE_LABELS[m]}</b></label>
        <label>Exit <input type="number" id="exit-${m}" value="${n("exit_delay_s")}" placeholder="Std."></label>
        <label>Entry <input type="number" id="entry-${m}" value="${n("entry_delay_s")}" placeholder="Std."></label>
        <label>Alarmdauer <input type="number" id="trig-${m}" value="${n("trigger_time_s")}" placeholder="Std."></label>
      </fieldset>`;
    }).join("");
    const opts = doc.options || {};
    const profileOptions = (sel) => `<option value="">kein Profil</option>` +
      (this._data.profiles || []).map((pr) =>
        `<option value="${pr.id}" ${sel === pr.id ? "selected" : ""}>${esc(pr.name)}</option>`).join("");
    const assignments = ALARM_TYPES.map((t) => {
      const current = ((doc.alarm_types || {})[t] || {}).profile_id || "";
      return `<label>${ALARM_TYPE_LABELS[t]} <select id="prof-${t}">${profileOptions(current)}</select></label>`;
    }).join("<br>");
    return `<div class="card"><h3>${doc.id ? "Bereich bearbeiten" : "Neuer Bereich"}</h3>
      <label>HA-Bereich (area_id) <input type="text" id="f-area" list="dl-areas" value="${esc(doc.scope?.area_id || "")}"></label>
      <datalist id="dl-areas">${areas}</datalist>
      <h4>Modi</h4>${modes}
      <h4>Optionen</h4>
      <label><input type="checkbox" id="f-codearm" ${opts.code_arm_required ? "checked" : ""}> Code zum Scharfschalten</label>
      <label><input type="checkbox" id="f-codedisarm" ${opts.code_disarm_required !== false ? "checked" : ""}> Code zum Entschärfen</label>
      <label><input type="checkbox" id="f-rearm" ${opts.rearm_after_trigger !== false ? "checked" : ""}> Nach Alarmdauer wieder scharf</label>
      <h4>Reaktionsprofile je Alarmtyp</h4>${assignments}
      <p><button class="primary" data-action="save-panel" data-id="${doc.id || ""}">Speichern</button>
         <button data-action="cancel">Abbrechen</button></p></div>`;
  }

  _zoneForm(doc, panelId) {
    const panelDoc = (this._data.panels || []).find((p) => p.id === panelId);
    const enabledModes = Object.entries(panelDoc?.modes || {})
      .filter(([, c]) => c.enabled).map(([m]) => m);
    const roles = (enabledModes.length ? enabledModes : ["armed_away"]).map((m) => {
      const current = (doc.modes || {})[m] || "inactive";
      return `<label>${MODE_LABELS[m]}
        <select id="role-${m}">${ROLES.map((r) =>
          `<option ${r === current ? "selected" : ""}>${r}</option>`).join("")}</select></label>`;
    }).join("");
    const o = doc.options || {};
    const chk = (id, key, label, dflt=false) =>
      `<label><input type="checkbox" id="${id}" ${ (o[key] ?? dflt) ? "checked" : ""}> ${label}</label>`;
    return `<div class="card"><h3>${doc.id ? "Zone bearbeiten" : "Neue Zone"}</h3>
      <label>Entität <input type="text" id="z-entity" list="dl-zone-entities" value="${esc(doc.entity_id || "")}"></label>
      ${this._datalist("dl-zone-entities", ["binary_sensor","input_boolean","switch","sensor"])}
      <label>Name <input type="text" id="z-name" value="${esc(doc.name || "")}"></label>
      <label>Alarmtyp <select id="z-type">${ALARM_TYPES.map((t) =>
        `<option value="${t}" ${ (doc.alarm_type || "burglary") === t ? "selected" : ""}>${ALARM_TYPE_LABELS[t]}</option>`).join("")}</select></label>
      <h4>Rolle je Modus</h4>${roles}
      <h4>Optionen</h4>
      ${chk("z-exitok","use_exit_delay","darf beim Verlassen offen sein")}
      ${chk("z-armclose","arm_after_closing","Schließen beendet Exit-Delay")}
      ${chk("z-allowopen","allow_open","darf offen bleiben")}
      ${chk("z-bypass","auto_bypass","offen = automatisch überbrücken")}
      ${chk("z-unavail","trigger_when_unavailable","unavailable löst aus")}
      <label>Bei totem Sensor <select id="z-unavailpol">${["ignore","block_arm","auto_bypass"].map((v) =>
        `<option ${ (o.unavailable_policy || "ignore") === v ? "selected" : ""}>${v}</option>`).join("")}</select></label>
      <p><button class="primary" data-action="save-zone" data-id="${doc.id || ""}" data-panel="${panelId}">Speichern</button>
         <button data-action="cancel">Abbrechen</button></p></div>`;
  }

  _render_bereiche() {
    let form = "";
    if (this._edit?.kind === "panel") form = this._panelForm(this._edit.draft);
    if (this._edit?.kind === "zone") form = this._zoneForm(this._edit.draft, this._edit.panelId);
    const cards = (this._data.panels || []).map((p) => {
      const zones = (this._data.zones || []).filter((z) => z.panel_id === p.id);
      const zoneRows = zones.map((z) => `
        <tr><td>${esc(z.name || z.entity_id)}</td><td><code>${esc(z.entity_id)}</code></td>
          <td>${ALARM_TYPE_LABELS[z.alarm_type] || z.alarm_type}</td>
          <td>${Object.entries(z.modes).map(([m, r]) => `${MODE_LABELS[m] || m}: ${r}`).join(", ") || "-"}</td>
          <td><button data-action="edit-zone" data-id="${z.id}" data-panel="${p.id}">Bearbeiten</button>
              <button class="danger" data-action="del-zone" data-id="${z.id}">Löschen</button></td></tr>`).join("");
      const modes = Object.entries(p.modes).filter(([, c]) => c.enabled)
        .map(([m]) => MODE_LABELS[m] || m).join(", ");
      return `
        <div class="card">
          <h3>${esc(p.scope.area_id || p.scope.type)}</h3>
          <p class="muted">Modi: ${modes || "keine"} | Code: Scharf ${p.options.code_arm_required ? "ja" : "nein"},
             Unscharf ${p.options.code_disarm_required ? "ja" : "nein"}</p>
          ${zones.length
            ? `<table><tr><th>Zone</th><th>Entität</th><th>Alarmtyp</th><th>Rollen</th><th></th></tr>${zoneRows}</table>`
            : `<p class="muted">Keine Zonen.</p>`}
          <p><button data-action="new-zone" data-panel="${p.id}">Zone hinzufügen</button>
             <button data-action="edit-panel" data-id="${p.id}">Bereich bearbeiten</button>
             <button class="danger" data-action="del-panel" data-id="${p.id}">Bereich löschen</button></p>
        </div>`;
    }).join("");
    return `${form}<p><button class="primary" data-action="new-panel">Neuer Bereich</button></p>${cards}`;
  }

  // ------------------------------------------------------------------
  // Profile (stage/block builder)
  // ------------------------------------------------------------------

  _blockFields(b, i, j) {
    const id = (f) => `b-${i}-${j}-${f}`;
    const t = (f, label, extra="") =>
      `<label>${label} <input type="text" id="${id(f)}" value="${esc(Array.isArray(b[f]) ? b[f].join(", ") : (b[f] ?? ""))}" ${extra}></label>`;
    const n = (f, label) =>
      `<label>${label} <input type="number" step="0.1" id="${id(f)}" value="${b[f] ?? ""}"></label>`;
    switch (b.type) {
      case "flash_lights": {
        const hex = "#" + (b.color_rgb || [255,0,0]).map((c) => c.toString(16).padStart(2,"0")).join("");
        return `${t("targets","Ziele","list=dl-lights")}
          <label>Farbe <input type="color" id="${id("color")}" value="${hex}"></label>
          ${n("brightness_pct","Helligkeit %")} ${n("period_s","Periode s")} ${n("fade_s","Fade s")}
          <label>Nicht-Farbige <select id="${id("ncb")}">${["off","hard_blink","ignore"].map((v) =>
            `<option ${b.non_color_behavior===v?"selected":""}>${v}</option>`).join("")}</select></label>`;
      }
      case "lights_on":
        return `${t("targets","Ziele","list=dl-lights")} ${n("brightness_pct","Helligkeit %")}
                ${n("refresh_interval_s","Refresh s (0=aus)")}`;
      case "sound":
        return `${t("targets","Ziele","list=dl-sound")} ${n("retrigger_interval_s","Nachtrigger s")}
                ${n("max_duration_s","Maximaldauer s (Pflicht)")}`;
      case "announce_loop":
        return `${t("notify_service","Notify-Service")} ${t("message","Text")}
                ${n("interval_s","Intervall s")} ${t("media_targets","Player","list=dl-media")}
                ${n("volume_pct","Lautstärke %")} ${n("volume_fallback_pct","Fallback %")}`;
      case "notify":
        return `${t("service","Service")} ${t("title","Titel")} ${t("message","Text")}`;
      case "lock":
        return `${t("targets","Schlösser","list=dl-locks")}
          <label>Aktion <select id="${id("action")}">${["lock","unlock"].map((v) =>
            `<option ${b.action===v?"selected":""}>${v}</option>`).join("")}</select></label>
          <span class="muted">unlock nur bei Feuer/CO wirksam</span>`;
    }
    return "";
  }

  _profileForm(doc) {
    const stages = (doc.stages || []).map((s, i) => {
      const blocks = s.blocks.map((b, j) => `
        <fieldset><b>${BLOCK_LABELS[b.type]}</b>
          <button class="danger" style="float:right" data-action="del-block" data-i="${i}" data-j="${j}">entfernen</button><br>
          ${this._blockFields(b, i, j)}</fieldset>`).join("");
      return `<fieldset><h4>Stufe ${i + 1}
          <button class="danger" style="float:right" data-action="del-stage" data-i="${i}">Stufe entfernen</button></h4>
        <label>Dauer s (leer = bis Alarmende) <input type="number" id="stage-${i}-dur" value="${s.duration_s ?? ""}"></label>
        ${blocks}
        <label>Baustein <select id="stage-${i}-newblock">${Object.keys(BLOCK_DEFAULTS).map((t) =>
          `<option value="${t}">${BLOCK_LABELS[t]}</option>`).join("")}</select></label>
        <button data-action="add-block" data-i="${i}">hinzufügen</button>
      </fieldset>`;
    }).join("");
    return `<div class="card"><h3>${doc.id ? "Profil bearbeiten" : "Neues Profil"}</h3>
      ${this._datalist("dl-lights", ["light","switch"])}
      ${this._datalist("dl-sound", ["siren","switch","input_boolean","button","input_button"])}
      ${this._datalist("dl-media", ["media_player"])}
      ${this._datalist("dl-locks", ["lock"])}
      <label>Name <input type="text" id="p-name" value="${esc(doc.name || "")}"></label>
      ${stages}
      <p><button data-action="add-stage">Stufe hinzufügen</button></p>
      <p><button class="primary" data-action="save-profile" data-id="${doc.id || ""}">Speichern</button>
         <button data-action="cancel">Abbrechen</button></p>
      <p class="muted">Ziele als Komma-Liste. Reihenfolge der Stufen = Zeitachse ab Alarmbeginn.</p></div>`;
  }

  _render_profile() {
    let form = "";
    if (this._edit?.kind === "profile") form = this._profileForm(this._edit.draft);
    const cards = (this._data.profiles || []).map((prof) => {
      const stages = prof.stages.map((s, i) => {
        const blocks = s.blocks.map((b) => {
          const targets = (b.targets || b.media_targets || []).join(", ");
          return `${BLOCK_LABELS[b.type] || b.type}${targets ? ` → ${esc(targets)}` : ""}`;
        }).join("<br>");
        return `<tr><td>Stufe ${i + 1}</td>
          <td>${s.duration_s === null ? "bis Alarmende" : s.duration_s + " s"}</td>
          <td>${blocks || "-"}</td></tr>`;
      }).join("");
      return `<div class="card"><h3>${esc(prof.name)}</h3>
        <table><tr><th></th><th>Dauer</th><th>Bausteine</th></tr>${stages}</table>
        <p><button data-action="edit-profile" data-id="${prof.id}">Bearbeiten</button>
           <button class="danger" data-action="del-profile" data-id="${prof.id}">Löschen</button></p></div>`;
    }).join("");
    return `${form}<p><button class="primary" data-action="new-profile">Neues Profil</button></p>
      ${cards || `<p class="muted">Noch keine Reaktionsprofile.</p>`}`;
  }

  // ------------------------------------------------------------------
  // Personen (users, presence persons, rules)
  // ------------------------------------------------------------------

  _userForm(doc) {
    const r = doc.rights || {};
    const panelChecks = (this._data.panels || []).map((p) =>
      `<label><input type="checkbox" class="u-panel" value="${p.id}"
        ${r.panels && r.panels.includes(p.id) ? "checked" : ""}> ${esc(this._panelName(p.id))}</label>`).join("");
    return `<div class="card"><h3>${doc.id ? "Benutzer bearbeiten" : "Neuer Benutzer"}</h3>
      <label>Name <input type="text" id="u-name" value="${esc(doc.name || "")}"></label>
      <label><input type="checkbox" id="u-enabled" ${doc.enabled !== false ? "checked" : ""}> aktiv</label>
      <label><input type="checkbox" id="u-arm" ${r.can_arm !== false ? "checked" : ""}> darf scharfschalten</label>
      <label><input type="checkbox" id="u-disarm" ${r.can_disarm !== false ? "checked" : ""}> darf entschärfen</label><br>
      <label><input type="checkbox" id="u-allpanels" ${r.panels == null ? "checked" : ""}> alle Bereiche</label>
      ${panelChecks}
      <p><button class="primary" data-action="save-user" data-id="${doc.id || ""}">Speichern</button>
         <button data-action="cancel">Abbrechen</button></p></div>`;
  }

  _personForm(doc) {
    return `<div class="card"><h3>${doc.id ? "Person bearbeiten" : "Neue Person"}</h3>
      ${this._datalist("dl-trackers", ["person","device_tracker"])}
      ${this._datalist("dl-distance", ["sensor","input_number"])}
      <label>Name <input type="text" id="pe-name" value="${esc(doc.name || "")}"></label>
      <label>Tracker <input type="text" id="pe-tracker" list="dl-trackers" value="${esc(doc.tracker_entity || "")}"></label>
      <label>Distanz-Entität <input type="text" id="pe-dist" list="dl-distance" value="${esc(doc.distance_entity || "")}"></label>
      <label>Weg-Schwelle m <input type="number" id="pe-threshold" value="${doc.away_confirm_distance_m ?? ""}" placeholder="Std."></label>
      <p><button class="primary" data-action="save-person" data-id="${doc.id || ""}">Speichern</button>
         <button data-action="cancel">Abbrechen</button></p></div>`;
  }

  _ruleForm(doc) {
    const arm = doc.arm || {};
    const panelOptions = `<option value="master" ${doc.panel_id === "master" ? "selected" : ""}>Gesamtsystem</option>` +
      (this._data.panels || []).map((p) =>
        `<option value="${p.id}" ${doc.panel_id === p.id ? "selected" : ""}>${esc(this._panelName(p.id))}</option>`).join("");
    const personChecks = (this._data.persons || []).map((p) =>
      `<label><input type="checkbox" class="r-person" value="${p.id}"
        ${doc.persons && doc.persons.includes(p.id) ? "checked" : ""}> ${esc(p.name)}</label>`).join("");
    return `<div class="card"><h3>${doc.id ? "Regel bearbeiten" : "Neue Regel"}</h3>
      <label>Name <input type="text" id="r-name" value="${esc(doc.name || "")}"></label>
      <label><input type="checkbox" id="r-enabled" ${doc.enabled !== false ? "checked" : ""}> aktiv</label>
      <label>Bereich <select id="r-panel">${panelOptions}</select></label>
      <label>Modus <select id="r-mode">${ALL_MODES.map((m) =>
        `<option value="${m}" ${ (arm.mode || "armed_away") === m ? "selected" : ""}>${MODE_LABELS[m]}</option>`).join("")}</select></label>
      <label>Ausführung <select id="r-exec">${["prewarn","immediate"].map((v) =>
        `<option ${ (arm.execution || "prewarn") === v ? "selected" : ""}>${v}</option>`).join("")}</select></label>
      <label>Vorwarnzeit s <input type="number" id="r-prewarn" value="${arm.prewarn_s ?? ""}" placeholder="Std."></label>
      <label><input type="checkbox" id="r-return" ${doc.return_action?.disarm !== false ? "checked" : ""}> bei Ankunft entschärfen</label><br>
      <label><input type="checkbox" id="r-allpersons" ${doc.persons == null ? "checked" : ""}> alle Personen</label>
      ${personChecks}
      <p><button class="primary" data-action="save-rule" data-id="${doc.id || ""}">Speichern</button>
         <button data-action="cancel">Abbrechen</button></p></div>`;
  }

  _render_personen() {
    let form = "";
    if (this._edit?.kind === "user") form = this._userForm(this._edit.draft);
    if (this._edit?.kind === "person") form = this._personForm(this._edit.draft);
    if (this._edit?.kind === "rule") form = this._ruleForm(this._edit.draft);
    const users = (this._data.users || []).map((u) => {
      const panels = u.rights.panels === null ? "alle"
        : u.rights.panels.map((p) => esc(this._panelName(p))).join(", ");
      return `<tr><td>${esc(u.name)}</td><td>${u.enabled ? "ja" : "nein"}</td>
        <td>${u.rights.can_arm ? "ja" : "nein"}</td><td>${u.rights.can_disarm ? "ja" : "nein"}</td>
        <td>${panels}</td>
        <td><button data-action="edit-user" data-id="${u.id}">Bearbeiten</button>
            <button data-action="set-pin" data-id="${u.id}" data-kind="normal">PIN setzen</button>
            <button data-action="set-pin" data-id="${u.id}" data-kind="duress">Duress-PIN</button>
            <button class="danger" data-action="del-user" data-id="${u.id}">Löschen</button></td></tr>`;
    }).join("");
    const phases = {};
    for (const p of (this._data.state.presence || [])) phases[p.person_id] = p.phase;
    const persons = (this._data.persons || []).map((p) => `
      <tr><td>${esc(p.name)}</td><td><code>${esc(p.tracker_entity)}</code></td>
      <td><code>${esc(p.distance_entity || "-")}</code></td>
      <td>${p.away_confirm_distance_m || "Std."}</td>
      <td>${PHASE_LABELS[phases[p.id]] || phases[p.id] || "-"}</td>
      <td><button data-action="edit-person" data-id="${p.id}">Bearbeiten</button>
          <button class="danger" data-action="del-person" data-id="${p.id}">Löschen</button></td></tr>`).join("");
    const rules = (this._data.rules || []).map((r) => `
      <tr><td>${esc(r.name)}</td><td>${r.enabled ? "ja" : "nein"}</td>
      <td>${r.panel_id === "master" ? "Gesamtsystem" : esc(this._panelName(r.panel_id))}</td>
      <td>${MODE_LABELS[r.arm.mode] || r.arm.mode}, ${r.arm.execution}</td>
      <td>${r.return_action.disarm ? "entschärft bei Ankunft" : "-"}</td>
      <td><button data-action="edit-rule" data-id="${r.id}">Bearbeiten</button>
          <button class="danger" data-action="del-rule" data-id="${r.id}">Löschen</button></td></tr>`).join("");
    return `${form}
      <div class="card"><h3>Benutzer (Zugang)</h3>
        ${users ? `<table><tr><th>Name</th><th>Aktiv</th><th>Scharf</th><th>Unscharf</th><th>Bereiche</th><th></th></tr>${users}</table>` : `<p class="muted">Keine Benutzer.</p>`}
        <p><button class="primary" data-action="new-user">Neuer Benutzer</button></p></div>
      <div class="card"><h3>Anwesenheits-Personen</h3>
        ${persons ? `<table><tr><th>Name</th><th>Tracker</th><th>Distanz</th><th>Schwelle (m)</th><th>Phase</th><th></th></tr>${persons}</table>` : `<p class="muted">Keine Personen.</p>`}
        <p><button class="primary" data-action="new-person">Neue Person</button></p></div>
      <div class="card"><h3>Automatik-Regeln</h3>
        ${rules ? `<table><tr><th>Name</th><th>Aktiv</th><th>Bereich</th><th>Scharf</th><th>Rückkehr</th><th></th></tr>${rules}</table>` : `<p class="muted">Keine Regeln.</p>`}
        <p><button class="primary" data-action="new-rule">Neue Regel</button></p></div>`;
  }

  // ------------------------------------------------------------------
  // Betrieb
  // ------------------------------------------------------------------

  _render_betrieb() {
    const walk = (this._data.panels || []).map((p) => {
      const info = (this._data.state.walk_tests || {})[p.id];
      return `<div class="card"><h3>Walk-Test: ${esc(p.scope.area_id || p.scope.type)}</h3>
        ${info
          ? `<p>läuft, Ende <span class="muted" data-ends-at="${info.ends_at}"></span><br>
             Getestet: ${info.tested.map((z) => esc(this._zoneName(z))).join(", ") || "noch keine Zone"}</p>
             <button data-action="walk" data-walk="stop" data-panel="${p.id}">Beenden</button>`
          : `<p class="muted">nicht aktiv</p>
             <button data-action="walk" data-walk="start" data-panel="${p.id}">Starten</button>`}
      </div>`;
    }).join("");
    const audit = (this._data.audit?.entries || []).map((e) => {
      const { ts, seq, kind, ...rest } = e;
      return `<tr><td class="muted">${ts.slice(0, 19).replace("T", " ")}</td>
        <td>${esc(kind)}</td><td class="muted"><code>${esc(JSON.stringify(rest))}</code></td></tr>`;
    }).join("");
    return `${walk}
      <div class="card"><h3>Einstellungen</h3>
        <p class="muted">Zentrale Defaults (Delays, Anwesenheit, Engine). Änderungen wirken sofort.</p>
        <textarea id="settings-json">${esc(JSON.stringify(this._data.settings, null, 2))}</textarea>
        <p><button class="primary" data-action="save-settings">Einstellungen speichern</button></p></div>
      <div class="card"><h3>Protokoll (${this._data.audit?.month || ""})</h3>
        ${audit ? `<table><tr><th>Zeit (UTC)</th><th>Ereignis</th><th>Details</th></tr>${audit}</table>`
                : `<p class="muted">Noch keine Einträge.</p>`}</div>`;
  }

  // ------------------------------------------------------------------
  // Actions
  // ------------------------------------------------------------------

  async _onAction(ds) {
    const a = ds.action;
    if (a === "tab") { this._tab = ds.tab; this._edit = null; this._render(); return; }
    if (a === "cancel") { this._edit = null; this._render(); return; }
    if (a === "service") return this._service(ds.service, ds.panel);
    if (a === "walk") { await this._ws("kustos/walk_test", { panel_id: ds.panel, action: ds.walk }); return this._refresh(); }

    // ----- Bereiche
    if (a === "new-panel") { this._edit = { kind: "panel", draft: { modes: { armed_away: { enabled: true } }, options: {} } }; return this._render(); }
    if (a === "edit-panel") { this._edit = { kind: "panel", draft: structuredClone((this._data.panels || []).find((p) => p.id === ds.id)) }; return this._render(); }
    if (a === "del-panel") {
      if (!confirm("Bereich samt Konfiguration löschen?")) return;
      await this._ws("kustos/panels/delete", { panel_id: ds.id }); return this._refresh();
    }
    if (a === "save-panel") {
      const modes = {};
      for (const m of ALL_MODES) {
        const entry = { enabled: this._chk(`mode-${m}`) };
        for (const [f, key] of [["exit","exit_delay_s"],["entry","entry_delay_s"],["trig","trigger_time_s"]]) {
          const v = this._num(`${f}-${m}`);
          if (v !== null) entry[key] = v;
        }
        if (entry.enabled || Object.keys(entry).length > 1) modes[m] = entry;
      }
      const alarm_types = {};
      for (const t of ALARM_TYPES) {
        const v = this._val(`prof-${t}`);
        if (v) alarm_types[t] = { profile_id: v };
      }
      const payload = {
        scope: { type: "area", area_id: this._val("f-area") },
        modes, alarm_types,
        options: {
          code_arm_required: this._chk("f-codearm"),
          code_disarm_required: this._chk("f-codedisarm"),
          rearm_after_trigger: this._chk("f-rearm"),
        },
      };
      const res = ds.id
        ? await this._ws("kustos/panels/update", { panel_id: ds.id, ...payload })
        : await this._ws("kustos/panels/create", payload);
      if (res.ok) { this._edit = null; this._refresh(); }
      return;
    }

    // ----- Zonen
    if (a === "new-zone") { this._edit = { kind: "zone", panelId: ds.panel, draft: {} }; return this._render(); }
    if (a === "edit-zone") {
      const z = (this._data.zones || []).find((x) => x.id === ds.id);
      this._edit = { kind: "zone", panelId: ds.panel, draft: structuredClone(z) }; return this._render();
    }
    if (a === "del-zone") {
      if (!confirm("Zone löschen?")) return;
      await this._ws("kustos/zones/delete", { zone_id: ds.id }); return this._refresh();
    }
    if (a === "save-zone") {
      const modes = {};
      for (const m of ALL_MODES) {
        const sel = this._q(`role-${m}`);
        if (sel && sel.value !== "inactive") modes[m] = sel.value;
      }
      const payload = {
        entity_id: this._val("z-entity"), panel_id: ds.panel,
        name: this._val("z-name") || null, alarm_type: this._val("z-type"), modes,
        options: {
          use_exit_delay: this._chk("z-exitok"), arm_after_closing: this._chk("z-armclose"),
          allow_open: this._chk("z-allowopen"), auto_bypass: this._chk("z-bypass"),
          trigger_when_unavailable: this._chk("z-unavail"),
          unavailable_policy: this._val("z-unavailpol"),
        },
      };
      const res = ds.id
        ? await this._ws("kustos/zones/update", { zone_id: ds.id, ...payload })
        : await this._ws("kustos/zones/create", payload);
      if (res.ok) { this._edit = null; this._refresh(); }
      return;
    }

    // ----- Profile
    if (a === "new-profile") { this._edit = { kind: "profile", draft: { stages: [{ duration_s: null, blocks: [] }] } }; return this._render(); }
    if (a === "edit-profile") { this._edit = { kind: "profile", draft: structuredClone((this._data.profiles || []).find((p) => p.id === ds.id)) }; return this._render(); }
    if (a === "del-profile") {
      if (!confirm("Profil löschen?")) return;
      await this._ws("kustos/profiles/delete", { profile_id: ds.id }); return this._refresh();
    }
    if (a === "add-stage") { this._syncProfileDraft(); this._edit.draft.stages.push({ duration_s: null, blocks: [] }); return this._render(); }
    if (a === "del-stage") { this._syncProfileDraft(); this._edit.draft.stages.splice(Number(ds.i), 1); return this._render(); }
    if (a === "add-block") {
      this._syncProfileDraft();
      const type = this._val(`stage-${ds.i}-newblock`);
      this._edit.draft.stages[Number(ds.i)].blocks.push(structuredClone(BLOCK_DEFAULTS[type]));
      return this._render();
    }
    if (a === "del-block") { this._syncProfileDraft(); this._edit.draft.stages[Number(ds.i)].blocks.splice(Number(ds.j), 1); return this._render(); }
    if (a === "save-profile") {
      this._syncProfileDraft();
      const payload = { name: this._val("p-name"), stages: this._edit.draft.stages };
      const res = ds.id
        ? await this._ws("kustos/profiles/update", { profile_id: ds.id, ...payload })
        : await this._ws("kustos/profiles/create", payload);
      if (res.ok) { this._edit = null; this._refresh(); }
      return;
    }

    // ----- Benutzer
    if (a === "new-user") { this._edit = { kind: "user", draft: {} }; return this._render(); }
    if (a === "edit-user") { this._edit = { kind: "user", draft: structuredClone((this._data.users || []).find((u) => u.id === ds.id)) }; return this._render(); }
    if (a === "del-user") {
      if (!confirm("Benutzer löschen?")) return;
      await this._ws("kustos/users/delete", { user_id: ds.id }); return this._refresh();
    }
    if (a === "save-user") {
      const all = this._chk("u-allpanels");
      const panels = all ? null
        : [...this.shadowRoot.querySelectorAll(".u-panel:checked")].map((x) => x.value);
      const payload = {
        name: this._val("u-name"), enabled: this._chk("u-enabled"),
        rights: { can_arm: this._chk("u-arm"), can_disarm: this._chk("u-disarm"), panels },
      };
      const res = ds.id
        ? await this._ws("kustos/users/update", { user_id: ds.id, ...payload })
        : await this._ws("kustos/users/create", payload);
      if (res.ok) { this._edit = null; this._refresh(); }
      return;
    }
    if (a === "set-pin") {
      const pin = prompt(ds.kind === "duress"
        ? "Duress-PIN (nur Ziffern, min. 4). Entschärft normal und alarmiert still:"
        : "PIN (nur Ziffern, min. 4):");
      if (pin === null) return;
      await this._ws("kustos/users/set_pin", { user_id: ds.id, pin: pin || null, kind: ds.kind });
      return this._refresh();
    }

    // ----- Personen
    if (a === "new-person") { this._edit = { kind: "person", draft: {} }; return this._render(); }
    if (a === "edit-person") { this._edit = { kind: "person", draft: structuredClone((this._data.persons || []).find((p) => p.id === ds.id)) }; return this._render(); }
    if (a === "del-person") {
      if (!confirm("Person löschen?")) return;
      await this._ws("kustos/persons/delete", { person_id: ds.id }); return this._refresh();
    }
    if (a === "save-person") {
      const payload = {
        name: this._val("pe-name"), tracker_entity: this._val("pe-tracker"),
        distance_entity: this._val("pe-dist") || null,
        away_confirm_distance_m: this._num("pe-threshold"),
      };
      const res = ds.id
        ? await this._ws("kustos/persons/update", { person_id: ds.id, ...payload })
        : await this._ws("kustos/persons/create", payload);
      if (res.ok) { this._edit = null; this._refresh(); }
      return;
    }

    // ----- Regeln
    if (a === "new-rule") { this._edit = { kind: "rule", draft: {} }; return this._render(); }
    if (a === "edit-rule") { this._edit = { kind: "rule", draft: structuredClone((this._data.rules || []).find((r) => r.id === ds.id)) }; return this._render(); }
    if (a === "del-rule") {
      if (!confirm("Regel löschen?")) return;
      await this._ws("kustos/rules/delete", { rule_id: ds.id }); return this._refresh();
    }
    if (a === "save-rule") {
      const all = this._chk("r-allpersons");
      const persons = all ? null
        : [...this.shadowRoot.querySelectorAll(".r-person:checked")].map((x) => x.value);
      const arm = { mode: this._val("r-mode"), execution: this._val("r-exec") };
      const prewarn = this._num("r-prewarn");
      if (prewarn !== null) arm.prewarn_s = prewarn;
      const payload = {
        name: this._val("r-name"), enabled: this._chk("r-enabled"),
        panel_id: this._val("r-panel"), persons, arm,
        return_action: { disarm: this._chk("r-return"), fire_on: "arrived" },
      };
      const res = ds.id
        ? await this._ws("kustos/rules/update", { rule_id: ds.id, ...payload })
        : await this._ws("kustos/rules/create", payload);
      if (res.ok) { this._edit = null; this._refresh(); }
      return;
    }

    // ----- Einstellungen
    if (a === "save-settings") {
      let parsed;
      try { parsed = JSON.parse(this._val("settings-json")); }
      catch (err) { alert("Kein gültiges JSON: " + err.message); return; }
      const res = await this._ws("kustos/settings/update", { settings: parsed });
      if (res.ok) this._refresh();
      return;
    }
  }

  _syncProfileDraft() {
    // Pull current input values into the draft before structural re-renders.
    const draft = this._edit?.draft;
    if (!draft) return;
    draft.name = this._val("p-name") || draft.name;
    (draft.stages || []).forEach((s, i) => {
      const dur = this._num(`stage-${i}-dur`);
      s.duration_s = dur;
      s.blocks.forEach((b, j) => {
        const id = (f) => `b-${i}-${j}-${f}`;
        const listF = (f) => { if (this._q(id(f))) b[f] = this._list(id(f)); };
        const numF = (f) => { const v = this._num(id(f)); if (v !== null) b[f] = v; };
        const txtF = (f) => { if (this._q(id(f))) b[f] = this._val(id(f)); };
        switch (b.type) {
          case "flash_lights": {
            listF("targets"); numF("brightness_pct"); numF("period_s"); numF("fade_s");
            const hex = this._val(id("color"));
            if (hex) b.color_rgb = [1, 3, 5].map((k) => parseInt(hex.slice(k, k + 2), 16));
            if (this._q(id("ncb"))) b.non_color_behavior = this._val(id("ncb"));
            break;
          }
          case "lights_on": listF("targets"); numF("brightness_pct"); numF("refresh_interval_s"); break;
          case "sound": listF("targets"); numF("retrigger_interval_s"); numF("max_duration_s"); break;
          case "announce_loop":
            txtF("notify_service"); txtF("message"); numF("interval_s");
            listF("media_targets"); numF("volume_pct"); numF("volume_fallback_pct"); break;
          case "notify": txtF("service"); txtF("title"); txtF("message"); break;
          case "lock": listF("targets"); if (this._q(id("action"))) b.action = this._val(id("action")); break;
        }
      });
    });
  }

  async _service(service, panelId) {
    const entityId = this._panelEntity(panelId);
    if (!entityId) return;
    const domain = service === "acknowledge" ? "kustos" : "alarm_control_panel";
    const data = { entity_id: entityId };
    const st = this._hass.states[entityId];
    if (st && st.attributes.code_format) {
      const code = prompt("Code:");
      if (code === null) return;
      data.code = code;
    }
    try { await this._hass.callService(domain, service, data); }
    catch (err) { alert("Fehler: " + (err.message || err)); }
    setTimeout(() => this._refresh(), 300);
  }
}

if (!customElements.get("kustos-panel")) {
  customElements.define("kustos-panel", KustosPanel);
}
