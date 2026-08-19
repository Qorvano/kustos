/* Kustos sidebar panel: root component, data layer, routing, actions.
   Look and feel mirror HA's automation editor: sticky 56px toolbar with
   centered tabs, centered 1040px content column, editors as subpages with
   back arrow and a save pill bottom right. */
import { STYLES, PICKER_STYLES, esc, icon } from "./styles.js";
import {
  renderLeitstand, renderBereiche, renderProfile, renderPersonen, renderBetrieb,
  ALL_MODES, ALARM_TYPES,
} from "./views.js";
import { renderEditor, pickerValueHTML, BLOCK_DEFAULTS, EDITOR_TITLES } from "./editors.js";

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

  _friendly(entityId) {
    const st = this._hass.states[entityId];
    return (st && st.attributes.friendly_name) || entityId;
  }
  _areaName(areaId) {
    if (!areaId) return areaId;
    const area = (this._hass.areas || {})[areaId];
    return (area && area.name) || areaId;
  }
  _panelName(panelId) {
    const doc = (this._data.panels || []).find((p) => p.id === panelId);
    if (doc) {
      if (doc.scope.type === "custom") return doc.scope.name || panelId;
      return this._areaName(doc.scope.area_id) || doc.scope.type;
    }
    const group = (this._data.state?.groups || []).find((g) => g.group_id === panelId);
    return group ? group.name : panelId;
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
    this.shadowRoot.innerHTML = `<style>${STYLES}${PICKER_STYLES}</style>${toolbar}${body}`;
    this._bindActions(this.shadowRoot);
    this._updateCountdowns();
  }

  _bindActions(root) {
    for (const el of root.querySelectorAll("[data-action]")) {
      el.onclick = (ev) => {
        ev.stopPropagation();
        if (el.dataset.action === "chip-del") {
          const field = el.closest(".picker-field");
          if (field) {
            const values = (this._q(field.dataset.input)?.value || "")
              .split(",").map((s) => s.trim()).filter(Boolean)
              .filter((v) => v !== el.dataset.value);
            this._updatePickerDisplay(field.dataset, values);
          }
          return;
        }
        this._onAction(el.dataset);
      };
    }
  }

  /* ---------- picker ---------- */

  _pickerOptions(ds) {
    if (ds.kind === "area") {
      return Object.values(this._hass.areas || {}).map((a) =>
        ({ value: a.area_id, primary: a.name || a.area_id, secondary: a.area_id }));
    }
    if (ds.kind === "service") {
      const notify = Object.keys((this._hass.services || {}).notify || {})
        .map((s) => "notify." + s);
      return [...notify, "persistent_notification.create"]
        .map((v) => ({ value: v, primary: v, secondary: "" }));
    }
    const domains = (ds.domains || "").split(",").filter(Boolean);
    return Object.keys(this._hass.states)
      .filter((e) => domains.some((d) => e.startsWith(d + ".")))
      .map((e) => ({ value: e, primary: this._friendly(e), secondary: e }))
      .sort((a, b) => a.primary.localeCompare(b.primary));
  }

  _updatePickerDisplay(ds, values) {
    const input = this._q(ds.input);
    input.value = values.join(",");
    const display = this._q(ds.input + "-display");
    if (display) {
      display.innerHTML = pickerValueHTML(
        this, values, ds.multi === "1", ds.kind, ds.placeholder || "Auswählen");
      this._bindActions(display);
    }
  }

  _openPicker(ds) {
    const input = this._q(ds.input);
    const multi = ds.multi === "1";
    let selected = new Set(input.value.split(",").map((s) => s.trim()).filter(Boolean));
    const options = this._pickerOptions(ds);
    const ov = document.createElement("div");
    ov.className = "overlay";
    ov.innerHTML = `<div class="picker-dialog">
      <div class="picker-title">${esc(ds.label || "Auswählen")}</div>
      <div class="picker-search"><input type="text" placeholder="Suchen..."></div>
      <div class="picker-list"></div>
      <div class="picker-actions">
        <button class="btn" data-x="cancel">Abbrechen</button>
        ${multi ? '<button class="btn accent" data-x="done">Übernehmen</button>' : ""}
      </div></div>`;
    const listEl = ov.querySelector(".picker-list");
    const renderList = (q = "") => {
      const ql = q.toLowerCase();
      listEl.innerHTML = options
        .filter((o) => !ql || o.primary.toLowerCase().includes(ql)
          || o.value.toLowerCase().includes(ql))
        .slice(0, 300)
        .map((o) => `
          <div class="picker-item ${selected.has(o.value) ? "selected" : ""}" data-v="${esc(o.value)}">
            <span class="pi-body"><div>${esc(o.primary)}</div>
              ${o.secondary && o.secondary !== o.primary
                ? `<div class="pi-sec">${esc(o.secondary)}</div>` : ""}</span>
            <span class="pi-check">${icon("check", 20)}</span>
          </div>`).join("")
        || `<div class="empty">Keine Treffer.</div>`;
      for (const item of listEl.querySelectorAll(".picker-item")) {
        item.onclick = () => {
          const v = item.dataset.v;
          if (multi) {
            if (selected.has(v)) selected.delete(v); else selected.add(v);
            item.classList.toggle("selected");
          } else {
            selected = new Set([v]);
            commit();
          }
        };
      }
    };
    const commit = () => { this._updatePickerDisplay(ds, [...selected]); ov.remove(); };
    ov.querySelector('[data-x="cancel"]').onclick = () => ov.remove();
    const done = ov.querySelector('[data-x="done"]');
    if (done) done.onclick = commit;
    ov.onclick = (ev) => { if (ev.target === ov) ov.remove(); };
    const search = ov.querySelector(".picker-search input");
    search.oninput = () => renderList(search.value);
    renderList();
    this.shadowRoot.appendChild(ov);
    search.focus();
  }

  /* ---------- actions ---------- */

  async _onAction(ds) {
    const a = ds.action;
    if (a === "tab") { this._tab = ds.tab; this._edit = null; this._render(); return; }
    if (a === "cancel") { this._edit = null; this._refresh(); return; }
    if (a === "service") return this._service(ds.service, ds.panel);
    if (a === "pick") return this._openPicker(ds);
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
      const scope = this._val("f-scopetype") === "custom"
        ? { type: "custom", name: this._val("f-cname") }
        : { type: "area", area_id: this._val("f-area") };
      const payload = {
        scope, modes, alarm_types,
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

    // Bereichsgruppen
    if (a === "new-group") { this._edit = { kind: "group", draft: { panel_ids: [] } }; return this._render(); }
    if (a === "edit-group") {
      const g = (this._data.state.groups || []).find((x) => x.group_id === ds.id);
      this._edit = { kind: "group", draft: { id: g.group_id, name: g.name, panel_ids: g.panel_ids } };
      return this._render();
    }
    if (a === "del-group") {
      if (!confirm("Bereichsgruppe löschen? (Die Bereiche selbst bleiben.)")) return;
      await this._ws("kustos/groups/delete", { group_id: ds.id }); return this._refresh();
    }
    if (a === "save-group") {
      const payload = {
        name: this._val("g-name"),
        panel_ids: [...this.shadowRoot.querySelectorAll(".g-panel:checked")].map((x) => x.value),
      };
      const res = ds.id
        ? await this._ws("kustos/groups/update", { group_id: ds.id, ...payload })
        : await this._ws("kustos/groups/create", payload);
      if (res.ok) { this._edit = null; this._refresh(); }
      return;
    }

    // Personen (automatisch aus HA; nur Rechte/PIN/Anwesenheit editierbar)
    if (a === "edit-member") {
      const user = structuredClone((this._data.users || []).find((u) => u.id === ds.id));
      const person = structuredClone((this._data.persons || [])
        .find((pe) => pe.person_entity === user.person_entity) || null);
      this._edit = { kind: "member", draft: { id: user.id, user, person } };
      return this._render();
    }
    if (a === "save-member") {
      const { user, person } = this._edit.draft;
      const panels = this._chk("u-allpanels") ? null
        : [...this.shadowRoot.querySelectorAll(".u-panel:checked")].map((x) => x.value);
      const res = await this._ws("kustos/users/update", {
        user_id: user.id,
        enabled: this._chk("u-enabled"),
        rights: { can_arm: this._chk("u-arm"), can_disarm: this._chk("u-disarm"), panels },
      });
      let ok = res.ok;
      if (ok && person) {
        const res2 = await this._ws("kustos/persons/update", {
          person_id: person.id,
          distance_entity: this._val("pe-dist") || null,
          away_confirm_distance_m: this._num("pe-threshold"),
        });
        ok = res2.ok;
      }
      if (ok) { this._edit = null; this._refresh(); }
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
    if (a === "edit-settings") {
      this._edit = { kind: "settings", draft: structuredClone(this._data.settings) };
      return this._render();
    }
    if (a === "prio-up" || a === "prio-down") {
      this._syncSettingsDraft();
      const list = this._edit.draft.engine.alarm_type_priority;
      const i = Number(ds.i);
      const j = a === "prio-up" ? i - 1 : i + 1;
      [list[i], list[j]] = [list[j], list[i]];
      return this._render();
    }
    if (a === "save-settings") {
      this._syncSettingsDraft();
      const res = await this._ws("kustos/settings/update", { settings: this._edit.draft });
      if (res.ok) { this._edit = null; this._refresh(); }
      return;
    }
  }

  _syncSettingsDraft() {
    const d = this._edit?.draft;
    if (!d) return;
    const set = (path, id) => {
      const v = this._num(id);
      if (v !== null) {
        const keys = path.split(".");
        let node = d;
        while (keys.length > 1) node = node[keys.shift()];
        node[keys[0]] = v;
      }
    };
    set("defaults.exit_delay_s", "s-exit");
    set("defaults.entry_delay_s", "s-entry");
    set("defaults.trigger_time_s", "s-trigger");
    set("defaults.debounce_s", "s-debounce");
    set("defaults.walk_test_timeout_s", "s-walk");
    set("presence.away_confirm_distance_m", "s-away");
    set("presence.min_away_duration_s", "s-minaway");
    set("presence.prewarn_s", "s-prewarn");
    set("engine.restore_retry_window_s", "s-retry");
    set("audit.query_limit", "s-audit");
    set("storage.runtime_save_delay_s", "s-save");
    if (this._q("s-ack")) d.security.require_explicit_ack = this._chk("s-ack");
    if (this._q("s-disack")) d.security.disarm_acknowledges = this._chk("s-disack");
    const ls = [...this.shadowRoot.querySelectorAll(".ls-type:checked")].map((x) => x.value);
    if (this._q("s-exit")) d.engine.life_safety_unlock_types = ls;
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
      if (eid.startsWith("alarm_control_panel.")
          && (st.attributes.panel_id === panelId || st.attributes.group_id === panelId)) {
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
