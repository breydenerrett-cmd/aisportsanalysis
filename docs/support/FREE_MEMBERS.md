# Free members: give someone full access, free, forever

A free member (a "comp") has full access with no card and no end date, until you
revoke it. It is not a tester (no 7-day clock, no slot of the 20) and it is not
revenue (the revenue view counts subscriptions only). The policy lives in
`src/appstate/comps.py`; this page is the clicks.

Admin page: <https://linehound.app/web/admin.html>
Where they sign in: <https://linehound.app/web/index.html#/signin>

## Give someone free access

1. Open <https://linehound.app/web/admin.html>.
2. In the **Admin token** box paste your admin token, press **Save token**. The
   sections load. (The token is kept for this tab only.)
3. Scroll to **Free members**.
4. **Email**: the person's email. A new address creates the account. An address
   that is already waitlisted, an expired tester or an existing user keeps its
   account and is simply made active.
5. **Why**: one line for your own log, for example `early-access signup, friend of
   the project`. It is required. Never paste a token or key into it; the page
   refuses one.
6. Press **Give free access forever**.
7. The page shows the access token once, in a box. Press **Copy** (the token) or
   **Copy the message to send** (a ready-to-send note that names the sign-in page
   and holds the token).
8. Send it to them yourself, by email or DM. The token is not stored and cannot be
   shown again. Do not paste it into a ticket or any chat that keeps history.

They open <https://linehound.app/web/index.html#/signin>, paste the token into the
box, press **Save token**, and they are in. Their Billing page says **Free
member**, and nothing asks them to pay.

## Approve someone who is on the waitlist (one click)

1. Same admin page, scroll to **Users**.
2. Find the row whose status is `waitlisted`.
3. Press **Approve as free member** in that row.
4. A box asks why. Type a line and confirm. Cancel, or an empty answer, sends
   nothing.
5. The token appears in the **Free members** section above. Copy and send it as in
   steps 7 and 8 above. The row now shows `yes` under **free member**.

## What can be refused (the page prints the reason)

| Message | Meaning | What to do |
| --- | --- | --- |
| this account is suspended | You suspended them | Lift the suspension first, or leave it |
| a live paid subscription | They are paying right now | Nothing: they already have access |
| a checkout is open | Status `pending_payment` | Let it finish or lapse, then try again |
| already a free member | They have it | Use **New token** if they lost theirs |

A person whose subscription has lapsed or been cancelled is not refused.

## They lost their token

Verify it is them first: write to the address on the account and wait for a reply
FROM that mailbox (the Get help form proves nothing, anyone can type an address).
Then in **Free members**, on their row: type a reason (what you verified, which
ticket) and press **New token**. The old token stops working, the new one is shown
once. Send it as above.

## Take it away

1. **Free members**, on their row, type a reason in the box.
2. Press **Revoke**.

The access and every token end at once, and the row stays in the list as `revoked`
with the date and your reason. To give it back later, use **Give free access
forever** again with the same email.

## What is recorded

- The list keeps who, when, why and whether they have signed in. It never holds a
  token.
- Each grant and revoke writes one analytics event (`comp_access_granted`,
  `comp_access_revoked`) in the same step as the change. It records what the
  account was before and how many tokens were revoked, never the token, the email
  or your reason.
- The access token lasts 10 years. That is "forever" for this product; New token
  gives another 10.

## If something looks wrong

- Section missing or empty after saving the admin token: the token was rejected, or
  `APP_ADMIN_TOKEN` is not set on that server. The page says which.
- They paste the token and are sent to a payment page: they were not made a free
  member (check the **Free members** list for their email) or the token was
  replaced by a newer one.
