/**
 * NFL-specific wording for the card and record screens.
 *
 * WHY THIS EXISTS
 * ---------------------------------------------------------------
 * card.js and cardrecord.js use sport-specific language:
 * MLB: "first pitch", "run line", "runs"
 * NFL: "kickoff", "spread", "points"
 *
 * This module provides the NFL wording map so card.js and
 * cardrecord.js can read it by sport.
 */

export const NFL_WORDING = {
  start: "kickoff",
  startPlural: "kickoffs",
  alternative: "spread",
  unit: "points",
  record: "NFL PICKS (W-L-P)",
};
