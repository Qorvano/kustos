/* Kustos sidebar panel: buildless vanilla web component.
   Pure projection of the WebSocket API; tabs mirror the approved structure
   (Leitstand, Bereiche, Reaktionsprofile, Personen, Betrieb). */

const STATE_LABELS = {
  disarmed: "Unscharf", arming: "Wird scharf", armed: "Scharf",
  pending: "Eintrittsverzögerung", triggered: "ALARM",
};
const MODE_LABELS = {
  armed_away: "Abwesend", armed_home: "Zuhause", armed_night: "Nacht",
  armed_vacation: "Urlaub", armed_custom_bypass: "Benutzerdefiniert",
};
const PHASE_LABELS = {
  home: "zuhause", leaving: "verlässt gerade", confirmed_away: "bestätigt abwesend",
  returning: "auf dem Rückweg", untracked: "nicht verfolgbar", arrived: "angekommen",
};
const BLOCK_LABELS = {
  flash_lights: "Licht blinken", lights_on: "Licht an", sound: "Alarmgeber",
  announce_loop: "Ansage-Loop", notify: "Benachrichtigung", lock: "Schloss",
};

class KustosPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "leitstand";
    this._data = {};
    this._hass = null;
    this._tick = null;
    this._unsubs = [];
  }

  set hass(hass) {
    const first = this._hass === null;
    this._hass = hass;
    if (first) {
      this._refresh();
      this._subscribe();
    }
  }

  connectedCallback() {
    this._render();
    this._tick = setInterval(() => this._updateCountdowns(), 1000);
  }
  disconnectedCallback() {
    clearInterval(this._tick);
    for (const unsub of this._unsubs) unsub.then((u) => u()).catch(() => {});
    this._unsubs = [];
  }

  async _subscribe() {
    const conn = this._hass.connection;
    for (const evt of [
      "kustos_arming", "kustos_armed", "kustos_pending", "kustos_triggered",
      "kustos_disarmed", "kustos_arm_failed", "kustos_acknowledged",
      "kustos_zone_bypassed", "kustos_walk_test_zone", "kustos_presence_phase",
      "kustos_auto_arm_pending", "kustos_auto_armed", "kustos_auto_disarmed",
    ]) {
      this._unsubs.push(conn.subscribeEvents(() => this._refresh(), evt));
    }
  }

  async _refresh() {
    if (!this._hass) return;
    const ws = (type, extra) => this._hass.callWS({ type, ...(extra || {}) });
    try {
      const [state, panels, zones, profiles, users, persons, rules, audit] =
        await Promise.all([
          ws("kustos/state/list"), ws("kustos/panels/list"), ws("kustos/zones/list"),
          ws("kustos/profiles/list"), ws("kustos/users/list"),
          ws("kustos/persons/list"), ws("kustos/rules/list"),
          ws("kustos/audit/query", { limit: 50 }),
        ]);
      this._data = { state, panels, zones, profiles, users, persons, rules, audit };
    } catch (err) {
      this._data = { error: String(err.message || err) };
    }
    this._render();
  }

  _panelEntity(panelId) {
    for (const [entityId, st] of Object.entries(this._hass.states)) {
      if (entityId.startsWith("alarm_control_panel.") &&
          st.attributes.panel_id === panelId) return entityId;
    }
    return null;
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
    try {
      await this._hass.callService(domain, service, data);
    } catch (err) {
      alert("Fehler: " + (err.message || err));
    }
    setTimeout(() => this._refresh(), 300);
  }

  async _walkTest(panelId, action) {
    await this._hass.callWS({ type: "kustos/walk_test", panel_id: panelId, action });
    this._refresh();
  }

  _updateCountdowns() {
    for (const el of this.shadowRoot.querySelectorAll("[data-ends-at]")) {
      const remaining = Math.max(0,
        Math.round((new Date(el.dataset.endsAt) - Date.now()) / 1000));
      el.textContent = `noch ${remaining} s`;
    }
  }

  _panelName(panelId) {
    const doc = (this._data.panels || []).find((p) => p.id === panelId);
    return doc ? (doc.scope.area_id || doc.scope.type) : panelId;
  }

  _zoneName(zoneId) {
    const z = (this._data.zones || []).find((z) => z.id === zoneId);
    return z ? (z.name || z.entity_id) : zoneId;
  }

  _render() {
    const style = `
      :host { display:block; padding:16px; font-family: var(--paper-font-body1_-_font-family, sans-serif);
              color: var(--primary-text-color); background: var(--primary-background-color); min-height:100%; }
      h1 { font-size:1.4em; margin:0 0 12px; }
      h3 { margin:0 0 8px; }
      nav button { margin:0 8px 8px 0; padding:8px 16px; border:none; border-radius:4px;
                   background: var(--secondary-background-color); color: var(--primary-text-color); cursor:pointer; }
      nav button.active { background: var(--primary-color); color: var(--text-primary-color, #fff); }
      .card { background: var(--card-background-color); border-radius:8px; padding:16px;
              margin:12px 0; box-shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,.3)); }
      .state { font-weight:bold; }
      .state.triggered { color: var(--error-color, #d32f2f); }
      .state.pending, .state.arming { color: var(--warning-color, #f9a825); }
      .state.armed { color: var(--success-color, #2e7d32); }
      .actions button, .inline-btn { margin:4px 6px 0 0; padding:6px 12px; border:1px solid var(--divider-color);
                        border-radius:4px; background: var(--secondary-background-color);
                        color: var(--primary-text-color); cursor:pointer; }
      table { border-collapse:collapse; width:100%; }
      td, th { text-align:left; padding:4px 12px 4px 0; border-bottom:1px solid var(--divider-color);
               vertical-align:top; }
      .muted { color: var(--secondary-text-color); font-size:.9em; }
      .badge { display:inline-block; padding:2px 8px; border-radius:10px; font-size:.85em;
               background: var(--secondary-background-color); margin-left:6px; }
      code { font-size:.85em; }
    `;
    const tabs = ["leitstand","bereiche","profile","personen","betrieb"];
    const labels = { leitstand:"Leitstand", bereiche:"Bereiche", profile:"Reaktionsprofile",
                     personen:"Personen", betrieb:"Betrieb" };
    const nav = `<nav>${tabs.map((t) =>
      `<button class="${this._tab===t?"active":""}" data-tab="${t}">${labels[t]}</button>`).join("")}</nav>`;
    let body;
    if (this._data.error) body = `<p>Fehler: ${this._data.error}</p>`;
    else if (!this._data.state) body = `<p class="muted">Lade Daten...</p>`;
    else body = this[`_render_${this._tab}`]();
    this.shadowRoot.innerHTML = `<style>${style}</style><h1>Kustos</h1>${nav}${body}`;
    for (const btn of this.shadowRoot.querySelectorAll("nav button")) {
      btn.onclick = () => { this._tab = btn.dataset.tab; this._render(); };
    }
    for (const btn of this.shadowRoot.querySelectorAll("[data-service]")) {
      btn.onclick = () => this._service(btn.dataset.service, btn.dataset.panel);
    }
    for (const btn of this.shadowRoot.querySelectorAll("[data-walk]")) {
      btn.onclick = () => this._walkTest(btn.dataset.panel, btn.dataset.walk);
    }
    this._updateCountdowns();
  }

  _render_leitstand() {
    const { state } = this._data;
    const master = state.master;
    const presence = state.presence || [];
    const cards = state.panels.map((p) => {
      const zones = (this._data.zones || []).filter((z) => z.panel_id === p.panel_id);
      const walk = (state.walk_tests || {})[p.panel_id];
      const memory = p.alarm_memory.length
        ? `<p class="muted">Alarmspeicher: ${p.alarm_memory
            .map((m) => `${m.entity_id} (${m.alarm_type})`).join(", ")}</p>` : "";
      const bypassed = p.bypassed_zones.length
        ? `<p class="muted">Überbrückt: ${p.bypassed_zones.map((z) => this._zoneName(z)).join(", ")}</p>` : "";
      return `
        <div class="card">
          <h3>${p.area_id || p.panel_id}${walk ? '<span class="badge">Walk-Test läuft</span>' : ""}</h3>
          <p><span class="state ${p.state}">${STATE_LABELS[p.state] || p.state}</span>
             ${p.arm_mode ? `(${MODE_LABELS[p.arm_mode] || p.arm_mode})` : ""}
             ${p.ends_at ? `<span class="muted" data-ends-at="${p.ends_at}"></span>` : ""}</p>
          <p class="muted">${zones.length} Zone(n) zugeordnet | aktive Alarmtypen: ${p.active_alarm_types.join(", ") || "keine"}</p>
          ${bypassed}${memory}
          <div class="actions">
            <button data-service="alarm_arm_away" data-panel="${p.panel_id}">Abwesend</button>
            <button data-service="alarm_arm_home" data-panel="${p.panel_id}">Zuhause</button>
            <button data-service="alarm_arm_night" data-panel="${p.panel_id}">Nacht</button>
            <button data-service="alarm_disarm" data-panel="${p.panel_id}">Unscharf</button>
            <button data-service="acknowledge" data-panel="${p.panel_id}">Quittieren</button>
          </div>
        </div>`;
    });
    const presenceCard = presence.length ? `
      <div class="card"><h3>Anwesenheit</h3><table>
        <tr><th>Person</th><th>Phase</th><th>Trip</th></tr>
        ${presence.map((p) => `<tr><td>${p.name}</td><td>${PHASE_LABELS[p.phase] || p.phase}</td>
          <td class="muted">${p.trip_id ? p.trip_id.slice(-6) : "-"}</td></tr>`).join("")}
      </table></div>` : "";
    return `
      <div class="card"><h3>Gesamtsystem</h3>
        <p><span class="state ${master.state}">${STATE_LABELS[master.state] || master.state}</span>
           ${master.arm_mode ? `(${MODE_LABELS[master.arm_mode] || master.arm_mode})` : ""}</p></div>
      ${cards.join("") || `<p class="muted">Noch keine Bereiche angelegt.</p>`}
      ${presenceCard}`;
  }

  _render_bereiche() {
    return (this._data.panels || []).map((p) => {
      const zones = (this._data.zones || []).filter((z) => z.panel_id === p.id);
      const assignments = Object.entries(p.alarm_types || {})
        .filter(([, a]) => a.profile_id)
        .map(([type, a]) => {
          const prof = (this._data.profiles || []).find((x) => x.id === a.profile_id);
          return `${type}: ${prof ? prof.name : a.profile_id}`;
        }).join(", ");
      const zoneRows = zones.map((z) => {
        const options = Object.entries(z.options)
          .filter(([, v]) => v === true || (typeof v === "string" && v !== "ignore"))
          .map(([k, v]) => (v === true ? k : `${k}=${v}`)).join(", ");
        return `<tr><td>${z.name || z.entity_id}</td><td><code>${z.entity_id}</code></td>
          <td>${z.alarm_type}</td>
          <td>${Object.entries(z.modes).map(([m, r]) => `${MODE_LABELS[m] || m}: ${r}`).join(", ") || "-"}</td>
          <td class="muted">${options || "-"}</td></tr>`;
      }).join("");
      const modes = Object.entries(p.modes).filter(([, c]) => c.enabled)
        .map(([m, c]) => `${MODE_LABELS[m] || m} (Exit ${c.exit_delay_s ?? "Std."} s, Entry ${c.entry_delay_s ?? "Std."} s, Alarmdauer ${c.trigger_time_s ?? "Std."} s)`)
        .join("<br>");
      return `
        <div class="card">
          <h3>${p.scope.area_id || p.scope.type}</h3>
          <p class="muted">${modes || "keine Modi aktiviert"}</p>
          <p class="muted">Code nötig: Scharf ${p.options.code_arm_required ? "ja" : "nein"},
             Unscharf ${p.options.code_disarm_required ? "ja" : "nein"} |
             Profile: ${assignments || "keine zugeordnet"}</p>
          ${zones.length
            ? `<table><tr><th>Zone</th><th>Entität</th><th>Alarmtyp</th><th>Rollen</th><th>Optionen</th></tr>${zoneRows}</table>`
            : `<p class="muted">Keine Zonen zugeordnet.</p>`}
        </div>`;
    }).join("") || `<p class="muted">Noch keine Bereiche angelegt.</p>`;
  }

  _render_profile() {
    return (this._data.profiles || []).map((prof) => {
      const stages = prof.stages.map((s, i) => {
        const blocks = s.blocks.map((b) => {
          const targets = (b.targets || b.media_targets || []).join(", ");
          return `${BLOCK_LABELS[b.type] || b.type}${targets ? ` → ${targets}` : ""}`;
        }).join("<br>");
        return `<tr><td>Stufe ${i + 1}</td>
          <td>${s.duration_s === null ? "bis Alarmende" : s.duration_s + " s"}</td>
          <td>${blocks || "-"}</td></tr>`;
      }).join("");
      return `<div class="card"><h3>${prof.name}</h3>
        <table><tr><th></th><th>Dauer</th><th>Bausteine</th></tr>${stages}</table></div>`;
    }).join("") || `<p class="muted">Noch keine Reaktionsprofile angelegt.</p>`;
  }

  _render_personen() {
    const users = (this._data.users || []).map((u) => {
      const panels = u.rights.panels === null ? "alle"
        : u.rights.panels.map((p) => this._panelName(p)).join(", ");
      return `<tr><td>${u.name}</td><td>${u.enabled ? "ja" : "nein"}</td>
        <td>${u.rights.can_arm ? "ja" : "nein"}</td><td>${u.rights.can_disarm ? "ja" : "nein"}</td>
        <td>${panels}</td></tr>`;
    }).join("");
    const phases = {};
    for (const p of (this._data.state.presence || [])) phases[p.person_id] = p.phase;
    const persons = (this._data.persons || []).map((p) => `
      <tr><td>${p.name}</td><td><code>${p.tracker_entity}</code></td>
      <td><code>${p.distance_entity || "-"}</code></td>
      <td>${p.away_confirm_distance_m || "Std."}</td>
      <td>${PHASE_LABELS[phases[p.id]] || phases[p.id] || "-"}</td></tr>`).join("");
    const rules = (this._data.rules || []).map((r) => `
      <tr><td>${r.name}</td><td>${r.enabled ? "ja" : "nein"}</td>
      <td>${r.panel_id === "master" ? "Gesamtsystem" : this._panelName(r.panel_id)}</td>
      <td>${MODE_LABELS[r.arm.mode] || r.arm.mode}, ${r.arm.execution}</td>
      <td>${r.return_action.disarm ? "entschärft bei Ankunft" : "-"}</td></tr>`).join("");
    return `
      <div class="card"><h3>Benutzer (Zugang)</h3>
        ${users ? `<table><tr><th>Name</th><th>Aktiv</th><th>Scharf</th><th>Unscharf</th><th>Bereiche</th></tr>${users}</table>`
                : `<p class="muted">Keine Benutzer. PINs werden über die API gesetzt (users/set_pin).</p>`}</div>
      <div class="card"><h3>Anwesenheits-Personen</h3>
        ${persons ? `<table><tr><th>Name</th><th>Tracker</th><th>Distanz</th><th>Schwelle (m)</th><th>Phase</th></tr>${persons}</table>`
                  : `<p class="muted">Keine Personen angelegt.</p>`}</div>
      <div class="card"><h3>Automatik-Regeln</h3>
        ${rules ? `<table><tr><th>Name</th><th>Aktiv</th><th>Bereich</th><th>Scharf</th><th>Rückkehr</th></tr>${rules}</table>`
                : `<p class="muted">Keine Regeln angelegt.</p>`}</div>`;
  }

  _render_betrieb() {
    const walk = (this._data.panels || []).map((p) => {
      const info = (this._data.state.walk_tests || {})[p.id];
      return `<div class="card"><h3>Walk-Test: ${p.scope.area_id || p.scope.type}</h3>
        ${info
          ? `<p>läuft, Ende <span class="muted" data-ends-at="${info.ends_at}"></span><br>
             Getestet: ${info.tested.map((z) => this._zoneName(z)).join(", ") || "noch keine Zone"}</p>
             <button class="inline-btn" data-walk="stop" data-panel="${p.id}">Beenden</button>`
          : `<p class="muted">nicht aktiv</p>
             <button class="inline-btn" data-walk="start" data-panel="${p.id}">Starten</button>`}
      </div>`;
    }).join("");
    const audit = (this._data.audit?.entries || []).map((e) => {
      const { ts, seq, kind, ...rest } = e;
      return `<tr><td class="muted">${ts.slice(0, 19).replace("T", " ")}</td>
        <td>${kind}</td><td class="muted"><code>${JSON.stringify(rest)}</code></td></tr>`;
    }).join("");
    return `${walk}
      <div class="card"><h3>Protokoll (letzte ${this._data.audit?.entries?.length || 0} Einträge, ${this._data.audit?.month || ""})</h3>
        ${audit ? `<table><tr><th>Zeit (UTC)</th><th>Ereignis</th><th>Details</th></tr>${audit}</table>`
                : `<p class="muted">Noch keine Einträge.</p>`}</div>`;
  }
}

if (!customElements.get("kustos-panel")) {
  customElements.define("kustos-panel", KustosPanel);
}
