/**
 * The builder's markup as DOM, for the kennel studio's Rules tab (web/js/kennel.js). web/build-a-hound.html carries the
 * same structure as static HTML (so it is on that page with scripts off); web/js/hounds-build.js drives either one
 * through its data-hooks and never builds the page's frame itself. tests/test_kennel_page.py holds the two to the same
 * hook set, so a hook added to one cannot be forgotten in the other.
 *
 * `data-embedded` on the root tells the builder it lives inside the studio (it does not scroll the window to the top).
 */

import { h } from "./hounds-core.js";

export function builderSkeleton() {
  const hook = (name, extra = {}) => Object.assign({ "data-hook": name }, extra);
  return h("div", { class: "bd-embedded", "data-hook": "build-app", "data-embedded": "" }, [
    h("h3", { class: "bd-embedded__title", "data-hook": "build-title", text: "Build your hound" }),
    h("p", { class: "hd-fine", "data-hook": "build-from-note", hidden: true }),
    h("div", hook("build-gate", { class: "hd-state hd-state--missing", role: "status", hidden: true })),

    h("section", hook("step-describe", { class: "bd-step", "aria-label": "Describe your strategy" }), [
      h("p", { class: "bd-step__no", text: "1. Say it" }),
      h("label", { class: "bd-sr", for: "english-input", text: "Your strategy in plain English" }),
      h("textarea", hook("english-input", { id: "english-input", class: "bd-english", rows: "3", "aria-describedby": "english-count-note",
        placeholder: "e.g. Bet home underdogs between +120 and +200 on 2+ days rest. Max 2 bets a day." })),
      h("p", { class: "bd-countrow" }, [h("span", hook("english-count", { class: "hd-fine bd-count", id: "english-count-note", "aria-live": "polite", text: "0 / 600" }))]),
      h("p", hook("english-limit", { class: "bd-msg bd-msg--warn", role: "status", hidden: true })),
      h("div", hook("example-chips", { class: "bd-chips", role: "group", "aria-label": "Examples to start from" })),
      h("div", { class: "bd-actions" }, [
        h("button", hook("english-go", { type: "button", class: "btn btn--primary", text: "Read my strategy" })),
        h("button", hook("blank-rule", { type: "button", class: "btn btn--ghost", text: "Start from a blank rule" })),
        h("span", hook("english-status", { class: "hd-fine", role: "status", "aria-live": "polite" }))]),
      h("div", hook("english-read", { class: "bd-read", hidden: true }), [
        h("h4", { class: "hd-h3", text: "How I read it" }),
        h("ul", hook("english-understood", { class: "bd-list" })),
        h("div", hook("english-unread", { class: "bd-unread", hidden: true }), [
          h("h4", { class: "hd-h3", text: "What I could not read" }),
          h("ul", hook("english-notread", { class: "bd-list bd-list--warn" })),
          h("p", hook("english-translator", { class: "hd-fine bd-translator", role: "status", "aria-live": "polite" }))]),
        h("div", hook("english-suggestions", { class: "bd-suggest", hidden: true }), [
          h("h4", { class: "hd-h3", text: "Try saying it this way" }),
          h("ul", hook("english-suggest-list", { class: "bd-list" }))]),
        h("p", hook("english-assumed", { class: "hd-fine", hidden: true }))])]),

    h("section", hook("step-rules", { class: "bd-step", "aria-label": "What your hound will do" }), [
      h("p", { class: "bd-step__no", text: "2. Check it" }),
      h("div", hook("rules-empty", { class: "bd-empty" }), [h("p", { text: "Describe a strategy above, or start from a blank rule." })]),
      h("div", hook("rules-body", { hidden: true }), [
        h("div", hook("rule-sentences", { class: "bd-sentences", "aria-live": "polite" })),
        h("div", hook("build-problems", { class: "bd-problems", role: "alert", hidden: true })),
        h("details", hook("rules-advanced", { class: "bd-advanced" }), [
          h("summary", { text: "Edit rules" }),
          h("div", hook("rule-cards", { class: "bd-cards" })),
          h("p", {}, [h("button", hook("add-rule", { type: "button", class: "btn btn--ghost", text: "Add another rule" })),
            h("span", hook("rule-limit", { class: "hd-fine" }))]),
          h("fieldset", hook("globals", { class: "hd-fieldset bd-globals" }), [
            h("legend", { text: "For the whole hound" }),
            h("div", hook("globals-grid", { class: "bd-globals__grid" }))])])])]),

    h("section", hook("step-identity", { class: "bd-step", "aria-label": "Make it yours" }), [
      h("p", { class: "bd-step__no", text: "3. Name it" }),
      h("div", { class: "bd-identity" }, [
        h("div", { class: "bd-identity__fields" }, [
          h("div", { class: "hd-field" }, [h("label", { for: "f-name", text: "Name" }),
            h("input", hook("f-name", { id: "f-name", type: "text", maxlength: "24", autocomplete: "off" })),
            h("span", hook("name-count", { class: "hd-fine", text: "0 / 24" }))]),
          h("div", { class: "hd-field" }, [h("label", { for: "f-tagline", text: "Catchphrase" }),
            h("input", hook("f-tagline", { id: "f-tagline", type: "text", maxlength: "80", autocomplete: "off" })),
            h("span", hook("tagline-count", { class: "hd-fine", text: "0 / 80" }))]),
          h("fieldset", { class: "hd-fieldset" }, [h("legend", { text: "Colour" }),
            h("div", hook("color-picker", { class: "bd-swatches", role: "radiogroup", "aria-label": "Colour" }))]),
          h("fieldset", { class: "hd-fieldset" }, [h("legend", { text: "Badge" }),
            h("div", hook("badge-picker", { class: "bd-badges", role: "radiogroup", "aria-label": "Badge" }))])]),
        h("div", hook("build-dog-preview", { class: "bd-dogcard", "aria-label": "Your hound, so far" }), [
          h("div", hook("build-dog-card", { class: "bd-dogcard__body" }))])]),
      h("div", hook("diff", { class: "bd-diff", hidden: true }), [
        h("h4", { class: "hd-h3", text: "What changes if you save" }),
        h("ul", hook("diff-list", { class: "bd-list" })),
        h("p", hook("diff-note", { class: "hd-fine", text: "The old version keeps its record and stops betting. The new version starts fresh." }))]),
      h("div", hook("build-keep-host", { class: "bd-keep-host" })),
      h("div", hook("build-message", { "aria-live": "polite" })),
      h("div", hook("build-server-error", { class: "hd-state hd-state--down", role: "alert", hidden: true })),
      h("p", { class: "bd-save" }, [
        h("button", hook("build-submit", { type: "button", class: "btn btn--primary btn--lg", text: "Keep your hound" })),
        h("button", hook("edit-cancel", { type: "button", class: "btn btn--ghost", hidden: true, text: "Stop editing" })),
        h("span", hook("limit-text", { class: "hd-fine" })),
        h("span", hook("save-hint", { class: "hd-fine" }))])]),

    h("details", { class: "bd-advanced bd-advanced--preview" }, [
      h("summary", { text: "Would have bet today" }),
      h("section", hook("preview-panel", { class: "bd-preview" }), [
        h("p", hook("preview-count", { class: "bd-preview__count", "aria-live": "polite", text: "Nothing to preview yet." })),
        h("p", hook("preview-sub", { class: "hd-fine" })),
        h("p", hook("preview-retry-row", { class: "bd-preview__retry", hidden: true }), [
          h("button", hook("preview-retry", { type: "button", class: "btn btn--ghost", text: "Check again" }))]),
        h("ul", hook("preview-list", { class: "bd-picks" })),
        h("p", hook("preview-note", { class: "hd-fine", text: "A read-only look at today's board. It places nothing, and it is never counted." }))])]),

    // the builder keeps its own "my hounds" list; the studio shows the dogs itself, so these stay out of sight
    h("div", { hidden: true }, [h("p", hook("my-dogs-state")), h("ul", hook("my-dogs"))]),
    h("div", hook("preview-pill", { class: "bd-pill", role: "status", "aria-live": "off", hidden: true })),
  ]);
}
