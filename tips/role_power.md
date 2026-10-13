# Role power

Refit 2026-10-13 08:08 UTC by `role_power.py` from 84 finished live games (Village won 49). Power is how much a role adds to the Village's win chance, in logits (+0.4 is about +10 points near even). Offset +0.03 (prior -0.30). Change the priors in role_power.py; this file is rewritten after every game.

| Role | Side | Prior | Power | Games |
|---|---|---|---|---|
| Puppeteer | Evil | -1.00 | -0.79 | 24 |
| Smuggler | Evil | -0.90 | -0.81 | 21 |
| Informant | Evil | -0.95 | -0.82 | 3 |
| Fabricator | Evil | -1.00 | -0.83 | 23 |
| Mortician | Evil | -0.95 | -0.87 | 11 |
| Wiretap | Evil | -1.00 | -0.96 | 12 |
| Clerk | Evil | -0.95 | -0.96 | 27 |
| Pharmacist | Evil | -1.10 | -0.99 | 26 |
| Diviner | Evil | -1.05 | -1.00 | 20 |
| Talent Agent | Evil | -0.95 | -1.00 | 3 |
| Fixer | Evil | -0.95 | -1.00 | 4 |
| Grunt | Evil | -0.85 | -1.01 | 33 |
| Ballot Stuffer | Evil | -1.20 | -1.10 | 16 |
| Ritualist | Evil | -1.00 | -1.12 | 17 |
| Medic | Good | +0.55 | +0.77 | 53 |
| Sheriff | Good | +0.55 | +0.70 | 42 |
| Trapper | Good | +0.70 | +0.67 | 12 |
| Vigilante | Good | +0.45 | +0.59 | 26 |
| Seer | Good | +0.40 | +0.57 | 17 |
| Party Animal | Good | +0.45 | +0.56 | 10 |
| Veteran | Good | +0.50 | +0.53 | 13 |
| Lookout | Good | +0.45 | +0.52 | 41 |
| Tracker | Good | +0.45 | +0.51 | 25 |
| Oracle | Good | +0.45 | +0.50 | 23 |
| Prosecutor | Good | +0.40 | +0.49 | 14 |
| Insomniac | Good | +0.35 | +0.48 | 3 |
| Surveyor | Good | +0.40 | +0.47 | 13 |
| Cartographer | Good | +0.35 | +0.47 | 10 |
| Census Taker | Good | +0.45 | +0.45 | 8 |
| Profiler | Good | +0.45 | +0.45 | 11 |
| Eavesdropper | Good | +0.40 | +0.44 | 11 |
| Archivist | Good | +0.40 | +0.44 | 23 |
| Auditor | Good | +0.40 | +0.43 | 5 |
| Sniper | Good | +0.45 | +0.41 | 5 |
| Kitsune | Good | +0.60 | +0.39 | 6 |
| Enforcer | Good | +0.45 | +0.38 | 2 |
| Coroner | Good | +0.35 | +0.38 | 4 |
| Chronicler | Good | +0.40 | +0.37 | 1 |
| Vanilla Villager | Good | +0.25 | +0.37 | 65 |
| Fortune Teller | Good | +0.35 | +0.37 | 19 |
| Bloodhound | Good | +0.40 | +0.36 | 5 |
| Scout | Good | +0.30 | +0.36 | 11 |
| Accountant | Good | +0.35 | +0.36 | 18 |
| Philanthropist | Good | +0.35 | +0.36 | 8 |
| Juror | Good | +0.35 | +0.26 | 6 |
| Scrutineer | Good | +0.30 | +0.17 | 4 |
| Roleplayer | Good | +0.00 | +0.01 | 6 |
| Executioner | Neutral | -0.20 | -0.07 | 18 |
| Jester | Neutral | -0.15 | -0.16 | 27 |
| Vulture | Neutral | -0.25 | -0.17 | 6 |
| Magpie | Neutral | -0.15 | -0.22 | 2 |
| Bounty Hunter | Neutral | -0.30 | -0.30 | 6 |
| Serial Killer | Neutral | -0.60 | -0.71 | 14 |
| Arsonist | Neutral | -0.80 | -0.91 | 17 |

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
| Grudge | Village, Neutral | +0.10 | +0.13 | 1 |
| Kindred | Village | +0.15 | +0.12 | 1 |
| Faultline | Village | +0.15 | +0.12 | 1 |
| Confidant | Village, Yakuza, Neutral | +0.10 | +0.10 | 1 |
| Selfless | Yakuza | +0.10 | +0.10 | 0 |
| Loud | Village, Yakuza, Neutral | +0.10 | +0.07 | 1 |
| Sleepwalker | Yakuza | +0.05 | +0.05 | 0 |
| Bonded | Village, Yakuza | +0.00 | +0.00 | 0 |
| Sleepwalker | Village, Neutral | -0.05 | -0.01 | 9 |
| Oblivious | Yakuza | -0.05 | -0.05 | 0 |
| Notorious | Village | -0.10 | -0.05 | 11 |
| Cursed | Village | -0.10 | -0.08 | 14 |
| Remorseful | Village | -0.10 | -0.10 | 0 |
| Merciful | Village, Neutral | -0.10 | -0.10 | 0 |
| Disguised | Village, Neutral | -0.10 | -0.10 | 0 |
| Selfish | Village, Yakuza | -0.10 | -0.10 | 0 |
| Oblivious | Village, Neutral | -0.10 | -0.10 | 0 |
| Merciful | Yakuza | -0.15 | -0.10 | 1 |
| Curt | Village, Yakuza, Neutral | -0.10 | -0.13 | 1 |
| Zealot | Village, Neutral | -0.10 | -0.15 | 1 |
| Paranoid | Village | -0.10 | -0.15 | 1 |
| Zealot | Yakuza | -0.15 | -0.15 | 0 |
| Selfless | Village | -0.15 | -0.15 | 0 |
| Drowsy | Village, Yakuza, Neutral | -0.15 | -0.20 | 1 |
| Usurper | Yakuza | -0.30 | -0.30 | 0 |
| Shaky | Yakuza | -0.30 | -0.30 | 0 |
| Turncoat | Village | -0.40 | -0.40 | 0 |
