/**
 * THE VERSIONS LIST AND "GO BACK TO THIS VERSION" (owner request 2026-10-28: "a way for users to undo an upgraded hound and revert").
 *
 *   GET  /hounds/{id}/versions   the owner's list: v1..vN, each with its status, when, why and its FORWARD record (never a rehearsal)
 *   POST /hounds/{id}/revert     {version_no, current_id, confirm: true}: makes the NEXT version with that version's rules
 *
 * Going back never reopens an old version: the server makes version n+1 with a copy of the chosen version's rules, retires the one it
 * leaves with its record intact, and the copy starts with an empty record. So the list only ever moves forward (v1, v2, v3 ...), the
 * button is "Go back to this version" and it asks once, in the row, before it sends anything. This file draws what the server answered and
 * works out nothing: every sentence, record and rule is the server's, text is always textContent, and the page never sends a rule set,
 * only a version number (and the id of the version the list was drawn on, so a stale list is refused in words).
 *
 * `undoBlock(result)` is the same button on the card a training leaves behind ("Undo (go back to version N)"): one tap, one confirmation.
 */

import { h, clearNode, isNum } from "./hounds-core.js";
import { get, post, errorText, errorCode } from "./dog-common.js";

const SLOW = 60000;

export const CONFIRM_TEXT = (name, versionNo) =>
  `Go back to version ${versionNo}? ${name} gets version ${versionNo}'s rules as its next version. The version it is on now keeps its record, `
  + "and the next version starts with an empty record.";

const button = (text, hook, kind, onClick, extra = {}) => h("button", Object.assign(
  { type: "button", class: `btn ${kind === "quiet" ? "btn--ghost" : "btn--primary"}`, "data-hook": hook, text, on: { click: onClick } }, extra));

/** "Jun 4, 2026" from an ISO time, or "" when it does not parse. */
export function whenText(iso) {
  const d = iso ? new Date(iso) : null;
  if (!d || Number.isNaN(d.getTime())) return "";
  try { return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }); } catch (err) { return String(iso).slice(0, 10); }
}

/** "3-2, +1.2 units (5 graded bets)" for a version's forward record, or the plain words for one with no bets. */
export function recordText(rec) {
  if (!rec || !isNum(rec.bets) || rec.bets === 0) return "No bets yet";
  const open = rec.open ? `, ${rec.open} open` : "";
  if (!rec.graded) return `${rec.bets} bet${rec.bets === 1 ? "" : "s"}, none settled yet`;
  const units = isNum(rec.units) ? `, ${rec.units > 0 ? "+" : ""}${rec.units} units` : "";
  return `${rec.wins}-${rec.losses}${rec.pushes ? `-${rec.pushes}` : ""}${units} (${rec.graded} graded bet${rec.graded === 1 ? "" : "s"}${open})`;
}

/**
 * The button that goes back, with its one confirmation inline. `go` is { id, name, toVersion, currentId, label, hook, onDone }.
 * Resolves nothing: it draws into the returned node and calls `onDone(result)` after the server made the version.
 */
export function goBackControl({ id, name, toVersion, currentId = null, label = "Go back to this version", hook = "version-go-back", onDone = null }) {
  const root = h("div", { class: "vs-go", "data-hook": `${hook}-box` });
  const start = () => {
    clearNode(root);
    root.appendChild(button(label, hook, "quiet", ask, { "aria-label": `${label}: version ${toVersion}` }));
  };
  const ask = () => {
    clearNode(root);
    const status = h("p", { class: "hd-fine rt-status", role: "status", "aria-live": "polite", "data-hook": `${hook}-status` });
    const yes = button("Go back", `${hook}-confirm`, "primary", async () => {
      yes.setAttribute("disabled", "");
      no.setAttribute("disabled", "");
      status.textContent = "Going back...";
      try {
        const result = await post(`/hounds/${encodeURIComponent(id)}/revert`,
          Object.assign({ version_no: toVersion, confirm: true }, currentId ? { current_id: currentId } : {}), SLOW);
        done(result);
      } catch (err) {
        status.textContent = "";
        clearNode(root);
        root.appendChild(h("p", { class: "rt-refused", role: "alert", "data-hook": `${hook}-refused`, "data-code": errorCode(err),
          text: errorText(err, `${name} could not go back just now. Nothing was changed.`) }));
        root.appendChild(button("Close", `${hook}-close`, "quiet", start));
      }
    });
    const no = button("Keep it as it is", `${hook}-cancel`, "quiet", start);
    root.appendChild(h("p", { class: "hd-muted", "data-hook": `${hook}-ask`, text: CONFIRM_TEXT(name, toVersion) }));
    root.appendChild(status);
    root.appendChild(h("div", { class: "rt-actions", "data-hook": "rites-actions" }, [no, yes]));
    if (no.focus) no.focus();
  };
  const done = (result) => {
    clearNode(root);
    const fresh = (result && result.new) || {};
    root.appendChild(h("p", { class: "rt-note", role: "status", "data-hook": `${hook}-done`, text: (result && result.headline) || `${name} went back.` }));
    root.appendChild(h("a", { class: "btn btn--ghost", href: fresh.page_href || `hound.html?id=${encodeURIComponent(fresh.id || id)}`,
      "data-hook": `${hook}-open`, text: `Open version ${fresh.version_no || ""}`.trim() }));
    if (onDone) onDone(result);
  };
  start();
  return root;
}

/** The Undo on the card a Fine-tune, a Full rebuild or a check-up leaves: null when the server did not offer one. */
export function undoBlock(result, { onDone = null } = {}) {
  const u = result && result.undo;
  const fresh = result && result.new;
  if (!u || !u.available || !fresh || !isNum(u.to_version)) return null;
  const name = (result.name || (result.headline || "").split(" is back")[0] || "The hound").trim();
  return h("div", { class: "vs-undo", "data-hook": "training-undo-block" }, [
    h("p", { class: "hd-fine", text: "Not what you wanted? You can go back." }),
    goBackControl({ id: fresh.id, name, toVersion: u.to_version, currentId: fresh.id, label: u.label || `Undo (go back to version ${u.to_version})`,
      hook: "training-undo", onDone })]);
}

function versionRow(v, ctx) {
  const rules = v.rule_text ? h("details", { class: "vs-rules", "data-hook": "version-rules" }, [
    h("summary", { text: "Its rules" }), h("p", { class: "hd-fine", text: v.rule_text })]) : null;
  const current = v.status === "current";
  return h("li", { class: "vs-row", "data-hook": "version", "data-version": String(v.version_no), "data-status": v.status }, [
    h("p", { class: "vs-row__head" }, [
      h("span", { class: "dk-chip", "data-hook": "version-no", text: `Version ${v.version_no}` }), " ",
      h("span", { class: `dk-chip ${current ? "dk-chip--good" : ""}`, "data-hook": "version-status",
        text: current ? (v.running ? "Current, running" : "Current") : "Earlier" })]),
    h("p", { class: "hd-fine", "data-hook": "version-when", text: [whenText(v.created_at), v.why].filter(Boolean).join(" · ") }),
    h("p", { class: "vs-row__record", "data-hook": "version-record", text: recordText(v.record) }),
    rules,
    v.can_go_back
      ? goBackControl({ id: ctx.id, name: ctx.name, toVersion: v.version_no, currentId: ctx.currentId, onDone: ctx.onChanged })
      : h("p", { class: "hd-fine", "data-hook": "version-cannot", text: v.cannot_reason || "" })]);
}

/**
 * Draw the Versions list into `host` for the owner of hound `id`. Resolves with the number of versions (0 on a refusal or when it cannot be
 * read, so the caller can keep its section hidden for a hound with a single version).
 */
export async function mountVersions(host, { id, name = "This hound", onChanged = null } = {}) {
  clearNode(host);
  let data;
  try {
    data = await get(`/hounds/${encodeURIComponent(id)}/versions`);
  } catch (err) {
    host.appendChild(h("p", { class: "hd-muted", "data-hook": "versions-error", "data-code": errorCode(err),
      text: errorText(err, "The versions could not be loaded just now. Nothing was changed.") }));
    return 0;
  }
  const list = Array.isArray(data && data.versions) ? data.versions : [];
  const ctx = { id, name: data.name || name, currentId: data.current && data.current.id, onChanged };
  host.appendChild(h("p", { class: "hd-muted", "data-hook": "versions-intro",
    text: "Every version it has been, oldest first. Going back makes the next version with the rules of the one you choose; no record is ever changed." }));
  host.appendChild(h("ol", { class: "vs-list", "data-hook": "versions-list" }, list.map((v) => versionRow(v, ctx))));
  if (data.honesty) host.appendChild(h("p", { class: "hd-fine", "data-hook": "versions-honesty", text: data.honesty }));
  return list.length;
}
