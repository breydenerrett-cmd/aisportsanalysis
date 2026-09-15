/**
 * Page-anatomy primitives shared by every route (DESIGN_SYSTEM.md section
 * 4, "Page anatomy"): the page header, the section head, the one
 * experimental notice, a generic expand-in-place disclosure, and the
 * status/condition chip. Every screen builds its own layout from these
 * instead of inventing its own eyebrow/title/status markup, its own
 * "View breakdown" toggle, or its own chip styling.
 *
 * Pure DOM construction -- no fetches, no routing, no knowledge of any
 * screen's data shape.
 *
 * `compactPickCard` is deliberately NOT exported from here. It lives in
 * `card.js` (gameday-card-owned) as the one implementation of the pick
 * card, per DESIGN_SYSTEM.md section 4 -- this file only carries the
 * generic primitives every screen shares, never a specific card.
 *
 * WHY pageHeader() RETURNS A SEPARATE `body` NODE
 * -------------------------------------------------------------------
 * Several screens today call `renderError(container, err)` (and the
 * loading/empty equivalents) where `container` is the WHOLE content area
 * including the page header -- confirmed by reading `performance.js`,
 * `cardrecord.js`, `dayrecap.js`, `live.js` and `signup.js` directly.
 * Those render functions `clear()` their container first, which would
 * wipe a header the design system says must "always stay on screen."
 * `pageHeader()` mounts `node` (the header) once per route and hands
 * back a separate, empty `body` node -- every loading/empty/error/
 * content render now clears and repaints `body` only. The header itself
 * is never touched again after it mounts. See DESIGN_SYSTEM.md section 3
 * (the status-line note) and section 4.
 */

import { el } from "./dom.js";

/**
 * The page header: eyebrow ("sport · section"), the h1 title, a one-
 * sentence purpose, and a status line (`role="status"`, DESIGN_SYSTEM.md
 * section 4 -- "Every fact is named, e.g. 'Published 9:40 AM PDT ·
 * prices checked 11:05 AM PDT'.").
 *
 * Returns `{node, setStatus, body}`:
 *   - `node` is the header element. A route mounts it once.
 *   - `setStatus(text, options)` updates the status line in place. Kept
 *     as a closure (rather than requiring the caller to re-render the
 *     whole header) so `shell.js`'s `setShellStatus` can write into
 *     whichever header is currently mounted without either module
 *     knowing about the other's routing. `options.stale` swaps on the
 *     caution/`--caution-text` treatment for a real-age stale reading
 *     (DESIGN_SYSTEM.md section 3's game-hours-aware threshold) rather
 *     than a second, separately-styled "STALE" badge.
 *   - `body` is a separate, empty container. Every loading/empty/error/
 *     content render clears and repaints `body` -- never `node`.
 *
 * One h1 per page (DESIGN_SYSTEM.md section 8).
 */
export function pageHeader({ eyebrow, title, purpose, status } = {}) {
  const node = el("header", { class: "pagehead", "data-hook": "page-header" });

  if (eyebrow) {
    node.appendChild(el("p", { class: "pagehead__eyebrow", text: eyebrow }));
  }

  node.appendChild(el("h1", { class: "pagehead__title", text: title || "" }));

  if (purpose) {
    node.appendChild(el("p", { class: "pagehead__purpose", text: purpose }));
  }

  const statusLine = el("p", {
    class: "pagehead__status",
    role: "status",
    "data-hook": "page-status",
  });
  node.appendChild(statusLine);

  function setStatus(text, options = {}) {
    statusLine.textContent = text || "";
    statusLine.classList.toggle("pagehead__status--stale", Boolean(options && options.stale));
  }
  if (status) setStatus(status);

  const body = el("div", { "data-hook": "page-body" });

  return { node, setStatus, body };
}

/**
 * A section head (`.sechead`, DESIGN_SYSTEM.md section 4): a label, a
 * hairline, and meta text -- a count, a board age, whatever real field
 * the caller has. Meta is rendered whenever supplied: the design system
 * says it is "never hidden, because it carries counts" -- CSS
 * repositions it under the label on phone, it does not omit it.
 */
export function sectionHead(label, meta) {
  const head = el("div", { class: "sechead", "data-hook": "section-head" });
  head.appendChild(el("span", { class: "sechead__label", text: label || "" }));
  head.appendChild(el("span", { class: "sechead__rule", "aria-hidden": "true" }));
  if (meta !== undefined && meta !== null && meta !== "") {
    head.appendChild(el("span", { class: "sechead__meta", text: meta }));
  }
  return head;
}

/**
 * The one experimental notice (DESIGN_SYSTEM.md section 4): fixed copy,
 * shown once above the picks -- never a per-card badge -- and left in
 * place through empty and error states. Takes no parameters on purpose:
 * a caller cannot reword or condition away the one sentence every reader
 * of a pick sees.
 */
export function experimentalNotice() {
  return el(
    "div",
    { class: "notice notice--experimental", "data-hook": "experimental-notice" },
    [
      el("p", {
        class: "notice__text",
        text: "Experimental selections. Performance is still being evaluated.",
      }),
    ]
  );
}

let disclosureAutoId = 0;

/**
 * A generic "View breakdown"-style disclosure (DESIGN_SYSTEM.md sections
 * 4 and 8): a text button with `aria-expanded`/`aria-controls` that
 * expands `body` in place, starting collapsed. `body` may be a string, a
 * single DOM node, or an array of nodes -- the caller owns everything
 * inside it (e.g. card.js's three labelled boxes, the comparison
 * sentence, the argument/counterargument, the alternate bet, the grade
 * legend and the "Open this matchup" link all live in card.js, not
 * here). `id` lets a caller give the panel a stable, predictable id
 * (useful when many disclosures render on one page, e.g. one per pick
 * card); when omitted one is generated so `aria-controls` always points
 * at a real element.
 */
export function disclosure({ summary, body, id } = {}) {
  disclosureAutoId += 1;
  const panelId = id || `disclosure-${disclosureAutoId}`;

  const wrap = el("div", { class: "disclosure", "data-hook": "disclosure" });
  const toggle = el("button", {
    type: "button",
    class: "disclosure__summary btn btn--text",
    "aria-expanded": "false",
    "aria-controls": panelId,
    text: summary || "View breakdown",
  });
  const panel = el("div", { class: "disclosure__body", id: panelId, hidden: "" });

  if (body !== undefined && body !== null) {
    const items = Array.isArray(body) ? body : [body];
    for (const item of items) {
      if (item === undefined || item === null) continue;
      panel.appendChild(typeof item === "string" ? document.createTextNode(item) : item);
    }
  }

  toggle.addEventListener("click", () => {
    const expanded = toggle.getAttribute("aria-expanded") === "true";
    toggle.setAttribute("aria-expanded", String(!expanded));
    panel.hidden = expanded;
  });

  wrap.appendChild(toggle);
  wrap.appendChild(panel);
  return wrap;
}

/**
 * A chip (DESIGN_SYSTEM.md section 4): the word comes first, rendered
 * verbatim -- this never composes or rewords the caller's text, only
 * applies the tone class for one of the variants `components.css`
 * defines: `confirmed` (cyan dot, e.g. "Lineup posted"), `waiting`
 * (amber ring, e.g. "Lineup not posted", "Starter unconfirmed", "No
 * price yet"), `neutral` (dashed, e.g. "Provisional until ...",
 * "Locked", "Lock pending"), `win` (the word "Win" only), `settled`
 * (Loss/Push/Void -- neutral-toned, never red: a customer's own loss is
 * not a warning to flash at them) and `coming-soon`.
 */
export function chip(word, kind = "neutral") {
  return el("span", { class: `chip chip--${kind}`, "data-hook": "chip", text: word });
}
