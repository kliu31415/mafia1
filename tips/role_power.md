# Role power

Refit 2026-10-11 10:01 by `role_power.py` from 58 finished live games (Village won 37). Power is how much a role adds to the Village's win chance, in logits (+0.4 is about +10 points near even). Offset +0.26 (prior -0.30). Change the priors in role_power.py; this file is rewritten after every game.

| Role | Side | Prior | Power | Games |
|---|---|---|---|---|
| Grunt | Evil | -0.85 | -0.81 | 24 |
| Ballot Stuffer | Evil | -0.95 | -0.83 | 8 |
| Smuggler | Evil | -0.90 | -0.88 | 14 |
| Mortician | Evil | -0.95 | -0.90 | 11 |
| Puppeteer | Evil | -1.00 | -0.91 | 20 |
| Fabricator | Evil | -1.00 | -0.91 | 18 |
| Fixer | Evil | -0.95 | -0.91 | 1 |
| Informant | Evil | -0.95 | -0.91 | 1 |
| Wiretap | Evil | -1.00 | -0.95 | 8 |
| Clerk | Evil | -0.95 | -0.97 | 25 |
| Pharmacist | Evil | -1.10 | -0.98 | 22 |
| Ritualist | Evil | -1.00 | -1.00 | 11 |
| Diviner | Evil | -1.05 | -1.06 | 16 |
| Sheriff | Good | +0.55 | +0.82 | 32 |
| Medic | Good | +0.55 | +0.78 | 40 |
| Trapper | Good | +0.55 | +0.61 | 6 |
| Party Animal | Good | +0.45 | +0.52 | 8 |
| Vigilante | Good | +0.45 | +0.52 | 20 |
| Tracker | Good | +0.45 | +0.51 | 18 |
| Prosecutor | Good | +0.40 | +0.50 | 13 |
| Lookout | Good | +0.45 | +0.50 | 34 |
| Oracle | Good | +0.45 | +0.49 | 20 |
| Census Taker | Good | +0.45 | +0.49 | 5 |
| Profiler | Good | +0.45 | +0.47 | 5 |
| Seer | Good | +0.40 | +0.46 | 14 |
| Surveyor | Good | +0.40 | +0.46 | 13 |
| Veteran | Good | +0.50 | +0.45 | 9 |
| Auditor | Good | +0.40 | +0.44 | 1 |
| Eavesdropper | Good | +0.40 | +0.42 | 8 |
| Archivist | Good | +0.40 | +0.41 | 20 |
| Cartographer | Good | +0.35 | +0.41 | 7 |
| Philanthropist | Good | +0.35 | +0.40 | 5 |
| Chronicler | Good | +0.40 | +0.40 | 0 |
| Coroner | Good | +0.35 | +0.39 | 2 |
| Insomniac | Good | +0.35 | +0.39 | 1 |
| Accountant | Good | +0.35 | +0.38 | 15 |
| Scout | Good | +0.30 | +0.36 | 11 |
| Fortune Teller | Good | +0.35 | +0.33 | 17 |
| Vanilla Villager | Good | +0.25 | +0.31 | 37 |
| Cardinal | Good | +0.10 | +0.15 | 11 |
| Ex-Con | Good | +0.05 | +0.08 | 8 |
| Roleplayer | Good | +0.00 | +0.00 | 4 |
| Executioner | Neutral | -0.20 | -0.08 | 16 |
| Jester | Neutral | -0.15 | -0.14 | 21 |
| Vulture | Neutral | -0.25 | -0.18 | 4 |
| Serial Killer | Neutral | -0.60 | -0.54 | 6 |
| Arsonist | Neutral | -0.80 | -0.90 | 15 |
