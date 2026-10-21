# Licensing of the data service's sources (read 2026-10-20)

This is an engineering reading of each source's published terms, not legal advice. A paid product that shows or sells
data under a "non-commercial" term should have a lawyer read the real text first.

**Evidence tiers.** **A** = the source's own terms page or licence file was fetched and read on 2026-10-20; the quoted
words are from it. **B** = taken from this repository's earlier rounds of the data service (docs/datasvc/*.md) or from
a third-party page; not re-read from the source today. **C** = not read; recalled or inferred, treat as unknown.

**Classes.** *Commercial* = the terms allow use in a paid product. *Non-commercial* = they bar it (or allow only
personal/individual use). *Unclear* = no terms found, or the terms were not readable.

## Summary

| Source | Class | We ship raw rows or only derived picks | Risk | Tier |
|---|---|---|---|---|
| ESPN site/core JSON (NBA, NHL, NCAA, soccer box scores etc.) | Non-commercial (general Disney terms; the JSON has no terms of its own) | **Raw rows are committed to the public repository and copied into the web image** (`data/datasvc/espn`) | **High** | A |
| ESPN tennis and MMA (scoreboards, UFC core JSON) | Non-commercial (same terms) | Raw MMA rows committed and shipped (`data/datasvc/ufc`); tennis results only feed grading | **High** | A |
| MLB statsapi | Non-commercial | Neither: `data/datasvc/mlb` is git-ignored and out of the image | **High** if it backs a paid surface; contained today | A |
| NHL api-web | Non-commercial | Neither: play-by-play cache is git-ignored and out of the image | **High** | A |
| nflverse | Commercial, with attribution (CC BY 4.0) | Raw rows shipped (`data/datasvc/nfl`), attribution kept in the manifest | Low (upstream NFL rights not cleared by the licence) | A |
| Kalshi | Unclear (the API is under a Developer Agreement that could not be read) | Neither | Medium | B |
| The Odds API | Commercial, if the data is not the product | Derived picks and prices shown in the app; **the odds and props stores must not be sold or served as a data feed** | Low for picks, **High** for a data-service product | A |
| football-data.co.uk | Non-commercial | Neither: store git-ignored; fetch gated behind `--i-have-permission` | **High** | A |
| openfootball | Commercial (public domain, per repo) | Not used yet; could ship | Low | A |
| EuroLeague official feeds | Unclear (terms page not readable) | Not built | Medium | C |
| OpenLigaDB | Commercial, with attribution and share-alike (ODbL) | Not built | Low to medium | A |
| Jolpica / Ergast (F1) | Non-commercial (CC BY-NC-SA 4.0) | Not built | **High** if built | A |
| Sleeper | Non-commercial free tier; commercial by arrangement | Not built | Medium | A |
| UFC.com | Non-commercial | Profiles from UFC.com are committed and shipped (`data/datasvc/ufc/`) | **High** | A |

## What the table means for what is shipped today

Two tracked, image-shipped data sets come from sources whose terms bar commercial use: the ESPN-fed league files
(`data/datasvc/espn`) and the UFC files (`data/datasvc/ufc`: ESPN core JSON and UFC.com). They are **raw
redistribution** (public git history, web image), not derived picks. Round 2's guards (git-ignore and image exclusion) already keep the MLB, NHL
play-by-play and football-data stores local; the ESPN and UFC files are the open exposure. Options: (1) keep them
internal by git-ignoring and excluding them, serving only derived numbers; (2) license a replacement (below); (3) ask
ESPN/UFC for written permission. This document does not change any of it: that is an owner decision.

Two more rules cut across the data-service plan. **The Odds API** and **BALLDONTLIE** both forbid using their data to
build a competing data feed ("Do not resell, repackage, or redistribute our data as a standalone data product"; "You may
not use Data to build or operate a sports-data API or equivalent data feed"). The odds stores can back picks and a UI,
not an odds/props API. And **no source here grants a right to resell raw box scores**.

## Per source

### ESPN site JSON, ESPN core JSON, ESPN tennis and MMA scoreboards (one set of terms)
* URL read: https://www.disneytermsofuse.com/english/ (Disney Terms of Use, which ESPN products fall under; ESPN has
  no separate API licence and the JSON endpoints are undocumented). The older espn.com terms URL returned 404.
* Clauses: prohibits "use the Disney Products for any commercial or business-related use" (s.2.B(viii)) and use of a
  "robot, spider, script, or other automated means" including for "data mining or web scraping" (s.2.B(x)); AI
  training on the products is also barred (s.2.A).
* Class: non-commercial; automated access prohibited. Whether the undocumented JSON counts as a "Disney Product" is
  untested, and the wording is broad.
* Ship: raw rows are tracked and in the image today. Risk **high**.
* Licensed alternative (core non-commercial source): BALLDONTLIE ALL-ACCESS, $299.99/month (the plan being cancelled;
  tier B for the price, from COVERAGE_MATRIX.md), whose terms (tier A, https://www.balldontlie.io/terms) say "any
  lawful personal or commercial purpose" and allow selling displayed data, but not a competing feed. SportsDataIO's
  commercial Leagues API is quote-only (a buyer-reported median of about $16,500 a year, tier B, via vendr.com); its
  public $99-$149/month tiers are not licensed for commercial redistribution. Sportradar is custom-quoted (third-party
  estimates from about 1,300 euros to $10,000+ a month, tier B, unverified).

### MLB statsapi (statsapi.mlb.com)
* URL read: https://gdx.mlb.com/components/copyright.txt (the notice every response points to).
* Clause: "Only individual, non-commercial, non-bulk use of the Materials is permitted"; anything else needs "prior
  written authorization from MLBAM".
* Class: non-commercial and non-bulk. The project's schedule use and the round-2 box-score layer are both "bulk" in
  this sense once automated.
* Ship: neither raw nor in the image (git-ignored, excluded). Keep it internal. Risk **high** for any paid surface.
* Alternative: written authorization from MLBAM (no published price, tier C), or a licensed feed: SportsDataIO (quote),
  Sportradar (quote), BALLDONTLIE ALL-ACCESS $299.99/month (MLB is on the plan).

### NHL api-web (api-web.nhle.com) and api.nhle.com/stats/rest
* URL read: https://www.nhl.com/info/terms-of-service. The page does not mention an API or robots.txt.
* Clauses: use "only for non-commercial, informational, personal use" (s.7); no "unauthorized spidering, scraping, or
  harvesting" (s.2); no "enter into a database" copying (s.7).
* Class: non-commercial. The API host is unofficial and has no terms of its own that we found.
* Ship: neither (play-by-play cache is git-ignored and image-excluded). Risk **high**.
* Alternative: BALLDONTLIE ALL-ACCESS $299.99/month (NHL on the plan); Sportradar/SportsDataIO by quote.

### nflverse (GitHub release assets)
* URL read: https://raw.githubusercontent.com/nflverse/nflverse-data/main/LICENSE.md.
* Clause: Creative Commons Attribution 4.0; reproduce, share and adapt, and "You must" keep creator identification,
  copyright notice and licence reference when sharing, and say what was changed (s.3(a)(1)).
* Class: commercial with attribution. The licence covers nflverse's compilation; it cannot clear rights the NFL or the
  original stat providers may hold (tier C on that point).
* Ship: raw rows are shipped; every record's `source` and the manifest keep the attribution (NFL_SCHEMA.md). Risk **low**.
* Alternative: none needed.

### Kalshi (api.elections.kalshi.com, public market data)
* URLs read: https://docs.kalshi.com/welcome (A). The Developer Agreement (https://kalshi.com/developer-agreement)
  returned HTTP 429 and was not read.
* Clause: "By continuing to use or access Kalshi's API, you are agreeing to be bound to our Developer Agreement."
* Class: unclear until the agreement is read. Treat as: read for analysis, do not redistribute prices.
* Ship: neither. Risk **medium**.
* Alternative: Kalshi's own commercial data terms, by contact (price unknown, tier C).

### The Odds API (the paid feed behind every odds and props capture)
* URL read: https://the-odds-api.com/terms-and-conditions.html.
* Clauses: use is allowed "including commercial use, provided our data is not the primary product being sold or
  redistributed"; "Do not resell, repackage, or redistribute our data as a standalone data product"; displaying in a
  UI or app, storing "indefinitely", computing derived values and training statistical/ML models are all listed as
  permitted.
* Class: commercial, conditional. Ship derived picks, edges and prices-in-context; never the stores as a feed.
* This applies to the player-props store (`allsports_props.jsonl`) and the multibook store. They are git-tracked in a
  public repository; the props store is kept out of the web image (`.dockerignore`), but public git history is
  itself a redistribution of a raw feed. If that matters, make the repository private or git-ignore the stores and
  archive them elsewhere (storage is not the constraint, RESOURCE_POLICY.md).
* Risk: **low** for a picks product, **high** for a data-service/API product built on these stores.
* Alternative: it is the licensed source; the plan is $59/month for 100,000 credits.

### football-data.co.uk
* URL read: https://www.football-data.co.uk/data.php.
* Clauses: "its use is intended for private individuals only, NOT commerical or data training products using
  automated bots/scrapers/AI" (their spelling), and the data is "made available for the purposes of league match
  prediction only". The notes page (notes.txt) states no licence.
* Class: non-commercial. The round-2 fetch is already gated (`--i-have-permission`).
* Ship: neither. Risk **high**.
* Licensed alternative: The Odds API's historical odds from 2020-06-06 on the existing plan (10x credit cost per call,
  `src/providers/odds.py`), or Sportmonks football plans at about 29 to 249 euros/month (tier B, third-party page).

### openfootball
* URL read: https://github.com/openfootball/england (one repository of the family).
* Clause: "The football.db schema, data and scripts are dedicated to the public domain."
* Class: commercial. Other repositories in the organisation may differ (check each before use).
* Ship: could ship. Risk **low**. Not built.

### EuroLeague / EuroCup official feeds (api-live.euroleague.net)
* URL tried: https://www.euroleaguebasketball.net/en/terms-and-conditions/ returned HTTP 429. **Not read.**
* Earlier rounds found no licence on the feed (tier B). Class: unclear; assume non-commercial until read.
* Ship: not built; derived only if built. Risk **medium**.
* Alternative: BALLDONTLIE ALL-ACCESS lists EuroLeague ($299.99/month).

### OpenLigaDB
* URL read: https://www.openligadb.de/ (statement in German, translated here).
* Clause: the data "stehen unter der Open Database License (ODbL)".
* Class: commercial with attribution; ODbL share-alike applies to a publicly shared derivative database, not to
  picks computed from it. Free community project, no key.
* Ship: not built; attribution required if shipped. Risk **low to medium**.

### Jolpica (Ergast-compatible F1 API)
* URL read: https://raw.githubusercontent.com/jolpica/jolpica-f1/main/TERMS.md.
* Clauses: "The API is freely available for non-commercial use" (commercial: contact the maintainers); "The data is
  licensed under Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International".
* Class: non-commercial. Ship: not built. Risk **high** if built.
* Alternative: BALLDONTLIE ALL-ACCESS lists F1 ($299.99/month); Sportradar F1 by quote.

### Sleeper (api.sleeper.app)
* URL read: https://docs.sleeper.com/.
* Clauses: "free to use for non-commercial purposes"; commercial use: contact Sleeper; "stay under 1000 API calls per
  minute, otherwise, you risk being IP-blocked"; attribution requested for the trending data.
* Class: non-commercial free tier. Ship: not built. Risk **medium**.
* Alternative for the NFL id crosswalk: nflverse's player-id tables (CC BY 4.0) at no cost.

### UFC.com
* URL read: https://www.ufc.com/terms.
* Clauses: no "deep-link", "page-scrape", "robot", "spider" or other automatic device; content for "non-commercial,
  personal, entertainment use"; "may not copy, reproduce, distribute, publish, enter into a database".
* Class: non-commercial; scraping barred. The profile layer (`src/datasvc/ufc/ufccom.py`) is a scrape and its files
  are tracked and shipped. Risk **high**.
* Alternative: BALLDONTLIE ALL-ACCESS lists MMA ($299.99/month); Sportradar MMA by quote.

## What was not obtainable today

The EuroLeague terms (HTTP 429) and Kalshi's Developer Agreement (HTTP 429) were not read, so those two rows are
unclear by construction, not by finding. The NHL api-web host and the ESPN JSON hosts publish no terms of their own;
the terms read are those of the parent sites (NHL.com, Disney). No price in this file was obtained from a vendor
quote; vendor prices marked tier B are third-party pages.
