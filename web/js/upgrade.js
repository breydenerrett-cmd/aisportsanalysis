/**
 * THE UPGRADE PROMPT: what a FREE account sees when the server refuses a paid dog tool.
 *
 * OWNER DECISION 2026-10-20. Free = one active dog. Members = up to five dogs, every sport, Live "send a dog",
 * Backtest and Ask. The server enforces it (api/entitlements.py, api/hounds_create.py): a refusal is a 402 with
 * `{error: "upgrade_required", feature, message}`. This module is the one place the pages turn that refusal
 * into words and a way forward, so Ask, Backtest, Live, the dog page and the builder cannot say different things.
 *
 * The pages key on `error` and `feature` and never on the sentence; the sentence shown is the server's own
 * `message` when it sent one. The prompt states what the plan is and links to the billing page, where the
 * price (the founding price while seats remain, from GET /billing/offer) is shown. It makes no claim about
 * results, profit or an edge.
 */

import { h, clearNode } from "./hounds-core.js";

export const UPGRADE_ERROR = "upgrade_required";
export const UPGRADE_HREF = "index.html#/billing";
export const UPGRADE_LABEL = "See the member plan";

/** Which tool was refused, for the heading. Unknown or missing falls back to a plain heading. */
const FEATURE_TITLES = {
  live_send: "Sending a dog at a live game is a member tool",
  backtest: "Backtest is a member tool",
  ask: "Ask is a member tool",
  more_dogs: "A free account keeps one dog",
};

export const FALLBACK_MESSAGE =
  "A free account keeps one dog. Members run up to five, in every sport, with Live, Backtest and Ask.";
export const FINE_PRINT = "Paper bets only. This is analysis, not advice. 21+.";

/** True for the server's "this needs the member plan" refusal. */
export function isUpgradeRefusal(err) {
  const detail = err && err.detail;
  return !!err && err.status === 402 && !!detail && typeof detail === "object" && detail.error === UPGRADE_ERROR;
}

/** The prompt node for a refusal: heading, the server's sentence, one link. */
export function upgradePrompt(err) {
  const detail = (err && err.detail) || {};
  const title = FEATURE_TITLES[detail.feature] || "That is part of the member plan";
  const message = typeof detail.message === "string" && detail.message ? detail.message : FALLBACK_MESSAGE;
  return h("div", { class: "upgrade-prompt", role: "status", "data-hook": "upgrade-prompt", "data-feature": detail.feature || "" }, [
    h("p", { class: "upgrade-prompt__title" }, [h("strong", { text: title })]),
    h("p", { class: "hd-muted upgrade-prompt__body", text: message }),
    h("p", {}, [h("a", { class: "btn btn--primary", href: UPGRADE_HREF, "data-hook": "upgrade-link", text: UPGRADE_LABEL })]),
    h("p", { class: "hd-fine", text: FINE_PRINT }),
  ]);
}

/**
 * If `err` is an upgrade refusal, replace `container`'s contents with the prompt and return true; otherwise
 * leave `container` alone and return false so the caller shows its usual error.
 */
export function showUpgrade(container, err) {
  if (!container || !isUpgradeRefusal(err)) return false;
  clearNode(container);
  container.appendChild(upgradePrompt(err));
  return true;
}
