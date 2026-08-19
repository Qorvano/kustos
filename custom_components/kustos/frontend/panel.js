/* Kustos sidebar panel: root component, data layer, routing, actions.
   Look and feel mirror HA's automation editor: sticky 56px toolbar with
   centered tabs, centered 1040px content column, editors as subpages with
   back arrow and a save pill bottom right. */
import { STYLES, esc, icon } from "./styles.js";
import {
  renderLeitstand, renderBereiche, renderProfile, renderPersonen, renderBetrieb,
  ALL_MODES, ALARM_TYPES,
} from "./views.js";
import { renderEditor, BLOCK_DEFAULTS, EDITOR_TITLES } from "./editors.js";

const TABS = {
  leitstand: ["Leitstand", renderLeitstand],
  bereiche: ["Bereiche", renderBereiche],
  profile: ["Reaktionsprofile", renderProfile],
  personen: ["Personen", renderPersonen],
  betrieb: ["Betrieb", renderBetrieb],
};

class KustosPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "leitstand";
    this._data = {};
    this._edit = null;
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
      "kustos_arming", "kustos_armed", "kustos_pending", "kustos_triggered",
      "kustos_disarmed", "kustos_arm_failed", "kustos_acknowledged",
      "kustos_zone_bypassed", "kustos_walk_test_zone", "kustos_presence_phase",
      "kustos_auto_arm_pending", "kustos_auto_armed", "kustos_auto_disarmed",
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
      return { ok: true, result: await this._hass.callWS({ type, ...payload }) };
    } catch (err) {
      alert("Fehler: " + (err.message || err));
      return { ok: false };
    }
  }

  /* ---------- shared helpers (used by views/editors) ---------- */

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
      .sort().map((e) => `<option value="${esc(e)}">`).join("");
    return `<datalist id="${id}">${options}</datalist>`;
  }
  _q(id) { return this.shadowRoot.getElementById(id); }
  _val(id) { return this._q(id) ? this._q(id).value.trim() : ""; }
  _num(id) { const v = this._val(id); return v === "" ? null : Number(v); }
  _chk(id) { return this._q(id) ? this._q(id).checked : false; }
  _list(id) { return this._val(id).split(",").map((s) => s.trim()).filter(Boolean); }

  _updateCountdowns() {
    for (const el of this.shadowRoot.querySelectorAll("[data-ends-at]")) {
      const remaining = Math.max(0,
        Math.round((new Date(el.dataset.endsAt) - Date.now()) / 1000));
      el.textContent = `noch ${remaining} s`;
    }
  }

  /* ---------- rendering ---------- */

  _render() {
    let toolbar, body;
    if (this._edit) {
      const title = EDITOR_TITLES[this._edit.kind][this._edit.draft.id ? 1 : 0];
      toolbar = `<div class="toolbar">
        <button class="icon-btn" data-action="cancel" title="Zurück">${icon("arrow-left")}</button>
        <span class="title">${title}</span><span class="spacer"></span></div>`;
      body = this._data.state
        ? `<div class="content narrow-col editor">${renderEditor(this)}</div>`
        : `<div class="content"><p class="muted">Lade Daten...</p></div>`;
    } else {
      const tabs = Object.entries(TABS).map(([key, [label]]) =>
        `<button class="${this._tab === key ? "active" : ""}" data-action="tab" data-tab="${key}">${label}</button>`
      ).join("");
      toolbar = `<div class="toolbar"><span class="title">Kustos</span>
        <div class="tabs">${tabs}</div></div>`;
      let inner;
      if (this._data.error) inner = `<div class="card"><div class="empty">Fehler: ${esc(this._data.error)}</div></div>`;
      else if (!this._data.state) inner = `<p class="muted">Lade Daten...</p>`;
      else inner = TABS[this._tab][1](this);
      body = `<div class="content">${inner}</div>`;
    }
    this.shadowRoot.innerHTML = `<style>${STYLES}</style>${toolbar}${body}`;
    for (const el of this.shadowRoot.querySelectorAll("[data-action]")) {
      el.onclick = () => this._onAction(el.dataset);
    }
    this._updateCountdowns();
  }

  /* ---------- actions ---------- */

  async _onAction(ds) {
    const a = ds.action;
    if (a === "tab") { this._tab = ds.tab; this._edit = null; this._render(); return; }
    if (a === "cancel") { this._edit = null; this._refresh(); return; }
    if (a === "service") return this._service(ds.service, ds.panel);
    if (a === "walk") {
      await this._ws("kustos/walk_test", { panel_id: ds.panel, action: ds.walk });
      return this._refresh();
    }

    // Bereiche
    if (a === "new-panel") { this._edit = { kind: "panel", draft: { modes: { armed_away: { enabled: true } }, options: {}, scope: {} } }; return this._render(); }
    if (a === "edit-panel") { this._edit = { kind: "panel", draft: structuredClone((this._data.panels || []).find((p) => p.id === ds.id)) }; return this._render(); }
    if (a === "del-panel") {
      if (!confirm("Bereich samt Zonen-Konfiguration löschen?")) return;
      await this._ws("kustos/panels/delete", { panel_id: ds.id }); return this._refresh();
    }
    if (a === "save-panel") {
      const modes = {};
      for (const m of ALL_MODES) {
        const entry = { enabled: this._chk(`mode-${m}`) };
        for (const [f, key] of [["exit", "exit_delay_s"], ["entry", "entry_delay_s"], ["trig", "trigger_time_s"]]) {
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

    // Zonen
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

    // Profile
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

    // Benutzer
    if (a === "new-user") { this._edit = { kind: "user", draft: {} }; return this._render(); }
    if (a === "edit-user") { this._edit = { kind: "user", draft: structuredClone((this._data.users || []).find((u) => u.id === ds.id)) }; return this._render(); }
    if (a === "del-user") {
      if (!confirm("Benutzer löschen?")) return;
      await this._ws("kustos/users/delete", { user_id: ds.id }); return this._refresh();
    }
    if (a === "save-user") {
      const panels = this._chk("u-allpanels") ? null
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
        ? "Duress-PIN (nur Ziffern, min. 4). Entschärft normal und alarmiert still. Leer = entfernen:"
        : "PIN (nur Ziffern, min. 4). Leer = entfernen:");
      if (pin === null) return;
      await this._ws("kustos/users/set_pin", { user_id: ds.id, pin: pin || null, kind: ds.kind });
      return this._refresh();
    }

    // Personen
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

    // Regeln
    if (a === "new-rule") { this._edit = { kind: "rule", draft: {} }; return this._render(); }
    if (a === "edit-rule") { this._edit = { kind: "rule", draft: structuredClone((this._data.rules || []).find((r) => r.id === ds.id)) }; return this._render(); }
    if (a === "del-rule") {
      if (!confirm("Regel löschen?")) return;
      await this._ws("kustos/rules/delete", { rule_id: ds.id }); return this._refresh();
    }
    if (a === "save-rule") {
      const persons = this._chk("r-allpersons") ? null
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

    // Einstellungen
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
    const draft = this._edit?.draft;
    if (!draft) return;
    draft.name = this._val("p-name") || draft.name;
    (draft.stages || []).forEach((s, i) => {
      s.duration_s = this._num(`stage-${i}-dur`);
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
    let entityId = null;
    for (const [eid, st] of Object.entries(this._hass.states)) {
      if (eid.startsWith("alarm_control_panel.") && st.attributes.panel_id === panelId) {
        entityId = eid; break;
      }
    }
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
