# Pre-Registered Experimental Hypotheses — Multi-Sport Forward Tests
## 2026-09-14

These four hypotheses are experimental forward tests registered on **2026-09-14 BEFORE the first observation** for NFL card data and live in-play edges. No edge is claimed; all are research instruments and forward candidates only. Live readings never appear on the card or payoff record.

All four use family-wise alpha=0.05/3 where noted, one read at the pre-registered floor. A separate scan of historical NFL/MLB live data at any discovery window does not count toward these pre-registrations.

---

## 1. NFL_CARD:market_favourite_model_agreement_v1:h2h

**Family:** NFL_CARD_V1  
**Sport:** nfl  
**Market:** h2h  
**Direction:** The moneyline side the de-vigged multibook consensus favours, ranked by that consensus and confirmed by a v0 EPA-based margin model (Normal distribution, sigma=13.5), wins more often than its de-vigged consensus probability implies, over settled NFL card picks.

**Candidate bet:** Consensus favourite moneyline.  
**Logged at:** The price frozen on the NFL card when the pick locked (four hours before its own kickoff), exactly as the MLB card records its price.

**What counts as a win:** The selected side wins the game. Moneyline only; the spread is shown as an alternative and is not graded under this hypothesis.

**Floor:** 100 settled picks (games where both consensus and model agree on favourite).  
**Alpha declared:** 0.05 (no family correction; solo scan).  
**Read plan:** One read at floor; no continuation.  
**Data window:** discovery=null, replication=2026-09-15.., sealed_untouched=true  
**Status:** registered

---

## 2. LIVE_V0:mlb_favorite_trails_after_3:h2h

**Family:** LIVE_V0  
**Sport:** mlb  
**Market:** h2h  
**Direction:** When the pre-game consensus favourite (probability >= 0.55) trails by one or two runs at the end of the third inning, the favourite's in-play moneyline is priced below its fair probability at that state; the market under-reacts to the deficit.

**Candidate bet:** Favourite moneyline at in-play price (captured at top of 4th inning).  
**Logged at:** In-play quote price and timestamp.

**What counts as a win:** Favourite wins the game (any margin).

**Floor:** 150 settled candidates.  
**Alpha declared:** 0.05/3 (family-wise, three LIVE_V0 rules).  
**Read plan:** One read at floor; family-wise alpha across LIVE_V0:mlb_favorite_trails_after_3, LIVE_V0:mlb_starter_pulled_early, and LIVE_V0:nfl_favorite_trails_halftime.  
**Data window:** discovery=null, replication=2026-09-15.., sealed_untouched=true  
**Status:** registered

---

## 3. LIVE_V0:mlb_starter_pulled_early:h2h

**Family:** LIVE_V0  
**Sport:** mlb  
**Market:** h2h  
**Direction:** When the favourite's starting pitcher leaves before completing four innings while the favourite leads or is tied, the market under-reacts; the opponent's moneyline is priced above its fair probability given the pitcher change.

**Candidate bet:** Opponent moneyline at in-play price (captured after pitcher change).  
**Logged at:** In-play quote price and timestamp.

**What counts as a win:** Opponent wins the game (any margin).

**Floor:** 150 settled candidates.  
**Alpha declared:** 0.05/3 (family-wise, three LIVE_V0 rules).  
**Read plan:** One read at floor; family-wise alpha across LIVE_V0:mlb_favorite_trails_after_3, LIVE_V0:mlb_starter_pulled_early, and LIVE_V0:nfl_favorite_trails_halftime.  
**Data window:** discovery=null, replication=2026-09-15.., sealed_untouched=true  
**Status:** registered

---

## 4. LIVE_V0:nfl_favorite_trails_halftime:h2h

**Family:** LIVE_V0  
**Sport:** nfl  
**Market:** h2h  
**Direction:** When the pre-game consensus favourite (probability >= 0.60) trails by one to seven points at halftime, its in-play moneyline is priced below its fair probability; the market under-reacts to the trailing deficit.

**Candidate bet:** Favourite moneyline at in-play price (captured at or just before halftime).  
**Halftime proxy:** The scores feed used for NFL live state carries no clock or period, so "halftime" is proxied by elapsed time: the first observation 80 to 100 minutes after kickoff with the game not yet completed. Declared here before the first observation; a later feed with a real clock may replace the proxy only by a new registration.  
**Logged at:** In-play quote price and timestamp.

**What counts as a win:** Favourite wins the game (any margin).

**Floor:** 150 settled candidates.  
**Alpha declared:** 0.05/3 (family-wise, three LIVE_V0 rules).  
**Read plan:** One read at floor; family-wise alpha across LIVE_V0:mlb_favorite_trails_after_3, LIVE_V0:mlb_starter_pulled_early, and LIVE_V0:nfl_favorite_trails_halftime.  
**Data window:** discovery=null, replication=2026-09-15.., sealed_untouched=true  
**Status:** registered

