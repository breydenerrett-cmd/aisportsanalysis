"""The Hounds breeding program (docs/PREREG_BREEDING.md): every 3 days pick the fittest members of each
tunable hound's family on FORWARD closing-line value, breed at most 2 babies through the learning loop's
own proposal door (so the referee alone can promote them), and cull the worst.

    select.py   members, forward-only fitness with shrinkage, eligibility, the parent pool, the culls
    cross.py    crossover on the grid, the one-step mutation, the litter plan, the code-written reason
    cycle.py    the cycle, the breeding ledger, the auto-pause, the family tree payload
    cli.py      python -m src.hounds.breeding tick [--dry-run] | status | resume | verify
"""
