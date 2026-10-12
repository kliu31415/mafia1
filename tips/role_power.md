# Role power

Refit 2026-10-12 12:22 UTC by `role_power.py` from 66 finished live games (Village won 39). Power is how much a role adds to the Village's win chance, in logits (+0.4 is about +10 points near even). Offset +0.08 (prior -0.30). Change the priors in role_power.py; this file is rewritten after every game.

| Role | Side | Prior | Power | Games |
|---|---|---|---|---|
| Fabricator | Evil | -1.00 | -0.75 | 18 |
| Smuggler | Evil | -0.90 | -0.85 | 18 |
| Informant | Evil | -0.95 | -0.85 | 2 |
| Puppeteer | Evil | -1.00 | -0.86 | 14 |
| Ballot Stuffer | Evil | -0.95 | -0.87 | 12 |
| Mortician | Evil | -0.95 | -0.91 | 7 |
| Wiretap | Evil | -1.00 | -0.92 | 11 |
| Grunt | Evil | -0.85 | -0.96 | 30 |
| Talent Agent | Evil | -0.95 | -0.97 | 2 |
| Clerk | Evil | -0.95 | -0.98 | 16 |
| Fixer | Evil | -0.95 | -1.01 | 4 |
| Pharmacist | Evil | -1.10 | -1.01 | 24 |
| Diviner | Evil | -1.05 | -1.04 | 15 |
| Ritualist | Evil | -1.00 | -1.07 | 14 |
| Medic | Good | +0.55 | +0.78 | 39 |
| Sheriff | Good | +0.55 | +0.65 | 33 |
| Trapper | Good | +0.70 | +0.63 | 7 |
| Lookout | Good | +0.45 | +0.55 | 35 |
| Vigilante | Good | +0.45 | +0.55 | 21 |
| Veteran | Good | +0.50 | +0.54 | 10 |
| Tracker | Good | +0.45 | +0.53 | 20 |
| Party Animal | Good | +0.45 | +0.52 | 7 |
| Seer | Good | +0.40 | +0.52 | 13 |
| Archivist | Good | +0.40 | +0.50 | 18 |
| Cartographer | Good | +0.35 | +0.50 | 10 |
| Oracle | Good | +0.45 | +0.49 | 18 |
| Profiler | Good | +0.45 | +0.49 | 8 |
| Insomniac | Good | +0.35 | +0.48 | 3 |
| Auditor | Good | +0.40 | +0.48 | 2 |
| Surveyor | Good | +0.40 | +0.47 | 7 |
| Eavesdropper | Good | +0.40 | +0.45 | 10 |
| Census Taker | Good | +0.45 | +0.44 | 8 |
| Kitsune | Good | +0.60 | +0.44 | 4 |
| Prosecutor | Good | +0.40 | +0.44 | 11 |
| Sniper | Good | +0.45 | +0.42 | 3 |
| Scout | Good | +0.30 | +0.40 | 8 |
| Fortune Teller | Good | +0.35 | +0.39 | 17 |
| Philanthropist | Good | +0.35 | +0.38 | 6 |
| Enforcer | Good | +0.45 | +0.38 | 2 |
| Chronicler | Good | +0.40 | +0.37 | 1 |
| Coroner | Good | +0.35 | +0.36 | 3 |
| Accountant | Good | +0.35 | +0.33 | 14 |
| Bloodhound | Good | +0.40 | +0.32 | 2 |
| Vanilla Villager | Good | +0.25 | +0.32 | 46 |
| Juror | Good | +0.35 | +0.22 | 3 |
| Scrutineer | Good | +0.30 | +0.20 | 3 |
| Ex-Con | Good | +0.05 | +0.10 | 8 |
| Roleplayer | Good | +0.00 | -0.04 | 4 |
| Executioner | Neutral | -0.20 | -0.03 | 12 |
| Magpie | Neutral | -0.15 | -0.19 | 1 |
| Jester | Neutral | -0.15 | -0.20 | 17 |
| Vulture | Neutral | -0.25 | -0.23 | 3 |
| Bounty Hunter | Neutral | -0.30 | -0.30 | 4 |
| Serial Killer | Neutral | -0.60 | -0.73 | 11 |
| Arsonist | Neutral | -0.80 | -0.82 | 11 |
