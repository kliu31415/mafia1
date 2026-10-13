# Role power

Refit 2026-10-13 12:45 UTC by `role_power.py` from 89 finished live games (Village won 53). Power is how much a role adds to the Village's win chance, in logits (+0.4 is about +10 points near even). Offset +0.05 (prior -0.30). Change the priors in role_power.py; this file is rewritten after every game.

| Role | Side | Prior | Power | Games |
|---|---|---|---|---|
| Puppeteer | Evil | -1.00 | -0.81 | 26 |
| Informant | Evil | -0.95 | -0.82 | 3 |
| Smuggler | Evil | -0.90 | -0.83 | 23 |
| Fabricator | Evil | -1.00 | -0.84 | 23 |
| Mortician | Evil | -0.95 | -0.85 | 12 |
| Pharmacist | Evil | -1.10 | -0.96 | 28 |
| Wiretap | Evil | -1.00 | -0.97 | 12 |
| Clerk | Evil | -0.95 | -0.98 | 27 |
| Talent Agent | Evil | -0.95 | -0.99 | 4 |
| Grunt | Evil | -0.85 | -0.99 | 35 |
| Diviner | Evil | -1.05 | -0.99 | 21 |
| Fixer | Evil | -0.95 | -1.05 | 5 |
| Ritualist | Evil | -1.00 | -1.08 | 19 |
| Ballot Stuffer | Evil | -1.20 | -1.11 | 16 |
| Medic | Good | +0.55 | +0.79 | 55 |
| Sheriff | Good | +0.55 | +0.72 | 44 |
| Trapper | Good | +0.70 | +0.64 | 14 |
| Vigilante | Good | +0.45 | +0.60 | 29 |
| Veteran | Good | +0.50 | +0.58 | 15 |
| Seer | Good | +0.40 | +0.57 | 18 |
| Party Animal | Good | +0.45 | +0.55 | 10 |
| Oracle | Good | +0.45 | +0.52 | 24 |
| Lookout | Good | +0.45 | +0.51 | 42 |
| Tracker | Good | +0.45 | +0.50 | 28 |
| Insomniac | Good | +0.35 | +0.48 | 3 |
| Prosecutor | Good | +0.40 | +0.48 | 14 |
| Archivist | Good | +0.40 | +0.48 | 25 |
| Cartographer | Good | +0.35 | +0.47 | 10 |
| Census Taker | Good | +0.45 | +0.46 | 9 |
| Eavesdropper | Good | +0.40 | +0.44 | 11 |
| Auditor | Good | +0.40 | +0.43 | 5 |
| Surveyor | Good | +0.40 | +0.43 | 14 |
| Chronicler | Good | +0.40 | +0.42 | 3 |
| Sniper | Good | +0.45 | +0.41 | 6 |
| Profiler | Good | +0.45 | +0.40 | 12 |
| Bloodhound | Good | +0.40 | +0.40 | 6 |
| Kitsune | Good | +0.60 | +0.38 | 6 |
| Coroner | Good | +0.35 | +0.38 | 4 |
| Enforcer | Good | +0.45 | +0.38 | 2 |
| Scout | Good | +0.30 | +0.37 | 12 |
| Fortune Teller | Good | +0.35 | +0.37 | 20 |
| Vanilla Villager | Good | +0.25 | +0.37 | 67 |
| Philanthropist | Good | +0.35 | +0.35 | 8 |
| Accountant | Good | +0.35 | +0.35 | 18 |
| Juror | Good | +0.35 | +0.26 | 6 |
| Scrutineer | Good | +0.30 | +0.17 | 4 |
| Roleplayer | Good | +0.00 | +0.08 | 7 |
| Executioner | Neutral | -0.20 | -0.06 | 19 |
| Jester | Neutral | -0.15 | -0.13 | 29 |
| Vulture | Neutral | -0.25 | -0.17 | 6 |
| Magpie | Neutral | -0.15 | -0.22 | 2 |
| Bounty Hunter | Neutral | -0.30 | -0.31 | 6 |
| Serial Killer | Neutral | -0.60 | -0.72 | 14 |
| Arsonist | Neutral | -0.80 | -0.91 | 18 |

A trait's power is how much it helps its holder's side (the Village for a Village holder, the Yakuza for a Yakuza; a Neutral holder's traits aren't counted). Its prior is its power in traits.py.

| Trait | Holder | Prior | Power | Games |
|---|---|---|---|---|
| Avenger | Village | +0.40 | +0.41 | 1 |
| Spare Blade | Yakuza | +0.35 | +0.40 | 1 |
| Grudge | Yakuza | +0.30 | +0.36 | 2 |
| Armed | Village | +0.25 | +0.34 | 3 |
| Disguised | Yakuza | +0.30 | +0.28 | 1 |
| Martyr | Village | +0.15 | +0.26 | 4 |
| Katana Master | Yakuza | +0.25 | +0.22 | 1 |
| Stocked | Village, Yakuza, Neutral | +0.15 | +0.20 | 1 |
| Kindred | Village | +0.15 | +0.18 | 3 |
| Narrow Escape | Yakuza | +0.10 | +0.14 | 1 |
| Grudge | Village, Neutral | +0.10 | +0.13 | 1 |
| Faultline | Village | +0.15 | +0.12 | 1 |
| Narrow Escape | Village, Neutral | +0.15 | +0.11 | 1 |
| Selfless | Yakuza | +0.10 | +0.10 | 0 |
| Loud | Village, Yakuza, Neutral | +0.10 | +0.09 | 2 |
| Confidant | Village, Yakuza, Neutral | +0.10 | +0.08 | 3 |
| Katana Expert | Yakuza | +0.10 | +0.07 | 1 |
| Bonded | Village, Yakuza | +0.00 | +0.03 | 1 |
| Sleepwalker | Village, Neutral | -0.05 | +0.02 | 10 |
| Sleepwalker | Yakuza | +0.05 | +0.00 | 2 |
| Oblivious | Yakuza | -0.05 | -0.05 | 0 |
| Notorious | Village | -0.10 | -0.06 | 11 |
| Disguised | Village, Neutral | -0.10 | -0.08 | 1 |
| Selfish | Village, Yakuza | -0.10 | -0.08 | 1 |
| Cursed | Village | -0.10 | -0.08 | 14 |
| Merciful | Yakuza | -0.15 | -0.10 | 1 |
| Remorseful | Village | -0.10 | -0.10 | 0 |
| Merciful | Village, Neutral | -0.10 | -0.10 | 0 |
| Oblivious | Village, Neutral | -0.10 | -0.10 | 0 |
| Zealot | Village, Neutral | -0.10 | -0.11 | 2 |
| Rival | Village, Yakuza | -0.15 | -0.15 | 0 |
| Selfless | Village | -0.15 | -0.15 | 0 |
| Paranoid | Village | -0.10 | -0.15 | 1 |
| Curt | Village, Yakuza, Neutral | -0.10 | -0.16 | 2 |
| Drowsy | Village, Yakuza, Neutral | -0.15 | -0.16 | 2 |
| Zealot | Yakuza | -0.15 | -0.17 | 1 |
| Usurper | Yakuza | -0.30 | -0.30 | 0 |
| Shaky | Yakuza | -0.30 | -0.30 | 0 |
| Turncoat | Village | -0.40 | -0.40 | 0 |
