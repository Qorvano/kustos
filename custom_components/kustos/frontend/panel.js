/* Kustos sidebar panel, M1: buildless vanilla web component.
   Pure projection of the WebSocket API; no state of its own beyond the
   fetched snapshots. User-facing texts are formal German (Sie-Form). */

const STATE_LABELS = {
  disarmed: "Unscharf",
  arming: "Wird scharf",
  armed: "Scharf",
  pending: "Eintrittsverzögerung",
  triggered: "ALARM",
};

const MODE_LABELS = {
  armed_away: "Abwesend",
  armed_home: "Zuhause",
  armed_night: "Nacht",
  armed_vacation: "Urlaub",
  armed_custom_bypass: "Benutzerdefiniert",
};

class KustosPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "leitstand";
    this._state = null;
    this._panels = [];
    this._zones = [];
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
      "kustos_zone_bypassed",
    ]) {
      this._unsubs.push(conn.subscribeEvents(() => this._refresh(), evt));
    }
  }

  async _refresh() {
    if (!this._hass) return;
    try {
      const [state, panels, zones] = await Promise.all([
        this._hass.callWS({ type: "kustos/state/list" }),
        this._hass.callWS({ type: "kustos/panels/list" }),
        this._hass.callWS({ type: "kustos/zones/list" }),
      ]);
      this._state = state;
      this._panels = panels;
      this._zones = zones;
    } catch (err) {
      this._state = { error: String(err.message || err) };
    }
    this._render();
  }

  _panelEntity(panelId) {
    for (const [entityId, st] of Object.entries(this._hass.states)) {
      if (
        entityId.startsWith("alarm_control_panel.") &&
        st.attributes.panel_id === panelId
      ) {
        return entityId;
      }
    }
    return null;
  }

  async _service(service, panelId) {
    const entityId = this._panelEntity(panelId);
    if (!entityId) return;
    const domain = service === "acknowledge" ? "kustos" : "alarm_control_panel";
    await this._hass.callService(domain, service, { entity_id: entityId });
    setTimeout(() => this._refresh(), 300);
  }

  _updateCountdowns() {
    for (const el of this.shadowRoot.querySelectorAll("[data-ends-at]")) {
      const remaining = Math.max(
        0,
        Math.round((new Date(el.dataset.endsAt) - Date.now()) / 1000)
      );
      el.textContent = `noch ${remaining} s`;
    }
  }

  _render() {
    const style = `
      :host { display: block; padding: 16px; font-family: var(--paper-font-body1_-_font-family, sans-serif);
              color: var(--primary-text-color); background: var(--primary-background-color); min-height: 100%; }
      h1 { font-size: 1.4em; margin: 0 0 12px; }
      nav button { margin-right: 8px; padding: 8px 16px; border: none; border-radius: 4px;
                   background: var(--secondary-background-color); color: var(--primary-text-color); cursor: pointer; }
      nav button.active { background: var(--primary-color); color: var(--text-primary-color, #fff); }
      .card { background: var(--card-background-color); border-radius: 8px; padding: 16px;
              margin: 12px 0; box-shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,.3)); }
      .state { font-weight: bold; }
      .state.triggered { color: var(--error-color, #d32f2f); }
      .state.pending, .state.arming { color: var(--warning-color, #f9a825); }
      .state.armed { color: var(--success-color, #2e7d32); }
      .actions button { margin: 4px 6px 0 0; padding: 6px 12px; border: 1px solid var(--divider-color);
                        border-radius: 4px; background: var(--secondary-background-color);
                        color: var(--primary-text-color); cursor: pointer; }
      table { border-collapse: collapse; width: 100%; }
      td, th { text-align: left; padding: 4px 12px 4px 0; border-bottom: 1px solid var(--divider-color); }
      .muted { color: var(--secondary-text-color); font-size: .9em; }
    `;
    const tabs = `
      <nav>
        <button class="${this._tab === "leitstand" ? "active" : ""}" data-tab="leitstand">Leitstand</button>
        <button class="${this._tab === "bereiche" ? "active" : ""}" data-tab="bereiche">Bereiche</button>
      </nav>`;
    const body = this._tab === "leitstand" ? this._renderLeitstand() : this._renderBereiche();
    this.shadowRoot.innerHTML = `<style>${style}</style><h1>Kustos</h1>${tabs}${body}`;
    for (const btn of this.shadowRoot.querySelectorAll("nav button")) {
      btn.onclick = () => { this._tab = btn.dataset.tab; this._render(); };
    }
    for (const btn of this.shadowRoot.querySelectorAll("[data-service]")) {
      btn.onclick = () => this._service(btn.dataset.service, btn.dataset.panel);
    }
    this._updateCountdowns();
  }

  _renderLeitstand() {
    if (!this._state) return `<p class="muted">Lade Daten...</p>`;
    if (this._state.error) return `<p>Fehler: ${this._state.error}</p>`;
    const master = this._state.master;
    const cards = this._state.panels.map((p) => {
      const zones = this._zones.filter((z) => z.panel_id === p.panel_id);
      const memory = p.alarm_memory.length
        ? `<p class="muted">Alarmspeicher: ${p.alarm_memory
            .map((m) => `${m.entity_id} (${m.alarm_type})`)
            .join(", ")}</p>`
        : "";
      const countdown = p.ends_at
        ? `<span class="muted" data-ends-at="${p.ends_at}"></span>`
        : "";
      const bypassed = p.bypassed_zones.length
        ? `<p class="muted">Überbrückt: ${p.bypassed_zones.length} Zone(n)</p>`
        : "";
      return `
        <div class="card">
          <h3>${p.area_id || p.panel_id}</h3>
          <p><span class="state ${p.state}">${STATE_LABELS[p.state] || p.state}</span>
             ${p.arm_mode ? `(${MODE_LABELS[p.arm_mode] || p.arm_mode})` : ""} ${countdown}</p>
          <p class="muted">${zones.length} Zone(n) zugeordnet</p>
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
    return `
      <div class="card">
        <h3>Gesamtsystem</h3>
        <p><span class="state ${master.state}">${STATE_LABELS[master.state] || master.state}</span>
           ${master.arm_mode ? `(${MODE_LABELS[master.arm_mode] || master.arm_mode})` : ""}</p>
      </div>
      ${cards.join("") || `<p class="muted">Noch keine Bereiche angelegt. Sie können Bereiche im Reiter "Bereiche" einsehen; das Anlegen erfolgt in M1 noch über die API.</p>`}`;
  }

  _renderBereiche() {
    const rows = this._panels.map((p) => {
      const zones = this._zones.filter((z) => z.panel_id === p.id);
      const zoneRows = zones
        .map(
          (z) => `<tr><td>${z.name || z.entity_id}</td><td>${z.entity_id}</td>
                  <td>${z.alarm_type}</td>
                  <td>${Object.entries(z.modes).map(([m, r]) => `${MODE_LABELS[m] || m}: ${r}`).join(", ") || "-"}</td></tr>`
        )
        .join("");
      return `
        <div class="card">
          <h3>${p.scope.area_id || p.scope.type}</h3>
          <p class="muted">Modi: ${Object.entries(p.modes)
            .filter(([, c]) => c.enabled)
            .map(([m]) => MODE_LABELS[m] || m)
            .join(", ") || "keine aktiviert"}</p>
          ${zones.length
            ? `<table><tr><th>Zone</th><th>Entität</th><th>Alarmtyp</th><th>Rollen</th></tr>${zoneRows}</table>`
            : `<p class="muted">Keine Zonen zugeordnet.</p>`}
        </div>`;
    });
    return rows.join("") || `<p class="muted">Noch keine Bereiche angelegt.</p>`;
  }
}

if (!customElements.get("kustos-panel")) {
  customElements.define("kustos-panel", KustosPanel);
}
