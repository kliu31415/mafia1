# Role power

Refit 2026-10-11 22:49 by `role_power.py` from 66 finished live games (Village won 41). Power is how much a role adds to the Village's win chance, in logits (+0.4 is about +10 points near even). Offset +0.24 (prior -0.30). Change the priors in role_power.py; this file is rewritten after every game.

| Role | Side | Prior | Power | Games |
|---|---|---|---|---|
| Grunt | Evil | -0.85 | -0.73 | 26 |
| Fabricator | Evil | -1.00 | -0.84 | 20 |
| Ballot Stuffer | Evil | -0.95 | -0.84 | 12 |
| Informant | Evil | -0.95 | -0.86 | 2 |
| Puppeteer | Evil | -1.00 | -0.87 | 21 |
| Mortician | Evil | -0.95 | -0.90 | 11 |
| Smuggler | Evil | -0.90 | -0.90 | 17 |
| Wiretap | Evil | -1.00 | -0.96 | 10 |
| Clerk | Evil | -0.95 | -0.97 | 25 |
| Talent Agent | Evil | -0.95 | -0.99 | 1 |
| Pharmacist | Evil | -1.10 | -0.99 | 22 |
| Fixer | Evil | -0.95 | -1.02 | 4 |
| Diviner | Evil | -1.05 | -1.04 | 17 |
| Ritualist | Evil | -1.00 | -1.10 | 14 |
| Sheriff | Good | +0.55 | +0.83 | 34 |
| Medic | Good | +0.55 | +0.76 | 43 |
| Trapper | Good | +0.55 | +0.64 | 7 |
| Party Animal | Good | +0.45 | +0.54 | 9 |
| Vigilante | Good | +0.45 | +0.53 | 22 |
| Oracle | Good | +0.45 | +0.51 | 21 |
| Tracker | Good | +0.45 | +0.50 | 18 |
| Prosecutor | Good | +0.40 | +0.50 | 13 |
| Lookout | Good | +0.45 | +0.50 | 38 |
| Seer | Good | +0.40 | +0.49 | 15 |
| Veteran | Good | +0.50 | +0.49 | 10 |
| Surveyor | Good | +0.40 | +0.46 | 13 |
| Profiler | Good | +0.45 | +0.45 | 7 |
| Census Taker | Good | +0.45 | +0.44 | 8 |
| Auditor | Good | +0.40 | +0.44 | 1 |
| Insomniac | Good | +0.35 | +0.44 | 2 |
| Cartographer | Good | +0.35 | +0.43 | 8 |
| Archivist | Good | +0.40 | +0.43 | 21 |
| Eavesdropper | Good | +0.40 | +0.42 | 10 |
| Chronicler | Good | +0.40 | +0.36 | 1 |
| Scout | Good | +0.30 | +0.36 | 11 |
| Philanthropist | Good | +0.35 | +0.36 | 6 |
| Coroner | Good | +0.35 | +0.35 | 3 |
| Fortune Teller | Good | +0.35 | +0.35 | 18 |
| Accountant | Good | +0.35 | +0.34 | 16 |
| Bloodhound | Good | +0.40 | +0.32 | 2 |
| Vanilla Villager | Good | +0.25 | +0.29 | 45 |
| Juror | Good | +0.35 | +0.28 | 2 |
| Scrutineer | Good | +0.30 | +0.23 | 2 |
| Cardinal | Good | +0.10 | +0.15 | 11 |
| Ex-Con | Good | +0.05 | +0.09 | 9 |
| Roleplayer | Good | +0.00 | -0.03 | 5 |
| Executioner | Neutral | -0.20 | -0.08 | 16 |
| Jester | Neutral | -0.15 | -0.15 | 21 |
| Magpie | Neutral | -0.15 | -0.19 | 1 |
| Vulture | Neutral | -0.25 | -0.21 | 5 |
| Bounty Hunter | Neutral | -0.30 | -0.34 | 3 |
| Serial Killer | Neutral | -0.60 | -0.58 | 7 |
| Arsonist | Neutral | -0.80 | -0.89 | 15 |
