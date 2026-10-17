# Role power

Refit 2026-10-17 14:04 UTC by `role_power.py` from 108 finished live games (Village won 68). Power is how much a role adds to the Village's win chance, in logits (+0.4 is about +10 points near even). Offset +0.09 (prior -0.30); all-frontier games add +1.08 (24 games, prior +0.00). Change the priors in role_power.py; this file is rewritten after every game.

| Role | Side | Prior | Power | Games |
|---|---|---|---|---|
| Informant | Evil | -0.95 | -0.77 | 4 |
| Grunt | Evil | -0.85 | -0.79 | 83 |
| Fabricator | Evil | -1.00 | -0.87 | 29 |
| Mortician | Evil | -0.95 | -0.93 | 16 |
| Pharmacist | Evil | -1.10 | -0.96 | 30 |
| Wiretap | Evil | -1.00 | -0.97 | 13 |
| Diviner | Evil | -1.05 | -0.98 | 24 |
| Talent Agent | Evil | -0.95 | -1.00 | 5 |
| Fixer | Evil | -0.95 | -1.02 | 9 |
| Ballot Stuffer | Evil | -1.20 | -1.08 | 22 |
| Ritualist | Evil | -1.00 | -1.11 | 23 |
| Oathsworn | Evil | -1.30 | -1.21 | 4 |
| Medic | Good | +0.55 | +0.78 | 64 |
| Sheriff | Good | +0.55 | +0.76 | 53 |
| Mirror Maker | Good | +0.65 | +0.74 | 4 |
| Vigilante | Good | +0.45 | +0.64 | 40 |
| Trapper | Good | +0.70 | +0.58 | 19 |
| Veteran | Good | +0.50 | +0.55 | 18 |
| Seer | Good | +0.40 | +0.54 | 20 |
| Tracker | Good | +0.45 | +0.54 | 32 |
| Lookout | Good | +0.45 | +0.54 | 50 |
| Party Animal | Good | +0.45 | +0.53 | 11 |
| Cartographer | Good | +0.35 | +0.50 | 12 |
| Insomniac | Good | +0.35 | +0.50 | 8 |
| Oracle | Good | +0.45 | +0.50 | 26 |
| Prosecutor | Good | +0.40 | +0.49 | 15 |
| Eavesdropper | Good | +0.40 | +0.46 | 11 |
| Scout | Good | +0.30 | +0.44 | 18 |
| Enforcer | Good | +0.45 | +0.44 | 8 |
| Chronicler | Good | +0.40 | +0.43 | 4 |
| Auditor | Good | +0.40 | +0.42 | 9 |
| Census Taker | Good | +0.45 | +0.42 | 11 |
| Coroner | Good | +0.35 | +0.41 | 5 |
| Sniper | Good | +0.45 | +0.41 | 8 |
| Bloodhound | Good | +0.40 | +0.40 | 8 |
| Archivist | Good | +0.40 | +0.39 | 26 |
| Mayor | Good | +0.40 | +0.39 | 3 |
| Fortune Teller | Good | +0.35 | +0.37 | 21 |
| Profiler | Good | +0.45 | +0.35 | 15 |
| Kitsune | Good | +0.60 | +0.35 | 11 |
| Vanilla Villager | Good | +0.25 | +0.21 | 80 |
| Saint | Good | +0.05 | +0.07 | 1 |
| Roleplayer | Good | +0.00 | -0.00 | 12 |
| Decoy | Neutral | +0.10 | +0.12 | 3 |
| Executioner | Neutral | -0.20 | -0.05 | 21 |
| Jester | Neutral | -0.15 | -0.14 | 32 |
| Vulture | Neutral | -0.25 | -0.17 | 10 |
| Magpie | Neutral | -0.15 | -0.19 | 4 |
| Bounty Hunter | Neutral | -0.30 | -0.28 | 9 |
| Hitman | Neutral | -0.40 | -0.38 | 4 |
| Werewolf | Neutral | -0.60 | -0.56 | 2 |
| Serial Killer | Neutral | -0.60 | -0.76 | 17 |
| Arsonist | Neutral | -0.80 | -0.95 | 20 |

A trait's power is how much it helps its holder's side (the Village for a Village holder, the Yakuza for a Yakuza; a Neutral holder's traits aren't counted). Its prior is its power in traits.py.

| Trait | Holder | Prior | Power | Games |
|---|---|---|---|---|
| Berserker | Yakuza | +0.45 | +0.45 | 0 |
| Spare Blade | Yakuza | +0.35 | +0.39 | 2 |
| Avenger | Village | +0.30 | +0.39 | 4 |
| Armed | Village | +0.25 | +0.36 | 4 |
| Grudge | Yakuza | +0.30 | +0.36 | 3 |
| Disguised | Yakuza | +0.30 | +0.29 | 5 |
| Stolen Blade | Village | +0.30 | +0.26 | 3 |
| Armed | Yakuza | +0.20 | +0.22 | 2 |
| Martyr | Village | +0.15 | +0.21 | 8 |
| Kindred | Village | +0.15 | +0.20 | 5 |
| Grudge | Village, Neutral | +0.10 | +0.19 | 5 |
| Katana Master | Yakuza | +0.25 | +0.18 | 3 |
| Confidant | Village, Yakuza, Neutral | +0.10 | +0.18 | 9 |
| Stocked | Village, Yakuza, Neutral | +0.15 | +0.18 | 3 |
| Faultline | Village | +0.15 | +0.17 | 4 |
| Narrow Escape | Village, Neutral | +0.15 | +0.11 | 1 |
| Narrow Escape | Yakuza | +0.10 | +0.11 | 3 |
| Selfless | Yakuza | +0.10 | +0.10 | 0 |
| Loud | Village, Yakuza, Neutral | +0.10 | +0.09 | 5 |
| Katana Expert | Yakuza | +0.10 | +0.07 | 1 |
| Bonded | Village, Yakuza | +0.00 | +0.07 | 4 |
| Cursed | Village | -0.10 | -0.01 | 20 |
| Sleepwalker | Village, Neutral | -0.05 | -0.01 | 11 |
| Disguised | Village, Neutral | -0.10 | -0.02 | 5 |
| Sleepwalker | Yakuza | +0.05 | -0.02 | 3 |
| Selfish | Village, Yakuza | -0.10 | -0.05 | 4 |
| Oblivious | Yakuza | -0.05 | -0.05 | 0 |
| Curt | Village, Yakuza, Neutral | -0.10 | -0.05 | 7 |
| Ashamed | Village | -0.05 | -0.06 | 3 |
| Rival | Village, Yakuza | -0.15 | -0.07 | 3 |
| Zealot | Village, Neutral | -0.10 | -0.07 | 7 |
| Merciful | Village, Neutral | -0.10 | -0.08 | 3 |
| Notorious | Village | -0.10 | -0.09 | 13 |
| Remorseful | Village | -0.10 | -0.10 | 3 |
| Merciful | Yakuza | -0.15 | -0.12 | 5 |
| Spiteful | Village | -0.15 | -0.12 | 1 |
| Oblivious | Village, Neutral | -0.10 | -0.13 | 2 |
| Selfless | Village | -0.15 | -0.15 | 0 |
| Zealot | Yakuza | -0.15 | -0.16 | 1 |
| Paranoid | Village | -0.10 | -0.18 | 6 |
| Drowsy | Village, Yakuza, Neutral | -0.15 | -0.19 | 4 |
| Shaky | Yakuza | -0.30 | -0.34 | 2 |
| Usurper | Yakuza | -0.30 | -0.36 | 3 |
| Turncoat | Village | -0.40 | -0.45 | 1 |
