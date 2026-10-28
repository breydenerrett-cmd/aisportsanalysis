# Texts from your hounds: the morning lineup and a text when a hound decides

Two messages, same wording everywhere (email, phone notification, text):

- **Morning lineup**, once a day at 9 AM your time: "Chalk Chihuahua: watching 4 MLB games (moneyline). Decides by 2:10 PM PT." One line per running hound that has a game today. No game, no message. Switch: Account -> Alerts -> **Morning lineup** (on for everyone).
- **Bet placed**, the moment a hound decides (existing alert, now also in the feed below).

Code: `src/notify/alert_morning.py`, the feed in `api/alerts_routes.py`. Texts are a paid-member feature (you and Jacob are comped, so you count). Free accounts keep email and push.

## A. Texts on your phone TODAY (Zapier bridge, about 10 minutes, no Twilio)

1. Open https://linehound.app/web/#/signin, sign in, go to **Account -> Alerts**. Under "Private alert feed" press **Make my feed link**, then **Copy feed link**. It is shown once. (**Reset link** later makes a new one and kills the old.) Treat it like a password.
2. Open https://zapier.com/app/zaps and press **Create** -> **Zap**.
3. **Trigger**: app **RSS by Zapier**, event **New Item in Feed**. Feed URL = the link you copied. Test trigger: you should see the newest item.
4. **Action**: app **SMS by Zapier**, event **Send SMS**. To Number = your own mobile (Zapier texts you a code to verify it the first time; it only sends to numbers you verified). Message = the trigger's **Description** field (that is the finished text).
5. Publish the Zap. Zapier checks the feed every 1 to 15 minutes depending on your Zapier plan, so a bet text can lag a few minutes; the morning lineup is unaffected.

Notes: SMS by Zapier is US-only and counts against your Zapier task quota (one task per message). STOP does nothing on these texts; turn the Zap off in Zapier instead.

## B. Real texts from LINEHOUND (Twilio go-live, days because of carrier registration)

1. Sign up: https://www.twilio.com/try-twilio (then upgrade the account so it can text numbers you have not verified).
2. Buy a US number: https://console.twilio.com/us1/develop/phone-numbers/manage/search (SMS-capable, local number is fine).
3. Register for A2P 10DLC (required by US carriers, approval takes days; do this first, texts are blocked until it passes): https://console.twilio.com/us1/develop/sms/regulatory-compliance/a2p-messaging (guide: https://www.twilio.com/docs/messaging/compliance/a2p-10dlc). Use case: "account notifications"; sample message = the morning line above; opt-in = the Account -> Alerts agree box and code check.
4. On the number's page, set **A message comes in** webhook (HTTP POST) to `https://linehound.app/alerts/sms/inbound` so STOP works.
5. Turn it on (names only here; paste the real values yourself from the Twilio console, https://console.twilio.com):

```powershell
fly secrets set TWILIO_ACCOUNT_SID=<paste> TWILIO_AUTH_TOKEN=<paste> TWILIO_FROM=<your +1 number> -a linehound-prod
```

6. The app restarts in about a minute. In Account -> Alerts add your phone, type the code, switch **Text messages** on, press **Send me a test alert**. From then on the morning lineup and each bet text arrive from the number; you can delete the Zap.
