# Role power

Refit 2026-10-11 23:56 by `role_power.py` from 67 finished live games (Village won 41). Power is how much a role adds to the Village's win chance, in logits (+0.4 is about +10 points near even). Offset +0.22 (prior -0.30). Change the priors in role_power.py; this file is rewritten after every game.

| Role | Side | Prior | Power | Games |
|---|---|---|---|---|
| Grunt | Evil | -0.85 | -0.72 | 26 |
| Fabricator | Evil | -1.00 | -0.84 | 20 |
| Ballot Stuffer | Evil | -0.95 | -0.86 | 13 |
| Informant | Evil | -0.95 | -0.86 | 2 |
| Puppeteer | Evil | -1.00 | -0.87 | 21 |
| Mortician | Evil | -0.95 | -0.89 | 11 |
| Smuggler | Evil | -0.90 | -0.92 | 18 |
| Wiretap | Evil | -1.00 | -0.96 | 10 |
| Clerk | Evil | -0.95 | -0.96 | 25 |
| Talent Agent | Evil | -0.95 | -0.98 | 1 |
| Pharmacist | Evil | -1.10 | -0.99 | 22 |
| Fixer | Evil | -0.95 | -1.02 | 4 |
| Diviner | Evil | -1.05 | -1.04 | 17 |
| Ritualist | Evil | -1.00 | -1.12 | 15 |
| Sheriff | Good | +0.55 | +0.84 | 34 |
| Medic | Good | +0.55 | +0.77 | 43 |
| Trapper | Good | +0.55 | +0.64 | 7 |
| Vigilante | Good | +0.45 | +0.54 | 22 |
| Party Animal | Good | +0.45 | +0.54 | 9 |
| Oracle | Good | +0.45 | +0.52 | 21 |
| Tracker | Good | +0.45 | +0.51 | 18 |
| Prosecutor | Good | +0.40 | +0.50 | 13 |
| Seer | Good | +0.40 | +0.50 | 15 |
| Veteran | Good | +0.50 | +0.49 | 10 |
| Lookout | Good | +0.45 | +0.48 | 39 |
| Surveyor | Good | +0.40 | +0.47 | 13 |
| Profiler | Good | +0.45 | +0.46 | 7 |
| Census Taker | Good | +0.45 | +0.44 | 8 |
| Auditor | Good | +0.40 | +0.44 | 1 |
| Insomniac | Good | +0.35 | +0.44 | 2 |
| Archivist | Good | +0.40 | +0.44 | 21 |
| Cartographer | Good | +0.35 | +0.43 | 8 |
| Eavesdropper | Good | +0.40 | +0.42 | 10 |
| Chronicler | Good | +0.40 | +0.37 | 1 |
| Scout | Good | +0.30 | +0.36 | 11 |
| Coroner | Good | +0.35 | +0.35 | 3 |
| Fortune Teller | Good | +0.35 | +0.35 | 18 |
| Philanthropist | Good | +0.35 | +0.34 | 7 |
| Accountant | Good | +0.35 | +0.32 | 17 |
| Bloodhound | Good | +0.40 | +0.30 | 3 |
| Vanilla Villager | Good | +0.25 | +0.29 | 46 |
| Juror | Good | +0.35 | +0.26 | 3 |
| Scrutineer | Good | +0.30 | +0.21 | 3 |
| Cardinal | Good | +0.10 | +0.12 | 12 |
| Ex-Con | Good | +0.05 | +0.09 | 9 |
| Roleplayer | Good | +0.00 | -0.03 | 5 |
| Executioner | Neutral | -0.20 | -0.08 | 16 |
| Jester | Neutral | -0.15 | -0.17 | 22 |
| Vulture | Neutral | -0.25 | -0.21 | 5 |
| Magpie | Neutral | -0.15 | -0.21 | 2 |
| Bounty Hunter | Neutral | -0.30 | -0.33 | 3 |
| Serial Killer | Neutral | -0.60 | -0.57 | 7 |
| Arsonist | Neutral | -0.80 | -0.89 | 15 |
