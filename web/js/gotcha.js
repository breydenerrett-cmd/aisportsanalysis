/**
 * GOTCHA -- a rickroll, for Jacob, from Brey.
 *
 * WHAT THIS IS
 * -------------------------------------------------------------------
 * A joke takeover. Jacob has spent two days reading this product's
 * pathologically honest copy -- "no demonstrated edge", "nothing clears
 * the bar", "we never say bet it", an entire test suite
 * (tests/test_customer_language.py) whose job is to fail the build if any
 * of it ever slips. So the funny version is LINEHOUND appearing to snap:
 * a maximum-conviction alert written in every single phrase this codebase
 * forbids, an unlock sequence that says it is disabling the honesty
 * module, and then Rick.
 *
 * HOW IT IS TRIGGERED, AND WHY IT CANNOT GO OFF BY ACCIDENT
 * -------------------------------------------------------------------
 * ONE way in: the hash is exactly `#/rollins-rickold` (GOTCHA_ROUTE).
 * Nothing else reaches this module -- no timer, no random roll, no "nth
 * visitor", no stored flag that could re-fire on a later visit, no
 * user-agent or IP sniffing. Any other hash and `maybeGotcha()` returns
 * false, having touched nothing; this file may as well not exist.
 *
 * A SLUG, NOT A QUERY PARAMETER. It was `?gotcha=jacob` first, which gave
 * the whole thing away in the URL bar before he had finished reading it.
 * A scouting-report slug for a player who does not exist reads like every
 * other deep link in this app (`#/game/...`, `#/day/...`, `#/odds/...`),
 * so the con survives being looked at -- which is the only property that
 * matters in a prank whose entire audience is one person who will
 * absolutely look.
 *
 * That matters more than the joke does. Founding-beta outreach starts
 * this week; a stranger's first impression of this product cannot be an
 * undismissable interstitial. The trigger is a link Brey chooses to send
 * to one person who is in on it -- not something that happens TO anybody.
 *
 * IT IS ALSO ALWAYS ESCAPABLE. The dismiss button dodges twice for the
 * bit and then works. Escape works from the reveal onward. Reloading
 * without the parameter clears it, because nothing is persisted.
 *
 * HOW TO DELETE IT
 * -------------------------------------------------------------------
 * `git rm web/js/gotcha.js web/css/gotcha.css tests/test_gotcha.py`,
 * drop the `maybeGotcha` import and call in web/js/main.js, and drop the
 * stylesheet link in web/index.html. Nothing else references it. It is
 * deliberately self-contained so removing it can never break a real
 * surface.
 *
 * A NOTE ON THE VOCABULARY IN HERE
 * -------------------------------------------------------------------
 * This file says "GUARANTEED", "LOCK OF THE DAY", "+EV", "FREE MONEY"
 * and prints a fake win probability -- every one of which
 * tests/test_customer_language.py bans outright, on purpose, because
 * they are the exact claims this product refuses to make. That is the
 * whole joke, and it is why tests/test_gotcha.py exists: the scanner
 * skips this ONE file by name, and in exchange there are tests pinning
 * that it can never render without the token. The guard is not weakened;
 * it is narrowed to one file that cannot reach a customer.
 */

/**
 * The route: a scouting-report slug for a player who does not exist.
 *
 * `?gotcha=jacob` was the first version and it announced itself in the URL
 * bar before he had finished reading it. `/rollins-rickold` was the second
 * and it is better, but "rick" is still sitting right there in the address
 * bar of a link whose entire audience is one suspicious person.
 *
 * So: a plain surname-initial slug of the same shape as every other deep
 * link in this app (`#/game/...`, `#/day/...`, `#/odds/...`), with no
 * rickroll signal in it at all. It reads as a player report, which is
 * exactly what he will expect a betting product to have.
 *
 * Matched against the hash PATH, exactly, after stripping any query. An
 * unknown hash otherwise falls through to Today (web/js/main.js), so this
 * slug is invisible unless it is opened exactly.
 */
const GOTCHA_ROUTE = "/scout/hollins-t";

/* The video. Yes, that one. nocookie host so it sets nothing.
 *
 * MUTED autoplay, deliberately. `autoplay=1` alone is refused by every
 * modern browser unless the video is also muted -- so the first live run
 * fell all the way back to a YouTube thumbnail with a play button, which
 * is a rickroll that has to be accepted rather than one that happens to
 * you. Muted autoplay is always permitted, so Rick is MOVING the instant
 * the reveal lands, and the sound button below turns it up in one tap.
 *
 * `playsinline=1` matters more than it looks: without it iOS Safari
 * hijacks the video into its own fullscreen player, which throws away the
 * whole surrounding joke. `enablejsapi=1` is what lets the sound button
 * postMessage an unMute command to the frame. */
const RICK = "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"
  + "?autoplay=1&mute=1&playsinline=1&enablejsapi=1&rel=0&modestbranding=1"
  + "&controls=1&loop=1&playlist=dQw4w9WgXcQ";

/* The unlock sequence. Timed to be just slow enough to be believed. */
const UNLOCK_LINES = [
  "AUTHENTICATING PRIVILEGED SESSION ................ OK",
  "SUBJECT IDENTIFIED: JACOB ........................ OK",
  "BYPASSING EVIDENCE THRESHOLD ..................... OK",
  "OVERRIDING FALSIFICATION BATTERY ................. OK",
  "SUPPRESSING COUNTERARGUMENT ENGINE ............... OK",
  "DISABLING HONESTY MODULE ......................... OK",
  "RECALIBRATING 40 PRE-REGISTERED HYPOTHESES ....... OK",
  "PROMOTING 1 STRATEGY ............................. OK",
  "DECRYPTING MAXIMUM CONVICTION PICK ...............",
];

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) node.appendChild(child);
  return node;
}

/** The hash path, normalised: no leading '#', no query, no trailing slash,
 *  lowercased. `#/Rollins-Rickold/` and `#/rollins-rickold?x=1` both reach
 *  the joke; `#/rollins-rickoldxyz` does not. */
function routeFromLocation() {
  let hash = (window.location.hash || "").replace(/^#/, "");
  const q = hash.indexOf("?");
  if (q !== -1) hash = hash.slice(0, q);
  hash = hash.replace(/\/+$/, "").toLowerCase();
  return hash || "/";
}

/* ---------------------------------------------------------------------
 * Act 1 -- the alert. Straight-faced, in the product's own visual
 * language, saying everything the product spends its life refusing to.
 * ------------------------------------------------------------------- */

function actOne(stage, onProceed) {
  const card = el("div", { class: "gotcha-card", "data-hook": "gotcha-alert" });

  card.appendChild(el("div", { class: "gotcha-siren" }, [
    el("span", { class: "gotcha-siren__dot" }),
    el("span", { class: "gotcha-siren__label",
      text: "PRIORITY ALERT · SUBSCRIBER EYES ONLY" }),
  ]));

  card.appendChild(el("h1", { class: "gotcha-headline",
    text: "THE MODEL FINALLY BROKE." }));

  card.appendChild(el("p", { class: "gotcha-sub",
    text: "After 40 pre-registered hypotheses and zero survivors, one "
        + "strategy just cleared every gate at once. We have never seen a "
        + "number like this. Legal has advised us not to publish it." }));

  const stats = el("div", { class: "gotcha-stats" });
  const stat = (value, label, tone) => stats.appendChild(
    el("div", { class: `gotcha-stat gotcha-stat--${tone}` }, [
      el("span", { class: "gotcha-stat__value", text: value }),
      el("span", { class: "gotcha-stat__label", text: label }),
    ]));
  stat("99.7%", "WIN PROBABILITY", "money");
  stat("+41.2%", "EXPECTED VALUE", "money");
  stat("LOCK", "OF THE DAY", "warn");
  stat("0", "WAYS TO LOSE", "live");
  card.appendChild(stats);

  card.appendChild(el("p", { class: "gotcha-fineprint",
    text: "GUARANTEED. FREE MONEY. THIS IS NOT FINANCIAL ADVICE, IT IS "
        + "BETTER THAN FINANCIAL ADVICE." }));

  const button = el("button", { type: "button", class: "gotcha-cta",
    "data-hook": "gotcha-unlock", text: "UNLOCK MY MAXIMUM CONVICTION PICK" });
  button.addEventListener("click", onProceed, { once: true });
  card.appendChild(button);

  card.appendChild(el("p", { class: "gotcha-nag",
    text: "This alert cannot be dismissed until the pick is claimed." }));

  stage.appendChild(card);
  requestAnimationFrame(() => card.classList.add("is-in"));
}

/* ---------------------------------------------------------------------
 * Act 2 -- the unlock. A terminal that takes itself very seriously.
 * ------------------------------------------------------------------- */

function actTwo(stage, onDone) {
  stage.innerHTML = "";
  const term = el("div", { class: "gotcha-term", "data-hook": "gotcha-unlock-seq" });
  term.appendChild(el("div", { class: "gotcha-term__bar" }, [
    el("span", { text: "linehound://conviction-engine" }),
  ]));
  const body = el("pre", { class: "gotcha-term__body" });
  term.appendChild(body);
  stage.appendChild(term);
  requestAnimationFrame(() => term.classList.add("is-in"));

  let i = 0;
  const tick = () => {
    if (i < UNLOCK_LINES.length) {
      body.textContent += (i ? "\n" : "") + UNLOCK_LINES[i];
      body.scrollTop = body.scrollHeight;
      i += 1;
      // The last line hangs, because of course it does.
      setTimeout(tick, i === UNLOCK_LINES.length ? 1100 : 260);
      return;
    }
    onDone();
  };
  setTimeout(tick, 320);
}

/* ---------------------------------------------------------------------
 * Act 3 -- Rick.
 * ------------------------------------------------------------------- */

function actThree(stage, teardown) {
  stage.innerHTML = "";
  const reveal = el("div", { class: "gotcha-reveal", "data-hook": "gotcha-reveal" });

  reveal.appendChild(el("h1", { class: "gotcha-reveal__shout",
    text: "GET RICK ROLLED" }));
  reveal.appendChild(el("p", { class: "gotcha-reveal__sub",
    text: "GET *!%#ED, JACOB — LMAO, ALL LOVE" }));

  const frame = el("div", { class: "gotcha-reveal__frame" });
  const video = el("iframe", {
    src: RICK, title: "Never Gonna Give You Up", frameborder: "0",
    // `autoplay` in the permissions list as well as the URL -- the attribute
    // grants the capability, the query parameter asks to use it, and a
    // cross-origin frame needs both.
    allow: "autoplay; encrypted-media; picture-in-picture",
    allowfullscreen: "", playsinline: "",
    "data-hook": "gotcha-video",
  });
  frame.appendChild(video);

  /* It arrives muted (see RICK). This turns it up, and is the second time
     he clicks a button that rickrolls him. */
  const sound = el("button", { type: "button", class: "gotcha-sound",
    "data-hook": "gotcha-sound", text: "TAP FOR SOUND" });
  sound.addEventListener("click", () => {
    try {
      video.contentWindow.postMessage(JSON.stringify(
        { event: "command", func: "unMute", args: [] }), "*");
      video.contentWindow.postMessage(JSON.stringify(
        { event: "command", func: "setVolume", args: [100] }), "*");
      video.contentWindow.postMessage(JSON.stringify(
        { event: "command", func: "playVideo", args: [] }), "*");
    } catch (err) {
      // A blocked postMessage is not worth breaking the joke over -- the
      // frame's own controls are right there.
    }
    sound.textContent = "♪ NEVER GONNA GIVE YOU UP";
    sound.disabled = true;
  });
  frame.appendChild(sound);
  reveal.appendChild(frame);

  reveal.appendChild(el("p", { class: "gotcha-reveal__credit",
    text: "No strategy was promoted. No gate was bypassed. The honesty "
        + "module is fine. You, however, clicked the button." }));

  /* The dismiss button dodges twice, then relents. It is a bit, not a
     trap -- and Escape works from here on regardless. */
  let dodges = 0;
  const close = el("button", { type: "button", class: "gotcha-close",
    "data-hook": "gotcha-close", text: "OK, YOU GOT ME" });
  close.addEventListener("mouseenter", () => {
    if (dodges >= 2) return;
    dodges += 1;
    close.style.transform =
      `translate(${dodges % 2 ? "" : "-"}${120 + dodges * 40}px, ${dodges * 18}px)`;
    close.textContent = dodges === 1 ? "NOT SO FAST" : "ONE MORE TIME";
  });
  close.addEventListener("click", teardown);
  reveal.appendChild(close);

  stage.appendChild(reveal);
  requestAnimationFrame(() => reveal.classList.add("is-in"));
}

/**
 * Run the whole bit, if and only if the hash is exactly GOTCHA_ROUTE.
 *
 * Returns true when it took over the screen, so main.js can skip the
 * normal route render. Returns false -- having done nothing at all, and
 * touched no DOM -- in every other case.
 *
 * Idempotent: a second call while the overlay is already up is a no-op,
 * so the hashchange listener cannot stack two of these on top of each
 * other.
 */
export function maybeGotcha() {
  if (routeFromLocation() !== GOTCHA_ROUTE) return false;
  if (document.querySelector("[data-hook='gotcha-overlay']")) return true;

  document.documentElement.classList.add("gotcha-on");
  const overlay = el("div", { class: "gotcha", "data-hook": "gotcha-overlay",
    role: "dialog", "aria-label": "a joke" });
  const stage = el("div", { class: "gotcha__stage" });
  overlay.appendChild(el("div", { class: "gotcha__scan", "aria-hidden": "true" }));
  overlay.appendChild(stage);
  document.body.appendChild(overlay);

  let escapable = false;
  const teardown = () => {
    document.removeEventListener("keydown", onKey);
    document.documentElement.classList.remove("gotcha-on");
    overlay.remove();
    // Send the hash back to a real route so a refresh returns the product
    // and the back button does not walk him into it again. replaceState,
    // not assignment, so no extra history entry is created.
    const url = new URL(window.location.href);
    url.hash = "#/today";
    window.history.replaceState({}, "", url.toString());
    window.location.reload();
  };
  const onKey = (event) => {
    if (escapable && event.key === "Escape") teardown();
  };
  document.addEventListener("keydown", onKey);

  actOne(stage, () => actTwo(stage, () => {
    escapable = true;
    actThree(stage, teardown);
  }));
  return true;
}
