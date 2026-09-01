/**
 * Minimal DOM-construction and generic-JSON-rendering helpers shared by
 * every view module.
 *
 * WHY A GENERIC JSON RENDERER EXISTS AT ALL
 * -------------------------------------------------------------------
 * docs/API_CONTRACTS.md states plainly that some fields are not yet a
 * stable per-field contract ("dossier": "full internal dossier dump --
 * not yet a stable per-field contract; treat as opaque today"; the same
 * for `sections`/`gaps` on the advanced game view). A structural client
 * cannot hardcode field names inside an opaque blob without becoming the
 * thing that breaks the day that blob's shape changes. `renderUnknown`
 * walks whatever JSON comes back into semantic <dl>/<ul> markup instead
 * of composing a claim about it -- this is display, not interpretation.
 */

export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null) continue;
    if (key === "text") {
      node.textContent = value;
    } else if (key.startsWith("data-") || key.startsWith("aria-")) {
      node.setAttribute(key, value);
    } else {
      node.setAttribute(key, value);
    }
  }
  const kids = Array.isArray(children) ? children : [children];
  for (const child of kids) {
    if (child === undefined || child === null) continue;
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

export function clear(container) {
  while (container.firstChild) container.removeChild(container.firstChild);
}

/** Known machine field names get a hand-written human label; anything
 * else falls back to a mechanical "snake_case -> Title Case" reformat
 * (spaces in, words capitalized) -- never a summary or interpretation of
 * the field, just its own name made readable. Content rule: "No raw
 * snake_case field names visible anywhere on a primary surface"
 * (design/linehound-v1 handoff, section 11). */
const FIELD_LABELS = {
  observed_utc: "Updated",
  age_seconds: "Age (seconds)",
  has_market: "Has market",
  has_board: "Has board",
  has_lineups: "Has lineups",
  has_starters: "Has starters",
  has_price_board: "Has price board",
  books: "Books",
  game_pk: "Game ID",
  game_id: "Game ID",
  start_time_utc: "Start time",
  first_pitch_utc: "First pitch",
  away_team: "Away",
  home_team: "Home",
  away_probable: "Away starter",
  home_probable: "Home starter",
  double_header: "Doubleheader",
  game_number: "Game number",
  detailed_state: "Status",
  generated_at: "Generated",
  checked_games: "Games checked",
  sample_n: "Sample size (n)",
  evidence_label: "Evidence status",
  best_price: "Best price",
  best_book: "Best book",
  consensus_probability: "Consensus probability",
  improvement_probability_points: "Improvement (points)",
  improvement_return_pct: "Improvement (%)",
};

export function humanizeKey(key) {
  if (Object.prototype.hasOwnProperty.call(FIELD_LABELS, key)) return FIELD_LABELS[key];
  return String(key)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** verdict is a small fixed enum (docs/API_CONTRACTS.md: no_play |
 * candidate | flagged | market_unavailable) -- this only reformats the
 * same string for reading (spaces, capitals), it never changes or
 * interprets which verdict was given. A future enum value not in this
 * table still gets the mechanical fallback rather than showing raw
 * snake_case. */
const VERDICT_LABELS = {
  no_play: "NO PLAY",
  candidate: "CANDIDATE",
  flagged: "FLAGGED",
  market_unavailable: "MARKET UNAVAILABLE",
};
export function verdictLabel(verdict) {
  if (!verdict) return null;
  return VERDICT_LABELS[verdict] || verdict.replace(/_/g, " ").toUpperCase();
}

/** Verdict -> chip color per the design system's reserved-color rule
 * (tokens.css: money is reserved for a price advantage, live/cyan is for
 * "live, changed, analytical"). `no_play` is the ordinary, expected
 * outcome on most games -- it is not a downside, so it gets the neutral
 * outline treatment, not the money-red one. `candidate`/`flagged` are the
 * analytically-noteworthy verdicts, so they get the cyan analytical
 * treatment. `market_unavailable` is a data gap, not a finding. */
export function verdictChipClass(verdict) {
  if (verdict === "candidate" || verdict === "flagged") return "badge--live";
  return "badge--outline";
}

/** ET, always with the meridiem -- never a bare UTC timestamp or a
 * 24-hour clock (design/linehound-v1 handoff, section 11's "Times" rule).
 * `Intl` resolves America/New_York against the real IANA database, so
 * this is correct across the DST boundary without a bundled tz table.
 * Returns null (never a guess) when `isoUtc` is missing or unparsable. */
export function formatEasternTime(isoUtc) {
  if (!isoUtc) return null;
  const date = new Date(isoUtc);
  if (Number.isNaN(date.getTime())) return null;
  const time = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York", hour: "numeric", minute: "2-digit", hour12: true,
  }).format(date);
  return `${time} ET`;
}

/** A single "value not present" marker. Not a composed claim -- a
 * placeholder for JSON `null`/`undefined`, distinct from any API-supplied
 * unavailability string, which is always rendered verbatim instead. */
export function renderAbsent() {
  return el("span", { class: "value-absent", "data-hook": "value-absent", text: "—" });
}

/** Render any JSON value (object/array/primitive) as semantic markup,
 * for fields the contract does not yet pin field-by-field. See module
 * docstring. */
export function renderUnknown(value) {
  if (value === null || value === undefined) {
    return renderAbsent();
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return renderAbsent();
    const list = el("ul", { class: "raw-list" });
    for (const item of value) {
      list.appendChild(el("li", { class: "raw-list__item" }, [renderUnknown(item)]));
    }
    return list;
  }
  if (typeof value === "object") {
    const keys = Object.keys(value);
    if (keys.length === 0) return renderAbsent();
    const dl = el("dl", { class: "raw-fields" });
    for (const key of keys) {
      dl.appendChild(el("dt", { class: "raw-fields__key", "data-raw-key": key, text: humanizeKey(key) }));
      dl.appendChild(el("dd", { class: "raw-fields__value" }, [renderUnknown(value[key])]));
    }
    return dl;
  }
  return document.createTextNode(String(value));
}


/* ---------------------------------------------------------------------
 * Display formatting shared by the designed screens.
 *
 * Every helper below either reformats a value the API supplied or
 * returns null. None of them derives a new claim, and none of them
 * invents a figure when the source field is missing -- a caller that
 * gets null renders NOT YET AVAILABLE or omits the line entirely.
 * ------------------------------------------------------------------- */

/** "THU SEP 1" in ET -- the shell clock's date half. */
export function formatEasternDate(isoUtc) {
  if (!isoUtc) return null;
  const date = new Date(isoUtc);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York", weekday: "short", month: "short", day: "numeric",
  }).format(date).toUpperCase().replace(/,/g, "");
}

/** "7:40pm" in ET, without the trailing " ET" -- for places the canvas
 * prints the meridiem time beside a separate ET marker. Times are always
 * ET with the meridiem (handoff section 11's Times rule). */
export function formatEasternClock(isoUtc) {
  if (!isoUtc) return null;
  const date = new Date(isoUtc);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York", hour: "numeric", minute: "2-digit", hour12: true,
  }).format(date).replace(/\s/g, "").toLowerCase();
}

/** "32 SEC AGO" / "13 MIN AGO" / "2 HR AGO" from the API's own
 * `age_seconds`. Null in, null out -- never a fabricated 0. */
export function formatAge(ageSeconds) {
  if (ageSeconds === null || ageSeconds === undefined) return null;
  const seconds = Number(ageSeconds);
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  if (seconds < 90) return `${Math.round(seconds)} SEC AGO`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes} MIN AGO`;
  const hours = Math.round(minutes / 60);
  if (hours < 36) return `${hours} HR AGO`;
  return `${Math.round(hours / 24)} DAY AGO`;
}

/** American prices print with an explicit sign: -132, +122. */
export function formatAmerican(price) {
  if (price === null || price === undefined) return null;
  const n = Number(price);
  if (!Number.isFinite(n)) return null;
  return n > 0 ? `+${n}` : String(n);
}

/** A market-implied consensus fraction as a percentage string. NOT a win
 * probability: this is the de-vigged MARKET-IMPLIED CONSENSUS, the
 * market's own implied share with the book margin removed (docs/
 * API_CONTRACTS.md's vocabulary rules), and it is always labelled that
 * way at the call site. */
export function formatConsensusShare(fraction) {
  if (fraction === null || fraction === undefined) return null;
  const n = Number(fraction);
  if (!Number.isFinite(n)) return null;
  return `${(n * 100).toFixed(1)}%`;
}

/** Book slugs arrive machine-shaped (`williamhill_us`) -- this only
 * reformats the same string for reading, it never renames a book. */
export function formatBook(book) {
  if (!book) return null;
  return String(book).replace(/_/g, " ").toUpperCase();
}

/* ---------------------------------------------------------------------
 * Screen states
 * ------------------------------------------------------------------- */

/** The canonical NOT YET AVAILABLE panel (handoff section 10): a labelled
 * hatch panel naming exactly what is missing and why. Mandatory wherever
 * a metric is absent -- empty space is not an acceptable substitute, and
 * an estimate is never one either. */
export function notYetAvailable(reason, label = "NOT INGESTED") {
  const panel = el("div", { class: "not-yet-available chamfer", "data-hook": "not-yet-available" });
  const head = el("div", { class: "not-yet-available__head" });
  head.appendChild(el("span", { class: "not-yet-available__marker chamfer" }));
  head.appendChild(el("span", { class: "not-yet-available__label", text: "NOT YET AVAILABLE" }));
  head.appendChild(el("span", { class: "not-yet-available__label not-yet-available__label--tag", text: label }));
  panel.appendChild(head);
  panel.appendChild(el("p", { class: "not-yet-available__body", text: reason }));
  return panel;
}

/** Loading: the chamfered shell IS the skeleton -- panel geometry at
 * final size, figures replaced by a mono placeholder. No spinners. */
export function renderLoading(text) {
  return el("div", { class: "state-loading panel chamfer", "data-hook": "view-loading" },
    [el("p", { class: "state-loading__figure", text })]);
}

/** A missing/invalid invite token. Customer language on the primary
 * surface, with the API's own words kept -- verbatim, never paraphrased
 * -- inside a collapsed disclosure. This client never decides WHY the
 * token is wrong, it only names the state and offers the one next step:
 * the interim #/signin route. */
function renderAuthRequired(container, err) {
  const detail = err && err.detail !== undefined ? err.detail : null;
  const section = el("section", {
    class: "gate chamfer", role: "alert", "data-hook": "auth-required",
  });
  section.appendChild(el("p", { class: "gate__eyebrow", text: "SIGN IN REQUIRED" }));
  section.appendChild(el("p", { class: "gate__title", text: "Sign in to view tonight's board." }));
  section.appendChild(el("p", { class: "gate__body",
    text: "This board is part of the private beta, so it needs your invite token. "
        + "Add it once and it stays on this device." }));
  const actions = el("div", { class: "gate__actions" });
  actions.appendChild(el("a", { href: "#/signin", class: "btn btn--primary chamfer chamfer--btn",
    "data-hook": "signin-link", text: "Sign in" }));
  section.appendChild(actions);
  if (detail) {
    const disclosure = el("details", { class: "gate__detail", "data-hook": "auth-required-detail" });
    disclosure.appendChild(el("summary", { text: "Technical detail" }));
    disclosure.appendChild(el("div", { class: "gate__detail-body" },
      [typeof detail === "string" ? document.createTextNode(detail) : renderUnknown(detail)]));
    section.appendChild(disclosure);
  }
  container.appendChild(section);
}

/** A lapsed subscription (402 {"error":"subscription_expired"}) -- a
 * distinct state from a missing token, with the one honest next step:
 * a link to the billing route (never a client-composed upsell). */
function renderSubscriptionExpired(container) {
  const section = el("section", {
    class: "gate chamfer", role: "alert", "data-hook": "subscription-expired",
  });
  section.appendChild(el("p", { class: "gate__eyebrow", text: "SUBSCRIPTION ENDED" }));
  section.appendChild(el("p", { class: "gate__title", text: "Your subscription has ended." }));
  section.appendChild(el("p", { class: "gate__body",
    text: "This page is not available right now. Billing has the details and the way back in." }));
  const actions = el("div", { class: "gate__actions" });
  actions.appendChild(el("a", { href: "#/billing", class: "btn btn--ghost chamfer chamfer--btn",
    "data-hook": "billing-link", text: "Go to billing" }));
  section.appendChild(actions);
  container.appendChild(section);
}

/** Render a fetch/API failure as a semantic status region rather than a
 * blank pane -- BOUNDARIES: never fabricate a message; the API's own
 * detail is kept verbatim, but it sits in a disclosure rather than
 * leading a customer surface. 401 and 402-subscription-expired get their
 * own distinct treatment (see above) -- and a `null` status (the fetch
 * itself never completed) is worded as "could not be reached" rather
 * than implying the server answered and said no, since those are
 * different failures for the reader even though this client cannot tell
 * local network trouble from a real service outage
 * (docs/OPERATIONS_RUNBOOK.md sect 7). */
export function renderError(container, err) {
  clear(container);
  const status = err && err.status != null ? String(err.status) : "network";
  if (status === "401") {
    renderAuthRequired(container, err);
    return;
  }
  if (status === "402" && err && err.detail && typeof err.detail === "object"
      && err.detail.error === "subscription_expired") {
    renderSubscriptionExpired(container);
    return;
  }
  const detail = err && err.detail !== undefined ? err.detail
    : (err && err.message) || "request failed";
  const section = el("section", {
    class: "gate view-error chamfer state-error", role: "alert", "data-hook": "view-error",
    "data-status": status,
  });
  section.appendChild(el("p", { class: "gate__eyebrow", text: "REQUEST FAILED" }));
  if (status === "network") {
    section.appendChild(el("p", { class: "gate__title", text: "We could not reach the board." }));
    section.appendChild(el("p", { class: "gate__body", text:
      "That could be your own connection or a service outage -- it is not the same as "
      + "the server answering \"no games\"." }));
  } else {
    section.appendChild(el("p", { class: "gate__title", text: "That request did not go through." }));
    section.appendChild(el("p", { class: "view-error__status gate__body", text: `Status: ${status}` }));
  }
  const disclosure = el("details", { class: "gate__detail" });
  disclosure.appendChild(el("summary", { text: "Technical detail" }));
  disclosure.appendChild(el("div", { class: "gate__detail-body view-error__detail" },
    [typeof detail === "string" ? document.createTextNode(detail) : renderUnknown(detail)]));
  section.appendChild(disclosure);
  container.appendChild(section);
}
