/**
 * "⭐ Follow": the dogs this browser follows, kept in localStorage.
 *
 * NO ACCOUNT, NO SERVER. A follow is a convenience for one browser: the dog page's star button writes the
 * id here and the kennel page pins followed dogs on top and offers a "My dogs ⭐" filter. Nothing is sent
 * anywhere, so there is nothing to leak and nothing to sign in for.
 *
 * STORAGE MAY THROW (private windows, blocked site data, a full quota, the accessor itself). Every read and
 * write is in try/catch, and the follows also live in memory for the life of the page, so the star still
 * works for the visit and the page never breaks; it just does not remember next time.
 */

export const FOLLOW_KEY = "linehound.followed_dogs";
export const MAX_FOLLOWED = 100;       // a sanity cap on a value a stranger's browser may hand back

const memory = new Set();
let loaded = false;

function storage() {
  try {
    return typeof window !== "undefined" && window.localStorage ? window.localStorage : null;
  } catch (err) {
    return null;
  }
}

/** Ids from storage (a JSON array of strings), merged into memory once. Junk is ignored, never thrown on. */
function load() {
  if (loaded) return;
  loaded = true;
  try {
    const store = storage();
    const raw = store ? store.getItem(FOLLOW_KEY) : null;
    const list = raw ? JSON.parse(raw) : [];
    if (Array.isArray(list)) {
      for (const id of list.slice(0, MAX_FOLLOWED)) if (typeof id === "string" && id) memory.add(id);
    }
  } catch (err) { /* unreadable or blocked: start empty */ }
}

function save() {
  try {
    const store = storage();
    if (!store) return false;
    store.setItem(FOLLOW_KEY, JSON.stringify([...memory].slice(0, MAX_FOLLOWED)));
    return true;
  } catch (err) {
    return false;       // the follow still holds for this visit
  }
}

export function followedIds() {
  load();
  return new Set(memory);
}

export function isFollowed(id) {
  load();
  return memory.has(String(id));
}

/** Follow or unfollow; returns the new state. `saved` on the result says whether it will be there next visit. */
export function toggleFollow(id) {
  load();
  const key = String(id);
  const now = !memory.has(key);
  if (now) memory.add(key); else memory.delete(key);
  const saved = save();
  return { followed: now, saved };
}

/** Test seam: forget what was loaded (a harness reloads the module per run, a unit test may not). */
export function resetFollowCache() {
  memory.clear();
  loaded = false;
}

/** Followed dogs first, everyone else after, each group in the order it came in. */
export function pinFollowed(hounds, followed) {
  const set = followed || followedIds();
  const mine = [], rest = [];
  for (const x of hounds || []) (set.has(String(x && x.id)) ? mine : rest).push(x);
  return mine.concat(rest);
}
