"""Static HTML briefing. One file, no server, no network, no dependencies.

WHY A GENERATED STATIC FILE
---------------------------
The briefing has to be openable on a phone, sendable to someone else, and
readable a year from now. A served dashboard needs the server to still be
running; a static file needs nothing. It also means the artifact is a snapshot:
the page for a given date shows what was known on that date and cannot silently
change when the data behind it does.

Everything -- data, styles, behaviour -- is inlined. The page works from a
file:// URL with the network switched off.

WHY EVERY CLAIM CARRIES AN EVIDENCE LABEL
-----------------------------------------
This project has one recurring failure mode: a number that is technically true
being read as a validated result. The reader cannot be expected to remember which
parts are proven, so the page never lets them guess -- every claim is stamped
with its status, and "unproven" is the default that has to be argued out of.

A page that looks confident about an unvalidated threshold is worse than no page.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from src.detect import base as detect

EVIDENCE_LABELS = {
    detect.PROVEN: ("Proven", "Held up on data it was not built from"),
    detect.FORWARD_TESTING: ("Forward testing", "Logged before the games; still accumulating"),
    detect.PROVISIONAL: ("Provisional", "One-shot backtest; weaker than forward proof"),
    detect.TUNING_EVIDENCE: ("Tuning evidence", "Thresholds were fitted on this; optimistic"),
    detect.HISTORICAL_CANDIDATE: ("Candidate", "Looks real in discovery data; untested"),
    detect.UNPROVEN: ("Unproven", "A written-down guess. Never tested."),
    detect.BLOCKED: ("Blocked", "Cannot be computed with the data we have"),
}


def render(slate, out_path, generated_at=None) -> str:
    """Write the briefing for one slate. Returns the path written."""
    stamp = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload = _payload(slate, stamp)
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_document(payload), encoding="utf-8")
    return str(target)


def _payload(slate, stamp) -> dict:
    games = []
    for entry in slate.get("games", []):
        dossier = entry["dossier"]
        findings = entry.get("findings", [])
        games.append({
            "away": dossier.game.get("away_team"),
            "home": dossier.game.get("home_team"),
            "start": dossier.game.get("start_time_utc"),
            "venue": dossier.game.get("venue"),
            "verdict": entry.get("verdict", "no_play"),
            "side": entry.get("side"),
            "market": entry.get("market"),
            "summary": entry.get("summary"),
            "findings": [_finding(f) for f in findings],
            "sections": _sections(dossier),
            "gaps": dossier.gaps,
        })
    return {
        "date": slate.get("date"),
        "generated_at": stamp.isoformat(),
        "games": games,
        "counts": {
            "games": len(games),
            "flagged": sum(1 for g in games if g["verdict"] == "flagged"),
            "candidates": sum(1 for g in games if g["verdict"] == "candidate"),
        },
        "notes": slate.get("notes", []),
    }


def _finding(finding) -> dict:
    label, meaning = EVIDENCE_LABELS.get(finding.evidence,
                                         (finding.evidence, ""))
    return {
        "detector": finding.detector,
        "kind": finding.kind,
        "claim": finding.claim,
        "value": finding.value,
        "baseline": finding.baseline,
        "sample": finding.sample,
        "surprise": finding.surprise,
        "side": finding.side,
        "market_relevance": finding.market_relevance,
        "evidence": finding.evidence,
        "evidence_label": label,
        "evidence_meaning": meaning,
        "detail": _plain(finding.detail),
    }


def _sections(dossier) -> dict:
    return {name: _plain(data) for name, data in dossier.sections.items()}


def _plain(value):
    """Make a value JSON-safe without ever inventing one.

    An unserialisable object becomes its repr rather than being dropped. A
    dropped field looks like missing data and would be read as "no value", which
    is a different and false statement.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return repr(value)


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------

def _document(payload) -> str:
    data = json.dumps(payload, sort_keys=True).replace("</", "<\\/")
    date = html.escape(str(payload.get("date") or ""))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Slate briefing {date}</title>
<style>{_CSS}</style>
</head>
<body>
<div id="app"></div>
<script id="slate" type="application/json">{data}</script>
<script>{_JS}</script>
</body>
</html>
"""


_CSS = """
:root {
  --paper:#EBEEEA; --surface:#F7F9F5; --sunk:#E0E5DC; --ink:#151A16;
  --muted:#525E52; --faint:#84907F; --rule:#CBD2C6;
  --accent:#2B5F44; --clay:#A0522A; --warn:#8A6D1F;
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper:#0C100D; --surface:#141A15; --sunk:#101512; --ink:#DCE4DA;
    --muted:#8C9789; --faint:#67725F; --rule:#232B24;
    --accent:#79C298; --clay:#DE9463; --warn:#D6B45C;
  }
}
* { box-sizing:border-box; }
body {
  margin:0; padding:0 18px 80px; background:var(--paper); color:var(--ink);
  font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased;
}
.wrap { max-width:1080px; margin:0 auto; }
header { padding:40px 0 22px; border-bottom:2px solid var(--ink); margin-bottom:26px; }
h1 { margin:0 0 6px; font-size:30px; letter-spacing:-.02em; }
.sub { color:var(--muted); font-size:14px; }
.mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
.counts { display:flex; gap:22px; margin-top:16px; flex-wrap:wrap; }
.count b { display:block; font-size:26px; line-height:1.1; }
.count span { font-size:11px; letter-spacing:.09em; text-transform:uppercase; color:var(--faint); }

.legend { margin:18px 0 0; display:flex; gap:8px; flex-wrap:wrap; }
.chip {
  font-size:10px; letter-spacing:.08em; text-transform:uppercase; font-weight:700;
  padding:3px 8px; border-radius:2px; border:1px solid currentColor; white-space:nowrap;
}
.chip.proven{color:var(--accent)} .chip.forward_testing{color:var(--accent)}
.chip.provisional{color:var(--warn)} .chip.tuning_evidence{color:var(--warn)}
.chip.historical_candidate{color:var(--muted)} .chip.unproven{color:var(--clay)}
.chip.blocked{color:var(--faint)}

.game {
  border:1px solid var(--rule); border-radius:5px; background:var(--surface);
  margin-bottom:12px; overflow:hidden;
}
.game.flagged { border-left:5px solid var(--accent); }
.game.candidate { border-left:5px solid var(--warn); }
.game.no_play { border-left:5px solid var(--rule); }
.gamehead {
  display:grid; grid-template-columns:1fr auto; gap:14px; align-items:start;
  padding:16px 18px; cursor:pointer; background:none; border:0; width:100%;
  text-align:left; color:inherit; font:inherit;
}
.gamehead:hover { background:var(--sunk); }
.gamehead:focus-visible { outline:2px solid var(--accent); outline-offset:-2px; }
.match { font-size:19px; font-weight:600; letter-spacing:-.01em; }
.meta { font-size:12.5px; color:var(--muted); margin-top:3px; }
.verdict { font-size:11px; letter-spacing:.09em; text-transform:uppercase; font-weight:700; text-align:right; }
.verdict.flagged{color:var(--accent)} .verdict.candidate{color:var(--warn)} .verdict.no_play{color:var(--faint)}
.price { font-size:12.5px; color:var(--muted); margin-top:4px; }

.body { display:none; padding:0 18px 18px; border-top:1px solid var(--rule); }
.game.open .body { display:block; }

.findings { margin:16px 0 0; display:flex; flex-direction:column; gap:9px; }
.finding { display:grid; grid-template-columns:56px 1fr; gap:13px; align-items:start; }
.spark { font-size:19px; font-weight:700; text-align:right; font-variant-numeric:tabular-nums; }
.finding.signal .spark{color:var(--accent)} .finding.debunk .spark{color:var(--clay)}
.finding.context .spark{color:var(--faint)}
.claim { font-size:15px; line-height:1.42; }
.support { font-size:12.5px; color:var(--muted); margin-top:3px; display:flex; gap:12px; flex-wrap:wrap; }

h3 { font-size:12px; letter-spacing:.1em; text-transform:uppercase; color:var(--faint);
     margin:22px 0 8px; font-weight:700; }
table { border-collapse:collapse; width:100%; font-size:14px; }
td,th { text-align:left; padding:6px 12px 6px 0; border-bottom:1px solid var(--rule); vertical-align:top; }
th { font-size:10px; letter-spacing:.09em; text-transform:uppercase; color:var(--faint); font-weight:600; }
td.n { text-align:right; padding-right:0; font-variant-numeric:tabular-nums;
       font-family:ui-monospace,monospace; white-space:nowrap; }
.gap { color:var(--clay); font-size:13px; margin:4px 0 0; }
.tw { overflow-x:auto; }
footer { margin-top:34px; padding-top:14px; border-top:1px solid var(--rule);
         font-size:11.5px; color:var(--faint); line-height:1.8; }
.empty { padding:30px 0; color:var(--muted); }
"""


_JS = r"""
(function () {
  var slate = JSON.parse(document.getElementById('slate').textContent);
  var app = document.getElementById('app');

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function num(v, digits) {
    if (v === null || v === undefined || v === '') return '--';
    if (typeof v === 'number') return v.toFixed(digits === undefined ? 2 : digits);
    return String(v);
  }

  function pct(v) {
    return (v === null || v === undefined) ? '--' : (v * 100).toFixed(1) + '%';
  }

  function american(v) {
    if (v === null || v === undefined) return '--';
    return v > 0 ? '+' + v : String(v);
  }

  function localTime(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d)) return '';
    return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  }

  // ---- header -----------------------------------------------------------
  var wrap = el('div', 'wrap');
  var head = document.createElement('header');
  head.appendChild(el('h1', null, 'Slate briefing — ' + (slate.date || '')));
  head.appendChild(el('div', 'sub mono',
    'generated ' + slate.generated_at + ' · all times local'));

  var counts = el('div', 'counts');
  [['games', 'games'], ['flagged', 'flagged'], ['candidates', 'candidates']]
    .forEach(function (pair) {
      var box = el('div', 'count');
      box.appendChild(el('b', null, slate.counts[pair[0]]));
      box.appendChild(el('span', null, pair[1]));
      counts.appendChild(box);
    });
  head.appendChild(counts);

  // The legend is not decoration. Nothing on this page is proven, and the
  // reader has to be able to see that at a glance rather than infer it.
  var legend = el('div', 'legend');
  var seen = {};
  slate.games.forEach(function (g) {
    (g.findings || []).forEach(function (f) {
      if (!seen[f.evidence]) {
        seen[f.evidence] = true;
        var chip = el('span', 'chip ' + f.evidence, f.evidence_label);
        chip.title = f.evidence_meaning;
        legend.appendChild(chip);
      }
    });
  });
  if (legend.childNodes.length) head.appendChild(legend);
  wrap.appendChild(head);

  // ---- games ------------------------------------------------------------
  if (!slate.games.length) {
    wrap.appendChild(el('p', 'empty', 'No games scheduled for this date.'));
  }

  function topSurprise(game) {
    return (game.findings || []).reduce(function (best, f) {
      return (f.kind === 'signal' && (f.surprise || 0) > best) ? f.surprise : best;
    }, -1);
  }
  var topIndex = 0, topScore = -1;
  slate.games.forEach(function (g, i) {
    var s = topSurprise(g);
    if (g.verdict !== 'no_play') s += 100;
    if (s > topScore) { topScore = s; topIndex = i; }
  });

  slate.games.forEach(function (game, index) {
    var card = el('div', 'game ' + game.verdict);

    var button = el('button', 'gamehead');
    button.setAttribute('aria-expanded', 'false');
    var left = el('div');
    left.appendChild(el('div', 'match', game.away + ' @ ' + game.home));
    var bits = [localTime(game.start), game.venue].filter(Boolean);
    left.appendChild(el('div', 'meta', bits.join(' · ')));
    if (game.summary) left.appendChild(el('div', 'meta', game.summary));
    button.appendChild(left);

    var right = el('div');
    var verdictText = game.verdict === 'no_play' ? 'no play' : game.verdict;
    right.appendChild(el('div', 'verdict ' + game.verdict, verdictText));
    var market = (game.sections.market || {}).markets || {};
    if (market.h2h) {
      right.appendChild(el('div', 'price mono',
        american(market.h2h.away_price) + ' / ' + american(market.h2h.home_price)));
    }
    if (market.h2h_1st_5_innings) {
      right.appendChild(el('div', 'price mono', 'F5 ' +
        american(market.h2h_1st_5_innings.away_price) + ' / ' +
        american(market.h2h_1st_5_innings.home_price)));
    }
    button.appendChild(right);
    card.appendChild(button);

    var body = el('div', 'body');
    body.appendChild(renderFindings(game));
    body.appendChild(renderMarket(game));
    body.appendChild(renderStarters(game));
    body.appendChild(renderTeams(game));
    body.appendChild(renderEnvironment(game));
    body.appendChild(renderGaps(game));
    card.appendChild(body);

    button.addEventListener('click', function () {
      var open = card.classList.toggle('open');
      button.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    // Open the most interesting game, not the first one. On a slate of fifteen
    // no-plays the first card is arbitrary, and an all-collapsed page reads as
    // though the tool found nothing at all.
    if (index === topIndex) {
      card.classList.add('open');
      button.setAttribute('aria-expanded', 'true');
    }
    wrap.appendChild(card);
  });

  // ---- sections ---------------------------------------------------------
  function renderFindings(game) {
    var box = el('div');
    box.appendChild(el('h3', null, 'Why this game is interesting'));
    if (!game.findings.length) {
      box.appendChild(el('p', 'gap',
        'No detector had anything to say about this game.'));
      return box;
    }
    var list = el('div', 'findings');
    game.findings.forEach(function (f) {
      var row = el('div', 'finding ' + f.kind);
      row.appendChild(el('div', 'spark',
        f.surprise === null || f.surprise === undefined ? '—' : num(f.surprise, 1)));
      var right = el('div');
      right.appendChild(el('div', 'claim', f.claim));
      var support = el('div', 'support');
      if (f.value !== null && f.value !== undefined) {
        support.appendChild(el('span', 'mono', 'value ' + num(f.value)));
      }
      if (f.baseline !== null && f.baseline !== undefined) {
        support.appendChild(el('span', 'mono', 'normal ' + num(f.baseline)));
      }
      if (f.sample !== null && f.sample !== undefined) {
        support.appendChild(el('span', 'mono', 'sample ' + f.sample));
      }
      var chip = el('span', 'chip ' + f.evidence, f.evidence_label);
      chip.title = f.evidence_meaning;
      support.appendChild(chip);
      right.appendChild(support);
      if (f.market_relevance) {
        right.appendChild(el('div', 'support', f.market_relevance));
      }
      row.appendChild(right);
      list.appendChild(row);
    });
    box.appendChild(list);
    return box;
  }

  function table(rows, headers) {
    var wrapper = el('div', 'tw');
    var t = document.createElement('table');
    if (headers) {
      var thead = document.createElement('thead');
      var tr = document.createElement('tr');
      headers.forEach(function (h, i) {
        var th = el('th', i ? 'n' : null, h);
        tr.appendChild(th);
      });
      thead.appendChild(tr);
      t.appendChild(thead);
    }
    var tbody = document.createElement('tbody');
    rows.forEach(function (cells) {
      var tr = document.createElement('tr');
      cells.forEach(function (c, i) {
        tr.appendChild(el('td', i ? 'n' : null, c));
      });
      tbody.appendChild(tr);
    });
    t.appendChild(tbody);
    wrapper.appendChild(t);
    return wrapper;
  }

  function renderMarket(game) {
    var box = el('div');
    var section = game.sections.market;
    box.appendChild(el('h3', null, 'Market'));
    if (!section) {
      box.appendChild(el('p', 'gap', game.gaps.market || 'no prices'));
      return box;
    }
    // Totals are Over/Under with a line, not away/home. Rendering them through
    // the moneyline columns showed a row of dashes for a market that was
    // actually priced -- a missing-data display for present data, which is the
    // one thing this page must never do.
    var sideRows = [], totalRows = [];
    Object.keys(section.markets || {}).sort().forEach(function (key) {
      var m = section.markets[key];
      if (m.total !== undefined && m.total !== null) {
        totalRows.push([key, num(m.total, 1), american(m.over_price),
                        american(m.under_price), pct(m.over_fair),
                        pct(m.under_fair)]);
      } else if (m.away_price !== undefined) {
        sideRows.push([key + (m.home_line !== undefined
                        ? ' (' + num(m.home_line, 1) + ')' : ''),
                       american(m.away_price), american(m.home_price),
                       pct(m.away_fair), pct(m.home_fair),
                       m.hold_pct === undefined ? '--' : num(m.hold_pct, 2) + '%']);
      }
    });
    if (sideRows.length) {
      box.appendChild(table(sideRows,
        ['market', 'away', 'home', 'away fair', 'home fair', 'hold']));
    }
    if (totalRows.length) {
      box.appendChild(table(totalRows,
        ['total', 'line', 'over', 'under', 'over fair', 'under fair']));
    }
    if (!sideRows.length && !totalRows.length) {
      box.appendChild(el('p', 'gap', 'no market priced this game'));
    }
    if (section.implied_bullpen_shift !== undefined) {
      var shift = section.implied_bullpen_shift;
      var who = shift > 0 ? game.home : game.away;
      box.appendChild(el('p', 'support',
        'Implied bullpen read: the market gives ' + who + ' ' +
        Math.abs(shift * 100).toFixed(1) +
        ' points of win probability from innings 6–9 — the gap between ' +
        'the full-game and first-five prices is the market’s bullpen opinion.'));
    }
    return box;
  }

  function renderStarters(game) {
    var box = el('div');
    var s = game.sections.starters;
    box.appendChild(el('h3', null, 'Starting pitchers'));
    if (!s) {
      box.appendChild(el('p', 'gap', game.gaps.starters || 'not available'));
      return box;
    }
    var fields = [['FIP', 'sp_fip', 2], ['ERA', 'sp_era', 2], ['WHIP', 'sp_whip', 2],
                  ['K/9', 'sp_k9', 2], ['BB/9', 'sp_bb9', 2],
                  ['K-BB%', 'sp_k_bb_pct', 3], ['IP', 'sp_innings', 1],
                  ['IP/start', 'sp_ip_per_start', 2], ['rest', 'sp_days_rest', 0]];
    var rows = fields.map(function (f) {
      return [f[0], num(s['away_' + f[1]], f[2]), num(s['home_' + f[1]], f[2])];
    });
    box.appendChild(table(rows, ['', game.away, game.home]));
    if (s.either_sp_thin) {
      box.appendChild(el('p', 'gap',
        'One starter is under the innings threshold — his rates are ' +
        'small-sample noise and are suppressed rather than shown.'));
    }
    return box;
  }

  function renderTeams(game) {
    var box = el('div');
    var t = game.sections.teams;
    box.appendChild(el('h3', null, 'Teams'));
    if (!t) {
      box.appendChild(el('p', 'gap', game.gaps.teams || 'not available'));
      return box;
    }
    var fields = [['Record', 'wins', 0], ['Win %', 'win_pct', 3],
                  ['Runs/gm', 'runs_scored_pg', 2],
                  ['Allowed/gm', 'runs_allowed_pg', 2],
                  ['Run diff/gm', 'run_diff_pg', 2],
                  ['Last 10 wins', 'last10_wins', 0],
                  ['Rest days', 'rest_days', 0]];
    var rows = fields.map(function (f) {
      return [f[0], num(t['away_' + f[1]], f[2]), num(t['home_' + f[1]], f[2])];
    });
    box.appendChild(table(rows, ['', game.away, game.home]));
    return box;
  }

  function renderEnvironment(game) {
    var box = el('div');
    box.appendChild(el('h3', null, 'Environment'));
    var park = game.sections.park, weather = game.sections.weather;
    var rows = [];
    if (park) {
      rows.push(['Park', park.name]);
      rows.push(['Roof', park.roof]);
      rows.push(['Altitude (m)', num(park.altitude_m, 0)]);
    }
    if (weather) {
      rows.push(['Temp (F)', num(weather.temp_f, 0)]);
      rows.push(['Wind (mph)', num(weather.wind_mph, 0)]);
      rows.push(['Humidity', num(weather.humidity_pct, 0)]);
    }
    if (!rows.length) {
      box.appendChild(el('p', 'gap', game.gaps.park || game.gaps.weather || 'none'));
      return box;
    }
    box.appendChild(table(rows));
    if (park && park.orientation_deg === null) {
      box.appendChild(el('p', 'gap',
        'Wind direction is not interpreted: park orientation is unknown, and a ' +
        'wrong bearing would invert a real effect.'));
    }
    return box;
  }

  function renderGaps(game) {
    var box = el('div');
    var keys = Object.keys(game.gaps || {});
    if (!keys.length) return box;
    box.appendChild(el('h3', null, 'Missing data'));
    keys.sort().forEach(function (k) {
      box.appendChild(el('p', 'gap', k + ': ' + game.gaps[k]));
    });
    return box;
  }

  var footer = document.createElement('footer');
  (slate.notes || []).forEach(function (n) {
    footer.appendChild(el('div', null, n));
  });
  footer.appendChild(el('div', null,
    'Paper only. No bet is placed by any code in this project. Every threshold ' +
    'behind these verdicts is an unvalidated guess until the evidence label says ' +
    'otherwise.'));
  wrap.appendChild(footer);

  app.appendChild(wrap);
})();
"""
