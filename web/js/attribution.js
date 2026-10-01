/**
 * WHO A VISITOR IS (anonymously) AND WHERE THEY FIRST CAME FROM.
 *
 * Two small facts, both kept in localStorage so they survive the hop from the
 * landing page to the app shell to Stripe and back:
 *
 *   1. A RANDOM VISITOR ID. Every funnel beacon used to hash to one shared
 *      sentinel, so "how many different people reached the signup form" had
 *      no answer. This id is generated here, once, from crypto.getRandomValues
 *      (never from anything about the person), and sent with every funnel
 *      event and with the signup. It is not an email, a cookie set by a
 *      server, or a fingerprint; clearing site data makes a new visitor.
 *
 *   2. THE FIRST TOUCH: utm_source / utm_medium / utm_campaign / utm_content /
 *      utm_term from the landing URL, plus the referring HOST (never the full
 *      URL). The landing page recorded these on its own beacons and then
 *      forgot them, so the signup, the account, the Stripe session and the
 *      paid event all read as unattributed. FIRST touch wins: once something
 *      is stored a later visit does not overwrite it, so a campaign gets
 *      credit for the person it found even if they come back direct to pay.
 *      A direct first visit stores nothing, so a later tagged visit can still
 *      be the first touch that counts.
 *
 * Every access is wrapped: private browsing and blocked storage make
 * localStorage throw, and tracking must never break the page it rides on.
 * Without storage the id lives for the page load only and no first touch is
 * kept, which degrades to "unattributed", never to an error.
 *
 * The server re-validates every value (src/appstate/attribution.py); this
 * file only trims and caps lengths so a long link cannot bloat a request.
 */

export const ANON_ID_STORAGE_KEY = "linehound.anon_id";
export const FIRST_TOUCH_STORAGE_KEY = "linehound.first_touch";

const UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"];
const MAX_VALUE_LENGTH = 64;

let _memoryAnonId = "";

function randomId() {
  const bytes = new Uint8Array(16);
  try {
    window.crypto.getRandomValues(bytes);
  } catch (err) {
    // No WebCrypto: fall back to Math.random. This id is a counter of
    // visitors, not a secret, so a weaker source is acceptable.
    for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  }
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** The visitor's random id (32 hex chars), created on first use. */
export function getAnonId() {
  try {
    const stored = window.localStorage.getItem(ANON_ID_STORAGE_KEY);
    if (stored) return stored;
    const fresh = randomId();
    window.localStorage.setItem(ANON_ID_STORAGE_KEY, fresh);
    return fresh;
  } catch (err) {
    if (!_memoryAnonId) _memoryAnonId = randomId();
    return _memoryAnonId;
  }
}

function readFirstTouch() {
  try {
    const raw = window.localStorage.getItem(FIRST_TOUCH_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (err) {
    return {};
  }
}

/** This page load's own UTM tags and referrer host, or {} if it has none. */
export function currentArrival() {
  const props = {};
  try {
    const params = new URLSearchParams(window.location.search);
    for (const key of UTM_KEYS) {
      const value = (params.get(key) || "").trim();
      if (value) props[key] = value.slice(0, MAX_VALUE_LENGTH);
    }
    // HOST only, never the full referring URL, and never our own host: an
    // internal navigation is not a referral.
    if (document.referrer) {
      const host = new URL(document.referrer).host;
      if (host && host !== window.location.host) props.referrer_host = host.slice(0, MAX_VALUE_LENGTH);
    }
  } catch (err) {
    // A malformed URL or referrer must never stop a page rendering.
  }
  return props;
}

/** Store this visit's arrival as the first touch, unless one is already
 * stored. Call once on landing. Returns the first touch now on record. */
export function captureFirstTouch() {
  const existing = readFirstTouch();
  if (Object.keys(existing).length) return existing;
  const arrival = currentArrival();
  if (!Object.keys(arrival).length) return {};
  try {
    window.localStorage.setItem(FIRST_TOUCH_STORAGE_KEY, JSON.stringify(arrival));
  } catch (err) {
    /* storage unavailable: attribution stays per-page-load */
  }
  return arrival;
}

/** The stored first touch ({} when none). */
export function getFirstTouch() {
  return readFirstTouch();
}

/** First-touch tags plus the visitor id: what rides on the signup request. */
export function attributionPayload() {
  return Object.assign({}, getFirstTouch(), { anon_id: getAnonId() });
}

/** First-touch tags only, for a funnel event's `properties` -- the visitor id
 * travels beside them as the event's own `anon_id`. When this page load has
 * its own tags and none are stored yet they are captured first. */
export function firstTouchProperties() {
  const touch = captureFirstTouch();
  return Object.keys(touch).length ? touch : undefined;
}
