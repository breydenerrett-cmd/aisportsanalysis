/**
 * SHARED STATES (V2-27..30) -- the four cross-screen state primitives every
 * V2 screen renders into instead of inventing its own skeleton / empty /
 * unavailable / error markup: LOADING (V2-27), EMPTY (V2-28), UNAVAILABLE
 * (V2-29) and ERROR (V2-30). Traced from design/linehound-v2/'LINEHOUND V2
 * Full Product.dc.html' lines 6084-6437 (see IMPLEMENTATION_MANIFEST.json's
 * V2-27..30 entries for the field-by-field ledger this file's comments
 * repeat inline).
 *
 * ONE DEFINITION, NOT A FORK (per design/linehound-v2/IMPLEMENTATION_PLAN.md
 * Wave 0 -- Group S)
 * -------------------------------------------------------------------
 * web/js/dom.js already owns two of these concepts and does them
 * correctly -- `renderLoading` (a minimal skeleton panel) and `renderError`
 * (request-failure rendering that already special-cases 401 and the 402
 * subscription-expired branch, and never fabricates a message). Re-exported
 * below UNCHANGED rather than re-implemented, so there is exactly one
 * place that decides what a 401 means or what an unreachable API looks
 * like. `notYetAvailable` (a single missing FIELD, e.g. one metric on a
 * dossier) is also re-exported unchanged -- it answers a different
 * question than any state below (a per-field gap vs. a whole-screen
 * condition) so nothing here duplicates it.
 *
 * The four functions this file ADDS (`renderLoadingSkeleton`,
 * `renderEmptySlate`, `renderCaptureUnavailable`, `renderWriteFailed`) are
 * genuinely new: V1 has no equivalent rich, full-panel treatment for any
 * of "still drawing the board", "an honest zero-game night",
 * "the capture pipeline stopped answering" or "that write did not save" --
 * so there is nothing pre-existing to fork. They render CONTENT ONLY (the
 * panel a screen mounts into its own host), not the page shell/rail/topbar
 * the artboard shows around them -- exactly like `renderLoading` and
 * `renderError` already do.
 *
 * WHAT THE ARTBOARD SHOWS THAT THIS FILE DELIBERATELY DOES NOT BIND
 * -------------------------------------------------------------------
 * V2-27's own body copy illustrates a partial-arrival counter (nine of
 * eleven books having arrived) with a progress bar -- but the manifest's own
 * `fields_NOT_available` entry for V2-27 says plainly "no live figures of
 * any kind while loading", because there is no streaming/partial-capture
 * signal on any customer endpoint: a fetch either has not resolved yet or
 * it has. `renderLoadingSkeleton` below never shows a book count, a
 * percentage, or a progress fill -- only geometry-matching skeleton rows
 * and an indeterminate spinner. Flagged in the L15 report per the task's
 * evidence rules.
 *
 * V2-29's body copy illustrates the exact wording "well past our
 * thirty-minute threshold" -- that number is odds.js's own
 * STALE_AFTER_SECONDS choice for ONE screen, not a universal constant this
 * shared primitive should hardcode for every caller. `renderCaptureUnavailable`
 * takes the threshold/age wording as caller-supplied text instead of
 * inventing "thirty minutes" here.
 */

import { el, clear, renderLoading, renderError, notYetAvailable,
  formatEasternClock, formatAge } from "./dom.js";

export { renderLoading, renderError, notYetAvailable };

/* ---------------------------------------------------------------------
 * Small shared bits
 * ------------------------------------------------------------------- */

function eyebrowRow(dotClass, text) {
  const row = el("div", { class: "vst-eyebrow" });
  row.appendChild(el("span", { class: `vst-eyebrow__dot ${dotClass}`, "aria-hidden": "true" }));
  row.appendChild(el("span", { class: "vst-eyebrow__text", text }));
  row.appendChild(el("span", { class: "vst-eyebrow__rule" }));
  return row;
}

function actionsRow(actions, note) {
  const row = el("div", { class: "vst-actions" });
  for (const action of actions || []) {
    if (!action) continue;
    const tag = action.href ? "a" : "button";
    const attrs = {
      class: `btn ${action.primary ? "btn--primary" : "btn--ghost"} chamfer chamfer--btn`,
      text: action.label,
    };
    if (action.href) attrs.href = action.href;
    else attrs.type = "button";
    if (action["data-hook"]) attrs["data-hook"] = action["data-hook"];
    const node = el(tag, attrs);
    if (!action.href && typeof action.onClick === "function") {
      node.addEventListener("click", action.onClick);
    }
    row.appendChild(node);
  }
  if (note) row.appendChild(el("span", { class: "vst-actions__note", text: note }));
  return row;
}

/* ---------------------------------------------------------------------
 * V2-27 -- LOADING · SKELETON
 * ------------------------------------------------------------------- */

/** A richer, multi-row loading treatment for a screen that wants row
 * geometry matching its real rows (V2-27) rather than dom.js's minimal
 * one-line `renderLoading`. NO live figures (see module docstring) --
 * `headline`/`subline` are plain static copy the caller supplies, never a
 * count this function invents. `rows` (default 4) draws that many
 * geometry-only skeleton bars, styled to suggest a generic list row
 * (label + two figures) without claiming to be any specific screen's
 * actual column layout. */
export function renderLoadingSkeleton({ eyebrow = "LOADING", headline, subline, rows = 4 } = {}) {
  const panel = el("div", { class: "vst-panel vst-panel--loading panel chamfer",
    "data-hook": "state-loading-skeleton" });
  panel.appendChild(eyebrowRow("vst-dot--live", eyebrow));
  if (headline) panel.appendChild(el("div", { class: "vst-headline", text: headline }));
  if (subline) panel.appendChild(el("p", { class: "vst-body", text: subline }));

  const list = el("div", { class: "vst-skel-rows", "aria-hidden": "true" });
  for (let i = 0; i < Math.max(0, rows); i += 1) {
    const row = el("div", { class: "vst-skel-row" });
    row.style.animationDelay = `${i * 120}ms`;
    row.appendChild(el("span", { class: "vst-skel-bar vst-skel-bar--label" }));
    row.appendChild(el("span", { class: "vst-spacer" }));
    row.appendChild(el("span", { class: "vst-skel-bar vst-skel-bar--figure" }));
    row.appendChild(el("span", { class: "vst-skel-bar vst-skel-bar--figure" }));
    list.appendChild(row);
  }
  panel.appendChild(list);

  const spinnerRow = el("div", { class: "vst-spinner-row" });
  spinnerRow.appendChild(el("span", { class: "vst-spinner", "aria-hidden": "true" }));
  spinnerRow.appendChild(el("span", { class: "vst-footnote",
    text: "SKELETON ROWS MATCH THE REAL ROW GEOMETRY — NO LAYOUT SHIFT ON ARRIVAL" }));
  panel.appendChild(spinnerRow);

  return panel;
}

/* ---------------------------------------------------------------------
 * V2-28 -- EMPTY · NO SLATE
 * ------------------------------------------------------------------- */

/** An honest zero-count state (V2-28): "the absence is written as a
 * sentence", never a bare empty list. `count`/`countField` are the real
 * field the caller has (e.g. {count: payload.checked_games, countField:
 * "checked_games"} or {count: summary.games_count, countField:
 * "summary.games_count"}) -- when `count` is omitted this renders a
 * generic honest sentence with no invented number rather than assuming
 * zero. `stats` is an optional array of {label, value} tiles built ONLY
 * from real fields the caller supplies (this function fabricates none of
 * its own -- the artboard's own next-slate-date tile, reading simply
 * "tomorrow", is exactly the kind of value nothing in the API states, so
 * it is omitted here unless a caller has a real field for it). */
export function renderEmptySlate({ eyebrow = "NOTHING SCHEDULED", headline, body,
  count, countField, stats = [], actions, actionsNote } = {}) {
  const panel = el("div", { class: "vst-panel vst-panel--empty panel chamfer",
    "data-hook": "state-empty" });
  panel.appendChild(eyebrowRow("vst-dot--live", eyebrow));
  if (headline) panel.appendChild(el("div", { class: "vst-headline", text: headline }));

  let sentence = body;
  if (!sentence) {
    sentence = (typeof count === "number" && countField)
      ? `${countField} is ${count} — an off day, not a failure. The board comes back when the schedule does.`
      : "Nothing to check right now — an off day, not a failure.";
  }
  panel.appendChild(el("p", { class: "vst-body", "data-hook": "state-empty-sentence", text: sentence }));

  const tiles = [];
  if (typeof count === "number") tiles.push({ label: (countField || "COUNT").toUpperCase(), value: String(count) });
  for (const s of stats) if (s && s.label) tiles.push(s);
  if (tiles.length) {
    const row = el("div", { class: "vst-tiles" });
    for (const t of tiles) {
      row.appendChild(el("div", { class: "vst-tile" }, [
        el("div", { class: "vst-tile__label", text: t.label }),
        el("div", { class: "vst-tile__value", text: t.value }),
      ]));
    }
    panel.appendChild(row);
  }

  if ((actions && actions.length) || actionsNote) panel.appendChild(actionsRow(actions, actionsNote));
  return panel;
}

/* ---------------------------------------------------------------------
 * V2-29 -- UNAVAILABLE · CAPTURE DOWN
 * ------------------------------------------------------------------- */

/** The honest-absence state (V2-29) for a systemic capture/data-pipeline
 * gap -- distinct from `notYetAvailable`, which names one missing field,
 * not a whole capture pipeline being unreachable. `reason` is rendered
 * verbatim (never composed); `lastGood` is optional {observedUtc} -- when
 * supplied, its age is computed with dom.js's own `formatAge` (never a
 * second, unrelated age formatter), never fabricated when absent. Amber
 * throughout, per the V2 token bridge's rule that caution/pending/
 * unavailable all read amber, never red (tokens.css's --v-warn-* family;
 * red stays reserved for a genuinely better price or the one primary
 * action). */
export function renderCaptureUnavailable({ eyebrow = "CAPTURE UNREACHABLE", headline, body,
  reason, lastGood, actions, actionsNote } = {}) {
  const panel = el("div", { class: "vst-panel vst-panel--unavailable panel chamfer",
    "data-hook": "state-unavailable" });
  panel.appendChild(eyebrowRow("vst-dot--warn", eyebrow));
  if (headline) panel.appendChild(el("div", { class: "vst-headline vst-headline--warn", text: headline }));
  if (body) panel.appendChild(el("p", { class: "vst-body vst-body--warn", text: body }));

  if (reason || lastGood) {
    const box = el("div", { class: "vst-reasonbox" });
    box.appendChild(el("div", { class: "vst-reasonbox__label", text: "LAST GOOD CAPTURE" }));
    const parts = [];
    if (lastGood && lastGood.observedUtc) {
      const clock = formatEasternClock(lastGood.observedUtc);
      if (clock) parts.push(`${clock} ET`);
      const age = formatAge(lastGood.ageSeconds);
      if (age) parts.push(age.toLowerCase());
    }
    if (reason) parts.push(reason);
    box.appendChild(el("p", { class: "vst-reasonbox__body", "data-hook": "state-unavailable-reason",
      text: parts.length ? parts.join(" — ") : "No reason given." }));
    panel.appendChild(box);
  }

  if ((actions && actions.length) || actionsNote) panel.appendChild(actionsRow(actions, actionsNote));
  return panel;
}

/* ---------------------------------------------------------------------
 * V2-30 -- ERROR · WRITE FAILED
 * ------------------------------------------------------------------- */

/** A failed WRITE (save/delete/submit) -- distinct from `renderError`,
 * which is dom.js's existing GET/fetch-failure treatment (and already
 * handles 401/402 correctly; reused as-is above, never re-derived here).
 * This is for the "that request never reached us, so nothing was
 * written" framing V1 has no equivalent of. `err` is optional and, when
 * present, only ever contributes a caller-decided, already-safe `body`
 * string -- this function never reads a raw status/stack trace out of it
 * itself (the same "never a stack trace" rule dom.js's renderError
 * follows). `refCode` is rendered ONLY when the caller supplies a real
 * server-issued reference -- never fabricated here. */
export function renderWriteFailed({ headline = "THAT DIDN’T SAVE.",
  body = "The request failed before it reached us, so nothing was written. "
    + "Your entry is still in the form — try it again.",
  refCode, actions, actionsNote = "NOTHING WAS WRITTEN — NO PARTIAL SAVE" } = {}) {
  const panel = el("div", { class: "vst-panel vst-panel--error panel chamfer",
    "data-hook": "state-write-error", role: "alert" });
  panel.appendChild(eyebrowRow("vst-dot--warn", "SOMETHING BROKE ON OUR SIDE"));
  panel.appendChild(el("div", { class: "vst-headline vst-headline--warn", text: headline }));
  panel.appendChild(el("p", { class: "vst-body vst-body--warn", text: body }));

  if (refCode) {
    const box = el("div", { class: "vst-refbox" });
    box.appendChild(el("span", { class: "vst-refbox__label", text: "FOR SUPPORT, QUOTE" }));
    box.appendChild(el("span", { class: "vst-refbox__value", "data-hook": "state-write-error-ref", text: refCode }));
    panel.appendChild(box);
  }

  if ((actions && actions.length) || actionsNote) panel.appendChild(actionsRow(actions, actionsNote));
  return panel;
}
