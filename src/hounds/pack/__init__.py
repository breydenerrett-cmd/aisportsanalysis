"""The LineHound Hounds house pack, v1: 21 paper-only strategies with characters.

The rule book is `docs/PREREG_HOUSE_PACK_V1.md` (frozen before any replay). Each hound is one module
here exposing `HOUND`; `PACK` is the registry in the pre-registered order. Nothing in this package
claims an edge; the esoteric and random hounds are controls and entertainment.
"""

from __future__ import annotations

from src.hounds.pack import (bargain_bloodhound, chalk_chihuahua, coin_flip_collie, contrary_corgi,
                             dartboard_dalmatian, elimination_basset, gridiron_greyhound, grudge_bulldog,
                             home_dog_hank, hot_streak_husky, jetlag_jack, kelly_kelpie, lunar_lab,
                             numerology_newfie, pack_leader, professor_paws, relief_retriever,
                             scrappy_schnauzer, stale_bread_beagle, steamy_setter, totals_terrier)

PACK_ID = "house_v1"

MODULES = (professor_paws, totals_terrier, relief_retriever, gridiron_greyhound, elimination_basset,
           jetlag_jack, steamy_setter, contrary_corgi, stale_bread_beagle, bargain_bloodhound, kelly_kelpie,
           hot_streak_husky, grudge_bulldog, numerology_newfie, lunar_lab, coin_flip_collie,
           dartboard_dalmatian, pack_leader, scrappy_schnauzer, chalk_chihuahua, home_dog_hank)

PACK = tuple(m.HOUND for m in MODULES)
BY_ID = {h.id: h for h in PACK}
