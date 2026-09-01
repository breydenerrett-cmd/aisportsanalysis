/**
 * Single source of truth for the product's working brand name.
 *
 * LINEHOUND is a working brand pending final legal/trademark clearance
 * (design/linehound-v1/HANDOFF_README.md) -- every page must be able to
 * pick up a rename by changing this one constant, never by hunting down
 * hardcoded "LINEHOUND" literals across web/*.html and web/js/*.js.
 * `<title>` tags stay static markup (they run before any script), but
 * every *visible* wordmark this design system renders should read from
 * BRAND_NAME rather than spelling the name out again.
 */

export const BRAND_NAME = "LINEHOUND";

/** Mounts the wordmark mark + text into `container` (expects the
 * `.wordmark` CSS component from css/nav.css). */
export function renderWordmark(container, text = BRAND_NAME) {
  container.innerHTML = "";
  container.classList.add("wordmark");
  const mark = document.createElement("span");
  mark.className = "wordmark__mark";
  const sheen = document.createElement("span");
  mark.appendChild(sheen);
  const label = document.createElement("span");
  label.className = "wordmark__text";
  label.textContent = text;
  container.appendChild(mark);
  container.appendChild(label);
}
