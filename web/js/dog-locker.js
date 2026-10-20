/**
 * The locker room: the character creator for a builder dog's owner (PUT /hounds/{id}/look).
 *
 * A look is a handful of CHOICES (art style, breed, coat, eyes, background, head piece, glasses, neck piece, body piece, jersey
 * number) from the fixed tables in dog-look.js, which the server holds to the same lists. The stage on top is the live preview: the
 * dog is redrawn by the hound rig (dog-rig.js) as you pick, springs a little on every choice, and can be shown in each of its
 * five expressions (idle, grin, snarl, focus, howl: a preview toggle, nothing is saved by it). Every option is a small dog wearing
 * it, so you pick by looking. THE STYLE (Mascot, Street or Elite) redraws the whole dog; THE BREED defaults to the one the dog's name
 * picks ("From the name") and any of the 33 breeds can replace it. "Randomize" rolls a whole outfit and keeps the breed;
 * "Save look" stores it on the dog's whole lineage, so a new version keeps it, and the dog howls when it lands. Cosmetic only: a
 * look changes no rule, no ticket and no record. The name and catchphrase are edited in the builder.
 */

import { h, clearNode } from "./hounds-core.js";
import { put, errorText, statusLine, builderHref, celebrate } from "./dog-common.js";
import { COATS, EYES, BACKGROUNDS, HEAD, FACE, NECK, BODY, DEFAULT_LOOK, cleanLook, randomLook, lookFor } from "./dog-look.js";
import { dogSvg, breedFor, breedLabel, cleanPose, POSES, BREEDS, STYLES, STYLE_LABELS, STYLE_BLURBS } from "./dog-rig.js";

const title = (key) => key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
/** The preview toggle's labels: the pose ids are the product's old words (data-pose), the label is the expression the pose draws. */
const POSE_LABEL = { idle: "Idle", happy: "Grin", sad: "Snarl", thinking: "Focus", celebrate: "Howl" };

const GROUPS = [
  { key: "style", label: "Style", kind: "style", options: STYLES },
  { key: "breed", label: "Breed", kind: "breed", options: ["auto", ...BREEDS] },
  { key: "coat", label: "Coat", kind: "swatch", options: Object.keys(COATS), color: (k) => COATS[k].base },
  { key: "eyes", label: "Eyes", kind: "swatch", options: Object.keys(EYES), color: (k) => EYES[k] },
  { key: "bg", label: "Backdrop", kind: "swatch", options: Object.keys(BACKGROUNDS), color: (k) => BACKGROUNDS[k][0] },
  { key: "head", label: "Head", kind: "thumb", options: HEAD },
  { key: "face", label: "Face", kind: "thumb", options: FACE },
  { key: "neck", label: "Neck", kind: "thumb", options: NECK },
  { key: "body", label: "Body", kind: "thumb", options: BODY },
];
const NECK_LABEL = { collar: "Spiked collar" };

/** A small spring on an element, only when the browser can animate and the visitor has not asked for less motion. */
function spring(el, frames, ms = 380) {
  try {
    if (!el || typeof el.animate !== "function") return;
    if (typeof window !== "undefined" && window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    el.animate(frames, { duration: ms, easing: "cubic-bezier(.34,1.56,.64,1)" });
  } catch (err) { /* no animation: the choice still happened */ }
}

export function mountLocker(section, { id, name, kit, vibe, onSaved, onChange }) {
  const body = section.querySelector("[data-hook='dog-locker']");
  if (!body) return;
  clearNode(body);
  const nameBreed = breedFor({ id, name, vibe });            // the breed the dog's name picks: what "From the name" means
  let look = cleanLook(kit.look || lookFor(id));            // an undressed dog starts from the look every page already shows it in
  let saved = JSON.stringify(look);
  let pose = "idle";
  let poseTimer = null;
  const shownBreed = () => (look.breed !== "auto" ? look.breed : nameBreed);

  const stageDog = h("div", { class: "dk-stage__dog", "data-hook": "locker-dog" });
  const poseBar = h("div", { class: "dk-posebar", role: "group", "aria-label": "Preview expression" });
  const poseButtons = POSES.map((p) => {
    const b = h("button", { type: "button", class: "dk-posebtn", "data-hook": "locker-pose", "data-pose": p, "aria-pressed": "false", text: POSE_LABEL[p] });
    b.addEventListener("click", () => { pose = p; redraw(false); spring(stageDog, [{ transform: "scale(.96)" }, { transform: "scale(1)" }], 260); });
    poseBar.appendChild(b);
    return b;
  });
  const random = h("button", { type: "button", class: "dk-dice", "data-hook": "locker-random", "aria-label": "Randomize the look" }, [
    h("span", { class: "dk-dice__icon", "aria-hidden": "true", text: "⚄" }), h("span", { text: "Randomize" })]);
  const dirty = h("span", { class: "dk-dirty", "data-hook": "locker-dirty", hidden: "", text: "Unsaved changes" });
  const breedName = h("strong", { text: breedLabel(shownBreed()) });
  const breedNote = h("span", { class: "hd-fine", text: "from the name" });
  const previewBox = h("div", { class: "dk-preview dk-stage", "data-hook": "locker-preview" }, [
    h("div", { class: "dk-stage__spot", "aria-hidden": "true" }), stageDog,
    h("div", { class: "dk-stage__bar" }, [
      h("p", { class: "dk-stage__breed", "data-hook": "locker-breed" }, [breedName, " ", breedNote]),
      dirty]),
    poseBar,
    random]);
  const status = statusLine("locker-status");
  const numberInput = h("input", { type: "number", min: "0", max: "99", step: "1", inputmode: "numeric", "data-hook": "locker-number",
    "aria-label": "Jersey number" });
  const numberRow = h("div", { class: "dk-field dk-field--number", hidden: "" }, [h("label", { text: "Jersey number" }), numberInput]);
  const groupBoxes = {};
  const thumbs = [];                                  // the little dogs on the options, redrawn in the current look
  const sampleOf = (key, opt) => cleanLook(Object.assign({}, look, { [key]: opt, number: key === "body" && opt === "jersey" ? 7 : look.number },
    // a breed reads best bare: the thumbnails in the breed grid wear the dog's coat, eyes and style but none of its accessories
    key === "breed" ? { head: "none", face: "none", neck: "none", body: "none", number: null } : {}));
  const thumbSize = { style: 72, breed: 46, thumb: 52 };
  const refreshThumbs = () => {
    for (const t of thumbs) { clearNode(t.el); t.el.appendChild(dogSvg(sampleOf(t.key, t.opt), { size: t.size, breed: nameBreed, pose: "idle" })); }
  };

  function redraw(announce = true) {
    clearNode(stageDog);
    stageDog.appendChild(dogSvg(look, { size: 200, breed: nameBreed, pose, label: `${name || "Dog"}'s badge`, decorative: false }));
    for (const g of GROUPS) {
      for (const b of groupBoxes[g.key].querySelectorAll("button")) {
        b.setAttribute("aria-pressed", b.getAttribute("data-value") === look[g.key] ? "true" : "false");
      }
    }
    poseButtons.forEach((b) => b.setAttribute("aria-pressed", b.getAttribute("data-pose") === pose ? "true" : "false"));
    breedName.textContent = breedLabel(shownBreed());
    breedNote.textContent = look.breed === "auto" ? "from the name" : "your pick";
    if (look.body === "jersey") numberRow.removeAttribute("hidden"); else numberRow.setAttribute("hidden", "");
    if (JSON.stringify(look) !== saved) dirty.removeAttribute("hidden"); else dirty.setAttribute("hidden", "");
    if (announce) refreshThumbs();
    if (announce && onChange) onChange(look);
  }
  const set = (key, value) => {
    look = cleanLook(Object.assign({}, look, { [key]: value }));
    if (key === "body" && value !== "jersey") look.number = null;
    redraw();
    spring(stageDog, [{ transform: "scale(.92) rotate(-2deg)" }, { transform: "scale(1.05) rotate(1deg)" }, { transform: "scale(1)" }]);
  };

  const optionLabel = (g, opt) => {
    if (g.key === "style") return STYLE_LABELS[opt];
    if (g.key === "breed") return opt === "auto" ? "From the name" : breedLabel(opt);
    if (g.key === "neck" && NECK_LABEL[opt]) return NECK_LABEL[opt];
    return title(opt);
  };

  const controls = h("div", { class: "dk-locker__controls" });
  for (const g of GROUPS) {
    const row = h("div", { class: `dk-optrow dk-optrow--${g.kind}`, "data-group": g.key });
    groupBoxes[g.key] = row;
    for (const opt of g.options) {
      const label = optionLabel(g, opt);
      const b = h("button", { type: "button", class: g.kind === "swatch" ? "dk-swatch" : `dk-opt dk-opt--thumb dk-opt--${g.kind}`, "data-hook": "locker-opt",
        "data-value": opt, "aria-pressed": "false", title: label, "aria-label": `${g.label}: ${label}` });
      if (g.kind === "swatch") b.setAttribute("style", `--swatch:${g.color(opt)}`);
      else {
        // the option is a small dog wearing it: pick by looking
        const holder = h("span", { class: "dk-opt__dog", "aria-hidden": "true" });
        thumbs.push({ el: holder, key: g.key, opt, size: thumbSize[g.kind] });
        b.appendChild(holder);
        b.appendChild(h("span", { class: "dk-opt__label", text: label }));
        if (g.kind === "style") b.appendChild(h("span", { class: "dk-opt__blurb", text: STYLE_BLURBS[opt] }));
      }
      b.addEventListener("click", () => { set(g.key, opt); spring(b, [{ transform: "scale(.88)" }, { transform: "scale(1.08)" }, { transform: "scale(1)" }], 320); });
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

  const save = h("button", { type: "button", class: "btn btn--primary dk-save", "data-hook": "locker-save", text: "Save look" });
  const reset = h("button", { type: "button", class: "btn btn--ghost", "data-hook": "locker-reset", text: "Start over" });
  const flash = (p, ms) => {
    pose = p; redraw(false);
    if (poseTimer && typeof clearTimeout === "function") clearTimeout(poseTimer);
    if (typeof setTimeout === "function") poseTimer = setTimeout(() => { pose = "idle"; redraw(false); }, ms);
  };
  save.addEventListener("click", async () => {
    save.setAttribute("disabled", "");
    status.textContent = "Saving...";
    flash("thinking", 4000);
    try {
      const out = await put(`/hounds/${encodeURIComponent(id)}/look`, { look });
      look = cleanLook(out.look);
      saved = JSON.stringify(look);
      status.textContent = "Saved. Your dog wears this look everywhere it appears.";
      save.textContent = "Saved";
      flash(cleanPose("celebrate"), 2200);
      celebrate(previewBox, "look");
      if (typeof setTimeout === "function") setTimeout(() => { save.textContent = "Save look"; }, 2600);
      if (onSaved) onSaved(look);
    } catch (err) {
      status.textContent = errorText(err);
      flash("sad", 2400);
    } finally {
      save.removeAttribute("disabled");
    }
  });
  reset.addEventListener("click", () => { look = cleanLook(DEFAULT_LOOK); redraw(); spring(stageDog, [{ transform: "scale(.9)" }, { transform: "scale(1)" }], 300); });
  random.addEventListener("click", () => {
    look = cleanLook(Object.assign(randomLook(), { breed: look.breed }));
    redraw();
    spring(stageDog, [{ transform: "rotate(-8deg) scale(.9)" }, { transform: "rotate(6deg) scale(1.07)" }, { transform: "rotate(0) scale(1)" }], 460);
  });

  body.appendChild(h("p", { class: "hd-muted", text: "Dress your dog. A look is cosmetic: it changes no rule, no ticket and no record." }));
  body.appendChild(h("div", { class: "dk-locker" }, [previewBox, controls]));
  body.appendChild(h("div", { class: "dk-actions dk-actions--sticky" }, [save, reset, status]));
  body.appendChild(h("p", { class: "hd-fine" }, ["The name and the catchphrase are changed in the builder. ",
    h("a", { href: builderHref(id, {}), "data-hook": "locker-builder", text: "Open the builder" }), "."]));
  if (look.number !== null) numberInput.value = String(look.number);
  redraw();
  section.removeAttribute("hidden");
}
