# ATL at LAD 2026-10-04, version-2 packet (ccef50623366), attempt 1: transcript record

The answer file for attempt 1 was overwritten by attempt 2. What follows is everything the parent
session printed from it at 21:25Z on 2026-10-04. It is a partial record, not the answer file.

Checker result on attempt 1: 14 calls, 12 kept, 2 struck.
- moneyline: STRUCK (reasons[0] quoted -200, not a number in the data; reasons[1] used the banned
  word 'edge'; what_would_change_it quoted +201, not a number in the data)
- prop_11: STRUCK (reasons[0] quoted -200, not a number in the data)

Summary text (verbatim):
"The market looks mostly right here, and I find one spot worth a bet. LAD is -212 at the best price, past the point where I will bet a favorite, so the moneyline is a pass. The run line and total are passes because the data cuts both ways: Blake Snell has a 1.8984 ERA, while ATL's probable, Ray Kerr, has a small sample and the home hitters have run well against his kind of fastball-heavy mix. The weather is hot and dry, which the total already prices. The one lean is Snell strikeouts Under 6.5 at +120 on DraftKings. He strikes out 11.6016 batters per nine, but he averages only 4.741 innings a start and 3.556 over his last three, so the line asks for more than his usual workload. That is a thin read on a nine-start sample, and the other books price the Under near even money. The player props are passes: their quotes were captured long before the lineups posted, Max Muncy and Ha-Seong Kim are not in either posted lineup, and the books' own prices already reflect Snell."

Calls (slot, verdict, selection, price, book, fair_estimate):
moneyline PASS LAD -212 draftkings 0.66
run_line PASS ATL +1.5 -112 lowvig 0.52
total PASS Under 8 -110 lowvig 0.51
prop_01 TAKE_OTHER_SIDE Under 6.5 +120 draftkings 0.52
prop_02 PASS Over 0.5 -171 draftkings 0.62
prop_03 PASS Over 0.5 -135 bovada 0.55
prop_04 PASS Under 1.5 -150 williamhill_us 0.58
prop_05 PASS Under 1.5 -150 williamhill_us 0.57
prop_06 PASS Under 1.5 -170 williamhill_us 0.58
prop_07 PASS Under 1.5 -159 draftkings 0.575
prop_08 PASS Under 1.5 -169 draftkings 0.59
prop_09 PASS Over 0.5 -130 bovada (none)
prop_10 PASS Under 1.5 -173 williamhill_us 0.59
prop_11 PASS Under 0.5 -700 draftkings (none)

Other records:
- Attempt 2 (published as version 2): `evidence/analyst_pilot/2026-10-04_ATL-LAD/answer.json`.
  It was written after attempt 1's four rejection lines were passed back, with nothing else added.
  It passed on prop_01 (selection "Over 6.5", no fair_estimate).
- Independent sample 3 (never published, same request, no rejection lines):
  scratchpad `stability_answer_3.json`. It took prop_01 TAKE_OTHER_SIDE Under 6.5, fair_estimate 0.52.
