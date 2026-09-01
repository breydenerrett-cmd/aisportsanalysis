/**
 * Shared entrance/parallax/chart-draw engine for the LINEHOUND v1 design
 * system (handoff section 08, "named, measured, reducible"). Foundation
 * for every screen, not just Landing -- phase 2 (Gameday, Bet Check,
 * Games, Odds, Bets) imports the same module rather than re-implementing
 * IntersectionObserver plumbing per page.
 *
 * FAIL-SAFE REVEALS (non-negotiable, handoff section 08 + 12)
 * -------------------------------------------------------------------
 * Content marked [data-rise]/[data-tile]/[data-price] is visible by
 * default (see css/base.css). This module's only job on arm() is to add
 * .g-armed -- so if this script never runs (blocked, errors, disabled),
 * the page still renders complete and static. Only *after* arming does
 * an element go transparent, and only until its own entrance fires.
 *
 * PREFERS-REDUCED-MOTION (mandatory)
 * -------------------------------------------------------------------
 * When the media query matches, this module does not arm anything, does
 * not install parallax, and does not run the beat-pulse interval -- the
 * script branches before binding, per handoff section 08's reduced-motion
 * table. base.css's own reduced-motion block is the second, CSS-only
 * line of defense if a future call site forgets to check this.
 */

const REDUCED_MOTION = typeof window !== "undefined" && window.matchMedia
  ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
  : false;

/** Arms every [data-rise]/[data-tile]/[data-price] element in `root` for
 * IntersectionObserver-driven entrance, honoring each element's
 * `data-delay` (ms) as a transition-delay. No-ops entirely under reduced
 * motion, per the mandatory table above. */
export function armEntrances(root = document) {
  if (REDUCED_MOTION) return;
  const targets = root.querySelectorAll("[data-rise], [data-tile], [data-price]");
  if (!targets.length) return;
  const observer = new IntersectionObserver(
    (entries, obs) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add("g-in");
        obs.unobserve(entry.target);
      }
    },
    { threshold: .15, rootMargin: "0px 0px -10% 0px" }
  );
  for (const el of targets) {
    el.classList.add("g-armed");
    const delay = el.getAttribute("data-delay");
    if (delay) el.style.transitionDelay = `${delay}ms`;
    observer.observe(el);
  }
  return observer;
}

/** Installs the rAF-throttled hero-seam parallax on every
 * [data-parallax] element in `root`. No-ops under reduced motion. */
export function armParallax(root = document) {
  if (REDUCED_MOTION) return;
  const targets = Array.from(root.querySelectorAll("[data-parallax]"));
  if (!targets.length) return;
  let ticking = false;
  const update = () => {
    const y = window.scrollY || window.pageYOffset || 0;
    for (const el of targets) {
      const factor = parseFloat(el.getAttribute("data-parallax")) || 0;
      el.style.transform = `translate3d(0, ${(y * factor).toFixed(2)}px, 0)`;
    }
    ticking = false;
  };
  window.addEventListener(
    "scroll",
    () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(update);
    },
    { passive: true }
  );
}

/** Measures every [data-chart] SVG path's real length into --gdash so
 * the stroke-dashoffset draw-in animation is exact at any width, per
 * handoff section 08 ("do not hardcode dash lengths"). Under reduced
 * motion, paths are simply set to their final drawn state. */
export function armCharts(root = document) {
  const paths = root.querySelectorAll("[data-chart] path.chart-stroke");
  for (const path of paths) {
    let length = 0;
    try {
      length = path.getTotalLength();
    } catch (err) {
      continue;
    }
    path.style.setProperty("--gdash", String(length));
    if (REDUCED_MOTION) {
      path.style.strokeDashoffset = "0";
    }
  }
}

/** Fires a one-shot [data-beat] pulse (price-change emphasis) on `el`.
 * A no-op under reduced motion -- the figure still updates, it just
 * doesn't animate the update. */
export function beat(el) {
  if (!el || REDUCED_MOTION) return;
  el.classList.remove("g-beat");
  // Force reflow so re-adding the class restarts the animation.
  void el.offsetWidth;
  el.classList.add("g-beat");
}

export const reducedMotion = REDUCED_MOTION;
