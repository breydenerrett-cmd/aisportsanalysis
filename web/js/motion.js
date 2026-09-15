/**
 * Shared entrance/parallax/chart-draw engine -- kept as a module, with
 * every export it has ever had, but every export now arms nothing.
 *
 * WHY THIS FILE STILL EXISTS AT ALL (R_MOTION, DESIGN_SYSTEM.md section
 * 8, "Idle motion — an explicit removal list")
 * -------------------------------------------------------------------
 * "Nothing on the page moves unless the visitor did something or new
 * data arrived" -- and the ONLY motion the redesign keeps anywhere in
 * the app is the news banner's 150ms item swap and a disclosure's open/
 * close, both handled elsewhere (news.js, layout.js's `disclosure()`).
 * No entrance animation, no scroll-linked parallax, no chart draw-in and
 * no price-change pulse survive that list, so every function this
 * module exports below is now a no-op.
 *
 * `landing.js` still calls `armEntrances`/`armParallax`/`armCharts`, and
 * `landing-live.js` still calls `beat` -- rewiring every call site is
 * landing's own group's work, not foundation's, and DESIGN_SYSTEM.md's
 * own "Corrections applied" section is explicit that this module "keeps
 * every export ... since landing.js still calls them" but "arms
 * nothing." Deleting the exports here would break landing's import
 * before landing's own pass ever runs; keeping them as inert functions
 * means every existing call site keeps working, and every element it
 * touches renders directly in its final visible state instead of
 * starting hidden/offset and waiting for a script to reveal it.
 *
 * THIS IS SAFE BECAUSE OF HOW THE CSS WAS ALREADY WRITTEN
 * -------------------------------------------------------------------
 * `[data-rise], [data-tile], [data-price] { opacity: 1; }` in base.css
 * is the fail-safe default this module's own original docstring
 * described: an element marked for entrance motion is visible UNLESS a
 * script adds `.g-armed` to it first. Never adding `.g-armed` --
 * `armEntrances` below never does -- means every one of those elements
 * simply renders at its final, visible state, exactly as intended.
 * `landing.css`'s `[data-chart] .chart-stroke` rule reads
 * `stroke-dasharray: var(--gdash, 0); stroke-dashoffset: var(--gdash,
 * 0);` -- with `--gdash` never set (armCharts below never sets it), a
 * zero-length dash array renders as a solid, fully-drawn line, not a
 * hidden one. No CSS edit was required to make either primitive inert.
 *
 * `prefers-reduced-motion: reduce` removed every remaining transition
 * regardless (base.css's own reduced-motion block) even before this
 * pass; this module now behaves the same way for every visitor, not
 * only the ones who asked for it.
 */

/**
 * Whether the visitor's OS/browser asked for reduced motion. Kept and
 * still computed -- a caller may still want to know the visitor's own
 * preference for something unrelated to entrance/parallax/chart motion
 * -- but no function below reads it to decide whether to arm anything,
 * because none of them arm anything any more.
 */
export const reducedMotion = typeof window !== "undefined" && window.matchMedia
  ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
  : false;

/**
 * Used to mark every [data-rise]/[data-tile]/[data-price] element in
 * `root` for an IntersectionObserver-driven entrance. Now a deliberate
 * no-op: base.css already renders those elements at opacity 1 by
 * default, and never adding `.g-armed` here keeps them there. Kept
 * (rather than deleted) only so `landing.js`'s existing call does not
 * throw before landing's own pass removes it.
 */
export function armEntrances(_root = document) {
  return undefined;
}

/**
 * Used to install a scroll-linked parallax transform on every
 * [data-parallax] element in `root`. Now a deliberate no-op -- no
 * scroll listener is attached, so no element moves as the visitor
 * scrolls. Kept only so existing callers do not throw.
 */
export function armParallax(_root = document) {
  return undefined;
}

/**
 * Used to measure each [data-chart] path's length into --gdash for a
 * stroke-draw-in animation. Now a deliberate no-op -- `--gdash` is never
 * set, so `landing.css`'s own `var(--gdash, 0)` fallback renders every
 * chart line solid and fully drawn from the start, with no animation.
 * Kept only so existing callers do not throw.
 */
export function armCharts(_root = document) {
  return undefined;
}

/**
 * Used to fire a one-shot [data-beat] pulse (price-change emphasis) on
 * `el`. Now a deliberate no-op: DESIGN_SYSTEM.md section 8 names the
 * news banner's item swap and a disclosure's open/close as the only
 * motion anywhere in the app, and a price-change pulse is neither -- the
 * figure itself still updates wherever it is re-rendered, it simply no
 * longer animates the update. Kept only so `landing-live.js`'s existing
 * call does not throw.
 */
export function beat(_el) {
  return undefined;
}
