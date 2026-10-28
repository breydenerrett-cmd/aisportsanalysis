/**
 * THE RECORD PAGE'S SPREADSHEET LINK AND HINDSIGHT REVIEWS (owner ask 2026-10-28). Used by web/js/track-record.js.
 *
 *   SPREADSHEET  "Download bets (spreadsheet)": every bet the hound recorded, as a file (GET /hounds/{id}/export, src/hounds/bet_export.py).
 *                A house hound's file is open to anyone, so the link is a plain link; a member hound's is for its owner, so the click
 *                fetches it with the owner's sign-in and saves the bytes (a link cannot carry a header).
 *   ALL VERSIONS "All versions" beside it: the same sheet for every version of the hound (GET /hounds/{id}/export?versions=all), with a
 *                Version and a Version status column. The ordinary link is unchanged.
 *   REVIEWS      Under a settled ticket, a "Hindsight review" that opens to what happened, the key factors, whether the hound's reason
 *                was relevant, luck or process, what the hound did not know, the lesson, other analysts' takes and the sources.
 *                Fed by GET /hounds/{id}/postmortems, which says whether the viewer may see them (a member hound's are the
 *                owner's). Written AFTER the result, from the web, and labelled so: it is never shown as pre-game reasoning.
 *   DEEP REVIEW  Under the tickets, "Deep review (hindsight)" with its date: what is working, what is failing and the biggest changes
 *                worth trying, over the hound's whole record across every version. The newest opens; earlier ones stay listed.
 *
 * Every word of the review is the server's; this file only draws it. A source link is drawn only for an http(s) address, opens
 * in a new tab and carries no referrer.
 */

import { apiGet, getToken } from "./api.js";
import { h } from "./hounds-core.js";
import { formatStamp } from "./local-time.js";

export const EXPORT_TEXT = "Download bets (spreadsheet)";
export const ALL_VERSIONS_TEXT = "All versions";
export const DEEP_LABEL = "Deep review (hindsight)";
export const DEEP_NOTE = "Written after the results, from this hound's whole record across every version. The numbers are counted by the app and the words only explain them. It is not what the hound knew before a game.";
export const REVIEW_LABEL = "Hindsight review";
export const REVIEW_NOTE = "Written after the result, from news and recaps found on the web. It is not what the hound knew or reasoned before the game.";

export const RELEVANCE_WORDS = {
  valid: "Yes, its reason was about what decided the game",
  partly_valid: "Partly: its reason was only part of what decided the game",
  not_relevant: "No: other things decided the game",
  unverifiable: "Could not be checked against the sources",
};
export const LUCK_WORDS = {
  mostly_process: "Mostly sound process",
  mixed: "A mix of process and luck",
  mostly_luck: "Mostly luck",
  unclear: "Unclear",
};

// ---- pure helpers (the tests run these under node) ------------------------------------------------------------

export const exportHref = (id, fmt = "csv", versions = "") => `/hounds/${encodeURIComponent(id)}/export?format=${encodeURIComponent(fmt)}${versions === "all" ? "&versions=all" : ""}`;

/** The link shows on every house hound's record, and on a member hound's only for its owner. */
export const canExport = (hound, owner) => !!hound && !!(hound.is_house || owner);

/** A URL that is safe to link to: http or https and nothing else, else "". */
export function safeUrl(url) {
  const text = String(url || "").trim();
  return /^https?:\/\/[^\s<>"']+$/i.test(text) ? text : "";
}

export const fileNameOf = (id, fmt, versions = "") => `linehound-${String(id || "hound").replace(/[^A-Za-z0-9_.-]/g, "_")}-bets${versions === "all" ? "-all-versions" : ""}.${fmt}`;

// ---- the spreadsheet --------------------------------------------------------------------------------------------

/** Ask for the file with the viewer's sign-in and hand it to the browser. Returns {ok} or {ok: false, message}. */
export async function downloadExport(id, fmt = "csv", versions = "") {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let res;
  try {
    res = await fetch(exportHref(id, fmt, versions), { headers });
  } catch (err) {
    return { ok: false, message: "Could not reach the server. Try again in a minute." };
  }
  if (!res.ok) {
    let detail = {};
    try { detail = (JSON.parse(await res.text()) || {}).detail || {}; } catch (err) { /* not JSON */ }
    const message = detail && typeof detail === "object" && detail.message ? detail.message
      : res.status === 503 ? "The record is still being worked out. Try again in a few seconds."
      : res.status === 401 || res.status === 403 ? "Only the hound's owner can download this spreadsheet."
      : "The spreadsheet is not available right now. Try again in a minute.";
    return { ok: false, message };
  }
  const blob = typeof res.blob === "function" ? await res.blob() : new Blob([await res.text()], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: fileNameOf(id, fmt, versions), "data-hook": "export-download-link" });
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => { try { URL.revokeObjectURL(url); } catch (err) { /* nothing to free */ } }, 4000);
  return { ok: true };
}

/** Fill the container with the link (and a one-line status). `owner` is true for the hound's owner. Hidden when not allowed. */
export function renderExport(box, hound, owner, id) {
  while (box.firstChild) box.removeChild(box.firstChild);
  if (!canExport(hound, owner)) { box.hidden = true; return; }
  box.hidden = false;
  const note = h("span", { class: "rc-export__note", "data-hook": "export-note", role: "status", "aria-live": "polite" });
  const link = h("a", { class: "rc-export__link", href: exportHref(id), "data-hook": "export-link", text: EXPORT_TEXT });
  link.addEventListener("click", async (event) => {
    if (event && event.preventDefault) event.preventDefault();
    note.textContent = "Getting the spreadsheet...";
    const out = await downloadExport(id);
    note.textContent = out.ok ? "Saved. Replay bets are labelled and never counted." : out.message;
  });
  const all = h("a", { class: "rc-export__link", href: exportHref(id, "csv", "all"), "data-hook": "export-all-link", text: ALL_VERSIONS_TEXT,
    title: "Every bet of every version of this hound in one sheet, with a Version column" });
  all.addEventListener("click", async (event) => {
    if (event && event.preventDefault) event.preventDefault();
    note.textContent = "Getting every version...";
    const out = await downloadExport(id, "csv", "all");
    note.textContent = out.ok ? "Saved. Every version is in the one sheet, with its status. Replay bets are labelled and never counted." : out.message;
  });
  box.appendChild(link);
  box.appendChild(all);
  box.appendChild(note);
  box.appendChild(h("span", { class: "rc-export__hint", text: "Every bet with the reason it was made, plus a hindsight review once a bet settles. \"All versions\" adds the hound's earlier versions." }));
}

// ---- the reviews ---------------------------------------------------------------------------------------------------

/** The bet reviews and the Deep reviews of this hound, each null when there are none to show (not visible, none yet, or the route failed). */
export async function loadHindsight(id) {
  try {
    const data = await apiGet(`/hounds/${encodeURIComponent(id)}/postmortems`);
    if (!data || data.visible === false) return { reviews: null, deep: null };
    const reviews = data.reviews && typeof data.reviews === "object" && Object.keys(data.reviews).length ? data.reviews : null;
    const deep = Array.isArray(data.deep_reviews) && data.deep_reviews.length ? data.deep_reviews : null;
    return { reviews, deep };
  } catch (err) {
    return { reviews: null, deep: null };      // signed out, a server without the route, a failure: the page simply shows no reviews
  }
}

/** The reviews of this hound's settled bets, or null when there are none to show. */
export async function loadReviews(id) {
  return (await loadHindsight(id)).reviews;
}

function field(label, value) {
  return value ? h("p", { class: "rc-review__row" }, [h("strong", { text: `${label}: ` }), value]) : null;
}

function listOf(label, items) {
  const rows = (items || []).filter(Boolean);
  if (!rows.length) return null;
  return h("div", { class: "rc-review__list" }, [h("strong", { text: `${label}:` }), h("ul", {}, rows.map((t) => h("li", { text: t })))]);
}

function link(url, text) {
  const href = safeUrl(url);
  return href ? h("a", { href, target: "_blank", rel: "noopener noreferrer", text: text || href }) : h("span", { text: text || "" });
}

/** One review as a <details>: the summary says what it is, the body is the review itself. */
export function renderReview(review) {
  const deep = review.depth === "deep";
  const takes = (review.analyst_takes || []).filter((t) => safeUrl(t.url)).map((t) => h("li", {}, [`${t.outlet || "Analyst"}: ${t.take} `, link(t.url, "(source)")]));
  const sources = (review.sources || []).filter((s) => safeUrl(s.url)).map((s) => h("li", {}, [link(s.url, s.title || s.url)]));
  const body = [
    h("p", { class: "rc-review__note", text: REVIEW_NOTE }),
    review.grounded === false ? h("p", { class: "rc-review__warn", text: "No sources were found for this review, so treat it as unchecked." }) : null,
    field("What happened", review.what_happened),
    listOf("Key factors", review.key_factors),
    field("Was the hound's reason relevant", `${RELEVANCE_WORDS[review.reason_relevance] || ""}${review.reason_assessment ? `. ${review.reason_assessment}` : ""}`.trim()),
    field("Luck or process", LUCK_WORDS[review.luck_vs_process] || ""),
    listOf("What the hound did not know", review.info_hound_lacked),
    field("Lesson", review.lesson),
    deep ? field("Deeper notes", review.deeper_notes) : null,
    takes.length ? h("div", { class: "rc-review__list" }, [h("strong", { text: "Other analysts:" }), h("ul", {}, takes)]) : null,
    sources.length ? h("div", { class: "rc-review__list", "data-hook": "review-sources" }, [h("strong", { text: "Sources:" }), h("ul", {}, sources)]) : null,
  ];
  return h("details", { class: "rc-review", "data-hook": "review" }, [
    h("summary", { class: "rc-review__sum", text: `${REVIEW_LABEL}${deep ? " (deep)" : ""}` }),
    h("div", { class: "rc-review__body" }, body),
  ]);
}

// ---- the Deep review ---------------------------------------------------------------------------------------------------

/** One Deep review as a <details>: the label and its date, then the counted basis, the headline, what is working and failing, and the changes. */
export function renderDeepReview(review, { open = false } = {}) {
  const when = formatStamp("d", review.created_utc);
  const versions = Number(review.versions) || 0;
  const rec = review.record || null;
  const basis = review.settled
    ? `Rests on ${review.settled} settled bet${review.settled === 1 ? "" : "s"}${versions > 1 ? ` across ${versions} versions` : ""}${rec ? `: ${rec.wins}-${rec.losses}-${rec.pushes}` : ""}.`
    : "";
  const perVersion = (review.by_version || []).map((v) => `${v.version} (${v.status}): ${v.bets} bet${v.bets === 1 ? "" : "s"}, ${v.wins}-${v.losses}-${v.pushes}`);
  const body = [
    h("p", { class: "rc-review__note", text: DEEP_NOTE }),
    basis ? h("p", { class: "rc-review__row", "data-hook": "deep-basis", text: basis }) : null,
    review.headline ? h("p", { class: "rc-review__row rc-deep__headline", "data-hook": "deep-headline", text: review.headline }) : null,
    listOf("What is working", review.working),
    listOf("What is failing", review.failing),
    listOf("Biggest changes worth trying", review.changes),
    field("About the sample", review.sample_note),
    versions > 1 ? listOf("By version", perVersion) : null,
  ];
  return h("details", { class: "rc-review rc-deep", "data-hook": "deep-review", open }, [
    h("summary", { class: "rc-review__sum", text: `${DEEP_LABEL}${when ? `, ${when}` : ""}` }),
    h("div", { class: "rc-review__body" }, body),
  ]);
}

/** Fill the container with the hound's Deep reviews, newest first (the newest open). Hidden when there are none. */
export function renderDeepReviews(section, box, reviews) {
  while (box.firstChild) box.removeChild(box.firstChild);
  const list = Array.isArray(reviews) ? reviews.filter((r) => r && typeof r === "object") : [];
  section.hidden = !list.length;
  list.forEach((r, i) => box.appendChild(renderDeepReview(r, { open: i === 0 })));
}
