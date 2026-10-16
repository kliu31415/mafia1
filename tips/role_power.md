# Role power

Refit 2026-10-16 06:24 UTC by `role_power.py` from 102 finished live games (Village won 63). Power is how much a role adds to the Village's win chance, in logits (+0.4 is about +10 points near even). Offset +0.08 (prior -0.30). Change the priors in role_power.py; this file is rewritten after every game.

| Role | Side | Prior | Power | Games |
|---|---|---|---|---|
| Grunt | Evil | -0.85 | -0.78 | 83 |
| Informant | Evil | -0.95 | -0.83 | 3 |
| Fabricator | Evil | -1.00 | -0.84 | 27 |
| Mortician | Evil | -0.95 | -0.85 | 14 |
| Wiretap | Evil | -1.00 | -0.95 | 13 |
| Diviner | Evil | -1.05 | -0.95 | 23 |
| Pharmacist | Evil | -1.10 | -0.96 | 30 |
| Talent Agent | Evil | -0.95 | -0.97 | 5 |
| Fixer | Evil | -0.95 | -1.03 | 8 |
| Ballot Stuffer | Evil | -1.20 | -1.04 | 19 |
| Ritualist | Evil | -1.00 | -1.10 | 20 |
| Oathsworn | Evil | -1.30 | -1.30 | 0 |
| Medic | Good | +0.55 | +0.79 | 64 |
| Sheriff | Good | +0.55 | +0.75 | 53 |
| Vigilante | Good | +0.45 | +0.65 | 37 |
| Mirror Maker | Good | +0.65 | +0.65 | 0 |
| Trapper | Good | +0.70 | +0.59 | 17 |
| Seer | Good | +0.40 | +0.59 | 19 |
| Lookout | Good | +0.45 | +0.55 | 48 |
| Party Animal | Good | +0.45 | +0.55 | 10 |
| Veteran | Good | +0.50 | +0.54 | 16 |
| Tracker | Good | +0.45 | +0.52 | 31 |
| Insomniac | Good | +0.35 | +0.50 | 6 |
| Oracle | Good | +0.45 | +0.50 | 25 |
| Cartographer | Good | +0.35 | +0.49 | 11 |
| Auditor | Good | +0.40 | +0.47 | 8 |
| Prosecutor | Good | +0.40 | +0.47 | 14 |
| Archivist | Good | +0.40 | +0.46 | 25 |
| Scout | Good | +0.30 | +0.46 | 16 |
| Eavesdropper | Good | +0.40 | +0.45 | 11 |
| Census Taker | Good | +0.45 | +0.45 | 10 |
| Chronicler | Good | +0.40 | +0.44 | 4 |
| Sniper | Good | +0.45 | +0.43 | 8 |
| Bloodhound | Good | +0.40 | +0.40 | 6 |
| Mayor | Good | +0.40 | +0.40 | 2 |
| Enforcer | Good | +0.45 | +0.40 | 5 |
| Coroner | Good | +0.35 | +0.39 | 4 |
| Profiler | Good | +0.45 | +0.37 | 13 |
| Kitsune | Good | +0.60 | +0.37 | 7 |
| Fortune Teller | Good | +0.35 | +0.36 | 20 |
| Vanilla Villager | Good | +0.25 | +0.23 | 80 |
| Saint | Good | +0.05 | +0.05 | 0 |
| Roleplayer | Good | +0.00 | +0.01 | 11 |
| Decoy | Neutral | +0.10 | +0.12 | 1 |
| Executioner | Neutral | -0.20 | -0.03 | 21 |
| Vulture | Neutral | -0.25 | -0.13 | 9 |
| Jester | Neutral | -0.15 | -0.14 | 31 |
| Magpie | Neutral | -0.15 | -0.20 | 3 |
| Bounty Hunter | Neutral | -0.30 | -0.29 | 7 |
| Hitman | Neutral | -0.40 | -0.40 | 2 |
| Werewolf | Neutral | -0.60 | -0.60 | 0 |
| Serial Killer | Neutral | -0.60 | -0.75 | 17 |
| Arsonist | Neutral | -0.80 | -0.93 | 19 |

A trait's power is how much it helps its holder's side (the Village for a Village holder, the Yakuza for a Yakuza; a Neutral holder's traits aren't counted). Its prior is its power in traits.py.

| Trait | Holder | Prior | Power | Games |
|---|---|---|---|---|
| Berserker | Yakuza | +0.45 | +0.45 | 0 |
| Spare Blade | Yakuza | +0.35 | +0.41 | 1 |
| Avenger | Village | +0.30 | +0.39 | 4 |
| Grudge | Yakuza | +0.30 | +0.37 | 2 |
| Armed | Village | +0.25 | +0.35 | 4 |
| Disguised | Yakuza | +0.30 | +0.27 | 4 |
| Martyr | Village | +0.15 | +0.25 | 6 |
| Stolen Blade | Village | +0.30 | +0.25 | 2 |
| Armed | Yakuza | +0.20 | +0.22 | 2 |
| Katana Master | Yakuza | +0.25 | +0.20 | 2 |
| Stocked | Village, Yakuza, Neutral | +0.15 | +0.19 | 2 |
| Kindred | Village | +0.15 | +0.17 | 3 |
| Grudge | Village, Neutral | +0.10 | +0.17 | 3 |
| Faultline | Village | +0.15 | +0.16 | 3 |
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
| Disguised | Village, Neutral | -0.10 | -0.03 | 4 |
| Oblivious | Yakuza | -0.05 | -0.05 | 0 |
| Notorious | Village | -0.10 | -0.05 | 12 |
| Remorseful | Village | -0.10 | -0.07 | 2 |
| Ashamed | Village | -0.05 | -0.07 | 1 |
| Selfish | Village, Yakuza | -0.10 | -0.08 | 4 |
| Zealot | Village, Neutral | -0.10 | -0.09 | 4 |
| Merciful | Yakuza | -0.15 | -0.10 | 3 |
| Curt | Village, Yakuza, Neutral | -0.10 | -0.10 | 5 |
| Rival | Village, Yakuza | -0.15 | -0.12 | 1 |
| Merciful | Village, Neutral | -0.10 | -0.12 | 1 |
| Oblivious | Village, Neutral | -0.10 | -0.12 | 1 |
| Paranoid | Village | -0.10 | -0.14 | 4 |
| Selfless | Village | -0.15 | -0.15 | 0 |
| Spiteful | Village | -0.15 | -0.15 | 0 |
| Zealot | Yakuza | -0.15 | -0.16 | 1 |
| Drowsy | Village, Yakuza, Neutral | -0.15 | -0.17 | 2 |
| Shaky | Yakuza | -0.30 | -0.32 | 1 |
| Usurper | Yakuza | -0.30 | -0.33 | 1 |
| Turncoat | Village | -0.40 | -0.42 | 1 |
