/**
 * Table cell labels, so a wide table can read as stacked cards on a phone (web/css/member-screens.css,
 * "tables as cards"). A table's header text is copied onto each of its body cells as `data-label`, and the
 * table is marked `data-stackable`; the stylesheet does the rest under 640px. Nothing about the table's own
 * markup, text or behaviour changes, and above 640px the attributes are inert.
 *
 * The views build their tables after an await, so this watches the outlet and labels whatever lands in it.
 * No timers: the observer callback is the only trigger.
 */

const TABLE_SELECTOR = "table.ov2-table, table.board-table, table.gav-board__table, table.an-rec__table, table.ps-table, table.acct-table";

export function labelTable(table) {
  const heads = Array.from(table.querySelectorAll("thead th")).map((th) => (th.textContent || "").trim());
  if (!heads.length) return;
  for (const row of table.querySelectorAll("tbody tr")) {
    Array.from(row.children).forEach((cell, index) => {
      if (cell.tagName === "TD" && !cell.hasAttribute("data-label") && heads[index]) {
        cell.setAttribute("data-label", heads[index]);
      }
    });
  }
  table.setAttribute("data-stackable", "true");
}

export function labelTables(root) {
  if (!root || typeof root.querySelectorAll !== "function") return;
  for (const table of root.querySelectorAll(TABLE_SELECTOR)) labelTable(table);
}

/** Label every table now and as the outlet fills. A no-op where there is no MutationObserver (a test harness). */
export function watchTables(root) {
  if (!root || typeof MutationObserver === "undefined") return;
  labelTables(root);
  new MutationObserver(() => labelTables(root)).observe(root, { childList: true, subtree: true });
}
