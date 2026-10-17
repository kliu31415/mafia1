# Role power

Refit 2026-10-17 04:57 UTC by `role_power.py` from 106 finished live games (Village won 67). Power is how much a role adds to the Village's win chance, in logits (+0.4 is about +10 points near even). Offset +0.09 (prior -0.30); all-frontier games add +1.09 (22 games, prior +0.00). Change the priors in role_power.py; this file is rewritten after every game.

| Role | Side | Prior | Power | Games |
|---|---|---|---|---|
| Grunt | Evil | -0.85 | -0.79 | 83 |
| Informant | Evil | -0.95 | -0.82 | 3 |
| Fabricator | Evil | -1.00 | -0.87 | 29 |
| Mortician | Evil | -0.95 | -0.87 | 15 |
| Pharmacist | Evil | -1.10 | -0.95 | 30 |
| Wiretap | Evil | -1.00 | -0.97 | 13 |
| Diviner | Evil | -1.05 | -0.98 | 24 |
| Talent Agent | Evil | -0.95 | -1.00 | 5 |
| Fixer | Evil | -0.95 | -1.02 | 9 |
| Ballot Stuffer | Evil | -1.20 | -1.06 | 21 |
| Ritualist | Evil | -1.00 | -1.11 | 21 |
| Oathsworn | Evil | -1.30 | -1.24 | 3 |
| Medic | Good | +0.55 | +0.77 | 64 |
| Sheriff | Good | +0.55 | +0.76 | 53 |
| Mirror Maker | Good | +0.65 | +0.71 | 3 |
| Vigilante | Good | +0.45 | +0.67 | 39 |
| Trapper | Good | +0.70 | +0.58 | 19 |
| Seer | Good | +0.40 | +0.57 | 19 |
| Tracker | Good | +0.45 | +0.54 | 32 |
| Lookout | Good | +0.45 | +0.54 | 50 |
| Veteran | Good | +0.50 | +0.54 | 18 |
| Party Animal | Good | +0.45 | +0.51 | 10 |
| Cartographer | Good | +0.35 | +0.51 | 12 |
| Insomniac | Good | +0.35 | +0.50 | 8 |
| Prosecutor | Good | +0.40 | +0.49 | 15 |
| Scout | Good | +0.30 | +0.47 | 17 |
| Eavesdropper | Good | +0.40 | +0.46 | 11 |
| Auditor | Good | +0.40 | +0.43 | 9 |
| Chronicler | Good | +0.40 | +0.43 | 4 |
| Oracle | Good | +0.45 | +0.42 | 25 |
| Enforcer | Good | +0.45 | +0.42 | 7 |
| Census Taker | Good | +0.45 | +0.42 | 11 |
| Archivist | Good | +0.40 | +0.42 | 25 |
| Sniper | Good | +0.45 | +0.41 | 8 |
| Coroner | Good | +0.35 | +0.41 | 5 |
| Kitsune | Good | +0.60 | +0.40 | 10 |
| Bloodhound | Good | +0.40 | +0.40 | 8 |
| Mayor | Good | +0.40 | +0.39 | 3 |
| Fortune Teller | Good | +0.35 | +0.37 | 21 |
| Profiler | Good | +0.45 | +0.33 | 14 |
| Vanilla Villager | Good | +0.25 | +0.21 | 80 |
| Saint | Good | +0.05 | +0.07 | 1 |
| Roleplayer | Good | +0.00 | -0.00 | 12 |
| Decoy | Neutral | +0.10 | +0.12 | 1 |
| Executioner | Neutral | -0.20 | -0.06 | 21 |
| Jester | Neutral | -0.15 | -0.14 | 32 |
| Vulture | Neutral | -0.25 | -0.14 | 9 |
| Magpie | Neutral | -0.15 | -0.19 | 4 |
| Bounty Hunter | Neutral | -0.30 | -0.25 | 8 |
| Hitman | Neutral | -0.40 | -0.41 | 3 |
| Werewolf | Neutral | -0.60 | -0.56 | 2 |
| Serial Killer | Neutral | -0.60 | -0.76 | 17 |
| Arsonist | Neutral | -0.80 | -0.94 | 20 |

A trait's power is how much it helps its holder's side (the Village for a Village holder, the Yakuza for a Yakuza; a Neutral holder's traits aren't counted). Its prior is its power in traits.py.

| Trait | Holder | Prior | Power | Games |
|---|---|---|---|---|
| Berserker | Yakuza | +0.45 | +0.45 | 0 |
| Spare Blade | Yakuza | +0.35 | +0.39 | 2 |
| Avenger | Village | +0.30 | +0.39 | 4 |
| Grudge | Yakuza | +0.30 | +0.38 | 2 |
| Armed | Village | +0.25 | +0.36 | 4 |
| Disguised | Yakuza | +0.30 | +0.29 | 5 |
| Stolen Blade | Village | +0.30 | +0.26 | 3 |
| Martyr | Village | +0.15 | +0.24 | 7 |
| Armed | Yakuza | +0.20 | +0.22 | 2 |
| Katana Master | Yakuza | +0.25 | +0.21 | 2 |
| Kindred | Village | +0.15 | +0.19 | 5 |
| Stocked | Village, Yakuza, Neutral | +0.15 | +0.18 | 3 |
| Faultline | Village | +0.15 | +0.16 | 4 |
| Grudge | Village, Neutral | +0.10 | +0.16 | 4 |
| Confidant | Village, Yakuza, Neutral | +0.10 | +0.12 | 7 |
| Loud | Village, Yakuza, Neutral | +0.10 | +0.12 | 4 |
| Narrow Escape | Village, Neutral | +0.15 | +0.11 | 1 |
| Narrow Escape | Yakuza | +0.10 | +0.11 | 3 |
| Selfless | Yakuza | +0.10 | +0.10 | 0 |
| Katana Expert | Yakuza | +0.10 | +0.07 | 1 |
| Bonded | Village, Yakuza | +0.00 | +0.07 | 3 |
| Sleepwalker | Yakuza | +0.05 | +0.01 | 2 |
| Cursed | Village | -0.10 | -0.01 | 18 |
| Sleepwalker | Village, Neutral | -0.05 | -0.01 | 11 |
| Disguised | Village, Neutral | -0.10 | -0.02 | 5 |
| Zealot | Village, Neutral | -0.10 | -0.05 | 6 |
| Oblivious | Yakuza | -0.05 | -0.05 | 0 |
| Selfish | Village, Yakuza | -0.10 | -0.05 | 4 |
| Ashamed | Village | -0.05 | -0.06 | 3 |
| Curt | Village, Yakuza, Neutral | -0.10 | -0.07 | 6 |
| Notorious | Village | -0.10 | -0.09 | 13 |
| Merciful | Yakuza | -0.15 | -0.09 | 4 |
| Remorseful | Village | -0.10 | -0.10 | 3 |
| Merciful | Village, Neutral | -0.10 | -0.11 | 2 |
| Rival | Village, Yakuza | -0.15 | -0.12 | 1 |
| Oblivious | Village, Neutral | -0.10 | -0.13 | 2 |
| Paranoid | Village | -0.10 | -0.15 | 5 |
| Selfless | Village | -0.15 | -0.15 | 0 |
| Spiteful | Village | -0.15 | -0.15 | 0 |
| Zealot | Yakuza | -0.15 | -0.16 | 1 |
| Drowsy | Village, Yakuza, Neutral | -0.15 | -0.19 | 3 |
| Shaky | Yakuza | -0.30 | -0.31 | 1 |
| Usurper | Yakuza | -0.30 | -0.33 | 2 |
| Turncoat | Village | -0.40 | -0.45 | 1 |
