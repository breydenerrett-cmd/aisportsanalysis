/**
 * Whose kennel a hound lives in, as a label and a link (owner ruling 2026-10-20, kennel-first).
 *
 * A member's hound lives in that member's kennel (their own kennel name once set, else "Handler 3F2A's kennel"), which opens
 * web/kennel.html?u=<handle>. Every house hound (the pack the product runs itself, including its baselines) lives in the one
 * house kennel, labelled "LINEHOUND kennel", which opens the leaderboard filtered to it. Nothing here reaches the network.
 */

import { kennelHref, kennelName } from "./hounds-core.js";

export const HOUSE_KENNEL = "LINEHOUND kennel";
export const HOUSE_KENNEL_HREF = "hounds.html?scope=house";

/** { text, href, house } for a hound summary. A member's hound with no owner label is "A member's kennel", never the house one. */
export function kennelLabel(hound) {
  const d = hound || {};
  if (d.kind === "user") {
    return { text: kennelName(d.owner_display), href: kennelHref(d.owner_display), house: false };
  }
  return { text: HOUSE_KENNEL, href: HOUSE_KENNEL_HREF, house: true };
}
