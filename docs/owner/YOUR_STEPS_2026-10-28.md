# Your steps, 2026-10-28 (in order, about 25 minutes total)

Checked live before writing: your account is on the free plan since your tester window ended on 10-27, so texts are locked
until step 1. Jacob's hound still has 6 sports (no NHL, college basketball or WNBA), so step 3 has not run yet.

## 1. Make yourself free forever (2 min) — texts need this

1. Open https://linehound.app/web/admin.html
2. **People** section → press **Add person**.
3. Email = the email you sign in to LINEHOUND with. Why = `owner`.
4. Press **Give free access**. It shows an access token once; you can ignore it, your password keeps working.
5. Same button later for close friends.

## 2. Texts on your phone (10 min, Zapier)

Zapier, not Twilio, for now. You already pay for Zapier, and it works today. Twilio needs a card, a phone number and a
carrier approval that takes days to weeks before it can text anyone. Twilio only matters later, when members other than
you want texts. Its steps are in `docs/owner/TEXT_ALERTS.md` part B.

1. Sign in to Zapier in Chrome: https://zapier.com/app/login (it was signed out; I can't type your password).
2. Get your feed link: https://linehound.app/web/#/account → scroll to **Alerts** → under "Private alert feed" press
   **Make my feed link**, then **Copy feed link**. It is shown once. Treat it like a password.
3. Make the Zap: https://zapier.com/webintent/create-zap
   - **Trigger**: search **RSS by Zapier** → event **New Item in Feed** → Continue → **Feed URL** = paste the link →
     Continue → **Test trigger**. If it says no items yet, that's fine: items appear with tomorrow's 9 AM lineup.
   - **Action**: search **SMS by Zapier** → event **Send SMS** → **To Number** = your mobile → Zapier texts you a PIN,
     type it in → **Message** = pick the trigger's **Description** field → **Test step** (you get a text).
   - Press **Publish**.
   - Easier: once you're signed in to Zapier, say "zap" and I'll click through it in Chrome. You only paste the link
     and type the PIN.
4. What you'll get: the 9 AM PT lineup ("Chalk Chihuahua: watching 4 MLB games...") and a text each time a hound
   decides a bet. Bet texts can lag 1 to 15 minutes, because that's how often Zapier checks.

## 3. Jacob's hound: all sports + the kennel-fire joke (5 min)

Same in PowerShell or CMD. First open a shell on the server:

```
fly ssh console -a linehound-prod
```

Then paste these one at a time (you are now inside the server):

```
python -c "import sqlite3; s=sqlite3.connect('/app/data/app/app.db'); d=sqlite3.connect('/app/data/app/app-backup-20261028.db'); s.backup(d); d.close(); print('backup ok')"
python -m src.cli hounds add-sports --id u-bfa0440b58 --sports all
python -m src.cli announce --find-user u-bfa0440b58
```

The last line prints Jacob's user number. Put it in place of `N`:

```
python -m src.cli announce --user N --kind kennel_fire
exit
```

Then tell me "done". I'll check his hound shows the new sports. If anything goes wrong, his old version and its record
are untouched, and "Go back to this version" on his hound undoes it.

## 4. Tennis paper test (3 min)

**Why I asked for the Odds API key again:** it is connected, on the live server and in GitHub, and both hide a key once
it's saved. They never show it again, so I can't copy it from there. The tennis recorder has to run on this PC, so it
can save its evidence to git, and this PC has never had the key.

1. Copy your key from https://the-odds-api.com/account/
2. In PowerShell, paste this, press Enter, then paste the key when it asks:

```
$k = Read-Host "Paste your Odds API key"; Set-Content -Path C:\Users\KC\Desktop\wt_ship\.env -Value "ODDS_API_KEY=$k" -Encoding ascii
```

3. Keep the PC awake while it runs: `powercfg /change standby-timeout-ac 0`
4. Tell me "key in". I start the recorder in a terminal tab. Cost: at most 200 credits a day of your 100,000 a month,
   no new subscription. It only records prices and grades them. It never bets.

## 5. Already done, no action

- **Hound chat stays free**: 20 messages a day on free accounts, 100 on paid. If chat spend ever reaches $2 in a month,
  it pauses until the next month. We can move it to a paid plan later if it gets expensive.
- **Every old version keeps its record.** Retiring a version never deletes a bet. A one-sheet export of all versions is
  being built now.

## 6. Two yes/no answers I need

- **$25, once**: a deep hindsight review of every past bet (news and analysts' takes, why it won or lost) plus a deep
  review of every hound's whole record. That review feeds Fine-tune, Full rebuild and chat. It's being built now and
  ships switched off. Nothing is spent until you say yes.
- **Download free tennis history** (tennis-data.co.uk, about 12 yearly files of 2-3 MB each). It gives every pro match's
  set scores and pre-match odds, and answers "when a favourite loses set 1, how often do they come back?" From that
  you get a price table to check live bets like your Novak one against.

## 7. Survival reminder

The deadline to cover costs is 10-31, and 0 of 50 founding seats are sold. Say the word and I'll draft the posts and DMs.
