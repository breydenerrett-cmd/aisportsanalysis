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

export async function renderSupport(container) {
  clear(container);
  const section = el("section", { class: "support-view", "data-view": "support" });
  section.appendChild(el("h1", { text: "Support" }));

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
