# Role power

Refit 2026-10-15 08:15 UTC by `role_power.py` from 97 finished live games (Village won 60). Power is how much a role adds to the Village's win chance, in logits (+0.4 is about +10 points near even). Offset +0.11 (prior -0.30). Change the priors in role_power.py; this file is rewritten after every game.

| Role | Side | Prior | Power | Games |
|---|---|---|---|---|
| Grunt | Evil | -0.85 | -0.79 | 79 |
| Informant | Evil | -0.95 | -0.83 | 3 |
| Mortician | Evil | -0.95 | -0.83 | 13 |
| Fabricator | Evil | -1.00 | -0.83 | 25 |
| Wiretap | Evil | -1.00 | -0.95 | 13 |
| Pharmacist | Evil | -1.10 | -0.95 | 30 |
| Diviner | Evil | -1.05 | -0.96 | 23 |
| Talent Agent | Evil | -0.95 | -0.97 | 5 |
| Fixer | Evil | -0.95 | -1.03 | 8 |
| Ballot Stuffer | Evil | -1.20 | -1.04 | 19 |
| Ritualist | Evil | -1.00 | -1.11 | 20 |
| Medic | Good | +0.55 | +0.79 | 59 |
| Sheriff | Good | +0.55 | +0.75 | 49 |
| Mirror Maker | Good | +0.65 | +0.65 | 0 |
| Vigilante | Good | +0.45 | +0.64 | 33 |
| Trapper | Good | +0.70 | +0.59 | 17 |
| Seer | Good | +0.40 | +0.58 | 19 |
| Lookout | Good | +0.45 | +0.56 | 46 |
| Party Animal | Good | +0.45 | +0.55 | 10 |
| Veteran | Good | +0.50 | +0.53 | 16 |
| Insomniac | Good | +0.35 | +0.52 | 5 |
| Oracle | Good | +0.45 | +0.51 | 24 |
| Cartographer | Good | +0.35 | +0.49 | 11 |
| Tracker | Good | +0.45 | +0.48 | 29 |
| Prosecutor | Good | +0.40 | +0.47 | 14 |
| Auditor | Good | +0.40 | +0.47 | 8 |
| Census Taker | Good | +0.45 | +0.46 | 9 |
| Archivist | Good | +0.40 | +0.46 | 25 |
| Scout | Good | +0.30 | +0.45 | 16 |
| Eavesdropper | Good | +0.40 | +0.45 | 11 |
| Chronicler | Good | +0.40 | +0.44 | 4 |
| Sniper | Good | +0.45 | +0.43 | 8 |
| Mayor | Good | +0.40 | +0.42 | 1 |
| Enforcer | Good | +0.45 | +0.41 | 4 |
| Bloodhound | Good | +0.40 | +0.40 | 6 |
| Coroner | Good | +0.35 | +0.39 | 4 |
| Profiler | Good | +0.45 | +0.38 | 12 |
| Kitsune | Good | +0.60 | +0.37 | 7 |
| Fortune Teller | Good | +0.35 | +0.36 | 20 |
| Vanilla Villager | Good | +0.25 | +0.22 | 78 |
| Roleplayer | Good | +0.00 | +0.10 | 9 |
| Decoy | Neutral | +0.10 | +0.12 | 1 |
| Executioner | Neutral | -0.20 | -0.03 | 21 |
| Jester | Neutral | -0.15 | -0.14 | 31 |
| Vulture | Neutral | -0.25 | -0.15 | 8 |
| Magpie | Neutral | -0.15 | -0.19 | 3 |
| Bounty Hunter | Neutral | -0.30 | -0.28 | 7 |
| Hitman | Neutral | -0.40 | -0.40 | 0 |
| Werewolf | Neutral | -0.60 | -0.60 | 0 |
| Serial Killer | Neutral | -0.60 | -0.75 | 17 |
| Arsonist | Neutral | -0.80 | -0.91 | 18 |

A trait's power is how much it helps its holder's side (the Village for a Village holder, the Yakuza for a Yakuza; a Neutral holder's traits aren't counted). Its prior is its power in traits.py.

| Trait | Holder | Prior | Power | Games |
|---|---|---|---|---|
| Spare Blade | Yakuza | +0.35 | +0.41 | 1 |
| Avenger | Village | +0.30 | +0.38 | 4 |
| Grudge | Yakuza | +0.30 | +0.37 | 2 |
| Armed | Village | +0.25 | +0.35 | 4 |
| Martyr | Village | +0.15 | +0.27 | 5 |
| Disguised | Yakuza | +0.30 | +0.25 | 3 |
| Stolen Blade | Village | +0.30 | +0.25 | 2 |
| Armed | Yakuza | +0.20 | +0.22 | 2 |
| Stocked | Village, Yakuza, Neutral | +0.15 | +0.21 | 1 |
| Katana Master | Yakuza | +0.25 | +0.20 | 2 |
| Grudge | Village, Neutral | +0.10 | +0.16 | 3 |
| Kindred | Village | +0.15 | +0.16 | 3 |
| Faultline | Village | +0.15 | +0.15 | 3 |
| Narrow Escape | Yakuza | +0.10 | +0.12 | 2 |
| Confidant | Village, Yakuza, Neutral | +0.10 | +0.11 | 5 |
| Narrow Escape | Village, Neutral | +0.15 | +0.11 | 1 |
| Loud | Village, Yakuza, Neutral | +0.10 | +0.11 | 4 |
| Selfless | Yakuza | +0.10 | +0.10 | 0 |
| Katana Expert | Yakuza | +0.10 | +0.07 | 1 |
| Bonded | Village, Yakuza | +0.00 | +0.03 | 2 |
| Sleepwalker | Village, Neutral | -0.05 | +0.03 | 11 |
| Sleepwalker | Yakuza | +0.05 | +0.01 | 2 |
| Cursed | Village | -0.10 | -0.03 | 16 |
| Disguised | Village, Neutral | -0.10 | -0.04 | 4 |
| Ashamed | Village | -0.05 | -0.05 | 0 |
| Oblivious | Yakuza | -0.05 | -0.05 | 0 |
| Remorseful | Village | -0.10 | -0.05 | 1 |
| Notorious | Village | -0.10 | -0.05 | 12 |
| Zealot | Village, Neutral | -0.10 | -0.09 | 4 |
| Merciful | Village, Neutral | -0.10 | -0.10 | 0 |
| Oblivious | Village, Neutral | -0.10 | -0.10 | 0 |
| Selfish | Village, Yakuza | -0.10 | -0.10 | 3 |
| Rival | Village, Yakuza | -0.15 | -0.12 | 1 |
| Merciful | Yakuza | -0.15 | -0.12 | 2 |
| Curt | Village, Yakuza, Neutral | -0.10 | -0.12 | 4 |
| Paranoid | Village | -0.10 | -0.12 | 3 |
| Selfless | Village | -0.15 | -0.15 | 0 |
| Zealot | Yakuza | -0.15 | -0.16 | 1 |
| Drowsy | Village, Yakuza, Neutral | -0.15 | -0.17 | 2 |
| Shaky | Yakuza | -0.30 | -0.31 | 1 |
| Usurper | Yakuza | -0.30 | -0.32 | 1 |
| Turncoat | Village | -0.40 | -0.40 | 0 |
