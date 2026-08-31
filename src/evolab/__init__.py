"""The Evolution Lab's own namespace.

Nothing produced here is evidence (docs/EVOLAB_DESIGN.md §11). Code lives
in `src/evolab/`, data in `data/research/evolab/`, docs in `docs/EVOLAB_*`.
The lab consumes frozen machinery -- the falsification battery, the funnel,
de-vig and pairing -- and never modifies it.

`replay.py` is the point-in-time replay engine every later phase sits on. It
serves 2023-24 only, refuses the sealed 2026 window by name, and makes leakage
structurally impossible rather than filtered: it reads no outcome out of any
store, serves boards through a generator that stops at T, and hands out a
WorldView with no attribute for an outcome or a closing price. The two
assumptions it cannot avoid -- starter identity and lineup posting time -- are
named, versioned parameters stamped on every artifact it produces.
"""
