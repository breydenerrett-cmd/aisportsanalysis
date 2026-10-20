/**
 * The member app's sign-in wall and its other gates get a face: a dog in the thinking pose above the first line, so the one screen a
 * visitor meets before signing in has a character instead of an empty box (design system v2, 2026-10-19). It only decorates: it adds
 * one decorative element to a `.gate` the app already drew and never reads or changes what the gate says or does. Gates arrive as the
 * router draws each view, so a MutationObserver decorates each new one once.
 */

import { dogBadge, DEFAULT_LOOK } from "./dog-avatar.js";

export function decorateGates(root = document) {
  let added = 0;
  for (const gate of root.querySelectorAll ? root.querySelectorAll(".gate:not([data-dog])") : []) {
    gate.setAttribute("data-dog", "1");
    const holder = document.createElement("div");
    holder.setAttribute("class", "gate__dog");
    holder.setAttribute("aria-hidden", "true");
    holder.appendChild(dogBadge(DEFAULT_LOOK, { size: 88, mood: "thinking", id: "gate" }));
    gate.insertBefore(holder, gate.firstChild);
    added += 1;
  }
  return added;
}

if (typeof document !== "undefined" && document.body) {
  decorateGates(document);
  if (typeof MutationObserver === "function") new MutationObserver(() => decorateGates(document)).observe(document.body, { childList: true, subtree: true });
}
