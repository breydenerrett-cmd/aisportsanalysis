/**
 * Tabs, one small module for every page that has them (the dog page, the kennel studio, the leaderboard's two views).
 *
 *   <div role="tablist" data-autotabs data-param="tab">
 *     <button role="tab" data-tab="overview">Overview</button> ...
 *   </div>
 *   <div data-tabpanel="overview">...</div>  <div data-tabpanel="tickets" hidden>...</div>
 *
 * With scripts off every panel is simply visible. The chosen tab is remembered in the address (`?tab=`) so a link can
 * open one. A tab marked `data-optional` hides itself while its panel has nothing to show (every section inside is
 * `hidden`), which is how the dog page shows "Locker room" only to the owner. Arrow keys, Home and End move between
 * tabs. The panels fade in with CSS (css/lh.css), which is switched off for prefers-reduced-motion.
 */

const q = (root, sel) => Array.from(root.querySelectorAll(sel));

function panelHasContent(panel) {
  const kids = Array.from(panel.children || []);
  return kids.length === 0 ? false : kids.some((k) => !k.hasAttribute("hidden"));
}

export function mountTabs(list, { scope = document, onChange } = {}) {
  if (!list || list.getAttribute("data-mounted") === "1") return null;
  list.setAttribute("data-mounted", "1");
  const tabs = q(list, "[role='tab']");
  const panelOf = (key) => scope.querySelector(`[data-tabpanel='${key}']`);
  const param = list.getAttribute("data-param") || "tab";
  const keys = tabs.map((t) => t.getAttribute("data-tab"));

  const visible = (tab) => !tab.hasAttribute("hidden");
  let currentKey = null;
  const select = (key, { focus = false, push = true } = {}) => {
    if (!keys.includes(key)) key = keys.find((k) => visible(tabs[keys.indexOf(k)])) || keys[0];
    currentKey = key;
    tabs.forEach((tab) => {
      const on = tab.getAttribute("data-tab") === key;
      tab.setAttribute("aria-selected", on ? "true" : "false");
      tab.setAttribute("tabindex", on ? "0" : "-1");
      if (on && focus && tab.focus) tab.focus();
    });
    keys.forEach((k) => { const p = panelOf(k); if (p) { if (k === key) p.removeAttribute("hidden"); else p.setAttribute("hidden", ""); } });
    if (push) {
      try {
        const url = new URL(window.location.href);
        if (key === keys[0]) url.searchParams.delete(param); else url.searchParams.set(param, key);
        window.history.replaceState(null, "", url.pathname + (url.search || "") + url.hash);
      } catch (err) { /* a file:// page or a fake window: the tab still switched */ }
    }
    if (onChange) onChange(key);
    return key;
  };

  const sync = () => {
    tabs.forEach((tab) => {
      if (!tab.hasAttribute("data-optional")) return;
      const panel = panelOf(tab.getAttribute("data-tab"));
      // a panel that is hidden because it is not the active one still counts: look at its sections, not at itself
      const has = panel ? panelHasContent(panel) : false;
      if (has) tab.removeAttribute("hidden"); else tab.setAttribute("hidden", "");
    });
    const current = tabs.find((t) => t.getAttribute("aria-selected") === "true");
    if (current && !visible(current)) select(keys[0], { push: false });
  };

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => select(tab.getAttribute("data-tab")));
    tab.addEventListener("keydown", (evt) => {
      const shown = tabs.filter(visible);
      const at = shown.indexOf(tab);
      let next = null;
      if (evt.key === "ArrowRight") next = shown[(at + 1) % shown.length];
      else if (evt.key === "ArrowLeft") next = shown[(at - 1 + shown.length) % shown.length];
      else if (evt.key === "Home") next = shown[0];
      else if (evt.key === "End") next = shown[shown.length - 1];
      if (next) { if (evt.preventDefault) evt.preventDefault(); select(next.getAttribute("data-tab"), { focus: true }); }
    });
  });

  let start = null;
  try { start = new URLSearchParams(window.location.search).get(param); } catch (err) { start = null; }
  select(start || keys[0], { push: false });
  sync();
  if (typeof MutationObserver === "function") {
    const watch = new MutationObserver(sync);
    for (const k of keys) { const p = panelOf(k); if (p) watch.observe(p, { attributes: true, attributeFilter: ["hidden"], subtree: true, childList: true }); }
  }
  return { select, sync, keys, get current() { return currentKey; } };
}

if (typeof document !== "undefined" && document.querySelectorAll) {
  for (const list of document.querySelectorAll("[data-autotabs]")) mountTabs(list);
}
