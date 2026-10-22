# Bet alerts: turn them on (email, phone notifications, texts)

Code: `src/notify/alerts.py` (store, events), `alert_dispatch.py` (the sender loop), `alert_channels.py` (email, push, SMS, native stub), `webpush.py`, `api/alerts_routes.py`, `web/js/alerts.js` + `web/alerts-sw.js` (Account, Alerts).

A member opens **Account -> Alerts** (https://linehound.app/web/#/signin when signed in). Until they do, they have no alert row and get nothing. Each channel is OFF until its keys exist on the server; the page says so in words.

| Channel | Who | Needs | Cost |
|---|---|---|---|
| Email | everyone | `RESEND_API_KEY` (already set, see `RESEND_ATTACH.md`) | free tier |
| Phone/browser notifications (web push) | everyone | `VAPID_PRIVATE_KEY` (step 1) | free |
| Text (SMS) | paid members, incl. you and Jacob (comped) | Twilio + 10DLC (step 2) | see memo |
| Native app (APNs/FCM) | later | the Capacitor app | stub only |

Test any of them from the page: **Send me a test alert**.

## 1. Turn on phone/browser notifications (5 minutes, free)

Run this in PowerShell from the repo. It makes the key, sends it straight to Fly, and never prints it:

```powershell
cd C:\Users\KC\Desktop\aisportsanalysis; pip install cryptography; python scripts\vapid_keys.py --app linehound-prod
```

It prints only the PUBLIC key. Fly restarts the app (about a minute). Check or change secrets later at https://fly.io/apps/linehound-prod/secrets (button **Add Secret**). Re-running the script replaces the key and every member must switch notifications on again, so run it once.

Optional: `VAPID_SUBJECT` = `mailto:you@yourdomain` (a contact the push services can reach). Default `mailto:hounds@linehound.app`.

**iPhone:** web push only works after the site is on the Home Screen (iOS 16.4+): open https://linehound.app in Safari, **Share**, **Add to Home Screen**, open it from the icon, then Account -> Alerts -> switch on **Browser and phone notifications**. The Alerts screen tells members this. Android and desktop Chrome/Edge/Firefox need nothing extra.

## 2. Text alerts (SMS): the decision memo and the steps

**Decision made 2026-10-21:** texts are a paid-member feature (free accounts get email and notifications). The code is written and OFF until all three of `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM` are set. It stores a phone number only after the member ticks the agree box AND types back a 6-digit code texted to that number (so nobody can make LINEHOUND text a stranger; codes are limited to 1 a minute and 5 an hour per member), never texts a free account, and a STOP reply switches that number off until the member replies START (Twilio also enforces STOP at the carrier). HELP gets a one-line answer.

**Cost (verify on https://www.twilio.com/en-us/sms/pricing/us and https://www.twilio.com/en-us/user-authentication-identity/pricing before paying; figures change):**
- Per text: roughly 0.8 cents Twilio plus carrier fees of about 0.3 to 0.5 cent per segment, so about 1.1 to 1.4 cents each. A burst is ONE text (60-second batching) and the cap is 6 texts per member per hour.
- A US local number: about $1.15 a month.
- 10DLC registration (US rules for business texting; unregistered numbers are blocked): a one-time brand fee (a few dollars for a sole proprietor, about $46 for a standard brand), a one-time campaign vetting fee (about $15), then a small monthly campaign fee (a few dollars). Approvals take from a few days to two weeks.
- Rough running cost for 20 paid members at ~10 alerts a day each: 200 texts a day, about $2.50 to $3 a day, so about $75 to $90 a month. Texts are the expensive channel; it is why they sit behind the paid plan. The 6-per-hour cap bounds the worst case.

**Steps (you do these; I cannot):**
1. Sign up or sign in at https://www.twilio.com/console. Add a card under **Billing**.
2. Buy a number: Console -> **Phone Numbers** -> **Manage** -> **Buy a number**. Pick a US local number with SMS.
3. Register for 10DLC: Console -> **Messaging** -> **Regulatory Compliance** -> **A2P 10DLC** (direct page: https://console.twilio.com/us1/develop/sms/regulatory-compliance/a2p-10dlc). Then:
   a. **Register a Brand** (Standard or Sole Proprietor; use the business name and address from `config/business.json`).
   b. **Create a Campaign** (use case: **Account Notification** or **Low Volume Mixed**). Sample message: `LINEHOUND (paper): DRAKEO bet Atlanta Hawks ML +110 · stake $25 · starts Wed 7:10 PM EDT https://linehound.app/web/hound.html Reply STOP to end.` Opt-in description: the member ticks "I agree to get text messages about my hounds' bets" in Account -> Alerts. Include the STOP and HELP language and a link to your privacy page.
   c. Add your number to the campaign's **Messaging Service** sender pool.
4. Set the inbound webhook so STOP reaches us: Console -> Phone Numbers -> **Active numbers** -> your number -> **Messaging Configuration** -> "A message comes in": **Webhook**, `https://linehound.app/alerts/sms/inbound`, **HTTP POST**, **Save configuration**.
5. Put the three secrets on Fly. Paste this in PowerShell; each prompt hides what you type, and nothing is printed or saved:

```powershell
$sid  = Read-Host "TWILIO_ACCOUNT_SID" -AsSecureString
$tok  = Read-Host "TWILIO_AUTH_TOKEN" -AsSecureString
$from = Read-Host "TWILIO_FROM (your number, like +15551234567)"
$p = { param($s) [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)) }
"TWILIO_ACCOUNT_SID=$(& $p $sid)`nTWILIO_AUTH_TOKEN=$(& $p $tok)`nTWILIO_FROM=$from" | fly secrets import --app linehound-prod
Remove-Variable sid,tok,from,p
```

The SID and token are on the Console home page (https://www.twilio.com/console) under **Account Info**; the token is behind **Show**. Fly restarts the app. Until step 3 is approved, carriers may block texts even though the code is on.

### Free alternative for you and Jacob only (no Twilio, no 10DLC)

Zapier's **SMS by Zapier** texts a number you verify yourself. Each of you has a private RSS address of your own bet events: Account -> Alerts -> **Private feed of your bet alerts**. Then at https://zapier.com/app/zaps -> **Create**:
1. Trigger: **RSS by Zapier** -> **New Item in Feed** -> paste your private feed address.
2. Action: **SMS by Zapier** -> **Send SMS** -> **To** your verified number (Zapier asks you to verify it by code), **Message** = the item's **Description** field (it is already a one-line alert, paper and 21+ included).
3. **Publish**. Zapier polls every 1 to 15 minutes depending on your plan, so this is slower than the push or email alert and each text spends a Zap task (the free plan has 100 tasks a month). Treat the feed address like a password: **Make a new private address** on the same screen revokes the old one.

## 3. What the alerts do (so you can explain them)

- A "bet placed" alert goes out right after a member hound's bet is written (engine, Unleash, or a manual pick); "settled" after grading (win, loss or push, with the P&L at the member's own unit size). Voids are not announced.
- Bets within 60 seconds are ONE message; the first alert is held at most about 10 seconds to catch a burst.
- Per member per hour: email 12, push 30, texts 6. Over the cap, alerts wait and go out together as one message.
- Failed sends retry at 30 seconds, 2 minutes, 8 minutes, then stop. The same alert is never sent twice on a channel. Alerts older than 12 hours are dropped.
- Members can set quiet hours and choose placed, settled or both.
- Dollars use the member's sizing (a fixed unit is exact; a percent sizing shows `~` against the starting bankroll).
- Each alert email has a one-click "turn off" link (`/alerts/off`).
- Settings that switch things off: `ALERTS_JOBS=off` stops the sender loop.

## 4. Native apps later

`alert_devices` holds iOS/Android device tokens (`POST /me/alerts/device`). `NativePushChannel` in `alert_channels.py` is a stub that reports "not released"; the app worker fills in `deliver` (APNs/FCM) and flips `availability`. Nothing else changes.
