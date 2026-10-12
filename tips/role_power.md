# Role power

Refit 2026-10-12 15:00 UTC by `role_power.py` from 82 finished live games (Village won 49). Power is how much a role adds to the Village's win chance, in logits (+0.4 is about +10 points near even). Offset +0.09 (prior -0.30). Change the priors in role_power.py; this file is rewritten after every game.

| Role | Side | Prior | Power | Games |
|---|---|---|---|---|
| Fabricator | Evil | -1.00 | -0.80 | 22 |
| Puppeteer | Evil | -1.00 | -0.80 | 24 |
| Smuggler | Evil | -0.90 | -0.82 | 21 |
| Informant | Evil | -0.95 | -0.83 | 3 |
| Ballot Stuffer | Evil | -0.95 | -0.85 | 15 |
| Mortician | Evil | -0.95 | -0.89 | 11 |
| Talent Agent | Evil | -0.95 | -0.97 | 2 |
| Wiretap | Evil | -1.00 | -0.97 | 12 |
| Clerk | Evil | -0.95 | -0.97 | 27 |
| Diviner | Evil | -1.05 | -0.98 | 19 |
| Grunt | Evil | -0.85 | -0.98 | 32 |
| Pharmacist | Evil | -1.10 | -1.00 | 26 |
| Fixer | Evil | -0.95 | -1.01 | 4 |
| Ritualist | Evil | -1.00 | -1.14 | 17 |
| Medic | Good | +0.55 | +0.77 | 52 |
| Sheriff | Good | +0.55 | +0.71 | 41 |
| Trapper | Good | +0.70 | +0.70 | 11 |
| Vigilante | Good | +0.45 | +0.62 | 25 |
| Seer | Good | +0.40 | +0.56 | 17 |
| Party Animal | Good | +0.45 | +0.55 | 10 |
| Veteran | Good | +0.50 | +0.54 | 12 |
| Lookout | Good | +0.45 | +0.54 | 40 |
| Tracker | Good | +0.45 | +0.54 | 24 |
| Oracle | Good | +0.45 | +0.53 | 22 |
| Auditor | Good | +0.40 | +0.48 | 4 |
| Insomniac | Good | +0.35 | +0.48 | 3 |
| Prosecutor | Good | +0.40 | +0.48 | 14 |
| Cartographer | Good | +0.35 | +0.47 | 10 |
| Profiler | Good | +0.45 | +0.46 | 10 |
| Surveyor | Good | +0.40 | +0.46 | 13 |
| Archivist | Good | +0.40 | +0.45 | 22 |
| Census Taker | Good | +0.45 | +0.44 | 8 |
| Eavesdropper | Good | +0.40 | +0.44 | 11 |
| Kitsune | Good | +0.60 | +0.41 | 5 |
| Sniper | Good | +0.45 | +0.39 | 5 |
| Coroner | Good | +0.35 | +0.38 | 4 |
| Enforcer | Good | +0.45 | +0.38 | 2 |
| Chronicler | Good | +0.40 | +0.37 | 1 |
| Fortune Teller | Good | +0.35 | +0.37 | 19 |
| Scout | Good | +0.30 | +0.36 | 11 |
| Bloodhound | Good | +0.40 | +0.36 | 5 |
| Philanthropist | Good | +0.35 | +0.35 | 8 |
| Accountant | Good | +0.35 | +0.35 | 18 |
| Vanilla Villager | Good | +0.25 | +0.29 | 59 |
| Juror | Good | +0.35 | +0.25 | 6 |
| Scrutineer | Good | +0.30 | +0.17 | 4 |
| Ex-Con | Good | +0.05 | +0.10 | 9 |
| Roleplayer | Good | +0.00 | -0.00 | 6 |
| Executioner | Neutral | -0.20 | -0.05 | 17 |
| Jester | Neutral | -0.15 | -0.13 | 26 |
| Vulture | Neutral | -0.25 | -0.18 | 6 |
| Magpie | Neutral | -0.15 | -0.22 | 2 |
| Bounty Hunter | Neutral | -0.30 | -0.31 | 6 |
| Serial Killer | Neutral | -0.60 | -0.73 | 14 |
| Arsonist | Neutral | -0.80 | -0.89 | 16 |

A trait's power is how much it helps its holder's side (the Village for a Village holder, the Yakuza for a Yakuza; a Neutral holder's traits aren't counted). Its prior is its power in traits.py.

| Trait | Holder | Prior | Power | Games |
|---|---|---|---|---|
| Avenger | Village | +0.40 | +0.41 | 1 |
| Grudge | Yakuza | +0.30 | +0.33 | 1 |
| Armed | Village | +0.25 | +0.32 | 2 |
| Martyr | Village | +0.15 | +0.23 | 3 |
| Grudge | Village, Neutral | +0.10 | +0.13 | 1 |
| Kindred | Village | +0.15 | +0.12 | 1 |
| Faultline | Village | +0.15 | +0.12 | 1 |
| Confidant | Village, Yakuza, Neutral | +0.10 | +0.10 | 1 |
| Loud | Village, Yakuza, Neutral | +0.10 | +0.07 | 1 |
| Cursed | Village | -0.10 | -0.06 | 13 |
| Notorious | Village | -0.10 | -0.10 | 2 |
| Curt | Village, Yakuza, Neutral | -0.10 | -0.13 | 1 |
