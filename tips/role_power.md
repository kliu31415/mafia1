# Role power

Refit 2026-10-16 07:14 UTC by `role_power.py` from 103 finished live games (Village won 64). Power is how much a role adds to the Village's win chance, in logits (+0.4 is about +10 points near even). Offset +0.11 (prior -0.30). Change the priors in role_power.py; this file is rewritten after every game.

| Role | Side | Prior | Power | Games |
|---|---|---|---|---|
| Grunt | Evil | -0.85 | -0.79 | 83 |
| Informant | Evil | -0.95 | -0.83 | 3 |
| Fabricator | Evil | -1.00 | -0.85 | 27 |
| Mortician | Evil | -0.95 | -0.85 | 14 |
| Wiretap | Evil | -1.00 | -0.95 | 13 |
| Pharmacist | Evil | -1.10 | -0.96 | 30 |
| Diviner | Evil | -1.05 | -0.96 | 23 |
| Talent Agent | Evil | -0.95 | -0.98 | 5 |
| Ballot Stuffer | Evil | -1.20 | -1.01 | 20 |
| Fixer | Evil | -0.95 | -1.04 | 8 |
| Ritualist | Evil | -1.00 | -1.11 | 20 |
| Oathsworn | Evil | -1.30 | -1.27 | 1 |
| Medic | Good | +0.55 | +0.78 | 64 |
| Sheriff | Good | +0.55 | +0.74 | 53 |
| Mirror Maker | Good | +0.65 | +0.68 | 1 |
| Vigilante | Good | +0.45 | +0.64 | 37 |
| Trapper | Good | +0.70 | +0.62 | 18 |
| Seer | Good | +0.40 | +0.58 | 19 |
| Lookout | Good | +0.45 | +0.58 | 49 |
| Party Animal | Good | +0.45 | +0.55 | 10 |
| Tracker | Good | +0.45 | +0.54 | 32 |
| Veteran | Good | +0.50 | +0.53 | 16 |
| Insomniac | Good | +0.35 | +0.50 | 6 |
| Cartographer | Good | +0.35 | +0.50 | 11 |
| Oracle | Good | +0.45 | +0.49 | 25 |
| Auditor | Good | +0.40 | +0.49 | 9 |
| Prosecutor | Good | +0.40 | +0.47 | 14 |
| Archivist | Good | +0.40 | +0.46 | 25 |
| Scout | Good | +0.30 | +0.45 | 16 |
| Enforcer | Good | +0.45 | +0.45 | 6 |
| Eavesdropper | Good | +0.40 | +0.45 | 11 |
| Census Taker | Good | +0.45 | +0.45 | 10 |
| Chronicler | Good | +0.40 | +0.44 | 4 |
| Sniper | Good | +0.45 | +0.43 | 8 |
| Bloodhound | Good | +0.40 | +0.40 | 6 |
| Mayor | Good | +0.40 | +0.40 | 2 |
| Coroner | Good | +0.35 | +0.39 | 4 |
| Fortune Teller | Good | +0.35 | +0.36 | 20 |
| Kitsune | Good | +0.60 | +0.36 | 7 |
| Profiler | Good | +0.45 | +0.36 | 13 |
| Vanilla Villager | Good | +0.25 | +0.22 | 80 |
| Saint | Good | +0.05 | +0.08 | 1 |
| Roleplayer | Good | +0.00 | +0.04 | 12 |
| Decoy | Neutral | +0.10 | +0.12 | 1 |
| Executioner | Neutral | -0.20 | -0.04 | 21 |
| Vulture | Neutral | -0.25 | -0.13 | 9 |
| Jester | Neutral | -0.15 | -0.15 | 31 |
| Magpie | Neutral | -0.15 | -0.20 | 3 |
| Bounty Hunter | Neutral | -0.30 | -0.26 | 8 |
| Hitman | Neutral | -0.40 | -0.40 | 2 |
| Werewolf | Neutral | -0.60 | -0.60 | 0 |
| Serial Killer | Neutral | -0.60 | -0.75 | 17 |
| Arsonist | Neutral | -0.80 | -0.91 | 20 |

A trait's power is how much it helps its holder's side (the Village for a Village holder, the Yakuza for a Yakuza; a Neutral holder's traits aren't counted). Its prior is its power in traits.py.

| Trait | Holder | Prior | Power | Games |
|---|---|---|---|---|
| Berserker | Yakuza | +0.45 | +0.45 | 0 |
| Spare Blade | Yakuza | +0.35 | +0.41 | 1 |
| Avenger | Village | +0.30 | +0.38 | 4 |
| Grudge | Yakuza | +0.30 | +0.37 | 2 |
| Armed | Village | +0.25 | +0.35 | 4 |
| Disguised | Yakuza | +0.30 | +0.27 | 4 |
| Martyr | Village | +0.15 | +0.25 | 6 |
| Stolen Blade | Village | +0.30 | +0.25 | 2 |
| Armed | Yakuza | +0.20 | +0.22 | 2 |
| Katana Master | Yakuza | +0.25 | +0.20 | 2 |
| Stocked | Village, Yakuza, Neutral | +0.15 | +0.19 | 2 |
| Kindred | Village | +0.15 | +0.17 | 3 |
| Grudge | Village, Neutral | +0.10 | +0.16 | 3 |
| Faultline | Village | +0.15 | +0.15 | 3 |
| Narrow Escape | Yakuza | +0.10 | +0.12 | 2 |
| Confidant | Village, Yakuza, Neutral | +0.10 | +0.11 | 5 |
| Narrow Escape | Village, Neutral | +0.15 | +0.11 | 1 |
| Loud | Village, Yakuza, Neutral | +0.10 | +0.11 | 4 |
| Selfless | Yakuza | +0.10 | +0.10 | 0 |
| Katana Expert | Yakuza | +0.10 | +0.07 | 1 |
| Bonded | Village, Yakuza | +0.00 | +0.03 | 2 |
| Cursed | Village | -0.10 | +0.02 | 17 |
| Sleepwalker | Village, Neutral | -0.05 | +0.02 | 11 |
| Sleepwalker | Yakuza | +0.05 | +0.01 | 2 |
| Disguised | Village, Neutral | -0.10 | -0.04 | 4 |
| Ashamed | Village | -0.05 | -0.04 | 2 |
| Remorseful | Village | -0.10 | -0.04 | 3 |
| Oblivious | Yakuza | -0.05 | -0.05 | 0 |
| Notorious | Village | -0.10 | -0.06 | 12 |
| Merciful | Village, Neutral | -0.10 | -0.06 | 2 |
| Selfish | Village, Yakuza | -0.10 | -0.08 | 4 |
| Zealot | Village, Neutral | -0.10 | -0.09 | 4 |
| Merciful | Yakuza | -0.15 | -0.09 | 3 |
| Rival | Village, Yakuza | -0.15 | -0.12 | 1 |
| Oblivious | Village, Neutral | -0.10 | -0.12 | 1 |
| Curt | Village, Yakuza, Neutral | -0.10 | -0.13 | 6 |
| Paranoid | Village | -0.10 | -0.14 | 4 |
| Selfless | Village | -0.15 | -0.15 | 0 |
| Spiteful | Village | -0.15 | -0.15 | 0 |
| Zealot | Yakuza | -0.15 | -0.16 | 1 |
| Drowsy | Village, Yakuza, Neutral | -0.15 | -0.17 | 2 |
| Shaky | Yakuza | -0.30 | -0.32 | 1 |
| Usurper | Yakuza | -0.30 | -0.32 | 1 |
| Turncoat | Village | -0.40 | -0.42 | 1 |
