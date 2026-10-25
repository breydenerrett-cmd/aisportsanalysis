/**
 * Times in the VIEWER's zone (owner, 2026-10-25). The server never writes a clock for a person to read: it writes a token,
 * "[[t:<UTC ISO>]]", and this module turns each token into the browser's own zone and day words:
 *
 *   t  "Today 12:45 PM PT"        (Tomorrow / a weekday inside six days / "Oct 29" otherwise, judged on the viewer's calendar day)
 *   d  "Oct 25 at 12:25 PM PT"    (a date that is always named: a recorded ticket's time)
 *   w  "Thu 12:45 PM PT"          (a weekday and clock: the next game in a sentence)
 *   c  "12:45 PM PT"              (a clock only)
 *
 * The matching Python side is src/hounds/interact/fire.py (``stamp`` and ``resolve_plain``), which writes the Eastern form for a
 * plain-text reader. A token that cannot be read is left out, never shown raw. The zone name is the common abbreviation for the
 * US zones (PT, MT, CT, ET) and the browser's own short name everywhere else.
 */

const TOKEN = /\[\[(t|d|w|c):([^\]\s]+)\]\]/g;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const US_ZONE = { PDT: "PT", PST: "PT", MDT: "MT", MST: "MT", CDT: "CT", CST: "CT", EDT: "ET", EST: "ET" };

/** The browser's zone name for a moment: "PT" for Pacific, "ET" for Eastern, and so on. */
function zoneName(date) {
  try {
    const part = new Intl.DateTimeFormat("en-US", { timeZoneName: "short" }).formatToParts(date)
      .find((p) => p.type === "timeZoneName");
    const raw = part ? part.value : "";
    return US_ZONE[raw] || raw;
  } catch (err) {
    return "";
  }
}

/** "12:45 PM" in the viewer's zone, with its zone name. */
function clockText(date) {
  const clock = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" }).format(date);
  const zone = zoneName(date);
  return zone ? `${clock} ${zone}` : clock;
}

/** The viewer's calendar date as a day number, so two dates compare by whole days. */
function localDay(date) {
  return Math.round(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / 86400000);
}

/** "Today", "Tomorrow", "Yesterday", a weekday inside six days, else "Oct 29" (the viewer's calendar). */
function dayWords(date, now) {
  const gap = localDay(date) - localDay(now);
  if (gap === 0) return "Today";
  if (gap === 1) return "Tomorrow";
  if (gap === -1) return "Yesterday";
  if (gap > 1 && gap < 7) return WEEKDAYS[date.getDay()];
  return `${MONTHS[date.getMonth()]} ${date.getDate()}`;
}

/** One token's text, or "" when the stamp cannot be read. `now` is injectable so a test can fix the day. */
export function formatStamp(kind, stamp, now = new Date()) {
  const date = new Date(stamp);
  if (Number.isNaN(date.getTime())) return "";
  if (kind === "c") return clockText(date);
  if (kind === "d") return `${MONTHS[date.getMonth()]} ${date.getDate()} at ${clockText(date)}`;
  if (kind === "w") return `${WEEKDAYS[date.getDay()]} ${clockText(date)}`;
  return `${dayWords(date, now)} ${clockText(date)}`;
}

/** The text with every time token replaced by the viewer's own time. Safe on "" and on text with no tokens. */
export function localizeTimes(text, now = new Date()) {
  return String(text == null ? "" : text).replace(TOKEN, (match, kind, stamp) => formatStamp(kind, stamp, now));
}
