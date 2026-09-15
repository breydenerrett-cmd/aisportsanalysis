/**
 * Sport selection and routing.
 *
 * WHY THIS EXISTS
 * ---------------------------------------------------------------
 * The app serves both MLB (the original, default) and NFL cards.
 * Routing distinguishes them by a leading segment in the hash:
 * #/nfl/today routes to the NFL card, #/today routes to MLB.
 * This module extracts that segment and provides the sport switcher
 * nav component.
 */

export const SPORT_LABELS = {
  mlb: "MLB",
  nfl: "NFL",
  tennis: "Tennis",
};

export const NFL_NOTICE = "Experimental selections. Performance is still being evaluated.";

/**
 * Parse the hash to extract sport and segments.
 *
 * A leading segment "nfl" or "tennis" selects that sport and is removed
 * from segments; otherwise sport defaults to "mlb" and segments are unchanged.
 * Returns { sport, segments } where sport is "mlb"|"nfl"|"tennis" and
 * segments is the remaining path array.
 */
export function parseSport(hash) {
  const segments = hash || [];
  if (segments.length === 0) {
    return { sport: "mlb", segments };
  }
  const first = segments[0];
  if (first === "nfl" || first === "tennis") {
    return { sport: first, segments: segments.slice(1) };
  }
  return { sport: "mlb", segments };
}

/**
 * Render the sport switcher navigation component.
 *
 * Three small links (MLB, NFL, Tennis) plus a fourth "Live" link, showing
 * which is active. Mounts into host element.
 */
export function renderSportSwitcher(host, activeSport) {
  const nav = document.createElement("nav");
  nav.className = "sport-switcher";

  const sports = [
    { sport: "mlb", label: "MLB", href: "#/today" },
    { sport: "nfl", label: "NFL", href: "#/nfl/today" },
    { sport: "tennis", label: "Tennis", href: "#/tennis/board" },
  ];

  for (const { sport, label, href } of sports) {
    const a = document.createElement("a");
    a.href = href;
    a.className = "sport-switcher__link";
    a.textContent = label;
    if (sport === activeSport) {
      a.setAttribute("aria-current", "page");
    }
    nav.appendChild(a);
  }

  // Live link (visually quieter)
  const liveLink = document.createElement("a");
  liveLink.href = "#/live";
  liveLink.className = "sport-switcher__link sport-switcher__link--quiet";
  liveLink.textContent = "Live";
  if (activeSport === "live") {
    liveLink.setAttribute("aria-current", "page");
  }
  nav.appendChild(liveLink);

  // Clear and append
  while (host.firstChild) host.removeChild(host.firstChild);
  host.appendChild(nav);
}
