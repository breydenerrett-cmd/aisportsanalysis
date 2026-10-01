import re
ab = [('DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1', 'V1-GAME'), ('DAILY_CARD_PROP_LIKELY_AND_CLEARS_PRICE_V1', 'V1-PROP'),
      ('DAILY_CARD_BEST_BETS_V2_SHADOW_A_BAND_ONLY', 'V2-shA'), ('DAILY_CARD_BEST_BETS_V2_SHADOW_C_OTHER_WORST_PRI', 'V2-shC'),
      ('DAILY_CARD_BEST_BETS_V2_SHADOW_E_LIKELY_FIRST', 'V2-shE'), ('DAILY_CARD_BEST_BETS_V2', 'V2'),
      ('MLB_VALUE_SHADOW_V1_A_TOTAL_BASES', 'MVS-A_TB'), ('MLB_VALUE_SHADOW_V1_B_HITS', 'MVS-B_HITS'), ('MLB_VALUE_SHADOW_V1_C_RUN_LINE', 'MVS-C_RL'),
      ('mlb_favorite_trails_after_3', 'LIVE-fav_trails3'), ('mlb_starter_pulled_early', 'LIVE-starter_pulled'),
      ('batter_total_bases', 'TB'), ('batter_hits', 'hits'), ('batter_runs_scored', 'runs_scored'), ('run_line/spread', 'run_line'), ('moneyline_inplay', 'ML_inplay'), ('moneyline', 'ML'),
      ('PUBLIC   ', 'PUB'), ('SHADOW   ', 'SHAD'), ('cand(not_elig)', 'cand'), ('fill(SPLIT)', 'SPLIT')]
for l in open('out_record_table.txt', encoding='utf-8'):
    if l.startswith('### PAPER'): break
    if l.startswith('###') or not l.strip(): continue
    if l.startswith('RULE'): continue
    rule = l[:48].strip(); rest = l[49:]
    for a, b in ab: rule = rule.replace(a, b); rest = rest.replace(a, b)
    parts = rest.split()
    print(rule.ljust(19), ' '.join(parts))
