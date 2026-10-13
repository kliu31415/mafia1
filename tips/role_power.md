# Role power

Refit 2026-10-13 14:18 UTC by `role_power.py` from 91 finished live games (Village won 54). Power is how much a role adds to the Village's win chance, in logits (+0.4 is about +10 points near even). Offset +0.03 (prior -0.30). Change the priors in role_power.py; this file is rewritten after every game.

| Role | Side | Prior | Power | Games |
|---|---|---|---|---|
| Puppeteer | Evil | -1.00 | -0.81 | 26 |
| Smuggler | Evil | -0.90 | -0.82 | 23 |
| Informant | Evil | -0.95 | -0.82 | 3 |
| Fabricator | Evil | -1.00 | -0.83 | 24 |
| Mortician | Evil | -0.95 | -0.85 | 12 |
| Pharmacist | Evil | -1.10 | -0.94 | 29 |
| Wiretap | Evil | -1.00 | -0.95 | 13 |
| Clerk | Evil | -0.95 | -0.97 | 27 |
| Talent Agent | Evil | -0.95 | -0.99 | 4 |
| Grunt | Evil | -0.85 | -0.99 | 35 |
| Diviner | Evil | -1.05 | -0.99 | 21 |
| Fixer | Evil | -0.95 | -1.08 | 6 |
| Ballot Stuffer | Evil | -1.20 | -1.10 | 16 |
| Ritualist | Evil | -1.00 | -1.11 | 20 |
| Medic | Good | +0.55 | +0.79 | 55 |
| Sheriff | Good | +0.55 | +0.72 | 44 |
| Vigilante | Good | +0.45 | +0.60 | 29 |
| Trapper | Good | +0.70 | +0.59 | 15 |
| Seer | Good | +0.40 | +0.58 | 18 |
| Party Animal | Good | +0.45 | +0.55 | 10 |
| Veteran | Good | +0.50 | +0.55 | 16 |
| Oracle | Good | +0.45 | +0.52 | 24 |
| Lookout | Good | +0.45 | +0.51 | 42 |
| Tracker | Good | +0.45 | +0.50 | 28 |
| Insomniac | Good | +0.35 | +0.48 | 3 |
| Prosecutor | Good | +0.40 | +0.48 | 14 |
| Archivist | Good | +0.40 | +0.48 | 25 |
| Cartographer | Good | +0.35 | +0.47 | 10 |
| Census Taker | Good | +0.45 | +0.46 | 9 |
| Auditor | Good | +0.40 | +0.44 | 6 |
| Surveyor | Good | +0.40 | +0.44 | 15 |
| Eavesdropper | Good | +0.40 | +0.44 | 11 |
| Chronicler | Good | +0.40 | +0.43 | 3 |
| Sniper | Good | +0.45 | +0.41 | 6 |
| Enforcer | Good | +0.45 | +0.41 | 3 |
| Kitsune | Good | +0.60 | +0.40 | 7 |
| Profiler | Good | +0.45 | +0.40 | 12 |
| Bloodhound | Good | +0.40 | +0.40 | 6 |
| Scout | Good | +0.30 | +0.39 | 13 |
| Coroner | Good | +0.35 | +0.38 | 4 |
| Vanilla Villager | Good | +0.25 | +0.37 | 67 |
| Fortune Teller | Good | +0.35 | +0.37 | 20 |
| Philanthropist | Good | +0.35 | +0.36 | 8 |
| Accountant | Good | +0.35 | +0.32 | 19 |
| Juror | Good | +0.35 | +0.25 | 8 |
| Scrutineer | Good | +0.30 | +0.17 | 4 |
| Roleplayer | Good | +0.00 | +0.09 | 8 |
| Executioner | Neutral | -0.20 | -0.05 | 20 |
| Jester | Neutral | -0.15 | -0.13 | 29 |
| Vulture | Neutral | -0.25 | -0.17 | 6 |
| Magpie | Neutral | -0.15 | -0.22 | 2 |
| Bounty Hunter | Neutral | -0.30 | -0.29 | 7 |
| Serial Killer | Neutral | -0.60 | -0.75 | 15 |
| Arsonist | Neutral | -0.80 | -0.90 | 18 |

A trait's power is how much it helps its holder's side (the Village for a Village holder, the Yakuza for a Yakuza; a Neutral holder's traits aren't counted). Its prior is its power in traits.py.

| Trait | Holder | Prior | Power | Games |
|---|---|---|---|---|
| Avenger | Village | +0.40 | +0.41 | 1 |
| Spare Blade | Yakuza | +0.35 | +0.40 | 1 |
| Grudge | Yakuza | +0.30 | +0.36 | 2 |
| Armed | Village | +0.25 | +0.35 | 4 |
| Disguised | Yakuza | +0.30 | +0.28 | 1 |
| Martyr | Village | +0.15 | +0.27 | 5 |
| Armed | Yakuza | +0.20 | +0.24 | 1 |
| Stolen Blade | Village | +0.30 | +0.23 | 1 |
| Katana Master | Yakuza | +0.25 | +0.22 | 1 |
| Stocked | Village, Yakuza, Neutral | +0.15 | +0.20 | 1 |
| Kindred | Village | +0.15 | +0.18 | 3 |
| Grudge | Village, Neutral | +0.10 | +0.15 | 2 |
| Narrow Escape | Yakuza | +0.10 | +0.14 | 1 |
| Faultline | Village | +0.15 | +0.12 | 1 |
| Narrow Escape | Village, Neutral | +0.15 | +0.11 | 1 |
| Selfless | Yakuza | +0.10 | +0.10 | 0 |
| Confidant | Village, Yakuza, Neutral | +0.10 | +0.10 | 4 |
| Loud | Village, Yakuza, Neutral | +0.10 | +0.09 | 3 |
| Katana Expert | Yakuza | +0.10 | +0.07 | 1 |
| Bonded | Village, Yakuza | +0.00 | +0.03 | 1 |
| Sleepwalker | Village, Neutral | -0.05 | +0.02 | 10 |
| Sleepwalker | Yakuza | +0.05 | +0.00 | 2 |
| Oblivious | Yakuza | -0.05 | -0.05 | 0 |
| Notorious | Village | -0.10 | -0.06 | 11 |
| Disguised | Village, Neutral | -0.10 | -0.07 | 2 |
| Cursed | Village | -0.10 | -0.08 | 14 |
| Zealot | Village, Neutral | -0.10 | -0.10 | 3 |
| Merciful | Yakuza | -0.15 | -0.10 | 1 |
| Selfish | Village, Yakuza | -0.10 | -0.10 | 2 |
| Remorseful | Village | -0.10 | -0.10 | 0 |
| Merciful | Village, Neutral | -0.10 | -0.10 | 0 |
| Oblivious | Village, Neutral | -0.10 | -0.10 | 0 |
| Curt | Village, Yakuza, Neutral | -0.10 | -0.15 | 3 |
| Rival | Village, Yakuza | -0.15 | -0.15 | 0 |
| Selfless | Village | -0.15 | -0.15 | 0 |
| Paranoid | Village | -0.10 | -0.15 | 1 |
| Drowsy | Village, Yakuza, Neutral | -0.15 | -0.16 | 2 |
| Zealot | Yakuza | -0.15 | -0.17 | 1 |
| Usurper | Yakuza | -0.30 | -0.30 | 0 |
| Shaky | Yakuza | -0.30 | -0.30 | 0 |
| Turncoat | Village | -0.40 | -0.40 | 0 |
