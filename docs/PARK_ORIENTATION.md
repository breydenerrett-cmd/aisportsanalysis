# Filling in park orientations

`src/data/parks.py` has `orientation_deg: None` for all 30 parks. This document
explains what the field is, why it is blank, and exactly how to fill it.

## What the field is

The compass bearing from **home plate toward center field**, in degrees, where
0 is north and 90 is east.

## Why it matters

Wind speed on its own tells you nothing useful about a baseball game. A 15 mph
wind blowing out and a 15 mph wind blowing in have close to opposite effects on
run scoring, and the raw weather reading cannot distinguish them.

Turning a wind bearing into out / in / cross requires knowing which way the park
points. Without it, wind is a column that gets collected and never used.

## Why it is blank rather than estimated

A wrong bearing is worse than no bearing.

If a park's orientation is off by 180 degrees, the model applies a
carry-increasing adjustment on days when the wind is actually knocking balls
down. That is not a small error — it flips the sign of a real effect, and it
does so confidently and silently. A blank field produces no signal; a wrong one
produces an inverted signal, which is worse than nothing.

So `classify_wind` returns `None` for any park whose bearing is unverified, and
`wind_effect` reports `applicable: False` with the reason.

## How to fill it

Bounded, one-time, roughly an hour for all 30.

1. Open satellite imagery for the ballpark (Google Maps, Apple Maps, or any
   aerial view with a north-up orientation).
2. Locate home plate and the center field wall.
3. Measure the bearing of the line from home plate through second base to
   center field, relative to north.
4. Record it to the nearest degree in `PARKS[abbrev]["orientation_deg"]`.

A useful sanity check: MLB Rule 1.04 recommends the line from home plate
through the pitcher's plate to second base run **east-northeast**, so most parks
fall roughly in the 22–68 degree range. Parks well outside that band are real —
several famous ones deviate — but a value far from it is worth double-checking
against the imagery rather than trusting on the first read.

## After filling them

1. Update `test_no_orientation_is_claimed_without_verification` in
   `tests/test_data_parks.py`. It currently asserts all 30 are unverified, and
   it will fail once you fill any in. **That failure is intentional** — the test
   exists so orientation data cannot appear silently without someone
   deliberately acknowledging it.
2. Add a test asserting each filled bearing is in `[0, 360)`.
3. Run `python -m src.cli status` — it reports the verified count out of 30.
4. Rebuild any slate. `wind_effect` will populate automatically; no other code
   changes are needed.

## Roof handling

Nine parks have retractable or fixed roofs. Wind should never be applied for
those without knowing the roof state for that specific game, and roof state is
not currently in any data source this project uses.

`wind_effect` already handles this: it returns `applicable: False` for a roofed
park unless `roof_closed` is passed explicitly. Filling in orientations does not
change that — sourcing per-game roof state is a separate task.
