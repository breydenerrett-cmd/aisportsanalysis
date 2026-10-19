/**
 * ADMIN UI helpers -- small building blocks for web/js/admin-app.js and admin-views.js:
 * number/date wording, chips, inline SVG, toasts, the copy button and the dialog.
 *
 * Nothing here talks to the network or to storage, and nothing here ever sees an admin token.
 * A freshly issued ACCESS token reaches this file only as text handed to the dialog or to
 * copyText(), and neither keeps it: closing a dialog empties its root.
 *
 * The page builds DOM with el()/svgEl() only (no innerHTML), so a name, a reason or a support
 * message typed by a stranger is always text, never markup.
 */

import { el, clear } from "./dom.js";

const SVG_NS = "http://www.w3.org/2000/svg";

/** An SVG element. Attributes only; children are SVG nodes or strings. */
export function svgEl(tag, attrs = {}, children = []) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null) continue;
    node.setAttribute(key, value);
  }
  for (const child of Array.isArray(children) ? children : [children]) {
    if (child === undefined || child === null) continue;
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

// ---------------------------------------------------------------------------
// Numbers and times. Everything is UTC, because the server writes UTC.
// ---------------------------------------------------------------------------

/** 12345 -> "12,345"; anything that is not a finite number -> "—". */
export function fmtInt(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return String(Math.round(value)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** Epoch milliseconds from an ISO string the server wrote; NaN when unreadable. SQLite-style
 * "2026-10-19 14:03:00" and a bare date are read as UTC. */
export function parseTime(value) {
  if (typeof value !== "string" || !value) return NaN;
  let text = value.trim().replace(" ", "T");
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) text += "T00:00:00Z";
  else if (!/(Z|[+-]\d{2}:?\d{2})$/.test(text)) text += "Z";
  return Date.parse(text);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Oct 19" from a YYYY-MM-DD day. */
export function dayLabel(day) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(day || ""));
  return m ? `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}` : String(day || "—");
}

/** "Oct 19, 14:03 UTC" -- a moment, or an em dash when there is none. */
export function momentLabel(value) {
  const t = parseTime(value);
  if (!Number.isFinite(t)) return "—";
  const d = new Date(t);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}, ${hh}:${mm} UTC`;
}

/** "Oct 19" for a joined/granted date, an em dash when unreadable. */
export function dateLabel(value) {
  const t = parseTime(value);
  if (!Number.isFinite(t)) return "—";
  const d = new Date(t);
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
}

/** A span of milliseconds as "2d 4h", "5h 10m" or "25m" (never negative). */
export function spanLabel(ms) {
  const total = Math.max(0, Math.round(ms / 60000));
  const days = Math.floor(total / 1440);
  const hours = Math.floor((total % 1440) / 60);
  const minutes = total % 60;
  if (days >= 2) return `${days}d ${hours}h`;
  if (days === 1) return `1d ${hours}h`;
  if (hours >= 1) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

/** "3h 5m ago" for a past instant. */
export function agoLabel(value, now) {
  const t = parseTime(value);
  if (!Number.isFinite(t)) return "—";
  return `${spanLabel(now - t)} ago`;
}

/** "in 5h 10m" or "ended 2d 3h ago" for the moment a tester's access stops. */
export function untilLabel(value, now) {
  const t = parseTime(value);
  if (!Number.isFinite(t)) return "—";
  return t >= now ? `in ${spanLabel(t - now)}` : `ended ${spanLabel(now - t)} ago`;
}

// ---------------------------------------------------------------------------
// Small elements
// ---------------------------------------------------------------------------

/** A status chip. `tone` is ok | warn | bad | info | mute. Its word comes first; the colour
 * only repeats it. */
export function chip(text, tone = "mute", hook) {
  return el("span", { class: `adm-chip adm-chip--${tone}`, "data-hook": hook, "data-tone": tone, text });
}

/** A button. `variant`: primary | ghost | danger | text. */
export function button(label, { variant = "ghost", hook, onClick, type = "button", title } = {}) {
  const node = el("button", { type, class: `adm-btn adm-btn--${variant}`, "data-hook": hook, title, text: label });
  if (onClick) node.addEventListener("click", onClick);
  return node;
}

/** True when `node` is `root` or inside it. */
export function isInside(node, root) {
  for (let n = node; n; n = n.parentNode) if (n === root) return true;
  return false;
}

/** Copy text to the clipboard; resolves true or false and never throws. */
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (err) {
    return false;
  }
}

/** A short message in the corner; it removes itself. `host` is the live region. */
export function toast(host, message, tone = "ok") {
  if (!host) return;
  const node = el("div", { class: `adm-toast adm-toast--${tone}`, "data-hook": "admin-toast", text: message });
  host.appendChild(node);
  setTimeout(() => { if (node.parentNode) node.parentNode.removeChild(node); }, tone === "bad" ? 9000 : 5000);
}

/** Set a keyboard-focusable element's focus without ever throwing. */
export function focusSoon(node) {
  try {
    if (node && typeof node.focus === "function") node.focus();
  } catch (err) {
    /* focus is a convenience */
  }
}

// ---------------------------------------------------------------------------
// The dialog
// ---------------------------------------------------------------------------

let openDialog = null;

/** Close whatever dialog is open, emptying its root (which is what removes a token from the page). */
export function closeDialog() {
  if (!openDialog) return;
  const { root, inertTargets, restore, onKey } = openDialog;
  openDialog = null;
  clear(root);
  for (const target of inertTargets) target.removeAttribute("inert");
  if (typeof document.removeEventListener === "function") document.removeEventListener("keydown", onKey);
  focusSoon(restore);
}

/**
 * Open a dialog in `root` and return { panel, body, footer, close }. The rest of the page is
 * made inert while it is open (so Tab cannot leave it and nothing behind it can be clicked).
 * Escape closes it; a click on the backdrop closes it unless `sticky` (a token is on screen).
 */
export function showDialog(root, { title, hook = "admin-dialog", sticky = false, inertTargets = [] }) {
  closeDialog();
  clear(root);
  const restore = (typeof document !== "undefined" && document.activeElement) || null;
  const backdrop = el("div", { class: "adm-backdrop", "data-hook": "admin-backdrop" });
  const panel = el("div", { class: "adm-dialog", role: "dialog", "aria-modal": "true",
    "aria-label": title, "data-hook": hook });
  const head = el("div", { class: "adm-dialog__head" }, [
    el("h2", { class: "adm-dialog__title", text: title }),
  ]);
  const body = el("div", { class: "adm-dialog__body" });
  const footer = el("div", { class: "adm-dialog__foot" });
  panel.appendChild(head);
  panel.appendChild(body);
  panel.appendChild(footer);
  backdrop.appendChild(panel);
  root.appendChild(backdrop);

  const onKey = (event) => { if (event && event.key === "Escape") closeDialog(); };
  if (typeof document.addEventListener === "function") document.addEventListener("keydown", onKey);
  for (const target of inertTargets) target.setAttribute("inert", "");
  backdrop.addEventListener("click", (event) => {
    if (!sticky && event.target === backdrop) closeDialog();
  });
  openDialog = { root, inertTargets, restore, onKey };
  return { panel, body, footer, close: closeDialog };
}

/**
 * A form dialog: optional paragraphs, fields, one or more submit actions.
 *
 *   fields:  [{ key, label, type: "text"|"email"|"textarea", required, hint, placeholder, value }]
 *   actions: [{ label, variant, hook, requires?: [field keys], run(values) -> Promise }]
 *
 * A required field left empty stops the action BEFORE any request is made and says which field.
 * `run` may throw; its message (see `errorText`) is shown in the dialog, which stays open.
 * A resolved run closes the dialog and its value is returned to `onDone`.
 */
export function formDialog(root, spec) {
  const { title, intro = [], fields = [], actions = [], errorText, onDone, inertTargets, hook, onUnauthorized } = spec;
  const dialog = showDialog(root, { title, hook: hook || "admin-dialog", inertTargets });
  for (const line of intro) {
    dialog.body.appendChild(el("p", { class: "adm-dialog__text", text: line }));
  }
  const inputs = {};
  const errors = {};
  for (const field of fields) {
    const id = `adm-field-${field.key}`;
    const wrap = el("div", { class: "adm-field" });
    wrap.appendChild(el("label", { for: id, class: "adm-field__label", text: field.label }));
    const input = field.type === "textarea"
      ? el("textarea", { id, rows: "3", maxlength: "500", autocomplete: "off", placeholder: field.placeholder,
          "data-hook": `admin-field-${field.key}` })
      : el("input", { id, type: field.type || "text", maxlength: "500", autocomplete: "off",
          placeholder: field.placeholder, "data-hook": `admin-field-${field.key}` });
    if (field.value) input.value = field.value;
    wrap.appendChild(input);
    if (field.hint) wrap.appendChild(el("p", { class: "adm-field__hint", text: field.hint }));
    const error = el("p", { class: "adm-field__error", role: "alert", "data-hook": `admin-field-error-${field.key}` });
    wrap.appendChild(error);
    dialog.body.appendChild(wrap);
    inputs[field.key] = input;
    errors[field.key] = error;
  }
  const status = el("p", { class: "adm-dialog__status", role: "alert", "data-hook": "admin-dialog-status" });
  dialog.body.appendChild(status);

  const cancel = button("Cancel", { variant: "ghost", hook: "admin-dialog-cancel", onClick: closeDialog });
  dialog.footer.appendChild(cancel);
  let pending = false;
  const buttons = [];
  for (const action of actions) {
    const node = button(action.label, { variant: action.variant || "primary", hook: action.hook || "admin-dialog-confirm" });
    node.addEventListener("click", async () => {
      if (pending) return;
      status.textContent = "";
      const values = {};
      let missing = null;
      // An action may name the fields IT needs (an email-only grant does not need a reason).
      const needed = action.requires || fields.filter((f) => f.required).map((f) => f.key);
      for (const field of fields) {
        const value = String(inputs[field.key].value || "").trim();
        values[field.key] = value;
        errors[field.key].textContent = "";
        if (needed.includes(field.key) && !value && !missing) missing = field;
      }
      if (missing) {
        errors[missing.key].textContent = `Required: ${missing.requiredMessage || missing.label}.`;
        focusSoon(inputs[missing.key]);
        return;
      }
      pending = true;
      for (const b of buttons) b.disabled = true;
      status.textContent = action.pendingLabel || "Working...";
      try {
        const result = await action.run(values);
        closeDialog();
        if (typeof onDone === "function") await onDone(result, action);
      } catch (err) {
        if (err && err.status === 401 && typeof onUnauthorized === "function") {
          closeDialog();
          onUnauthorized();
          return;
        }
        status.textContent = typeof errorText === "function" ? errorText(err) : String((err && err.message) || err);
        pending = false;
        for (const b of buttons) b.disabled = false;
      }
    });
    buttons.push(node);
    dialog.footer.appendChild(node);
  }
  const first = fields.length ? inputs[fields[0].key] : null;
  focusSoon(first || buttons[0] || cancel);
  return dialog;
}
