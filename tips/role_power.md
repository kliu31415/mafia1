# Role power

Refit 2026-10-15 00:31 UTC by `role_power.py` from 94 finished live games (Village won 57). Power is how much a role adds to the Village's win chance, in logits (+0.4 is about +10 points near even). Offset +0.07 (prior -0.30). Change the priors in role_power.py; this file is rewritten after every game.

| Role | Side | Prior | Power | Games |
|---|---|---|---|---|
| Grunt | Evil | -0.85 | -0.80 | 76 |
| Fabricator | Evil | -1.00 | -0.82 | 25 |
| Mortician | Evil | -0.95 | -0.82 | 13 |
| Informant | Evil | -0.95 | -0.83 | 3 |
| Wiretap | Evil | -1.00 | -0.95 | 13 |
| Pharmacist | Evil | -1.10 | -0.95 | 29 |
| Diviner | Evil | -1.05 | -0.95 | 23 |
| Talent Agent | Evil | -0.95 | -0.97 | 5 |
| Fixer | Evil | -0.95 | -1.03 | 8 |
| Ballot Stuffer | Evil | -1.20 | -1.05 | 18 |
| Ritualist | Evil | -1.00 | -1.11 | 20 |
| Medic | Good | +0.55 | +0.78 | 56 |
| Sheriff | Good | +0.55 | +0.73 | 46 |
| Vigilante | Good | +0.45 | +0.61 | 30 |
| Trapper | Good | +0.70 | +0.60 | 17 |
| Seer | Good | +0.40 | +0.59 | 19 |
| Party Animal | Good | +0.45 | +0.56 | 10 |
| Veteran | Good | +0.50 | +0.54 | 16 |
| Lookout | Good | +0.45 | +0.53 | 43 |
| Oracle | Good | +0.45 | +0.52 | 24 |
| Insomniac | Good | +0.35 | +0.52 | 5 |
| Cartographer | Good | +0.35 | +0.50 | 11 |
| Tracker | Good | +0.45 | +0.48 | 28 |
| Prosecutor | Good | +0.40 | +0.48 | 14 |
| Auditor | Good | +0.40 | +0.47 | 8 |
| Census Taker | Good | +0.45 | +0.47 | 9 |
| Archivist | Good | +0.40 | +0.46 | 25 |
| Scout | Good | +0.30 | +0.46 | 16 |
| Eavesdropper | Good | +0.40 | +0.45 | 11 |
| Chronicler | Good | +0.40 | +0.44 | 4 |
| Sniper | Good | +0.45 | +0.44 | 8 |
| Enforcer | Good | +0.45 | +0.41 | 4 |
| Bloodhound | Good | +0.40 | +0.40 | 6 |
| Profiler | Good | +0.45 | +0.39 | 12 |
| Coroner | Good | +0.35 | +0.39 | 4 |
| Kitsune | Good | +0.60 | +0.37 | 7 |
| Fortune Teller | Good | +0.35 | +0.37 | 20 |
| Vanilla Villager | Good | +0.25 | +0.24 | 78 |
| Roleplayer | Good | +0.00 | +0.10 | 9 |
| Executioner | Neutral | -0.20 | -0.03 | 21 |
| Jester | Neutral | -0.15 | -0.14 | 30 |
| Vulture | Neutral | -0.25 | -0.16 | 7 |
| Magpie | Neutral | -0.15 | -0.19 | 3 |
| Bounty Hunter | Neutral | -0.30 | -0.28 | 7 |
| Serial Killer | Neutral | -0.60 | -0.76 | 16 |
| Arsonist | Neutral | -0.80 | -0.91 | 18 |

A trait's power is how much it helps its holder's side (the Village for a Village holder, the Yakuza for a Yakuza; a Neutral holder's traits aren't counted). Its prior is its power in traits.py.

| Trait | Holder | Prior | Power | Games |
|---|---|---|---|---|
| Avenger | Village | +0.40 | +0.44 | 3 |
| Spare Blade | Yakuza | +0.35 | +0.41 | 1 |
| Grudge | Yakuza | +0.30 | +0.37 | 2 |
| Armed | Village | +0.25 | +0.35 | 4 |
| Martyr | Village | +0.15 | +0.27 | 5 |
| Disguised | Yakuza | +0.30 | +0.25 | 3 |
| Stolen Blade | Village | +0.30 | +0.25 | 2 |
| Armed | Yakuza | +0.20 | +0.22 | 2 |
| Stocked | Village, Yakuza, Neutral | +0.15 | +0.21 | 1 |
| Katana Master | Yakuza | +0.25 | +0.20 | 2 |
| Kindred | Village | +0.15 | +0.17 | 3 |
| Grudge | Village, Neutral | +0.10 | +0.17 | 3 |
| Faultline | Village | +0.15 | +0.16 | 3 |
| Narrow Escape | Yakuza | +0.10 | +0.11 | 2 |
| Confidant | Village, Yakuza, Neutral | +0.10 | +0.11 | 5 |
| Narrow Escape | Village, Neutral | +0.15 | +0.11 | 1 |
| Loud | Village, Yakuza, Neutral | +0.10 | +0.11 | 4 |
| Selfless | Yakuza | +0.10 | +0.10 | 0 |
| Katana Expert | Yakuza | +0.10 | +0.07 | 1 |
| Bonded | Village, Yakuza | +0.00 | +0.03 | 2 |
| Sleepwalker | Village, Neutral | -0.05 | +0.03 | 11 |
| Sleepwalker | Yakuza | +0.05 | +0.01 | 2 |
| Cursed | Village | -0.10 | -0.03 | 16 |
| Disguised | Village, Neutral | -0.10 | -0.04 | 4 |
| Remorseful | Village | -0.10 | -0.05 | 1 |
| Oblivious | Yakuza | -0.05 | -0.05 | 0 |
| Notorious | Village | -0.10 | -0.05 | 12 |
| Zealot | Village, Neutral | -0.10 | -0.09 | 4 |
| Merciful | Village, Neutral | -0.10 | -0.10 | 0 |
| Oblivious | Village, Neutral | -0.10 | -0.10 | 0 |
| Selfish | Village, Yakuza | -0.10 | -0.10 | 3 |
| Rival | Village, Yakuza | -0.15 | -0.12 | 1 |
| Paranoid | Village | -0.10 | -0.12 | 3 |
| Merciful | Yakuza | -0.15 | -0.12 | 2 |
| Curt | Village, Yakuza, Neutral | -0.10 | -0.12 | 4 |
| Selfless | Village | -0.15 | -0.15 | 0 |
| Zealot | Yakuza | -0.15 | -0.16 | 1 |
| Drowsy | Village, Yakuza, Neutral | -0.15 | -0.17 | 2 |
| Shaky | Yakuza | -0.30 | -0.31 | 1 |
| Usurper | Yakuza | -0.30 | -0.33 | 1 |
| Turncoat | Village | -0.40 | -0.40 | 0 |
