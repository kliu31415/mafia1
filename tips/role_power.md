# Role power

Refit 2026-10-13 10:28 UTC by `role_power.py` from 86 finished live games (Village won 51). Power is how much a role adds to the Village's win chance, in logits (+0.4 is about +10 points near even). Offset +0.07 (prior -0.30). Change the priors in role_power.py; this file is rewritten after every game.

| Role | Side | Prior | Power | Games |
|---|---|---|---|---|
| Puppeteer | Evil | -1.00 | -0.77 | 25 |
| Smuggler | Evil | -0.90 | -0.79 | 22 |
| Informant | Evil | -0.95 | -0.82 | 3 |
| Fabricator | Evil | -1.00 | -0.84 | 23 |
| Mortician | Evil | -0.95 | -0.85 | 12 |
| Wiretap | Evil | -1.00 | -0.97 | 12 |
| Pharmacist | Evil | -1.10 | -0.97 | 27 |
| Clerk | Evil | -0.95 | -0.98 | 27 |
| Talent Agent | Evil | -0.95 | -1.00 | 3 |
| Grunt | Evil | -0.85 | -1.00 | 34 |
| Fixer | Evil | -0.95 | -1.01 | 4 |
| Diviner | Evil | -1.05 | -1.01 | 20 |
| Ritualist | Evil | -1.00 | -1.10 | 18 |
| Ballot Stuffer | Evil | -1.20 | -1.11 | 16 |
| Medic | Good | +0.55 | +0.77 | 54 |
| Sheriff | Good | +0.55 | +0.70 | 43 |
| Trapper | Good | +0.70 | +0.67 | 12 |
| Vigilante | Good | +0.45 | +0.61 | 27 |
| Veteran | Good | +0.50 | +0.58 | 15 |
| Seer | Good | +0.40 | +0.56 | 17 |
| Party Animal | Good | +0.45 | +0.55 | 10 |
| Lookout | Good | +0.45 | +0.52 | 42 |
| Oracle | Good | +0.45 | +0.52 | 24 |
| Tracker | Good | +0.45 | +0.52 | 26 |
| Insomniac | Good | +0.35 | +0.48 | 3 |
| Prosecutor | Good | +0.40 | +0.48 | 14 |
| Cartographer | Good | +0.35 | +0.47 | 10 |
| Surveyor | Good | +0.40 | +0.47 | 13 |
| Archivist | Good | +0.40 | +0.46 | 24 |
| Census Taker | Good | +0.45 | +0.44 | 8 |
| Profiler | Good | +0.45 | +0.44 | 11 |
| Eavesdropper | Good | +0.40 | +0.44 | 11 |
| Auditor | Good | +0.40 | +0.42 | 5 |
| Chronicler | Good | +0.40 | +0.41 | 2 |
| Sniper | Good | +0.45 | +0.40 | 5 |
| Bloodhound | Good | +0.40 | +0.39 | 6 |
| Kitsune | Good | +0.60 | +0.38 | 6 |
| Enforcer | Good | +0.45 | +0.38 | 2 |
| Coroner | Good | +0.35 | +0.38 | 4 |
| Fortune Teller | Good | +0.35 | +0.36 | 19 |
| Scout | Good | +0.30 | +0.36 | 11 |
| Vanilla Villager | Good | +0.25 | +0.35 | 66 |
| Philanthropist | Good | +0.35 | +0.35 | 8 |
| Accountant | Good | +0.35 | +0.35 | 18 |
| Juror | Good | +0.35 | +0.26 | 6 |
| Scrutineer | Good | +0.30 | +0.17 | 4 |
| Roleplayer | Good | +0.00 | +0.07 | 7 |
| Executioner | Neutral | -0.20 | -0.07 | 18 |
| Jester | Neutral | -0.15 | -0.15 | 28 |
| Vulture | Neutral | -0.25 | -0.18 | 6 |
| Magpie | Neutral | -0.15 | -0.22 | 2 |
| Bounty Hunter | Neutral | -0.30 | -0.31 | 6 |
| Serial Killer | Neutral | -0.60 | -0.72 | 14 |
| Arsonist | Neutral | -0.80 | -0.92 | 17 |

A trait's power is how much it helps its holder's side (the Village for a Village holder, the Yakuza for a Yakuza; a Neutral holder's traits aren't counted). Its prior is its power in traits.py.

| Trait | Holder | Prior | Power | Games |
|---|---|---|---|---|
| Avenger | Village | +0.40 | +0.41 | 1 |
| Spare Blade | Yakuza | +0.35 | +0.40 | 1 |
| Grudge | Yakuza | +0.30 | +0.36 | 2 |
| Armed | Village | +0.25 | +0.33 | 2 |
| Disguised | Yakuza | +0.30 | +0.30 | 0 |
| Martyr | Village | +0.15 | +0.24 | 3 |
| Stocked | Village, Yakuza, Neutral | +0.15 | +0.20 | 1 |
| Kindred | Village | +0.15 | +0.16 | 2 |
| Grudge | Village, Neutral | +0.10 | +0.13 | 1 |
| Faultline | Village | +0.15 | +0.12 | 1 |
| Selfless | Yakuza | +0.10 | +0.10 | 0 |
| Loud | Village, Yakuza, Neutral | +0.10 | +0.07 | 1 |
| Confidant | Village, Yakuza, Neutral | +0.10 | +0.06 | 2 |
| Sleepwalker | Village, Neutral | -0.05 | +0.02 | 10 |
| Sleepwalker | Yakuza | +0.05 | +0.02 | 1 |
| Bonded | Village, Yakuza | +0.00 | +0.00 | 0 |
| Oblivious | Yakuza | -0.05 | -0.05 | 0 |
| Notorious | Village | -0.10 | -0.06 | 11 |
| Cursed | Village | -0.10 | -0.08 | 14 |
| Merciful | Yakuza | -0.15 | -0.10 | 1 |
| Remorseful | Village | -0.10 | -0.10 | 0 |
| Merciful | Village, Neutral | -0.10 | -0.10 | 0 |
| Disguised | Village, Neutral | -0.10 | -0.10 | 0 |
| Selfish | Village, Yakuza | -0.10 | -0.10 | 0 |
| Oblivious | Village, Neutral | -0.10 | -0.10 | 0 |
| Zealot | Village, Neutral | -0.10 | -0.12 | 2 |
| Zealot | Yakuza | -0.15 | -0.15 | 0 |
| Selfless | Village | -0.15 | -0.15 | 0 |
| Paranoid | Village | -0.10 | -0.15 | 1 |
| Curt | Village, Yakuza, Neutral | -0.10 | -0.16 | 2 |
| Drowsy | Village, Yakuza, Neutral | -0.15 | -0.17 | 2 |
| Usurper | Yakuza | -0.30 | -0.30 | 0 |
| Shaky | Yakuza | -0.30 | -0.30 | 0 |
| Turncoat | Village | -0.40 | -0.40 | 0 |
