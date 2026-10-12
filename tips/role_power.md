# Role power

Refit 2026-10-12 13:50 UTC by `role_power.py` from 80 finished live games (Village won 48). Power is how much a role adds to the Village's win chance, in logits (+0.4 is about +10 points near even). Offset +0.09 (prior -0.30). Change the priors in role_power.py; this file is rewritten after every game.

| Role | Side | Prior | Power | Games |
|---|---|---|---|---|
| Fabricator | Evil | -1.00 | -0.80 | 22 |
| Puppeteer | Evil | -1.00 | -0.82 | 23 |
| Informant | Evil | -0.95 | -0.83 | 3 |
| Smuggler | Evil | -0.90 | -0.84 | 20 |
| Ballot Stuffer | Evil | -0.95 | -0.86 | 15 |
| Mortician | Evil | -0.95 | -0.89 | 11 |
| Wiretap | Evil | -1.00 | -0.94 | 11 |
| Clerk | Evil | -0.95 | -0.97 | 25 |
| Talent Agent | Evil | -0.95 | -0.97 | 2 |
| Diviner | Evil | -1.05 | -0.98 | 19 |
| Grunt | Evil | -0.85 | -0.99 | 32 |
| Pharmacist | Evil | -1.10 | -1.00 | 26 |
| Fixer | Evil | -0.95 | -1.01 | 4 |
| Ritualist | Evil | -1.00 | -1.14 | 17 |
| Medic | Good | +0.55 | +0.80 | 51 |
| Sheriff | Good | +0.55 | +0.71 | 41 |
| Trapper | Good | +0.70 | +0.67 | 10 |
| Vigilante | Good | +0.45 | +0.59 | 24 |
| Party Animal | Good | +0.45 | +0.55 | 10 |
| Veteran | Good | +0.50 | +0.54 | 12 |
| Lookout | Good | +0.45 | +0.54 | 40 |
| Tracker | Good | +0.45 | +0.54 | 24 |
| Seer | Good | +0.40 | +0.53 | 16 |
| Oracle | Good | +0.45 | +0.53 | 22 |
| Profiler | Good | +0.45 | +0.49 | 9 |
| Insomniac | Good | +0.35 | +0.48 | 3 |
| Prosecutor | Good | +0.40 | +0.48 | 14 |
| Cartographer | Good | +0.35 | +0.47 | 10 |
| Surveyor | Good | +0.40 | +0.46 | 13 |
| Auditor | Good | +0.40 | +0.46 | 2 |
| Archivist | Good | +0.40 | +0.45 | 22 |
| Census Taker | Good | +0.45 | +0.44 | 8 |
| Eavesdropper | Good | +0.40 | +0.44 | 11 |
| Kitsune | Good | +0.60 | +0.43 | 4 |
| Sniper | Good | +0.45 | +0.39 | 3 |
| Coroner | Good | +0.35 | +0.38 | 4 |
| Enforcer | Good | +0.45 | +0.38 | 2 |
| Chronicler | Good | +0.40 | +0.37 | 1 |
| Fortune Teller | Good | +0.35 | +0.37 | 19 |
| Scout | Good | +0.30 | +0.36 | 11 |
| Philanthropist | Good | +0.35 | +0.35 | 8 |
| Accountant | Good | +0.35 | +0.35 | 18 |
| Bloodhound | Good | +0.40 | +0.33 | 4 |
| Vanilla Villager | Good | +0.25 | +0.30 | 59 |
| Juror | Good | +0.35 | +0.25 | 6 |
| Scrutineer | Good | +0.30 | +0.17 | 4 |
| Ex-Con | Good | +0.05 | +0.10 | 9 |
| Roleplayer | Good | +0.00 | -0.03 | 5 |
| Executioner | Neutral | -0.20 | -0.05 | 17 |
| Jester | Neutral | -0.15 | -0.15 | 25 |
| Vulture | Neutral | -0.25 | -0.20 | 5 |
| Magpie | Neutral | -0.15 | -0.22 | 2 |
| Bounty Hunter | Neutral | -0.30 | -0.28 | 5 |
| Serial Killer | Neutral | -0.60 | -0.70 | 13 |
| Arsonist | Neutral | -0.80 | -0.89 | 16 |

A trait's power is how much it helps its holder's side (the Village for a Village holder, the Yakuza for a Yakuza; a Neutral holder's traits aren't counted). Its prior is its power in traits.py.

| Trait | Holder | Prior | Power | Games |
|---|---|---|---|---|
| Avenger | Village | +0.40 | +0.41 | 1 |
| Armed | Village | +0.25 | +0.32 | 2 |
| Grudge | Yakuza | +0.30 | +0.30 | 0 |
| Martyr | Village | +0.15 | +0.24 | 3 |
| Kindred | Village | +0.15 | +0.15 | 0 |
| Faultline | Village | +0.15 | +0.15 | 0 |
| Grudge | Village, Neutral | +0.10 | +0.10 | 0 |
| Loud | Village, Yakuza, Neutral | +0.10 | +0.10 | 0 |
| Confidant | Village, Yakuza, Neutral | +0.10 | +0.10 | 0 |
| Cursed | Village | -0.10 | -0.05 | 13 |
| Notorious | Village | -0.10 | -0.10 | 0 |
| Curt | Village, Yakuza, Neutral | -0.10 | -0.10 | 0 |
