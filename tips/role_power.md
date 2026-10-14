# Role power

Refit 2026-10-14 14:37 UTC by `role_power.py` from 93 finished live games (Village won 56). Power is how much a role adds to the Village's win chance, in logits (+0.4 is about +10 points near even). Offset +0.06 (prior -0.30). Change the priors in role_power.py; this file is rewritten after every game.

| Role | Side | Prior | Power | Games |
|---|---|---|---|---|
| Grunt | Evil | -0.85 | -0.79 | 76 |
| Mortician | Evil | -0.95 | -0.82 | 13 |
| Informant | Evil | -0.95 | -0.83 | 3 |
| Fabricator | Evil | -1.00 | -0.83 | 24 |
| Wiretap | Evil | -1.00 | -0.95 | 13 |
| Pharmacist | Evil | -1.10 | -0.95 | 29 |
| Diviner | Evil | -1.05 | -0.96 | 22 |
| Talent Agent | Evil | -0.95 | -0.97 | 5 |
| Fixer | Evil | -0.95 | -1.03 | 8 |
| Ballot Stuffer | Evil | -1.20 | -1.07 | 17 |
| Ritualist | Evil | -1.00 | -1.10 | 20 |
| Medic | Good | +0.55 | +0.77 | 55 |
| Sheriff | Good | +0.55 | +0.72 | 45 |
| Trapper | Good | +0.70 | +0.60 | 17 |
| Vigilante | Good | +0.45 | +0.60 | 29 |
| Seer | Good | +0.40 | +0.59 | 19 |
| Party Animal | Good | +0.45 | +0.56 | 10 |
| Veteran | Good | +0.50 | +0.54 | 16 |
| Lookout | Good | +0.45 | +0.53 | 43 |
| Oracle | Good | +0.45 | +0.53 | 24 |
| Insomniac | Good | +0.35 | +0.51 | 4 |
| Cartographer | Good | +0.35 | +0.50 | 11 |
| Tracker | Good | +0.45 | +0.49 | 28 |
| Prosecutor | Good | +0.40 | +0.48 | 14 |
| Auditor | Good | +0.40 | +0.47 | 8 |
| Archivist | Good | +0.40 | +0.47 | 25 |
| Census Taker | Good | +0.45 | +0.47 | 9 |
| Eavesdropper | Good | +0.40 | +0.45 | 11 |
| Sniper | Good | +0.45 | +0.44 | 8 |
| Scout | Good | +0.30 | +0.43 | 15 |
| Chronicler | Good | +0.40 | +0.43 | 3 |
| Enforcer | Good | +0.45 | +0.42 | 4 |
| Bloodhound | Good | +0.40 | +0.40 | 6 |
| Profiler | Good | +0.45 | +0.39 | 12 |
| Coroner | Good | +0.35 | +0.39 | 4 |
| Kitsune | Good | +0.60 | +0.38 | 7 |
| Fortune Teller | Good | +0.35 | +0.37 | 20 |
| Vanilla Villager | Good | +0.25 | +0.25 | 78 |
| Roleplayer | Good | +0.00 | +0.09 | 8 |
| Executioner | Neutral | -0.20 | -0.02 | 21 |
| Jester | Neutral | -0.15 | -0.15 | 29 |
| Vulture | Neutral | -0.25 | -0.16 | 7 |
| Magpie | Neutral | -0.15 | -0.19 | 3 |
| Bounty Hunter | Neutral | -0.30 | -0.28 | 7 |
| Serial Killer | Neutral | -0.60 | -0.77 | 15 |
| Arsonist | Neutral | -0.80 | -0.91 | 18 |

A trait's power is how much it helps its holder's side (the Village for a Village holder, the Yakuza for a Yakuza; a Neutral holder's traits aren't counted). Its prior is its power in traits.py.

| Trait | Holder | Prior | Power | Games |
|---|---|---|---|---|
| Avenger | Village | +0.40 | +0.43 | 2 |
| Spare Blade | Yakuza | +0.35 | +0.41 | 1 |
| Grudge | Yakuza | +0.30 | +0.37 | 2 |
| Armed | Village | +0.25 | +0.35 | 4 |
| Martyr | Village | +0.15 | +0.27 | 5 |
| Disguised | Yakuza | +0.30 | +0.27 | 2 |
| Stolen Blade | Village | +0.30 | +0.25 | 2 |
| Armed | Yakuza | +0.20 | +0.24 | 1 |
| Stocked | Village, Yakuza, Neutral | +0.15 | +0.21 | 1 |
| Katana Master | Yakuza | +0.25 | +0.19 | 2 |
| Kindred | Village | +0.15 | +0.17 | 3 |
| Grudge | Village, Neutral | +0.10 | +0.17 | 3 |
| Faultline | Village | +0.15 | +0.14 | 2 |
| Confidant | Village, Yakuza, Neutral | +0.10 | +0.11 | 5 |
| Narrow Escape | Yakuza | +0.10 | +0.11 | 2 |
| Narrow Escape | Village, Neutral | +0.15 | +0.11 | 1 |
| Selfless | Yakuza | +0.10 | +0.10 | 0 |
| Loud | Village, Yakuza, Neutral | +0.10 | +0.09 | 3 |
| Katana Expert | Yakuza | +0.10 | +0.07 | 1 |
| Bonded | Village, Yakuza | +0.00 | +0.03 | 2 |
| Sleepwalker | Village, Neutral | -0.05 | +0.01 | 10 |
| Sleepwalker | Yakuza | +0.05 | +0.01 | 2 |
| Remorseful | Village | -0.10 | -0.05 | 1 |
| Notorious | Village | -0.10 | -0.05 | 12 |
| Oblivious | Yakuza | -0.05 | -0.05 | 0 |
| Disguised | Village, Neutral | -0.10 | -0.05 | 3 |
| Cursed | Village | -0.10 | -0.05 | 15 |
| Merciful | Village, Neutral | -0.10 | -0.10 | 0 |
| Oblivious | Village, Neutral | -0.10 | -0.10 | 0 |
| Zealot | Village, Neutral | -0.10 | -0.10 | 3 |
| Selfish | Village, Yakuza | -0.10 | -0.10 | 2 |
| Rival | Village, Yakuza | -0.15 | -0.11 | 1 |
| Curt | Village, Yakuza, Neutral | -0.10 | -0.12 | 4 |
| Merciful | Yakuza | -0.15 | -0.12 | 2 |
| Paranoid | Village | -0.10 | -0.13 | 2 |
| Selfless | Village | -0.15 | -0.15 | 0 |
| Zealot | Yakuza | -0.15 | -0.16 | 1 |
| Drowsy | Village, Yakuza, Neutral | -0.15 | -0.17 | 2 |
| Shaky | Yakuza | -0.30 | -0.30 | 0 |
| Usurper | Yakuza | -0.30 | -0.33 | 1 |
| Turncoat | Village | -0.40 | -0.40 | 0 |
