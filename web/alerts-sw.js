/* LINEHOUND bet-alert service worker. Registered by web/js/alerts.js from Account -> Alerts, scope /web/.
 *
 * It does exactly two things: show the notification a push carries, and open the hound page when it is tapped.
 * It caches nothing and intercepts no request, so it can never serve a stale page. The payload is the JSON the
 * server encrypted (src/notify/alert_render.py push_payload): {title, body, url, tag}. Text is shown as plain
 * notification text, never as HTML. A tapped URL is opened only when it is on this site.
 */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (err) { data = {}; }
  const title = String(data.title || "LINEHOUND");
  event.waitUntil(self.registration.showNotification(title, {
    body: String(data.body || ""),
    tag: String(data.tag || "bet-alert"),
    icon: "/web/icons/icon-192.png",
    badge: "/web/icons/icon-192.png",
    data: { url: String(data.url || "/web/") },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  let target = "/web/";
  try {
    const url = new URL((event.notification.data && event.notification.data.url) || "/web/", self.location.origin);
    if (url.origin === self.location.origin) target = url.href;
  } catch (err) { /* keep the default */ }
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
    for (const w of wins) {
      if ("focus" in w) { w.navigate(target).catch(() => {}); return w.focus(); }
    }
    return self.clients.openWindow(target);
  }));
});
