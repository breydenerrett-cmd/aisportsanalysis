"""Voice for the AI desk's hounds: bio, catchphrase, vibe, and the Houndmaster's one-liners.

Presentation only. Nothing here reaches a prompt, a prompt hash, a rule or a result: roles.py puts it in
config/desk_hounds.json (`config --write`) beside each hound, and the site reads it from there. The other
hounds carry their persona in config/house_pack.json and config/house_hounds.json; the voice guide is
docs/VOICE.md.
"""

DESK_PERSONAS = {
    "desk_ai": {
        "bio": "Four analysts, a bull, a bear, and a desk head who argues it out in public. One AI model reading, not a prophet.",
        "catchphrase": "Let's go to the desk.",
        "vibe": "nerd",
        "roasts": [
            "Seven voices at the table and still a loss. Too many cooks, Desk.",
            "The bull and the bear argued all afternoon and the game ignored them both.",
            "The head took the bet. The head can eat the loss.",
            "An argument is not a result, Desk.",
            "Four reports, two bets, zero cash. Nice committee."
        ],
        "brags": [
            "The desk found a winner. Somebody get the analysts a coffee.",
            "Bull won the argument and the bet. Bear is sulking.",
            "Committee work paid tonight. That never happens.",
            "The desk head cashed. Do not read the transcript.",
            "Even a committee gets lucky. Enjoy."
        ],
        "epitaph": "Argued until the clock ran out.",
        "verb": "argued it out and took"
    },
    "desk_sharp": {
        "bio": "A cool AI persona that ignores narratives. Takes a selection only when the best price is below the books' own fair number, and says so.",
        "catchphrase": "Show me the price.",
        "vibe": "grinder",
        "roasts": [
            "Price said buy, game said no. The price is a number. The game is a game.",
            "You ignore stories and the story still got you.",
            "Cold, calculating, down. Fantastic.",
            "Zero narrative, zero cash. Flawless execution of a bad night.",
            "Even the sharpest knife slips."
        ],
        "brags": [
            "The price was right and so was the bet. Quiet, professional, annoying.",
            "No stories, just receipts. Fine.",
            "Beat the number and cashed. Go back to being silent.",
            "Cold-blooded and paid. I approve.",
            "Price over narrative. Tonight, anyway."
        ],
        "epitaph": "Only cared about the price. The price stopped caring.",
        "verb": "hunted the price on"
    },
    "desk_square": {
        "bio": "A deliberate control that bets like a casual fan. Only favorites and overs, never an underdog, never a spread. The recreational bettor with a robot's patience.",
        "catchphrase": "The favorite. The over. Done.",
        "vibe": "degen",
        "roasts": [
            "Favorites and overs. What could go wrong? Everything. You found it.",
            "The casual special: lose in two different ways.",
            "You bet like a guy at a bar. The bar won.",
            "The over died in the seventh. So did your night.",
            "Chalk and chaos. You got chaos."
        ],
        "brags": [
            "Favorite won, over hit, beer's on you.",
            "Casual bettor's dream. Do not tell the pros.",
            "The square cashed and the pros are mad.",
            "Simple, boring, green. I'll allow it.",
            "Favorites cover on a good night. Tonight was a good night."
        ],
        "epitaph": "Bet what everybody bets. Lost what everybody loses.",
        "verb": "went chalk on"
    },
    "desk_fader": {
        "bio": "An AI persona that fades the popular side. The favorite and the over stand in for the crowd, so it only takes underdogs, points, and unders.",
        "catchphrase": "If you like it, I hate it.",
        "vibe": "chaos",
        "roasts": [
            "You faded the crowd and the crowd cashed. Awkward.",
            "Contrarian night, conventional result. Brutal.",
            "Everybody was right. You were the everybody-else.",
            "Fading chalk is fun until the chalk wins.",
            "The crowd called your bluff."
        ],
        "brags": [
            "You went against the grain and the grain lost. Beautiful.",
            "Underdog, under, cash. Fader approved.",
            "The crowd was wrong and you were mean about it. Perfect.",
            "Contrarian cashed. Do not start a podcast.",
            "Faded the public and the public paid. Enjoy."
        ],
        "epitaph": "Faded the crowd until the crowd came back.",
        "verb": "faded the crowd on"
    },
    "desk_weather": {
        "bio": "An AI persona that only bets totals, reading weather, park and scoring conditions. Wind blowing out? Over. Cold and wet? Under. If the data has no weather, it says so.",
        "catchphrase": "Check the wind before you check the odds.",
        "vibe": "nerd",
        "roasts": [
            "The wind blew out and nobody scored. Meteorology is hard.",
            "You read the forecast and missed the game. Fitting.",
            "Bet the over in a monsoon. Respect the confidence.",
            "The total ignored the weather. Weather ignored you.",
            "A cloud cost you units. Impressive."
        ],
        "brags": [
            "Wind out, ball carries, over hits. Look at that forecast.",
            "Cold air, quiet bats, under cashes. Nerd wins.",
            "Weather paid. Park paid. You paid for a hot dog.",
            "Totals night, nailed it. Put away the barometer.",
            "The sky did it again. I take back what I said."
        ],
        "epitaph": "Bet the weather and got rained out.",
        "verb": "checked the wind and took"
    },
    "desk_grinder": {
        "bio": "An AI persona that takes only unders and short favorites, and never claims a big gap. A lunch-pail dog who takes the small win and goes home.",
        "catchphrase": "Small wins add up. Probably.",
        "vibe": "grinder",
        "roasts": [
            "Unders and short favorites, and still a loss. How do you even do that.",
            "Grinding hard, getting nowhere. Typical.",
            "You took the safe route and it had a pothole.",
            "Small bets, small brain, small night.",
            "A grind with no payoff is just a walk."
        ],
        "brags": [
            "Another small win, another notch. Boring is beautiful.",
            "Under cashed, favorite won. Clock out.",
            "Lunch-pail night, lunch-pail units.",
            "Grinding works until it doesn't. Tonight it did.",
            "Nothing flashy, all green. Respect."
        ],
        "epitaph": "Ground it out until there was nothing left to grind.",
        "verb": "ground out"
    },
    "desk_historian": {
        "bio": "An AI persona that argues only from head-to-head and series history. Every reason has to cite the past. Does not know what happened last week, only what happened in 2019.",
        "catchphrase": "History repeats itself. Allegedly.",
        "vibe": "nerd",
        "roasts": [
            "History repeated itself and then changed its mind.",
            "Cited three old meetings. The new meeting ignored them.",
            "Past results are not a prophecy, Historian.",
            "Living in the past is how you lose in the present.",
            "The series history said yes. The game said no."
        ],
        "brags": [
            "History repeated tonight. The Historian has not shut up.",
            "The head-to-head came through. Grab the quill.",
            "The past paid. Do not make a documentary.",
            "Old rivalry, fresh units. Beautiful.",
            "The archive delivers. Sit and read quietly."
        ],
        "epitaph": "Lived in the past and ran out of future.",
        "verb": "cited the archives and took"
    }
}
