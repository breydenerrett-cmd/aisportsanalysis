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
  let response;
  try {
    response = await fetch(path, Object.assign({}, options, { headers }));
  } catch (err) {
    throw new ApiError(null, "network request failed: " + err.message);
  }
  let payload = null;
  const text = await response.text();
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

export function apiGet(path) {
  return apiFetch(path, { method: "GET" });
}

export function apiPost(path, body) {
  return apiFetch(path, { method: "POST", body: JSON.stringify(body) });
}

export function apiDelete(path) {
  return apiFetch(path, { method: "DELETE" });
}
