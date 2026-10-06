/**
 * SUPPORT view -- POST /support (api/support.py).
 *
 * WHY THIS VIEW HAS NO LIST/HISTORY OF PAST MESSAGES
 * -------------------------------------------------------------------
 * There is no GET route for a user's own support messages -- v1 only
 * lets an admin read the queue back (docs/ONBOARDING_SUPPORT_PLAYBOOK.md
 * section 6). This view renders the one message the API just created as
 * confirmation and nothing more; it never fabricates a "your ticket
 * history" list the API cannot back.
 *
 * WHY THE FORM HAS NO EMAIL FIELD WHEN A TOKEN IS SAVED
 * -------------------------------------------------------------------
 * api/support.py identifies an authed sender by their account and ignores
 * any `email` the body carries (see that module's docstring) -- showing
 * an email input to a signed-in user would imply it does something it
 * doesn't. api.js's getToken() is the same signal main.js's token form
 * already uses to decide whether the caller is authed.
 */

import { apiPost, getToken } from "./api.js";
import { el, clear, renderError } from "./dom.js";

const MAX_SUBJECT_LENGTH = 200;
const MAX_BODY_LENGTH = 5000;

/**
 * LOCKED OUT: what to send, exactly. There is no email sender and no
 * self-service way to get a lost access token back, so this is SUPPORT
 * RECOVERY (docs/billing/RECOVERY_PROCEDURE.md): the email field on this form
 * is typed and unverified, so a form is never proof of anything. We write to the
 * address on the account, the person replies from that mailbox, and only then
 * does a new token go, to that address. Nothing is revoked before the reply, so
 * a stranger who types someone else's address locks nobody out. The page
 * therefore says to expect a confirmation email and to reply from the
 * account's address, says nothing is shown here, and
 * says what is not enough, so nobody sends a card number or an old token and
 * nobody expects a token in a chat. It claims no turnaround time: a person
 * answers by hand.
 */
export const LOCKED_OUT_STEPS = [
  "Write to us with the form below and type the email address your account uses. We answer only that address.",
  "Put \"Locked out\" in the subject. Say whether you bought a plan or were given early access.",
  "We write to the address on the account first, to confirm the request. Reply to that email from the email address your account uses. Until your reply arrives nothing changes, and your current token keeps working.",
  "After your reply we send a new access token to that address. The old one stops working the moment we do.",
  "Do not send a card number or an old token. An email address or a checkout number on its own is not enough, and we never send a token to a chat or a message.",
];

function lockedOutNote() {
  const box = el("section", { class: "support-lockedout", "data-hook": "support-locked-out" });
  box.appendChild(el("h2", { text: "Locked out of your account?" }));
  box.appendChild(el("p", { text:
    "If you lost your access token, or paid and never saw it, this is how we get you back in. "
    + "It is done by hand, so it takes a person, not a button. Your purchase or trial is not lost." }));
  box.appendChild(el("ol", { class: "support-lockedout__steps" },
    LOCKED_OUT_STEPS.map((text) => el("li", { text }))));
  return box;
}

export async function renderSupport(container) {
  clear(container);
  const section = el("section", { class: "support-view", "data-view": "support" });
  section.appendChild(el("h1", { text: "Support" }));
  // The page was a bare form -- four labels and a button, no sentence
  // saying what it was for or what happens next (read on 2026-09-12).
  section.appendChild(el("p", { class: "support__intro", "data-hook": "support-intro",
    text: "A question about a pick, a number that looks wrong, or something broken? Write it here and we reply by email." }));

  section.appendChild(lockedOutNote());

  const isAuthed = Boolean(getToken());
  const form = el("form", { class: "support-form", "data-hook": "support-form" });

  let emailInput = null;
  if (!isAuthed) {
    const emailLabel = el("label", { for: "support-email", text: "Email" });
    emailInput = el("input", { type: "email", id: "support-email", name: "email", required: "required" });
    const emailRow = el("p", { class: "support-form__row" });
    emailRow.appendChild(emailLabel);
    emailRow.appendChild(emailInput);
    form.appendChild(emailRow);
  }

  const subjectLabel = el("label", { for: "support-subject", text: "Subject" });
  const subjectInput = el("input", { type: "text", id: "support-subject", name: "subject",
    maxlength: String(MAX_SUBJECT_LENGTH), required: "required" });
  const subjectRow = el("p", { class: "support-form__row" });
  subjectRow.appendChild(subjectLabel);
  subjectRow.appendChild(subjectInput);
  form.appendChild(subjectRow);

  const bodyLabel = el("label", { for: "support-body", text: "Message" });
  const bodyInput = el("textarea", { id: "support-body", name: "body",
    maxlength: String(MAX_BODY_LENGTH), required: "required" });
  const bodyRow = el("p", { class: "support-form__row" });
  bodyRow.appendChild(bodyLabel);
  bodyRow.appendChild(bodyInput);
  form.appendChild(bodyRow);

  form.appendChild(el("button", { type: "submit", text: "Send" }));

  const statusRegion = el("p", { class: "support-form__status", role: "status",
    "data-hook": "support-form-status" });
  const confirmationHost = el("div", { "data-hook": "support-confirmation-host" });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clear(statusRegion);
    clear(confirmationHost);
    try {
      const body = { subject: subjectInput.value, body: bodyInput.value };
      if (emailInput) body.email = emailInput.value;
      const message = await apiPost("/support", body);
      form.reset();
      renderConfirmation(confirmationHost, message);
    } catch (err) {
      renderError(statusRegion, err);
    }
  });

  section.appendChild(form);
  section.appendChild(statusRegion);
  section.appendChild(confirmationHost);
  container.appendChild(section);
}

function renderConfirmation(container, message) {
  clear(container);
  const confirmation = el("section", { class: "support-confirmation",
    "data-hook": "support-confirmation" });
  confirmation.appendChild(el("h2", { text: "Message sent" }));
  confirmation.appendChild(el("p", {
    text: "We'll reply by email. This page will not show your message again.",
  }));
  confirmation.appendChild(el("dl", { class: "support-confirmation__fields" }, [
    el("dt", { text: "Subject" }),
    el("dd", { text: message.subject }),
    el("dt", { text: "Status" }),
    el("dd", { text: message.status }),
  ]));
  container.appendChild(confirmation);
}
