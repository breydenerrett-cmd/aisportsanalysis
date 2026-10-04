/**
 * Entry point and renderer for web/sample.html: ONE real brief, free to read, with no account.
 *
 * WHAT IT SHOWS
 * -------------
 * The game the owner designated in config/sample_brief.json, as the server serves it from GET
 * /sample/brief: the same analysis section the paid game page draws (renderAnalystSection: summary,
 * every call with its reasons and its case against, what the analysis could not use), the label the
 * server sent, when the brief was frozen and when the game starts, and the result of every call once
 * the game has been graded. It links to the public record and to the landing page and says the offer
 * in one line.
 *
 * WHAT IT MUST NOT DO
 * -------------------
 * - Claim anything the record has not earned. The offer line says what is on offer and what it costs
 *   and that this is analysis, not advice; there is no profit, no edge and no win-rate claim here, and
 *   the label stays "Unproven".
 * - Pick the game. The server serves the one designated game or says there is none; this file never
 *   passes a date or a team, so no URL parameter can make it show another brief.
 * - Lose the source. An outreach link opens this page with utm_source / utm_medium / utm_campaign in
 *   the address; `captureFirstTouch` (the one implementation, attribution.js, the same call the
 *   landing page makes) stores them on load, first touch wins. The links below carry nothing: the
 *   landing page and the signup read the stored source, so a lead who read this page and signs up
 *   later is credited to the message that found them.
 */

import { apiGet } from "./api.js";
import { captureFirstTouch } from "./attribution.js";
import { el, formatEasternClock } from "./dom.js";
import { renderAnalystSection } from "./analyst.js";
import { renderDisclaimerFooter } from "./meta.js";

export const OFFER_LINE =
  "MLB postseason briefs are posted before first pitch. Free for 7 days for the first testers, "
  + "no card. Planned price $19.99 a month. Analysis, not advice.";

export const NONE_TEXT = "There is no sample brief to show right now.";

/** Where the page's links go. Plain addresses: the stored first touch rides along by itself. */
export const LINKS = {
  record: { href: "index.html#/record-card", text: "See the public record" },
  landing: { href: "landing.html", text: "About LINEHOUND" },
  signup: { href: "index.html#/signup", text: "Start the free 7 days" },
};

function facts(data) {
  const list = el("ul", { class: "sp-facts", "data-hook": "sample-facts" });
  const frozen = formatEasternClock(data.published_utc);
  const starts = formatEasternClock(data.first_pitch_utc);
  if (frozen) list.appendChild(el("li", { "data-hook": "sample-frozen", text: `Frozen at ${frozen}, before the game.` }));
  if (starts) list.appendChild(el("li", { "data-hook": "sample-first-pitch", text: `First pitch ${starts}.` }));
  const a = data.analysis || {};
  if (a.graded) {
    const final = a.final;
    const score = final && final.away_score !== undefined && final.home_score !== undefined
      ? ` Final: ${a.away} ${final.away_score}, ${a.home} ${final.home_score}.` : "";
    list.appendChild(el("li", { "data-hook": "sample-graded", text: `Graded.${score} The result of each call is shown on it below.` }));
  } else {
    list.appendChild(el("li", { "data-hook": "sample-graded", text: "Not graded yet. The result of each call will be added here after the game." }));
  }
  return list;
}

function links() {
  const row = el("p", { class: "sp-links", "data-hook": "sample-links" });
  for (const key of ["record", "landing", "signup"]) {
    row.appendChild(el("a", { href: LINKS[key].href, "data-hook": `sample-link-${key}`, text: LINKS[key].text }));
  }
  return row;
}

/** @param data  GET /sample/brief: {available, label, analysis, reason, first_pitch_utc, published_utc} */
export function renderSample(data) {
  const page = el("div", { class: "sp-page", "data-hook": "sample-page" });
  page.appendChild(el("h1", { class: "an-family__head", text: "A sample brief" }));
  page.appendChild(el("p", { class: "sp-intro", "data-hook": "sample-intro",
    text: "One real brief, written before the game and kept exactly as it was. Every call is shown, "
      + "the passes as plainly as the takes, with the strongest reason against each one." }));
  if (data && data.available && data.analysis) {
    page.appendChild(facts(data));
    page.appendChild(renderAnalystSection(data));
  } else {
    page.appendChild(el("p", { class: "an-none", "data-hook": "sample-none",
      text: (data && data.reason) || NONE_TEXT }));
  }
  page.appendChild(links());
  page.appendChild(el("p", { class: "sp-offer", "data-hook": "sample-offer", text: OFFER_LINE }));
  return page;
}

async function fetchSample() {
  try {
    return await apiGet("/sample/brief");
  } catch (err) {
    return null;
  }
}

async function main() {
  // Store the outreach link's source before anything else can fail.
  try { captureFirstTouch(); } catch (err) { /* never break the page */ }
  const outlet = document.querySelector("[data-hook='app-outlet']");
  const footer = document.querySelector("[data-hook='disclaimer-host']");
  if (footer) renderDisclaimerFooter(footer, { linkPrefix: "index.html" });
  if (!outlet) return;
  outlet.appendChild(renderSample(await fetchSample()));
}

if (typeof document !== "undefined" && typeof window !== "undefined") {
  document.addEventListener("DOMContentLoaded", main);
}
