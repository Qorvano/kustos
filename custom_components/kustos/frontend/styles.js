/* Kustos UI kit: design tokens, stylesheet and inline MDI icons.
   All measurements verified against home-assistant/frontend (2026.8):
   ha-card, ha-config-section, hass-tabs-subpage, ha-button, ha-input,
   ha-switch, ha-settings-row. Pure CSS on HA theme variables; no imports
   from the HA frontend, no external resources. */

export const esc = (v) => String(v ?? "")
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");

/* MDI path data (Pictogrammers, Apache 2.0), 24x24 viewBox. */
const ICON_PATHS = {
  "arrow-left": "M20,11V13H8L13.5,18.5L12.08,19.92L4.16,12L12.08,4.08L13.5,5.5L8,11H20Z",
  plus: "M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z",
  pencil: "M20.71,7.04C21.1,6.65 21.1,6 20.71,5.63L18.37,3.29C18,2.9 17.35,2.9 16.96,3.29L15.12,5.12L18.87,8.87M3,17.25V21H6.75L17.81,9.93L14.06,6.18L3,17.25Z",
  delete: "M19,4H15.5L14.5,3H9.5L8.5,4H5V6H19M6,19A2,2 0 0,0 8,21H16A2,2 0 0,0 18,19V7H6V19Z",
  save: "M15,9H5V5H15M12,19A3,3 0 0,1 9,16A3,3 0 0,1 12,13A3,3 0 0,1 15,16A3,3 0 0,1 12,19M17,3H5C3.89,3 3,3.9 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,19V7L17,3Z",
  close: "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z",
  "chevron-right": "M8.59,16.58L13.17,12L8.59,7.41L10,6L16,12L10,18L8.59,16.58Z",
  check: "M21,7L9,19L3.5,13.5L4.91,12.09L9,16.17L19.59,5.59L21,7Z",
  "arrow-up": "M13,20H11V8L5.5,13.5L4.08,12.08L12,4.16L19.92,12.08L18.5,13.5L13,8V20Z",
  "arrow-down": "M11,4H13V16L18.5,10.5L19.92,11.92L12,19.84L4.08,11.92L5.5,10.5L11,16V4Z",
  shield: "M12,1L3,5V11C3,16.55 6.84,21.74 12,23C17.16,21.74 21,16.55 21,11V5L12,1Z",
  account: "M12,4A4,4 0 0,1 16,8A4,4 0 0,1 12,12A4,4 0 0,1 8,8A4,4 0 0,1 12,4M12,14C16.42,14 20,15.79 20,18V20H4V18C4,15.79 7.58,14 12,14Z",
  bell: "M21,19V20H3V19L5,17V11C5,7.9 7.03,5.17 10,4.29C10,4.19 10,4.1 10,4A2,2 0 0,1 12,2A2,2 0 0,1 14,4C14,4.1 14,4.19 14,4.29C16.97,5.17 19,7.9 19,11V17L21,19M14,21A2,2 0 0,1 12,23A2,2 0 0,1 10,21",
  cog: "M12,15.5A3.5,3.5 0 0,1 8.5,12A3.5,3.5 0 0,1 12,8.5A3.5,3.5 0 0,1 15.5,12A3.5,3.5 0 0,1 12,15.5M19.43,12.97C19.47,12.65 19.5,12.33 19.5,12C19.5,11.67 19.47,11.34 19.43,11L21.54,9.37C21.73,9.22 21.78,8.95 21.66,8.73L19.66,5.27C19.54,5.05 19.27,4.96 19.05,5.05L16.56,6.05C16.04,5.66 15.5,5.32 14.87,5.07L14.5,2.42C14.46,2.18 14.25,2 14,2H10C9.75,2 9.54,2.18 9.5,2.42L9.13,5.07C8.5,5.32 7.96,5.66 7.44,6.05L4.95,5.05C4.73,4.96 4.46,5.05 4.34,5.27L2.34,8.73C2.21,8.95 2.27,9.22 2.46,9.37L4.57,11C4.53,11.34 4.5,11.67 4.5,12C4.5,12.33 4.53,12.65 4.57,12.97L2.46,14.63C2.27,14.78 2.21,15.05 2.34,15.27L4.34,18.73C4.46,18.95 4.73,19.03 4.95,18.95L7.44,17.94C7.96,18.34 8.5,18.68 9.13,18.93L9.5,21.58C9.54,21.82 9.75,22 10,22H14C14.25,22 14.46,21.82 14.5,21.58L14.87,18.93C15.5,18.67 16.04,18.34 16.56,17.94L19.05,18.95C19.27,19.03 19.54,18.95 19.66,18.73L21.66,15.27C21.78,15.05 21.73,14.78 21.54,14.63L19.43,12.97Z",
};

export const icon = (name, size = 24) =>
  `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="currentColor" aria-hidden="true"><path d="${ICON_PATHS[name] || ""}"/></svg>`;

export const STYLES = `
  :host {
    display: block;
    min-height: 100%;
    background: var(--primary-background-color, #fafafa);
    color: var(--primary-text-color, #212121);
    font-family: var(--ha-font-family-body, Roboto, Noto, sans-serif);
    font-size: 14px;
    --k-primary: var(--primary-color, #03a9f4);
    --k-on-primary: var(--text-primary-color, #fff);
    --k-divider: var(--divider-color, rgba(0,0,0,.12));
    --k-secondary-text: var(--secondary-text-color, #727272);
    --k-fill: var(--ha-color-form-background, var(--input-fill-color, #f3f3f3));
    --k-label: var(--input-label-ink-color, rgba(0,0,0,.6));
    --k-line: var(--input-idle-line-color, rgba(0,0,0,.42));
  }
  * { box-sizing: border-box; }

  /* ---------- Toolbar (hass-tabs-subpage look) ---------- */
  .toolbar {
    position: sticky; top: 0; z-index: 4;
    display: flex; align-items: center;
    height: var(--header-height, 56px);
    padding: 0 12px;
    background: var(--sidebar-background-color, var(--card-background-color, #fff));
    border-bottom: 1px solid var(--k-divider);
    color: var(--sidebar-text-color, var(--primary-text-color));
  }
  .toolbar .title { font-size: 20px; font-weight: 400; line-height: 1.6;
                    margin-inline-start: 12px; white-space: nowrap; }
  .toolbar .tabs { flex: 1; display: flex; justify-content: center;
                   align-self: stretch; overflow-x: auto; }
  .toolbar .tabs button {
    appearance: none; border: none; background: none; cursor: pointer;
    padding: 0 32px; font: inherit; font-size: 14px; font-weight: 500;
    color: var(--k-secondary-text);
    border-bottom: 2px solid transparent; white-space: nowrap;
  }
  .toolbar .tabs button.active {
    color: var(--k-primary); border-bottom-color: var(--k-primary);
  }
  .toolbar .spacer { flex: 1; }
  .icon-btn {
    appearance: none; border: none; background: none; cursor: pointer;
    width: 48px; height: 48px; border-radius: 50%;
    display: inline-flex; align-items: center; justify-content: center;
    color: var(--sidebar-icon-color, var(--k-secondary-text));
    flex-shrink: 0; position: relative;
  }
  .icon-btn:hover { background: color-mix(in srgb, currentColor 10%, transparent); }

  /* ---------- Content column (ha-config-section wide) ---------- */
  .content { max-width: 1040px; margin: 0 auto;
             padding: 28px 20px calc(120px + env(safe-area-inset-bottom)); }
  .content.narrow-col { max-width: 760px; }
  .cards { display: flex; flex-direction: column; gap: 24px; }
  .content.editor .cards { gap: 16px; }

  /* ---------- Card (ha-card) ---------- */
  .card {
    background: var(--ha-card-background, var(--card-background-color, #fff));
    border-radius: var(--ha-card-border-radius, 12px);
    border: var(--ha-card-border-width, 1px) solid
            var(--ha-card-border-color, var(--k-divider));
    box-shadow: var(--ha-card-box-shadow, none);
    overflow: hidden;
  }
  .card-header { font-size: 24px; font-weight: 400; letter-spacing: -0.012em;
                 line-height: 1.4; padding: 12px 16px 4px; display: flex;
                 align-items: center; gap: 12px; }
  .card-header .hint { font-size: 12px; color: var(--k-secondary-text);
                       margin-left: auto; font-weight: 400; letter-spacing: 0; }
  .card-content { padding: 16px; }
  .card-actions { border-top: 1px solid var(--k-divider); padding: 8px;
                  display: flex; flex-wrap: wrap; gap: 4px; }

  /* ---------- Buttons (ha-button pill look) ---------- */
  .btn {
    appearance: none; cursor: pointer; border: none;
    display: inline-flex; align-items: center; gap: 8px;
    height: 40px; padding: 0 20px;
    border-radius: var(--ha-button-border-radius, 9999px);
    font: inherit; font-size: 14px; font-weight: 500; line-height: 1;
    background: none; color: var(--k-primary);
  }
  .btn:hover { background: color-mix(in srgb, var(--k-primary) 10%, transparent); }
  .btn.accent { background: var(--k-primary); color: var(--k-on-primary); }
  .btn.accent:hover { filter: brightness(1.08); }
  .btn.danger { color: var(--error-color, #db4437); }
  .btn.danger:hover { background: color-mix(in srgb, var(--error-color, #db4437) 10%, transparent); }
  .btn.outlined { border: 1px solid var(--k-divider); color: var(--primary-text-color); }
  .btn:disabled { opacity: .4; cursor: default; }

  .fab {
    position: fixed; right: calc(24px + env(safe-area-inset-right));
    bottom: calc(24px + env(safe-area-inset-bottom)); z-index: 5;
    height: 48px; padding: 0 20px; border: none; cursor: pointer;
    display: inline-flex; align-items: center; gap: 8px;
    border-radius: 9999px; font: inherit; font-size: 14px; font-weight: 500;
    background: var(--k-primary); color: var(--k-on-primary);
    box-shadow: var(--ha-box-shadow-l, 0 6px 20px rgba(0,0,0,.3));
  }

  /* ---------- Settings rows (ha-settings-row / list items) ---------- */
  .rows { display: flex; flex-direction: column; }
  .row { display: flex; align-items: center; min-height: 56px;
         padding: 4px 8px 4px 16px; gap: 16px; }
  .row + .row { border-top: 1px solid var(--k-divider); }
  .row .leading {
    width: 40px; height: 40px; border-radius: 50%; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
    background: color-mix(in srgb, var(--k-primary) 14%, transparent);
    color: var(--k-primary);
  }
  .row .body { flex: 1; min-width: 0; padding: 8px 0; }
  .row .body .primary { line-height: 1.4; }
  .row .body .secondary { padding-top: 2px; font-size: 12px;
                          color: var(--k-secondary-text); line-height: 1.4;
                          overflow-wrap: anywhere; }
  .row .meta { display: flex; align-items: center; gap: 0; flex-shrink: 0; }
  .row .meta .icon-btn { width: 40px; height: 40px; }

  /* ---------- Leitstand state ---------- */
  .big-state { font-size: 28px; font-weight: 400; line-height: 1.3; }
  .big-state.triggered { color: var(--error-color, #db4437); }
  .big-state.pending, .big-state.arming { color: var(--warning-color, #ffa600); }
  .big-state.armed { color: var(--success-color, #43a047); }
  .chip { display: inline-block; padding: 3px 12px; border-radius: 9999px;
          font-size: 12px; background: var(--k-fill); color: var(--k-secondary-text);
          margin-left: 8px; vertical-align: middle; }

  /* ---------- Form fields (ha-input material look) ---------- */
  .form { display: flex; flex-direction: column; gap: 16px; }
  .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
               gap: 12px 16px; }
  .field { position: relative; background: var(--k-fill);
           border-radius: 4px 4px 0 0; border-bottom: 1px solid var(--k-line);
           padding: 22px 16px 6px; min-height: 56px; }
  .field:focus-within { border-bottom: 2px solid var(--k-primary); padding-bottom: 5px; }
  .field > label { position: absolute; top: 7px; left: 16px; right: 16px;
                   font-size: 11px; color: var(--k-label); pointer-events: none;
                   white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .field:focus-within > label { color: var(--k-primary); }
  .field.disabled { opacity: .45; }
  .field.disabled select { cursor: not-allowed; }
  .field input, .field select {
    width: 100%; border: none; outline: none; background: transparent;
    font: inherit; font-size: 16px; color: var(--primary-text-color);
    padding: 0; margin: 0;
  }
  .field select option { background: var(--card-background-color, #fff);
                         color: var(--primary-text-color); }
  textarea.jsonbox { width: 100%; min-height: 220px; font-family: monospace;
    font-size: 13px; background: var(--k-fill); color: var(--primary-text-color);
    border: none; border-bottom: 1px solid var(--k-line); border-radius: 4px 4px 0 0;
    padding: 12px 16px; outline: none; }
  textarea.jsonbox:focus { border-bottom: 2px solid var(--k-primary); }

  /* ---------- Switch rows (ha-switch look) ---------- */
  .switch-row { display: flex; align-items: center; min-height: 48px; gap: 16px; }
  .switch-row .body { flex: 1; }
  .switch-row .body .secondary { font-size: 12px; color: var(--k-secondary-text); }
  .switch { position: relative; display: inline-block; width: 48px; height: 24px;
            flex-shrink: 0; }
  .switch input { opacity: 0; width: 100%; height: 100%; margin: 0; cursor: pointer;
                  position: absolute; z-index: 1; }
  .switch .track { position: absolute; inset: 0; border-radius: 9999px;
    background: var(--k-fill); border: 1px solid var(--k-line); transition: all .15s; }
  .switch .track::after { content: ""; position: absolute; top: 2px; left: 3px;
    width: 18px; height: 18px; border-radius: 50%; background: #fff;
    box-shadow: var(--ha-box-shadow-s, 0 1px 3px rgba(0,0,0,.3)); transition: all .15s; }
  .switch input:checked + .track { background: var(--k-primary); border-color: var(--k-primary); }
  .switch input:checked + .track::after { left: 25px; }

  .muted { color: var(--k-secondary-text); font-size: 13px; }
  .section-label { font-size: 14px; font-weight: 500; color: var(--k-secondary-text);
                   margin: 8px 0 4px; }
  .empty { text-align: center; padding: 32px 16px; color: var(--k-secondary-text); }
  code { font-size: .85em; }
  fieldset.block { border: 1px solid var(--k-divider); border-radius: 8px;
                   margin: 0 0 12px; padding: 12px; }
  fieldset.block legend { font-weight: 500; padding: 0 6px; }
`;

/* ---------- Picker overlay + chips (nachgereicht: Auswahl statt Tipperei) */
export const PICKER_STYLES = `
  .overlay { position: fixed; inset: 0; z-index: 20;
    background: rgba(0,0,0,.32); display: flex; align-items: center; justify-content: center; }
  .picker-dialog { width: min(480px, calc(100vw - 32px)); max-height: 72vh;
    display: flex; flex-direction: column; overflow: hidden;
    background: var(--card-background-color, #fff);
    border-radius: var(--ha-card-border-radius, 12px);
    box-shadow: var(--ha-box-shadow-l, 0 8px 32px rgba(0,0,0,.35)); }
  .picker-title { padding: 14px 16px 0; font-size: 18px; }
  .picker-search { padding: 10px 16px 12px; border-bottom: 1px solid var(--k-divider); }
  .picker-search input { width: 100%; height: 40px; padding: 0 14px; font: inherit;
    font-size: 15px; color: var(--primary-text-color);
    background: var(--k-fill); border: none; border-radius: 9999px; outline: none; }
  .picker-list { overflow-y: auto; flex: 1; }
  .picker-item { display: flex; align-items: center; gap: 12px; padding: 8px 16px;
    cursor: pointer; min-height: 52px; }
  .picker-item:hover { background: color-mix(in srgb, var(--k-primary) 8%, transparent); }
  .picker-item .pi-body { flex: 1; min-width: 0; }
  .picker-item .pi-sec { font-size: 12px; color: var(--k-secondary-text);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .picker-item .pi-check { width: 22px; color: var(--k-primary); visibility: hidden; }
  .picker-item.selected .pi-check { visibility: visible; }
  .picker-actions { border-top: 1px solid var(--k-divider); padding: 8px;
    display: flex; justify-content: flex-end; gap: 4px; }
  .picker-field { cursor: pointer; }
  .picker-field .value-display { display: flex; align-items: center; gap: 8px;
    min-height: 24px; font-size: 16px; }
  .picker-field .value-display .ph { color: var(--k-label); }
  .picker-field .value-display .vd-sec { font-size: 12px; color: var(--k-secondary-text); }
  .picker-field .chev { margin-left: auto; color: var(--k-secondary-text); flex-shrink: 0; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; min-height: 24px; align-items: center; }
  .chip-item { display: inline-flex; align-items: center; gap: 4px;
    background: color-mix(in srgb, var(--k-primary) 12%, transparent);
    border-radius: 9999px; padding: 3px 4px 3px 12px; font-size: 13px; }
  .chip-item .chip-x { border: none; background: none; cursor: pointer; padding: 0;
    width: 20px; height: 20px; border-radius: 50%; display: inline-flex;
    align-items: center; justify-content: center; color: inherit; }
  .chip-item .chip-x:hover { background: color-mix(in srgb, currentColor 15%, transparent); }
`;
