"""Reading a question: a typo-tolerant normalizer and a scorer that names ONE intent. Pure text, no data, no model.

WHY SCORING AND NOT A CHAIN OF IF-STATEMENTS. The first matcher (``ask.classify`` before 2026-10-19) was an
ordered list of regexes: the first one that fired won. It lost a real question from the owner's production test,
typed on a phone with no punctuation and one slipped key: "What bets would yopu have taken today pre market"
fell through to "what did you bet today" and a member dog with no tickets answered "I have not recorded a ticket
yet, so there is nothing to say about my bets". Every word that carried the meaning ("would", "have taken",
"pre market") was ignored because "yopu" matched nothing. People type "wat", "wud", "tday", "rn", "u"; a matcher
for a betting chat has to expect that.

HOW IT WORKS.
  1. ``normalize`` lowercases, drops punctuation and apostrophes, fixes the known slang and typos token by token
     (``yopu`` -> ``you``, ``wud`` -> ``would``, ``tday`` -> ``today``, ``rn`` -> ``right now``), repairs an unknown
     misspelling of a word the matcher knows with a close-match search (a long word, same first letter, one
     slip), stems each word lightly (``bets``/``betting`` -> ``bet``, ``taken``/``took`` -> ``take``) and folds the
     handful of multi-word ideas into one marker each (``premarket``, ``rightnow``, ``earlier``, ``wouldhave``).
  2. ``scores`` adds up weighted features per intent over that text. Several intents can fire on one question
     ("what would you have taken today pre market" is a bet question, a "today" question and a hindsight
     question); the largest total wins, ties go to the order of ``PRIORITY``. Below ``MIN_SCORE`` the question is
     unknown and the dog answers with the closest thing and the menu (never a dead end).

A team or player name must never be "corrected" into a betting word, so the caller can pass the words to protect.
"""

from __future__ import annotations

import difflib
import re
from typing import Dict, Iterable, Optional

# Highest first: when two intents score the same, the earlier one here wins.
PRIORITY = ("picks_earlier_today", "backtest_window", "picks_now", "why_not", "why_bet", "best_worst",
            "today", "explain_market", "record", "rules", "improve", "fans", "coach", "help", "hello")
MIN_SCORE = 3.0

# ---------------------------------------------------------------------------
# slang and slips, token by token (a value may be several words)
# ---------------------------------------------------------------------------

TYPOS = {
    # you / your
    "yopu": "you", "yuo": "you", "yoy": "you", "yu": "you", "ya": "you", "u": "you", "youu": "you", "yoi": "you",
    "ur": "your", "yur": "your", "youre": "you are", "yall": "you", "ye": "you",
    # what / when / why / how
    "wat": "what", "wht": "what", "waht": "what", "whta": "what", "wut": "what", "whut": "what", "hwat": "what",
    "whats": "what is", "wats": "what is", "whatre": "what are", "whatchu": "what you", "wassup": "what is up",
    "hows": "how is", "howd": "how did", "wy": "why", "wyh": "why", "whyd": "why did", "hwo": "how", "hw": "how",
    "whn": "when", "wen": "when",
    # would / should / could / have / do
    "wud": "would", "wld": "would", "woud": "would", "wouldd": "would", "woudl": "would", "wouldnt": "would not",
    "wouldve": "would have", "woulda": "would have", "shouldve": "would have", "shoulda": "would have",
    "couldve": "would have", "coulda": "would have", "shud": "should", "shld": "should", "cud": "could",
    "hve": "have", "hav": "have", "havent": "have not", "ave": "have", "dont": "do not", "didnt": "did not",
    "doesnt": "does not", "cant": "can not", "wont": "will not", "isnt": "is not", "dunno": "do not know",
    "gonna": "going to", "wanna": "want to", "gotta": "got to", "gimme": "give me", "lemme": "let me",
    "tell": "tell", "pls": "", "plz": "", "please": "", "pleeze": "", "kindly": "",
    # time words
    "tday": "today", "todai": "today", "2day": "today", "todya": "today", "tdy": "today", "toady": "today",
    "tonite": "tonight", "2nite": "tonight", "tnite": "tonight", "tonigt": "tonight", "tongiht": "tonight",
    "tn": "tonight", "yday": "yesterday", "yest": "yesterday", "yesturday": "yesterday", "yesterdy": "yesterday",
    "rn": "right now", "rite": "right", "nw": "now", "atm": "right now", "mornin": "morning", "morn": "morning",
    "wknd": "weekend", "weeknd": "weekend", "wk": "week", "wks": "weeks", "thsi": "this", "ths": "this",
    "lst": "last", "pst": "past", "prev": "previous", "dys": "days",
    # betting words
    "bett": "bet", "bte": "bet", "btes": "bets", "pck": "pick", "pcik": "pick", "pciks": "picks", "picsk": "picks",
    "pikc": "pick", "pic": "pick", "pics": "picks", "plya": "play", "plays": "plays", "taek": "take", "tkae": "take",
    "tken": "taken", "tooks": "took", "taking": "taking", "wager": "wager", "wagr": "wager", "hindsite": "hindsight",
    "backtst": "backtest", "bactest": "backtest", "recrod": "record", "reocrd": "record", "rcord": "record",
    "rec": "record", "recrd": "record", "perfomance": "performance", "preformance": "performance",
    "stratgy": "strategy", "straegy": "strategy", "stragety": "strategy", "improv": "improve",
    "imrpove": "improve", "improvr": "improve", "prmarket": "premarket", "premkt": "premarket",
    "pregame": "premarket", "mkt": "market", "mrkt": "market", "ml": "moneyline", "moneline": "moneyline",
    "runline": "run line", "rl": "run line", "ou": "over under", "o/u": "over under", "dog": "dog",
    "fav": "favourite", "favorite": "favourite", "favorites": "favourite", "favourites": "favourite",
    "favs": "favourite", "dogs": "underdog", "underdogs": "underdog", "ud": "underdog",
    "gam": "game", "gaem": "game", "gmae": "game", "gams": "games", "wot": "what", "thx": "", "ty": "",
    "abt": "about", "cuz": "because", "bc": "because", "coz": "because", "cos": "because", "idk": "do not know",
    "ok": "", "okay": "", "so": "", "hey": "hey", "yo": "hello", "sup": "hello", "heya": "hello", "hiya": "hello",
    "hii": "hi", "hiii": "hi", "helo": "hello", "hellp": "hello", "halp": "help", "hlp": "help", "hepl": "help",
}

# phrases folded to one marker after tokens are fixed and stemmed (order matters: longer first)
PHRASES = (
    (r"\b(?:pre ?market|pre ?game|before (?:the )?(?:market|game|games|first pitch|start))\b", " premarket "),
    (r"\b(?:right now|as of now|at the moment|for now|at this moment|currently|this very moment|this minute)\b", " rightnow "),
    (r"\b(?:this morning|earlier today|earlier|so far today|by now|up to now|this afternoon so far|before now)\b", " earlier "),
    (r"\blast night\b", " lastnight "),
    (r"\b(?:last|past|previous|prior) weekend\b", " lastweekend "),
    (r"\b(?:last|past|previous|prior|over the last|over the past) week\b", " lastweek "),
    (r"\bthis week\b", " thisweek "),
    (r"\b(?:this|last|past|previous|prior|over the last|over the past) month\b", " lastmonth "),
    (r"\b(?:last|past|previous|prior|over the last|over the past|in the last|in the past|within the last) (\d{1,2}) day\b", r" lastdays \1 "),
    (r"\b(?:last|past|previous|prior|over the last|over the past|in the last|in the past) (\d{1,2}) week\b", r" lastweeks \1 "),
    (r"\b(\d{1,2}) day\b", r" lastdays \1 "),
    (r"\b(?:would|should|could|will) (?:you |i |we )?(?:have|of|ve)\b", " wouldhave "),
    (r"\b(?:if you had|if you have|had you|what if you)\b", " wouldhave "),
    (r"\bover under\b", " overunder "),
    (r"\bmoney ?line\b", " moneyline "),
    (r"\brun ?line\b", " runline "),
    (r"\bpoint spread\b", " spread "),
    (r"\bpaper bankroll\b", " bankroll "),
    (r"\bclosing line(?: value)?\b", " clv "),
    (r"\bimplied (?:probability|prob|odds)\b", " impliedprob "),
    (r"\b(?:american )?odds format\b", " odds "),
    (r"\bline mov(?:e|ement|ing)\b", " steam "),
)

# canonical words fuzzy repair may land on (stemmed forms); built from the keyword families plus everyday words
VOCAB = frozenset("""
what would you have take today tonight tomorrow yesterday morning evening afternoon week weekend month record
strategy system logic method criteria approach explain improve better train teach change suggest coach upgrade
bet pick play back choose wager ticket slate games game team like lean target fire anything something nothing
please help menu options commands answer tell show give any best worst biggest greatest top win lose loss beat
perform performance result streak status standing rank verdict form units unit bankroll odds spread total prop
props moneyline runline favourite underdog parlay push vig juice steam clv market premarket backtest hindsight
drill replay simulate earlier ealier now right currently tonight skip pass ignore avoid miss reason because why
how come think fans feedback rating review tips coach rules rule hello who name build built about yourself
doing going really profit profitable money made lost bankroll paper edge angle secret overunder
""".split())

_STOP_FUZZ = frozenset("""
this that them then than they their there these those with from have what when where which while would could
should about after again before being below between during other since still those under until which while
""".split())

# ---------------------------------------------------------------------------
# stemming
# ---------------------------------------------------------------------------

IRREGULAR = {
    "took": "take", "taken": "take", "takes": "take", "taking": "take", "tooken": "take",
    "chose": "choose", "chosen": "choose", "chooses": "choose", "choosing": "choose",
    "backed": "back", "backing": "back", "backs": "back",
    "won": "win", "wins": "win", "winning": "win", "lost": "lose", "losing": "lose", "loses": "lose",
    "losses": "loss", "made": "make", "making": "make", "placed": "place", "placing": "place", "places": "place",
    "went": "go", "gone": "go", "saw": "see", "seen": "see", "thought": "think", "liked": "like", "likes": "like",
    "betting": "bet", "bets": "bet", "betted": "bet", "bettin": "bet", "picking": "pick", "picked": "pick",
    "picks": "pick", "playing": "play", "played": "play", "plays": "play", "wagers": "wager", "wagered": "wager",
    "odds": "odd", "was": "was", "has": "has", "this": "this", "does": "does", "is": "is", "its": "its",
    "less": "less", "yes": "yes", "unless": "unless", "us": "us", "as": "as", "gas": "gas",
    "morning": "morning", "evening": "evening", "anything": "anything", "something": "something",
    "nothing": "nothing", "everything": "everything", "thing": "thing", "during": "during", "string": "string",
    "bring": "bring", "spring": "spring", "king": "king", "ring": "ring", "sing": "sing", "wing": "wing",
    "series": "series", "news": "news", "always": "always", "perhaps": "perhaps", "across": "across",
    "texas": "texas", "dallas": "dallas", "atlanta": "atlanta", "chicago": "chicago", "kansas": "kansas",
}


def stem(word: str) -> str:
    w = word
    if w in IRREGULAR:
        return IRREGULAR[w]
    if len(w) <= 3:
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("sses"):
        return w[:-2]
    if w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    for suffix, floor in (("ing", 6), ("ed", 5)):
        if w.endswith(suffix) and len(w) >= floor:
            base = w[: -len(suffix)]
            if len(base) >= 3 and base[-1] == base[-2] and base[-1] not in "lsz":
                base = base[:-1]
            return base
    return w


_VOCAB_STEMS = tuple(sorted({stem(v) for v in VOCAB}))
_CLEAN = re.compile(r"[^a-z0-9+\-/ ]+")


def _fuzzy(token: str, protected: frozenset) -> str:
    """A close repair of a long unknown token to a word the matcher knows, else the token unchanged.

    Deliberately conservative: only tokens of five letters or more, the same first letter, and a similarity of
    0.8 or better, so ``tonigt`` -> ``tonight`` and ``recrod`` -> ``record`` but ``giants`` and ``astros`` are
    left alone (and a caller can protect the team words it knows)."""
    if len(token) < 5 or token in protected or token in VOCAB or token in _STOP_FUZZ or token.isdigit():
        return token
    if token in _VOCAB_STEMS:
        return token
    pool = [v for v in _VOCAB_STEMS if v[0] == token[0] and abs(len(v) - len(token)) <= 2]
    hit = difflib.get_close_matches(token, pool, n=1, cutoff=0.8)
    return hit[0] if hit else token


def normalize(question: str, protect: Iterable[str] = ()) -> str:
    """The question as the scorer reads it. See the module docstring for each step."""
    protected = frozenset(str(p).lower() for p in protect)
    text = str(question or "").lower().replace("’", "").replace("'", "")
    text = text.replace("pre-market", "premarket").replace("o/u", "over under")
    text = _CLEAN.sub(" ", text)
    tokens = []
    for tok in text.split():
        if tok in protected:
            tokens.append(tok)
            continue
        fixed = TYPOS.get(tok, tok)
        for part in fixed.split():
            part = _fuzzy(part, protected)
            tokens.append(stem(part) if part not in protected else part)
    out = " ".join(tokens)
    for pattern, repl in PHRASES:
        out = re.sub(pattern, repl, out)
    return re.sub(r"\s+", " ", out).strip()


# ---------------------------------------------------------------------------
# the features
# ---------------------------------------------------------------------------

def _rx(text: str, pattern: str) -> bool:
    return re.search(pattern, text) is not None


BETV = r"(?:bet|pick|take|play|back|choose|wager|ticket|lean|target|fire|like|go with|lock|selection|side)"
TIMEWORD = r"(?:today|tonight|tomorrow|rightnow|earlier|premarket|morning|evening|afternoon|now|slate)"
GAME_WORDS = r"(?:game|slate|matchup|team|board|card|schedule)"
WINDOW = r"(?:thisweek|lastweek|lastweekend|lastmonth|lastdays|lastweeks|yesterday|lastnight)"

GLOSSARY_TERMS = (
    ("runline", r"\brunline\b|\brun line\b"),
    ("spread", r"\bspread\b|\bpoint spread\b|\bhandicap\b"),
    ("moneyline", r"\bmoneyline\b"),
    ("total", r"\bover ?under\b|\btotals?\b|\bo/u\b|\bover\b.*\bunder\b"),
    ("prop", r"\bprops?\b|\bplayer props?\b"),
    ("unit", r"\bunit\b|\bunits\b|\bstake\b"),
    ("bankroll", r"\bbankroll\b|\bpaper money\b"),
    ("vig", r"\bvig\b|\bjuice\b|\bvigorish\b|\bhold\b"),
    ("parlay", r"\bparlay\b|\bteaser\b|\baccumulator\b"),
    ("push", r"\bpush\b"),
    ("odds", r"\bodd\b|\bamerican odd\b|\b\+\d{3}\b|\bdecimal odd\b|\bplus money\b|\bminus money\b"),
    ("impliedprob", r"\bimpliedprob\b|\bwin probability\b|\bprobability\b"),
    ("favourite", r"\bfavourite\b|\bunderdog\b"),
    ("clv", r"\bclv\b"),
    ("steam", r"\bsteam\b|\bsharp\b"),
    ("roi", r"\broi\b|\byield\b|\breturn\b"),
)
DEFINE = r"(?:what is|what are|what does|what do|what s|explain|define|meaning|mean\b|how do|how does|how is|tell me about|teach me|eli5|never heard|no idea|dont know|do not know|whats|what)"


def glossary_term(text: str) -> Optional[str]:
    """The betting term a question is about ('spread', 'unit', ...), or None. ``text`` is normalized."""
    for key, pattern in GLOSSARY_TERMS:
        if re.search(pattern, text):
            return key
    return None


def _add(score: Dict[str, float], intent: str, weight: float) -> None:
    score[intent] = score.get(intent, 0.0) + weight


def scores(question: str, protect: Iterable[str] = (), *, team_named: bool = False) -> Dict[str, float]:
    """{intent: score} for a question. ``team_named`` says the caller found a team or player of the dog's in it."""
    t = normalize(question, protect)
    s: Dict[str, float] = {k: 0.0 for k in PRIORITY}
    if not t:
        return s
    has = lambda pattern: _rx(t, pattern)               # noqa: E731
    you = has(r"\byou\b|\byour\b|\bu\b|\bdog\b")
    betv = has(r"\b" + BETV + r"\b")
    would = has(r"\bwould\b|\bwill\b|\bshould\b|\bgoing to\b|\bwanna\b|\bwant\b|\bgot to\b|\bmight\b")
    hindsight = has(r"\bwouldhave\b|\bhindsight\b|\bbacktest\b|\bback test\b|\breplay\b|\bsimulate\b|\bdrill\b|\bwhat if\b")
    timeword = has(r"\b" + TIMEWORD + r"\b")
    window = has(r"\b" + WINDOW + r"\b")
    why = has(r"(^|\b)why\b") or has(r"\bhow come\b|\bwhat make you\b|\bwhats the reason\b|\bwhat is the reason\b|\breason for\b|\breason you\b")
    neg = has(r"\b(?:not|no bet|no pick|skip|pass|ignore|avoid|miss|sit out|sat out|leave out|left out|except)\b") \
        or has(r"\bwhy no\b|\bwhy not\b")
    did = has(r"\b(?:did you|have you|had you|do you have|you have|you placed|you made|you took|you take)\b")

    # --- picks_earlier_today: hindsight about TODAY's boards at each game's decision time -----------------------
    if has(r"\bpremarket\b"):
        _add(s, "picks_earlier_today", 4.0)
    if has(r"\bearlier\b|\bmorning\b|\bby now\b"):
        _add(s, "picks_earlier_today", 2.0)
    if has(r"\bwouldhave\b") and has(r"\b(?:today|tonight|earlier|premarket|morning|evening|afternoon|lastnight)\b") \
            and not has(r"\b(?:lastweek|thisweek|lastweekend|lastmonth|lastdays|lastweeks|yesterday)\b"):
        _add(s, "picks_earlier_today", 4.0)
    if betv and (has(r"\bpremarket\b") or has(r"\bearlier\b")):
        _add(s, "picks_earlier_today", 1.0)

    # --- backtest_window: the rule replayed over several past days ------------------------------------------------
    if has(r"\b(?:thisweek|lastweek|lastweekend|lastmonth|lastdays|lastweeks)\b"):
        _add(s, "backtest_window", 3.0)
    if has(r"\byesterday\b|\blastnight\b"):
        _add(s, "backtest_window", 2.0)
    if has(r"\bwouldhave\b") and window:
        _add(s, "backtest_window", 4.0)
    if has(r"\b(?:backtest|back test|replay|simulate|drill|hindsight|rehearsal|training camp|what if)\b"):
        _add(s, "backtest_window", 5.0 if window or has(r"\bday\b|\bweek\b|\bmonth\b") else 3.0)
    if window and has(r"\b(?:done|do|go|fare|perform|result|win|lose|profit|made|make)\b") and has(r"\bwouldhave\b"):
        _add(s, "backtest_window", 2.0)

    # --- picks_now: what the dog would take on the boards as they stand -------------------------------------------
    if has(r"\brightnow\b"):
        _add(s, "picks_now", 3.0)
    if has(r"\bnow\b") and not has(r"\brightnow\b"):
        _add(s, "picks_now", 2.0)
    if has(r"\btonight\b|\bthis evening\b|\bfor tonight\b"):
        _add(s, "picks_now", 2.0)
    if has(r"\btoday\b|\bslate\b"):
        _add(s, "picks_now", 1.0)
    if would and betv and you:
        _add(s, "picks_now", 3.0)
    if has(r"\bany (?:pick|play|bet|lean|action|good|value|game|thing|one)\b|\banything\b|\bsomething\b"):
        _add(s, "picks_now", 3.0)
    if has(r"\bwho do you (?:like|lean|want|take|back|favou?r|see)\b|\bwho you like\b|\bwho s your\b"):
        _add(s, "picks_now", 5.0)
    if has(r"\b(?:give|show|got|have|send|drop|hit)\b.{0,12}\b(?:pick|play|bet|lean|lock|card|slate|one)\b") \
            and not did:
        _add(s, "picks_now", 4.0)
    if has(r"\b(?:what is|what s)\b.{0,6}\b(?:the |your )?(?:pick|play|lean|take|call|card|word)\b") or has(r"\bwhat you got\b|\bwhat do you got\b"):
        _add(s, "picks_now", 4.0)
    if has(r"\bwhat do you like\b|\bwhat are you (?:think|see|look|bet|back|take|play|like)\b|\bwhat do you see\b|\bwhat do you want\b|\bwhat you think\b"):
        _add(s, "picks_now", 4.0)
    if has(r"\bfire\b|\btake them out back\b|\bout back\b"):
        _add(s, "picks_now", 5.0)
    if has(r"\b(?:best|top|strongest|favourite) (?:bet|pick|play|lean|value)\b") and has(r"\b(?:today|tonight|rightnow|now|slate)\b"):
        _add(s, "picks_now", 5.0)
    if has(r"\b(?:any|got|have|where is|wheres)\b.*\b(?:value|edge|angle|action)\b") and timeword:
        _add(s, "picks_now", 2.0)
    if betv and has(r"\b(?:on the board|on the slate|for today|for tonight|on tonight)\b"):
        _add(s, "picks_now", 2.0)
    if betv and timeword and you and not did and not hindsight and not why:
        _add(s, "picks_now", 1.0)

    # --- why_bet / why_not ----------------------------------------------------------------------------------------
    if why:
        _add(s, "why_bet", 3.0)
        if betv or team_named or has(r"\b(?:go with|favourite|side|team|that one|this one|pick|game)\b"):
            _add(s, "why_bet", 2.0)
        if neg:
            _add(s, "why_not", 6.0)
    if has(r"\bwhy not\b|\bwhy no\b|\bwhy did you (?:not|skip|pass|ignore|avoid|miss)\b|\bdid not you (?:bet|take|pick|back|play)\b"):
        _add(s, "why_not", 5.0)
    if has(r"\bdid not you (?:bet|take|pick|back|play)\b|\bwhy (?:did you )?not\b"):
        _add(s, "why_not", 3.0)
    if has(r"\bexplain (?:that|this|your|the|it|why)\b.*\b(?:bet|pick|ticket|play)\b|\bexplain (?:that|this) one\b"):
        _add(s, "why_bet", 5.0)
    if has(r"\bwhat make you\b") or has(r"\bwhat s behind\b|\bwhat is behind\b"):
        _add(s, "why_bet", 4.0)

    # --- best_worst -----------------------------------------------------------------------------------------------
    if has(r"\b(?:best|worst|biggest|top|greatest|baddest|largest|ugliest)\b") \
            and has(r"\b(?:bet|pick|win|loss|lose|beat|call|ticket|play|winner|loser|hit|miss)\b"):
        _add(s, "best_worst", 5.0)
    if has(r"\bworst beat\b|\bbad beat\b"):
        _add(s, "best_worst", 5.0)

    # --- today: the dog's RECORDED tickets ------------------------------------------------------------------------
    if did and (betv or has(r"\bwager\b|\baction\b|\bticket\b")):
        _add(s, "today", 4.0)
    if has(r"\byour (?:bet|pick|ticket|play|wager|action)\b") and (timeword or window or has(r"\b(?:open|latest|last|recent|pending|current)\b")):
        _add(s, "today", 4.0)
    if has(r"\b(?:open|pending|latest|recent|last)\b") and has(r"\b(?:bet|pick|ticket|play|wager)\b"):
        _add(s, "today", 4.0)
    if has(r"\b(?:bet|pick|ticket|play)\b") and has(r"\b(?:so far|already|lately|open)\b"):
        _add(s, "today", 3.0)
    if has(r"\b(?:yesterday|lastnight|today|tonight)\b") and has(r"\b(?:did you|have you|you made|you placed|you took)\b"):
        _add(s, "today", 1.0)
    if has(r"\bwhat (?:bet|pick|ticket|play)\b.{0,20}\b(?:do you have|you got|are open|are pending)\b"):
        _add(s, "today", 2.0)

    # --- record ---------------------------------------------------------------------------------------------------
    if has(r"\bhow (?:are|is) you (?:do|go|look|run|perform|hold)\w*\b|\bhow is it going\b|\bhow you do\w*\b|\bhow you been\b|\bhow have you been\b|\bhow did you do\b|\bhow you do\b"):
        _add(s, "record", 4.0)
    if has(r"\b(?:record|roi|clv|perform|performance|streak|standing|rank|verdict|status|result|form|leaderboard|stats|numbers|scoreboard)\b"):
        _add(s, "record", 4.0)
    if has(r"\b(?:win|lose|loss)\b") and has(r"\b(?:how many|how much|are you|you up|you down|win rate|percent|percentage|total)\b"):
        _add(s, "record", 4.0)
    if has(r"\bany good\b|\bare you good\b|\bworth (?:it|follow|follow ing)\b|\bare you (?:profitable|up|down|hot|cold|worth)\b|\bhow good\b|\bgood or bad\b"):
        _add(s, "record", 4.0)
    if has(r"\b(?:units?|bankroll|balance|profit|money|dollar|up|down)\b") and has(r"\b(?:how many|how much|are you|you up|you down|have you (?:win|lose|made)|your)\b") \
            and not has(r"\b(?:what is|what s) (?:a|an|the) (?:unit|bankroll)\b"):
        _add(s, "record", 3.0)

    # --- rules ----------------------------------------------------------------------------------------------------
    if has(r"\b(?:rule|strategy|system|logic|method|criteria|approach|algorithm|formula|model|filter|trigger|recipe)\b") and you:
        _add(s, "rules", 5.0)
    if has(r"\b(?:rule|strategy|logic|method|criteria|approach)\b"):
        _add(s, "rules", 2.0)
    if has(r"\bhow do you (?:pick|choose|decide|work|bet|select|find|play|do it|make|come up)\b|\bwhat do you bet on\b|\bwhat do you look for\b|\bwhat are you looking for\b|\bexplain yourself\b|\bhow do you do it\b"):
        _add(s, "rules", 5.0)
    if has(r"\b(?:edge|angle|secret|sauce|trick|thesis|philosophy)\b") and you:
        _add(s, "rules", 4.0)
    if has(r"\bwhen do you (?:bet|pick|play|take|back|fire)\b|\bwhat make you (?:bet|take|pick|play)\b") and not why:
        _add(s, "rules", 3.0)

    # --- improve --------------------------------------------------------------------------------------------------
    if has(r"\b(?:improve|better|train|teach|tweak|tune|change|suggest|coach you|upgrade|fix|adjust|edit|modify|update|level up|smarter|stronger)\b") \
            and (you or has(r"\bhow\b|\bcan i\b|\bmake\b")):
        _add(s, "improve", 5.0)
    if has(r"\bhow (?:do|can|should) i (?:help|make|change|teach|train|fix|tune|improve|coach|edit)\b"):
        _add(s, "improve", 4.0)
    if has(r"\b(?:improve|train you|teach you|make you better|fix you|tweak you|tune you)\b"):
        _add(s, "improve", 2.0)

    # --- explain_market -------------------------------------------------------------------------------------------
    term = glossary_term(t)
    if term is not None:
        definitional = has(r"\b(?:what is|what are|what does|what do|what s|explain|define|meaning|mean|how do|how does|how is|tell me about|teach me|eli5|never heard|no idea|do not know|whats)\b")
        about_dog = has(r"\byour\b") or has(r"\bhow many\b.*\b(?:you|are you)\b") or has(r"\bare you\b") or has(r"\byou up\b|\byou down\b")
        if definitional and not about_dog:
            _add(s, "explain_market", 6.0)
        elif has(r"\b(?:explain|define|meaning|mean)\b") and not about_dog:
            _add(s, "explain_market", 5.0)
        elif definitional and has(r"\b(?:a|an|the) " + re.escape(term) + r"\b"):
            _add(s, "explain_market", 4.0)

    # --- fans, coach, help, hello --------------------------------------------------------------------------------
    if has(r"\b(?:fan|people think|feedback|review|rating|what do people|good call|bad call|crowd|vote|thumbs|likes)\b"):
        _add(s, "fans", 5.0)
    if has(r"\b(?:coach|tip|tipped|tip box|advice from)\b"):
        _add(s, "coach", 5.0)
    if has(r"\bhelp\b|\bmenu\b|\boptions?\b|\bcommands?\b|\bwhat can you (?:do|answer|tell|say|help)\b|\bwhat can i (?:ask|say|type)\b|\bhow does this work\b|\bhow do i use\b|\bwhat do you know\b|\bwhat can u\b|\bsuggestions?\b"):
        _add(s, "help", 6.0)
    if has(r"\bwho are you\b|\bhello\b|\bhi\b|\bhey\b|\byour name\b|\bwho (?:make|build|made|built|create) you\b|\bintroduce\b|\babout you(?:rself)?\b|\bwhat are you$|\bwhat is your name\b|\bwhat s your name\b|\bgreet\w*\b|\bgood (?:morning|evening|afternoon)\b|\bhow are you\b"):
        _add(s, "hello", 5.0 if not has(r"\bhow (?:are|is) you (?:do|go)") else 1.0)
    if has(r"^(?:hi|hey|hello|yo|sup)\b"):
        _add(s, "hello", 2.0)

    # "what bets would you have taken today": hindsight, not a plain 'now'
    if s["picks_earlier_today"] >= MIN_SCORE:
        s["picks_now"] = max(0.0, s["picks_now"] - 3.0)
        s["today"] = max(0.0, s["today"] - 2.0)
    # a hindsight word that names a window is the backtest, not today's rewind
    if s["backtest_window"] >= MIN_SCORE and window and has(r"\b(?:thisweek|lastweek|lastweekend|lastmonth|lastdays|lastweeks)\b"):
        s["picks_earlier_today"] = 0.0
    # "how did you do this week" is the record, not a replay
    if has(r"\bhow (?:did|are|is|have) you\b") and not hindsight:
        s["backtest_window"] = max(0.0, s["backtest_window"] - 3.0)
    # a definitional question is not a record question, and vice versa
    if s["explain_market"] >= MIN_SCORE:
        s["record"] = max(0.0, s["record"] - 4.0)
        s["rules"] = max(0.0, s["rules"] - 2.0)
    return s


def best_intent(scored: Dict[str, float]) -> tuple:
    """(intent, score) with the highest score, ties broken by ``PRIORITY``."""
    best, top = None, 0.0
    for name in PRIORITY:
        value = scored.get(name, 0.0)
        if value > top:
            best, top = name, value
    return best, top


# ---------------------------------------------------------------------------
# a time window named in a question
# ---------------------------------------------------------------------------

def parse_window(question: str, protect: Iterable[str] = ()) -> dict:
    """What span of days a replay question asks for: {'kind', 'days', 'label'} with ``days`` one of 7, 14, 30.

    ``kind`` is 'yesterday', 'weekend', 'thisweek', 'week', 'days', 'month' or 'default'. A request longer than
    30 days is shortened to 30 and says so (``clipped``); the drill's own choices are 7, 14 and 30."""
    t = normalize(question, protect)
    m = re.search(r"\blastdays (\d{1,2})\b", t)
    if m:
        n = int(m.group(1))
        days = 7 if n <= 7 else 14 if n <= 14 else 30
        return {"kind": "days", "days": days, "n": n, "label": f"the last {n} days", "clipped": n > 30}
    m = re.search(r"\blastweeks (\d{1,2})\b", t)
    if m:
        n = int(m.group(1)) * 7
        days = 7 if n <= 7 else 14 if n <= 14 else 30
        return {"kind": "days", "days": days, "n": n, "label": f"the last {int(m.group(1))} weeks", "clipped": n > 30}
    if _rx(t, r"\blastweekend\b"):
        return {"kind": "weekend", "days": 7, "label": "last weekend", "clipped": False}
    if _rx(t, r"\blastmonth\b"):
        return {"kind": "month", "days": 30, "label": "the last 30 days", "clipped": False}
    if _rx(t, r"\blastweek\b"):
        return {"kind": "week", "days": 7, "label": "the last 7 days", "clipped": False}
    if _rx(t, r"\bthisweek\b"):
        return {"kind": "thisweek", "days": 7, "label": "this week", "clipped": False}
    if _rx(t, r"\byesterday\b|\blastnight\b"):
        return {"kind": "yesterday", "days": 7, "label": "yesterday", "clipped": False}
    return {"kind": "default", "days": 7, "label": "the last 7 days", "clipped": False}
