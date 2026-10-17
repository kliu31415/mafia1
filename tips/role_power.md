# Role power

Refit 2026-10-17 01:21 UTC by `role_power.py` from 106 finished live games (Village won 67). Power is how much a role adds to the Village's win chance, in logits (+0.4 is about +10 points near even). Offset +0.19 (prior -0.30). Change the priors in role_power.py; this file is rewritten after every game.

| Role | Side | Prior | Power | Games |
|---|---|---|---|---|
| Grunt | Evil | -0.85 | -0.82 | 83 |
| Mortician | Evil | -0.95 | -0.83 | 15 |
| Informant | Evil | -0.95 | -0.83 | 3 |
| Fabricator | Evil | -1.00 | -0.84 | 29 |
| Diviner | Evil | -1.05 | -0.95 | 24 |
| Wiretap | Evil | -1.00 | -0.95 | 13 |
| Pharmacist | Evil | -1.10 | -0.96 | 30 |
| Talent Agent | Evil | -0.95 | -0.97 | 5 |
| Ballot Stuffer | Evil | -1.20 | -1.00 | 21 |
| Fixer | Evil | -0.95 | -1.02 | 9 |
| Ritualist | Evil | -1.00 | -1.09 | 21 |
| Oathsworn | Evil | -1.30 | -1.22 | 3 |
| Medic | Good | +0.55 | +0.74 | 64 |
| Mirror Maker | Good | +0.65 | +0.73 | 3 |
| Sheriff | Good | +0.55 | +0.73 | 53 |
| Vigilante | Good | +0.45 | +0.68 | 39 |
| Trapper | Good | +0.70 | +0.63 | 19 |
| Seer | Good | +0.40 | +0.57 | 19 |
| Veteran | Good | +0.50 | +0.57 | 18 |
| Lookout | Good | +0.45 | +0.56 | 50 |
| Party Animal | Good | +0.45 | +0.55 | 10 |
| Tracker | Good | +0.45 | +0.53 | 32 |
| Cartographer | Good | +0.35 | +0.53 | 12 |
| Insomniac | Good | +0.35 | +0.52 | 8 |
| Scout | Good | +0.30 | +0.50 | 17 |
| Auditor | Good | +0.40 | +0.49 | 9 |
| Prosecutor | Good | +0.40 | +0.49 | 15 |
| Enforcer | Good | +0.45 | +0.47 | 7 |
| Oracle | Good | +0.45 | +0.46 | 25 |
| Archivist | Good | +0.40 | +0.45 | 25 |
| Census Taker | Good | +0.45 | +0.45 | 11 |
| Chronicler | Good | +0.40 | +0.45 | 4 |
| Eavesdropper | Good | +0.40 | +0.44 | 11 |
| Bloodhound | Good | +0.40 | +0.44 | 8 |
| Kitsune | Good | +0.60 | +0.44 | 10 |
| Sniper | Good | +0.45 | +0.43 | 8 |
| Coroner | Good | +0.35 | +0.41 | 5 |
| Mayor | Good | +0.40 | +0.40 | 3 |
| Fortune Teller | Good | +0.35 | +0.39 | 21 |
| Profiler | Good | +0.45 | +0.35 | 14 |
| Vanilla Villager | Good | +0.25 | +0.20 | 80 |
| Saint | Good | +0.05 | +0.08 | 1 |
| Roleplayer | Good | +0.00 | +0.03 | 12 |
| Decoy | Neutral | +0.10 | +0.12 | 1 |
| Executioner | Neutral | -0.20 | -0.04 | 21 |
| Vulture | Neutral | -0.25 | -0.13 | 9 |
| Jester | Neutral | -0.15 | -0.13 | 32 |
| Magpie | Neutral | -0.15 | -0.16 | 4 |
| Bounty Hunter | Neutral | -0.30 | -0.26 | 8 |
| Hitman | Neutral | -0.40 | -0.39 | 3 |
| Werewolf | Neutral | -0.60 | -0.55 | 2 |
| Serial Killer | Neutral | -0.60 | -0.77 | 17 |
| Arsonist | Neutral | -0.80 | -0.93 | 20 |

A trait's power is how much it helps its holder's side (the Village for a Village holder, the Yakuza for a Yakuza; a Neutral holder's traits aren't counted). Its prior is its power in traits.py.

| Trait | Holder | Prior | Power | Games |
|---|---|---|---|---|
| Berserker | Yakuza | +0.45 | +0.45 | 0 |
| Avenger | Village | +0.30 | +0.39 | 4 |
| Spare Blade | Yakuza | +0.35 | +0.39 | 2 |
| Grudge | Yakuza | +0.30 | +0.38 | 2 |
| Armed | Village | +0.25 | +0.36 | 4 |
| Stolen Blade | Village | +0.30 | +0.26 | 3 |
| Martyr | Village | +0.15 | +0.26 | 7 |
| Disguised | Yakuza | +0.30 | +0.25 | 5 |
| Armed | Yakuza | +0.20 | +0.22 | 2 |
| Kindred | Village | +0.15 | +0.22 | 5 |
| Katana Master | Yakuza | +0.25 | +0.20 | 2 |
| Stocked | Village, Yakuza, Neutral | +0.15 | +0.20 | 3 |
| Grudge | Village, Neutral | +0.10 | +0.19 | 4 |
| Faultline | Village | +0.15 | +0.18 | 4 |
| Confidant | Village, Yakuza, Neutral | +0.10 | +0.14 | 7 |
| Loud | Village, Yakuza, Neutral | +0.10 | +0.12 | 4 |
| Narrow Escape | Village, Neutral | +0.15 | +0.11 | 1 |
| Selfless | Yakuza | +0.10 | +0.10 | 0 |
| Narrow Escape | Yakuza | +0.10 | +0.10 | 3 |
| Bonded | Village, Yakuza | +0.00 | +0.09 | 3 |
| Katana Expert | Yakuza | +0.10 | +0.07 | 1 |
| Cursed | Village | -0.10 | +0.05 | 18 |
| Sleepwalker | Village, Neutral | -0.05 | +0.03 | 11 |
| Disguised | Village, Neutral | -0.10 | +0.02 | 5 |
| Sleepwalker | Yakuza | +0.05 | +0.00 | 2 |
| Zealot | Village, Neutral | -0.10 | -0.00 | 6 |
| Ashamed | Village | -0.05 | -0.04 | 3 |
| Notorious | Village | -0.10 | -0.04 | 13 |
| Oblivious | Yakuza | -0.05 | -0.05 | 0 |
| Selfish | Village, Yakuza | -0.10 | -0.06 | 4 |
| Remorseful | Village | -0.10 | -0.08 | 3 |
| Merciful | Village, Neutral | -0.10 | -0.08 | 2 |
| Curt | Village, Yakuza, Neutral | -0.10 | -0.09 | 6 |
| Rival | Village, Yakuza | -0.15 | -0.10 | 1 |
| Paranoid | Village | -0.10 | -0.11 | 5 |
| Merciful | Yakuza | -0.15 | -0.12 | 4 |
| Oblivious | Village, Neutral | -0.10 | -0.12 | 2 |
| Selfless | Village | -0.15 | -0.15 | 0 |
| Spiteful | Village | -0.15 | -0.15 | 0 |
| Zealot | Yakuza | -0.15 | -0.17 | 1 |
| Drowsy | Village, Yakuza, Neutral | -0.15 | -0.18 | 3 |
| Shaky | Yakuza | -0.30 | -0.32 | 1 |
| Usurper | Yakuza | -0.30 | -0.35 | 2 |
| Turncoat | Village | -0.40 | -0.44 | 1 |
