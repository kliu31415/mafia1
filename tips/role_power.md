# Role power

Refit 2026-10-18 08:30 UTC by `role_power.py` from 110 finished live games (Village won 68). Power is how much a role adds to the Village's win chance, in logits (+0.4 is about +10 points near even). Offset +0.05 (prior -0.30); all-frontier games add +1.03 (25 games, prior +0.00). Change the priors in role_power.py; this file is rewritten after every game.

| Role | Side | Prior | Power | Games |
|---|---|---|---|---|
| Grunt | Evil | -0.85 | -0.78 | 84 |
| Informant | Evil | -0.95 | -0.82 | 5 |
| Fabricator | Evil | -1.00 | -0.87 | 30 |
| Mortician | Evil | -0.95 | -0.92 | 16 |
| Diviner | Evil | -1.05 | -0.97 | 24 |
| Pharmacist | Evil | -1.10 | -0.99 | 31 |
| Wiretap | Evil | -1.00 | -0.99 | 14 |
| Talent Agent | Evil | -0.95 | -0.99 | 5 |
| Fixer | Evil | -0.95 | -1.01 | 9 |
| Ballot Stuffer | Evil | -1.20 | -1.07 | 22 |
| Ritualist | Evil | -1.00 | -1.10 | 23 |
| Oathsworn | Evil | -1.30 | -1.20 | 4 |
| Medic | Good | +0.55 | +0.77 | 65 |
| Mirror Maker | Good | +0.65 | +0.75 | 4 |
| Sheriff | Good | +0.55 | +0.75 | 54 |
| Vigilante | Good | +0.45 | +0.59 | 42 |
| Trapper | Good | +0.70 | +0.57 | 20 |
| Lookout | Good | +0.45 | +0.57 | 50 |
| Tracker | Good | +0.45 | +0.56 | 32 |
| Veteran | Good | +0.50 | +0.55 | 18 |
| Seer | Good | +0.40 | +0.55 | 20 |
| Party Animal | Good | +0.45 | +0.54 | 11 |
| Cartographer | Good | +0.35 | +0.51 | 12 |
| Insomniac | Good | +0.35 | +0.51 | 8 |
| Prosecutor | Good | +0.40 | +0.50 | 15 |
| Oracle | Good | +0.45 | +0.49 | 27 |
| Eavesdropper | Good | +0.40 | +0.46 | 11 |
| Scout | Good | +0.30 | +0.45 | 18 |
| Enforcer | Good | +0.45 | +0.45 | 8 |
| Auditor | Good | +0.40 | +0.44 | 9 |
| Sniper | Good | +0.45 | +0.42 | 8 |
| Coroner | Good | +0.35 | +0.42 | 5 |
| Bloodhound | Good | +0.40 | +0.41 | 8 |
| Chronicler | Good | +0.40 | +0.41 | 5 |
| Archivist | Good | +0.40 | +0.40 | 26 |
| Mayor | Good | +0.40 | +0.39 | 3 |
| Magistrate | Good | +0.45 | +0.39 | 1 |
| Fortune Teller | Good | +0.35 | +0.37 | 21 |
| Profiler | Good | +0.45 | +0.37 | 15 |
| Census Taker | Good | +0.45 | +0.37 | 12 |
| Kitsune | Good | +0.60 | +0.36 | 11 |
| Vanilla Villager | Good | +0.25 | +0.22 | 81 |
| Saint | Good | +0.05 | +0.04 | 2 |
| Roleplayer | Good | +0.00 | +0.01 | 12 |
| Decoy | Neutral | +0.10 | +0.12 | 3 |
| Executioner | Neutral | -0.20 | -0.05 | 21 |
| Vulture | Neutral | -0.25 | -0.16 | 10 |
| Jester | Neutral | -0.15 | -0.17 | 33 |
| Magpie | Neutral | -0.15 | -0.19 | 4 |
| Bounty Hunter | Neutral | -0.30 | -0.31 | 10 |
| Hitman | Neutral | -0.40 | -0.37 | 4 |
| Werewolf | Neutral | -0.60 | -0.56 | 2 |
| Serial Killer | Neutral | -0.60 | -0.77 | 18 |
| Arsonist | Neutral | -0.80 | -0.94 | 20 |

A trait's power is how much it helps its holder's side (the Village for a Village holder, the Yakuza for a Yakuza; a Neutral holder's traits aren't counted). Its prior is its power in traits.py.

| Trait | Holder | Prior | Power | Games |
|---|---|---|---|---|
| Berserker | Yakuza | +0.45 | +0.45 | 0 |
| Spare Blade | Yakuza | +0.35 | +0.39 | 2 |
| Grudge | Yakuza | +0.30 | +0.38 | 4 |
| Armed | Village | +0.25 | +0.37 | 4 |
| Avenger | Village | +0.30 | +0.34 | 5 |
| Disguised | Yakuza | +0.30 | +0.28 | 5 |
| Stolen Blade | Village | +0.30 | +0.26 | 3 |
| Martyr | Village | +0.15 | +0.22 | 8 |
| Armed | Yakuza | +0.20 | +0.22 | 2 |
| Kindred | Village | +0.15 | +0.20 | 5 |
| Grudge | Village, Neutral | +0.10 | +0.20 | 5 |
| Stocked | Village, Yakuza, Neutral | +0.15 | +0.18 | 3 |
| Katana Master | Yakuza | +0.25 | +0.18 | 3 |
| Confidant | Village, Yakuza, Neutral | +0.10 | +0.16 | 10 |
| Faultline | Village | +0.15 | +0.15 | 5 |
| Narrow Escape | Village, Neutral | +0.15 | +0.11 | 1 |
| Narrow Escape | Yakuza | +0.10 | +0.10 | 3 |
| Selfless | Yakuza | +0.10 | +0.10 | 0 |
| Loud | Village, Yakuza, Neutral | +0.10 | +0.09 | 5 |
| Bonded | Village, Yakuza | +0.00 | +0.07 | 5 |
| Katana Expert | Yakuza | +0.10 | +0.07 | 1 |
| Cursed | Village | -0.10 | +0.01 | 20 |
| Sleepwalker | Yakuza | +0.05 | +0.00 | 4 |
| Sleepwalker | Village, Neutral | -0.05 | +0.00 | 11 |
| Disguised | Village, Neutral | -0.10 | -0.01 | 5 |
| Selfish | Village, Yakuza | -0.10 | -0.02 | 5 |
| Oblivious | Yakuza | -0.05 | -0.05 | 0 |
| Rival | Village, Yakuza | -0.15 | -0.06 | 3 |
| Zealot | Village, Neutral | -0.10 | -0.06 | 7 |
| Merciful | Village, Neutral | -0.10 | -0.08 | 3 |
| Ashamed | Village | -0.05 | -0.09 | 4 |
| Curt | Village, Yakuza, Neutral | -0.10 | -0.10 | 8 |
| Remorseful | Village | -0.10 | -0.10 | 3 |
| Notorious | Village | -0.10 | -0.11 | 14 |
| Merciful | Yakuza | -0.15 | -0.13 | 5 |
| Oblivious | Village, Neutral | -0.10 | -0.13 | 2 |
| Spiteful | Village | -0.15 | -0.15 | 2 |
| Selfless | Village | -0.15 | -0.15 | 0 |
| Zealot | Yakuza | -0.15 | -0.17 | 1 |
| Drowsy | Village, Yakuza, Neutral | -0.15 | -0.18 | 4 |
| Paranoid | Village | -0.10 | -0.19 | 7 |
| Shaky | Yakuza | -0.30 | -0.35 | 2 |
| Usurper | Yakuza | -0.30 | -0.37 | 3 |
| Turncoat | Village | -0.40 | -0.45 | 1 |
