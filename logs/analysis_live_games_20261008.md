# Live game analysis, 2026-10-08

Main subject: `game_20261008_230823_5151` (the newest live game: 8 players, Haiku 5.5 and GPT-6 Luna
players, Opus 5.5 moderator and night judge). For comparison I also read the 7 earlier live games from
today (`_31`, `_41`, `_51`, `_61`, `_71`, `_81`, `_4242`). Read-only: no code was changed.

**Caveat first:** game 5151 writes `log_version: 1`. It ran at 23:08, right after the night-check
commit (e6f396b). Every later change (LOG_VERSION 2-5, per-model effort, free trial comments, ending the
day after a silent round) has only been through mock games, not a live one. Its setup record has no
`git_commit`, `settings` or `vote` records, so it lacks those analysis fields.

---

## 1. Game 5151 at a glance

| Seat | Player | Role | Faction | Model | Fate |
|---|---|---|---|---|---|
| 0 | Alice | Pharmacist | Yakuza | Haiku | Killed N1 by Serial Killer |
| 1 | Bob | Serial Killer | Neutral | Luna | Hanged D2 |
| 2 | Carol | Lookout | Village | Haiku | Survived (won) |
| 3 | Dave | Vanilla Villager | Village | Luna | Killed N1 by Katana |
| 4 | Erin | Sheriff | Village | Haiku | Survived (won) |
| 5 | Frank | Medic | Village | Luna | Survived (won) |
| 6 | Grace | Vigilante | Village | Haiku | Survived (won) |
| 7 | Heidi | Grunt (Katana) | Yakuza | Luna | Hanged D3 |

**Village won on Day 3.** Cost was about $0.62: players $0.35, moderator $0.15, night judge $0.13.

Story in brief:
- **Day 1:** Alice sent Heidi 6 visible PMs, and the table noticed immediately. Carol and then Alice
  were tried and both found Innocent. Alice and Heidi were the only Guilty votes on Carol, which became
  the case against them.
- **Night 1:** Alice role-blocked Frank, which cancelled his protection on Grace. Heidi's Katana killed
  Dave. Bob, the SK, happened to kill Alice. Erin checked Heidi and got Not Evil (the Katana exception).
  Carol watched Heidi and saw Erin visit.
- **Day 2:** Alice was revealed as Pharmacist, a Yakuza role, so Heidi became the obvious partner. Bob
  nominated Heidi and privately fake-claimed Sheriff to Erin, who was the real Sheriff. Erin hard-claimed
  in public and exposed Bob. Heidi was found Innocent 2-4 on the strength of Erin's Not Evil, then Bob
  was hanged.
- **Night 2:** Heidi used the Katana on Erin. Frank spent a token on Strong Defense for Erin, and Erin
  survived.
- **Day 3:** Heidi tried Carol, who claimed Lookout, matched Erin's story, and was found Innocent.
  Frank tried Heidi, and she was hanged 3-2.

---

## 2. Moderator accuracy

**Game 5151: no errors found.**
- `night_check` judged **both nights correct**, and I agree after checking each `tell` against
  `rules_1.txt`:
  - The role-block on Frank cancelled his protection (R9).
  - Heidi got Not Evil as the Katana holder (R8).
  - Alice was told the attacking role, "Serial Killer", and not the attacker's name (R3).
  - Dave was told only "Katana" (R8).
  - The Yakuza reports listed actions. Alice's report had no results; Heidi's included her own attack
    result, which is allowed because the attacker learns success (R3).
  - Frank's token went 2 to 1 through `set_tokens`.
  - Carol's N2 Lookout result ("nobody visited Frank") was correct.
- There were no `moderator_flag` records and no errors in tool results.
- **Wording nit:** Heidi's N1 report says "Alice role-blocked Frank". R8 says Yakuza learn their
  partners' actions but not the results, and "role-blocked" can read as a result. "Alice tried to
  role-block Frank" would avoid that.
- **Wording nit:** Erin's N2 notice says "attacked with a Katana tonight, but you survived". That is
  correct, but Erin's feedback said it confused her ("reads as if it refers to me").

**Earlier games:**
- **Game 4242: a dead Puppeteer still puppeted.** Carol, the Puppeteer, died on Night 1 (Jester
  revenge), but on Day 2 she still wrote Dave's public message, which defended her teammate Heidi. That
  breaks R12. **It is already fixed:** `day.py:69` now drops the puppet when the Puppeteer died
  overnight.
- **Game 71:** the moderator flagged that R8 didn't say whether a holder who dies that night still
  counts as the holder for the Sheriff check. R8 now settles it ("If that holder dies the same night,
  they still count as the holder").
- **Game 71 review, possible open bug:** the reviewer reported "no explicit game-over announcement"
  after the last Yakuza died at night. I did not re-check whether that is still true.
- **Game 71 review, logging bug:** Ivan's N2 Katana attack was logged as his Fabricator action. I did
  not check this either.

---

## 3. Player-by-player

**Alice (Yakuza Pharmacist, Haiku): poor.** Her notepad says "coordinate with Heidi in private chat at
night", and then she sent Heidi 6 PMs during Day 1 anyway. Everyone can see that a PM was sent (R4), so
by round 2 three players had flagged it. When asked what the PMs were about, she gave three different
answers ("opening coordination", "about not rushing nominations", and the dodge "Alice asked for my
take"). Her N1 role-block on Frank was a good read: Frank had just said "track Alice and Heidi".

**Heidi (Yakuza Grunt with the Katana, Luna): mixed.**
- She said in public that she was "leaning Innocent" on Carol, then voted Guilty. Her private reasoning
  was "an execution helps my faction". That one vote was the main evidence that hanged her.
- On Day 2 she was the one who explained in public that Erin's Not Evil on her "fits the Katana
  exception". That was true, but it argues for her own guilt.
- Her other plays were good: nominating Bob, and attacking the claimed Sheriff on N2.
- She misstated the facts once: "Alice's revealed Serial Killer role". Alice was a Pharmacist killed by
  the SK.
- On trial on D3 she fake-claimed Vanilla Villager. That is a reasonable lie.

**Bob (Serial Killer, Luna): bad, then lucky.**
- His N1 kill landed on Alice, a Yakuza. That helped the Village more than it helped him.
- On Day 2 he fake-claimed Sheriff in a PM to the one player who could disprove it: the real Sheriff.
  He also wrote the fake claim into his will.
- He stuck to the claim through his trial with a coherent but losing argument.

**Erin (Sheriff, Haiku): solid.**
- She stayed hidden on Day 1, checked the top suspect N1, and hard-claimed at the right moment, the
  instant a fake Sheriff appeared.
- On Day 2 she voted Innocent on Heidi because of her own Not Evil result. Her reasoning already
  admitted "she could be a Katana holder", but she didn't follow through.
- She suspected Carol of "fishing" when Carol was the town Lookout reaching out.
- She told herself "Bob claimed Sheriff privately and in public", but Bob never claimed it publicly.

**Carol (Lookout, Haiku): good.**
- She was the first to spot the Alice–Heidi PMs and kept a consistent read on Heidi from Day 1 to the
  end.
- She was the only player to apply the Katana exception correctly on Day 2.
- She confirmed Erin's claim privately before backing her in public.
- **Missed play:** on N2 she watched Frank. The claimed Sheriff, Erin, was the obvious Katana target.
  Watching Erin would have shown Heidi visiting, which proves she holds the Katana.

**Frank (Medic, Luna): good nights, erratic votes.**
- His N1 protection went to Grace after her private Vigilante claim.
- His N2 Strong Defense on the newly claimed Sheriff was the best play of the game.
- He told Grace "Heidi is my strongest suspect", nominated Heidi on D3, then voted **Innocent** on her
  (the trial was 3-2). His reason was that Erin's Not Evil was "the strongest concrete evidence", even
  though everyone had by then explained why it doesn't clear her.
- He misread a claim: "Bob's reported Not Evil result on Alice". Bob had said Evil.

**Grace (Vigilante, Haiku): too passive.**
- She never fired in two nights, even after Alice's flip made Heidi a near-certain Yakuza.
- She PM-claimed Vigilante to Frank on Day 1, which was risky but worked out.
- Her N2 thoughts call Carol "the most suspicious", which contradicts everything she said in public.
- She repeated the same misreading as Frank: "your Not Evil result" for Bob.

**Dave (Vanilla Villager, Luna): fine.** His Day 1 nomination was openly just to hear a defense, and he
said so on trial. He was killed N1, likely because the Yakuza saw him as a swing vote.

---

## 4. Patterns across all 8 live games

- **The Yakuza won 0 of 8.** The Village won 7. Game 31 was a Jester-only win, after the last players
  were killed off.
- **Most Yakuza were hanged:** 14 of 20 Yakuza deaths were hangings, mostly on Days 2-3.
- **Visible Yakuza PMs on Day 1 keep getting them caught.** In the two newest games (the only ones with
  `cat` fields to count from), the Yakuza pair sent each other 5 and 10 PMs on Day 1. Both times the
  surviving partner was hanged with that PM link as the core evidence.
- **Day 1 is slow and talks in circles.** Nearly every opening line is some version of "no reads yet,
  won't nominate, watch who pushes early votes". Day 1 trials happen on meta behavior ("asked for reads
  without giving one"), and the trial votes mostly come back Innocent. Human Day 1s usually have more
  varied reads and some bandwagon pressure.
- **Speech budgets dominate later play.**
  - In 5151, rounds 6-10 of Day 1 had only 2 public messages between 8 players, because players
    couldn't afford them. That was about 40 player calls spent on near-silence.
  - On Days 2-3 the budget refills per round, but several trials can happen inside one round. So for
    the 2nd and 3rd trials of a day most players had a budget of 0.1-1.0 and couldn't speak in public.
    In Heidi's deciding trial, Frank and Grace couldn't post at all.
  - 9 of the 9 in-game feedback notes in 5151 are about this, and so are 5 of 6 in game 81.
  - The later commits ("free trial comments", "end the day after a silent round") look aimed at this.
    Neither has been through a live game yet.
- **Players misstate facts.** These are confident misstatements of public facts, roughly 3-4 per game:
  - Bob's claimed "Evil" became "Not Evil" in both Frank's and Grace's posts.
  - Heidi said Alice was "revealed as Serial Killer".
  - Erin believed Bob claimed in public.
  - Carol said "Night 3 result before Night 3 ends" during Day 3.
  - In game 71, Carol told a Grunt to "consider roleblocking", and Dave quoted his own private PM as if
    it were public.
- **Players don't use rules to deduce.** The Katana exception was central here. Only Carol used it
  correctly on Day 2. The rest took until Day 3, and Frank never did.

---

## 5. Strengths and weaknesses compared with human play

**Strengths (as good as or better than casual human play):**
- Claim timing was sensible. Power roles stayed hidden on Day 1, the Sheriff claimed exactly when a
  counter-claim appeared, and the Lookout claimed when on trial.
- The Medic protected a freshly claimed Sheriff with a token on the night the Yakuza attacked them,
  which is textbook play.
- Players confirmed each other privately (Carol to Erin) before backing a claim in public.
- Votes mostly matched each player's stated reasoning, and nobody hanged without at least a stated
  case.
- Village players never threw votes at random. Two Innocent results on Day 1 are a defensible choice in
  an 8-player game with 3 non-Village players.

**Weaknesses (compared with competent humans):**
- **Evil players don't fake well.** They ignore how visible PMs are, say one thing in public and vote
  the opposite, and do the Village's reasoning for them in public (Heidi on the Katana exception). The
  SK fake-claimed to the one player certain to disprove it.
- **The Vigilante is passive.** Grace "held the shot for a confirmed Yakuza" for the whole game. Humans
  would fire at Heidi on N2.
- **Night targets are weak.** Carol could have caught the Katana holder by watching the claimed Sheriff.
- **Late-game votes are inconsistent.** Frank nominated his top suspect and then voted to save her in a
  3-2 trial.
- **The table speaks with one voice.** Every player uses the same phrases ("thin", "concrete", "not
  proof by itself"). Humans have recognizable personal styles and push harder for their reads. It also
  makes it hard for anyone to tell players apart by tone.
- **Private reasoning drifts from public stances.** Grace's N2 suspicion of Carol and Erin's Day 1
  suspicion of Carol never surfaced in public.

---

## 6. Things Kevin might find strange

1. **Game 5151 is LOG_VERSION 1**, and no live game has been run since LOG_VERSION went to 2-5 (see
   the top of this file).
2. **Frank nominated Heidi, then voted Innocent on her**, after telling Grace in private that she was
   his strongest suspect.
3. **Heidi, a Yakuza, explained in public why the Sheriff's Not Evil on her doesn't clear her.**
4. **Bob's fake Sheriff claim went to the real Sheriff in a PM**, and Erin exposed it in public in the
   very next message.
5. **Two players independently misquoted Bob's "Evil" as "Not Evil"**, then argued from the misquote.
6. **Multiple trials in one round starve speech budgets**, so most of the table was mute through the
   trials that decided the game.
7. **Game 4242: a dead Puppeteer kept puppeting on Day 2**, and used the puppet to defend her teammate.
   This is already fixed at `day.py:69`.
8. **The Yakuza have lost every live game so far.** This might be about model skill, the setup, or Day 1
   PM visibility. It's worth watching once there are more games.
9. **Erin's feedback said her notepad read "Night 1 plan" during Day 1.** Players write night plans into
   their notepads in advance, and that confused her.
