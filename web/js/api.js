/**
 * Thin fetch wrapper for the api/ surface (docs/API_CONTRACTS.md).
 *
 * WHY A SHARED WRAPPER INSTEAD OF EACH VIEW CALLING fetch() DIRECTLY
 * -------------------------------------------------------------------
 * Every game-surface route requires `Authorization: Bearer <token>`
 * (api/app.py's `_authed` dependency list). Centralizing the header here
 * means a view module never touches localStorage itself, and a 401 is
 * handled once, not once per view.
 *
 * WHY THE TOKEN LIVES IN localStorage, NOT A MODULE VARIABLE
 * -------------------------------------------------------------------
 * This is a reference client with no build step and no session state
 * beyond a page load. localStorage is the only thing that survives a
 * refresh; a module-scoped variable would force re-entering the invite
 * token on every reload.
 */

export const TOKEN_STORAGE_KEY = "aisportsanalysis.invite_token";

/**
 * HOW LONG A REQUEST MAY HANG BEFORE WE GIVE UP AND SAY SO.
 *
 * There was no timeout here until 2026-09-10, and on that evening the
 * staging box stopped answering while still accepting connections. `fetch`
 * has no default timeout, so the promise simply never settled: `renderError`
 * below was never reached, the skeleton kept animating, and the owner
 * watched "LOADING THE SLATE" spin on his phone for minutes with no error,
 * no retry, and nothing to tell him the service was down.
 *
 * A 503 was never the problem -- that rejects immediately and renders the
 * error state correctly. The silent case is a server that holds the socket
 * open and never writes a response, which is exactly what an overloaded
 * container does before it dies, and it is the one case an infinite wait
 * handles worst.
 *
 * TWENTY SECONDS, and the number is a judgement rather than a measurement:
 * long enough that a genuinely slow cold build still lands (the slowest
 * endpoint measured locally is /opportunities at 4.6s), short enough that a
 * reader on a phone learns the truth while still caring. A caller with a
 * legitimately slower endpoint passes its own `timeoutMs`.
 */
export const DEFAULT_TIMEOUT_MS = 20000;

export function getToken() {
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY) || "";
  } catch (err) {
    // Private-browsing / storage-disabled: treat as "no token" rather than
    // throwing out of every view that calls getToken().
    return "";
  }
}

export function setToken(token) {
  try {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } catch (err) {
    // Storage unavailable -- the token entry form will simply not persist
    // across a reload; nothing here should crash the page over it.
  }
}

export function clearToken() {
  try {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch (err) {
    /* see setToken */
  }
}

/**
 * THE FREE-CHECK IDENTITY -- a different credential with a different job.
 *
 * `POST /betcheck/free` is open (no bearer token) and caps an anonymous
 * visitor at three introductory Bet Checks FOR LIFE
 * (src/appstate/freechecks.py). The server mints an identity on the first
 * successful check and expects it back in `X-Free-Check-Token`; it never
 * sets a cookie, so storing it is the client's job. It is NOT an invite
 * token and is never sent as an Authorization bearer -- kept under its
 * own key so the two can never be confused for one another.
 */
export const FREE_CHECK_TOKEN_STORAGE_KEY = "aisportsanalysis.free_check_token";

export function getFreeCheckToken() {
  try {
    return window.localStorage.getItem(FREE_CHECK_TOKEN_STORAGE_KEY) || "";
  } catch (err) {
    return "";
  }
}

export function setFreeCheckToken(token) {
  if (!token) return;
  try {
    window.localStorage.setItem(FREE_CHECK_TOKEN_STORAGE_KEY, token);
  } catch (err) {
    // Storage unavailable: the visitor is treated as a first-time caller
    // on the next check. The server, not this client, owns the budget.
  }
}

/**
 * PUBLIC DEMO FLAG (2026-09-07). When GET /meta says `public_demo` is true
 * the server serves the read-only game surface and POST /betcheck with no
 * token (api/app.py APP_PUBLIC_DEMO). The client must then use the open
 * paid route rather than /betcheck/free: the free route is capped at three
 * checks FOR LIFE per anonymous identity, which would end a demo on the
 * fourth click. main.js sets this once at boot, before the first route
 * renders; views read it through isPublicDemo().
 */
let _publicDemo = false;

export function setPublicDemo(value) {
  _publicDemo = !!value;
}

export function isPublicDemo() {
  return _publicDemo;
}

/**
 * A structured API error, distinct from a network failure -- callers need
 * to tell "the server said no, here is why" (status + whatever `detail`
 * the API sent, per its documented structured-error shape) apart from
 * "the request never completed at all".
 */
export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

/**
 * GET/POST/DELETE against the API, with the bearer token attached
 * whenever one is stored. Never composes a customer-facing claim from the
 * response -- callers render API strings verbatim (see each view module).
 */
export async function apiFetch(path, options = {}) {
  const headers = Object.assign({}, options.headers || {});
  const token = getToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  if (options.body !== undefined && headers["Content-Type"] === undefined) {
    headers["Content-Type"] = "application/json";
  }
  // THE SAME SIGNAL COVERS THE BODY READ, not just the headers. A stalled
  // response that sends a status line and then stops would otherwise hang
  // on `response.text()` below with the headers already in hand -- the
  // spinner case again, one step further along.
  const timeoutMs = options.timeoutMs === undefined
    ? DEFAULT_TIMEOUT_MS : options.timeoutMs;
  const controller = typeof AbortController === "function"
    ? new AbortController() : null;
  let timedOut = false;
  let timer = null;
  if (controller && timeoutMs) {
    timer = setTimeout(() => { timedOut = true; controller.abort(); },
                       timeoutMs);
  }
  const init = Object.assign({}, options, { headers });
  delete init.timeoutMs;          // not a fetch option; would be ignored,
  if (controller) {               // but leaving it there invites confusion
    init.signal = controller.signal;
  }

  let response;
  try {
    response = await fetch(path, init);
  } catch (err) {
    if (timer) clearTimeout(timer);
    if (timedOut) {
      // `status: null` routes this to renderError's "network" branch, which
      // already says the right thing: could be your connection, could be an
      // outage, and it is NOT the server answering "no games".
      throw new ApiError(null, `no response after ${Math.round(timeoutMs / 1000)}`
        + "s — the service did not answer");
    }
    throw new ApiError(null, "network request failed: " + err.message);
  }
  let payload = null;
  let text;
  try {
    text = await response.text();
  } catch (err) {
    if (timedOut) {
      throw new ApiError(null, `no response after ${Math.round(timeoutMs / 1000)}`
        + "s — the service stopped mid-answer");
    }
    throw new ApiError(null, "network request failed: " + err.message);
  } finally {
    if (timer) clearTimeout(timer);
  }
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch (err) {
      payload = text;
    }
  }
  if (!response.ok) {
    const detail = payload && payload.detail !== undefined ? payload.detail : payload;
    throw new ApiError(response.status, detail);
  }
  return payload;
}

export function apiGet(path, options = {}) {
  return apiFetch(path, Object.assign({ method: "GET" }, options));
}

export function apiPost(path, body) {
  return apiFetch(path, { method: "POST", body: JSON.stringify(body) });
}

export function apiDelete(path) {
  return apiFetch(path, { method: "DELETE" });
}

/**
 * Fire-and-forget funnel-event beacon (POST /funnel/event, api/funnel.py --
 * public, allowlisted to `landing_view`/`signup_started`). Deliberately
 * NOT awaited by anything that cares about the result: a dropped analytics
 * beacon must never block or surface an error on the page it is measuring,
 * the same "never fail the request it rides along with" contract
 * src/appstate/events.py's record_event_safe gives server-side.
 */
export function trackFunnelEvent(kind, properties) {
  apiPost("/funnel/event", { kind, properties }).catch(() => {});
}
