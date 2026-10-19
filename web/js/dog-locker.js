/**
 * The locker room: the avatar studio for a builder dog's owner (PUT /hounds/{id}/look).
 *
 * A look is a handful of CHOICES (coat, eyes, background, head piece, glasses, chain, body piece, jersey number)
 * from the fixed tables in dog-avatar.js, which the server holds to the same lists. The preview redraws as you
 * pick; "Save look" stores it on the dog's whole lineage, so a new version keeps it. Cosmetic only: a look changes
 * no rule, no ticket and no record. The name and catchphrase are edited in the builder, and the panel links there.
 */

import { h, clearNode } from "./hounds-core.js";
import { put, errorText, statusLine, builderHref } from "./dog-common.js";
import { dogBadge, cleanLook, COATS, EYES, BACKGROUNDS, HEAD, FACE, NECK, BODY, DEFAULT_LOOK } from "./dog-avatar.js";

const title = (key) => key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

const GROUPS = [
  { key: "coat", label: "Coat", kind: "swatch", options: Object.keys(COATS), color: (k) => COATS[k].base },
  { key: "eyes", label: "Eyes", kind: "swatch", options: Object.keys(EYES), color: (k) => EYES[k] },
  { key: "bg", label: "Background", kind: "swatch", options: Object.keys(BACKGROUNDS), color: (k) => BACKGROUNDS[k][0] },
  { key: "head", label: "Head", kind: "text", options: HEAD },
  { key: "face", label: "Face", kind: "text", options: FACE },
  { key: "neck", label: "Neck", kind: "text", options: NECK },
  { key: "body", label: "Body", kind: "text", options: BODY },
];

export function mountLocker(section, { id, name, kit, onSaved, onChange }) {
  const body = section.querySelector("[data-hook='dog-locker']");
  if (!body) return;
  clearNode(body);
  let look = cleanLook(kit.look || DEFAULT_LOOK);
  const previewBox = h("div", { class: "dk-preview", "data-hook": "locker-preview" });
  const status = statusLine("locker-status");
  const numberInput = h("input", { type: "number", min: "0", max: "99", step: "1", inputmode: "numeric", "data-hook": "locker-number",
    "aria-label": "Jersey number" });
  const numberRow = h("div", { class: "dk-field", hidden: "" }, [h("label", { text: "Jersey number" }), numberInput]);
  const groupBoxes = {};

  const redraw = () => {
    clearNode(previewBox);
    previewBox.appendChild(dogBadge(look, { size: 148, label: `${name || "Dog"}'s badge`, decorative: false }));
    for (const g of GROUPS) {
      for (const b of groupBoxes[g.key].querySelectorAll("button")) {
        b.setAttribute("aria-pressed", b.getAttribute("data-value") === look[g.key] ? "true" : "false");
      }
    }
    if (look.body === "jersey") numberRow.removeAttribute("hidden"); else numberRow.setAttribute("hidden", "");
    if (onChange) onChange(look);
  };
  const set = (key, value) => {
    look = cleanLook(Object.assign({}, look, { [key]: value }));
    if (key === "body" && value !== "jersey") look.number = null;
    redraw();
  };

  const controls = h("div", { class: "dk-locker__controls" });
  for (const g of GROUPS) {
    const row = h("div", { class: `dk-optrow dk-optrow--${g.kind}`, "data-group": g.key });
    groupBoxes[g.key] = row;
    for (const opt of g.options) {
      const b = h("button", { type: "button", class: g.kind === "swatch" ? "dk-swatch" : "dk-opt", "data-hook": "locker-opt",
        "data-value": opt, "aria-pressed": "false", title: title(opt), "aria-label": `${g.label}: ${title(opt)}` });
      if (g.kind === "swatch") b.setAttribute("style", `--swatch:${g.color(opt)}`); else b.textContent = title(opt);
      b.addEventListener("click", () => { set(g.key, opt); });
      row.appendChild(b);
    }
    controls.appendChild(h("fieldset", { class: "hd-fieldset dk-fieldset" }, [h("legend", { text: g.label }), row]));
  }
  numberInput.addEventListener("input", () => {
    const raw = numberInput.value;
    look = cleanLook(Object.assign({}, look, { number: raw === "" ? null : Number(raw) }));
    redraw();
  });
  controls.appendChild(numberRow);

  const save = h("button", { type: "button", class: "btn btn--primary", "data-hook": "locker-save", text: "Save look" });
  const reset = h("button", { type: "button", class: "btn btn--ghost", "data-hook": "locker-reset", text: "Start over" });
  save.addEventListener("click", async () => {
    save.setAttribute("disabled", "");
    status.textContent = "Saving...";
    try {
      const out = await put(`/hounds/${encodeURIComponent(id)}/look`, { look });
      look = cleanLook(out.look);
      status.textContent = "Saved. Your dog wears this look everywhere it appears.";
      if (onSaved) onSaved(look);
    } catch (err) {
      status.textContent = errorText(err);
    } finally {
      save.removeAttribute("disabled");
    }
  });
  reset.addEventListener("click", () => { look = cleanLook(DEFAULT_LOOK); redraw(); });

  body.appendChild(h("p", { class: "hd-muted", text: "Dress your dog. A look is cosmetic: it changes no rule, no ticket and no record." }));
  body.appendChild(h("div", { class: "dk-locker" }, [previewBox, controls]));
  body.appendChild(h("div", { class: "dk-actions" }, [save, reset, status]));
  body.appendChild(h("p", { class: "hd-fine" }, ["The name and the catchphrase are changed in the builder. ",
    h("a", { href: builderHref(id, {}), "data-hook": "locker-builder", text: "Open the builder" }), "."]));
  if (look.number !== null) numberInput.value = String(look.number);
  redraw();
  section.removeAttribute("hidden");
}
