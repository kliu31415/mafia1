# Rules ambiguities from the 12-player game, with recommendations

Each item has the problem, my recommendation, and suggested wording. The wording is new paragraphs (R16 onward) or a sentence added to an existing paragraph. I haven't edited `rules_1.txt`.

## 1. R13 now contradicts the code (fix this first)

R13 says wills are updated "once at the beginning of each day". Today's change lets players replace their will on any of their day turns.
**Recommendation:** update R13 to match the code.
> R13: Players are allowed to create and update last wills at the beginning of each day and during any of their turns in the day. (People who died the previous night can't.) When a player dies, their last will is immediately publicly shared.

## 2. The day ending on a silent round isn't in the rules

R4 only ends the day on an execution or three Innocent verdicts. The program also ends it when a full round passes with no public message or nomination. Since today's change, players who got a private message that round get one last turn first. There's also a cap of 10 rounds. Mallory, Niaj and Carol all ran into this.
**Recommendation:** make it a rule, so players can plan around it.
> R16 (Day length): Chat goes around the circle in turns. The day also ends when a full round passes in which nobody sends a public message or nominates, except that anyone sent a private message during that round first gets one last turn. The day ends after at most 10 rounds.

## 3. Whether a Lookout sees their own visit

R6 covers visiting yourself, but not whether the watcher's own visit to the target shows up. Mallory's "nobody visited Carol" result clashed with Dave's track, which showed Mallory visiting Carol, and nobody could resolve it.
**Recommendation:** the Lookout never sees themselves. This is the common convention and stops a Lookout from wrongly contradicting a Tracker.
> Add to Lookout: "Your own visit to the watched player is not included in your results."

## 4. Whether a Medic learns their protection worked, and what attacked players are told

Most of Day 3 was an argument about whether Grace "saw" an attack get stopped. The rules don't say, and neither the moderator nor the players could settle it.
**Recommendation:** protectors get no feedback, and a player who survives an attack is told they were attacked but not who protected them. That matches what the moderator did. It also keeps Medic claims unconfirmable, which helps the Yakuza a little; they're 0 for 9.
> R17 (Protection feedback): Players who protect others are never told whether the protection stopped an attack. A player who survives an attack is told they were attacked (and, for the Katana, only that it was the Katana), but not whether or by whom they were protected.

## 5. Who the Executioner's or Jester's revenge can hit

The rule says "a random player who voted Guilty". Erin, the Executioner, voted Guilty herself and left the game straight away, and some Guilty voters could be dead by that night. The moderator limited the pool to living players.
**Recommendation:** living Guilty voters only, excluding the Executioner or Jester themself.
> Add to Jester and Executioner: "The random player is chosen among Guilty voters who are still alive when the attack happens, never the Jester or Executioner themself."

## 6. What a frame does to roles that don't check alignment

The Fabricator rule says a framed player appears Evil "to all investigative roles", but only the Sheriff reports alignment. The moderator treated a frame as having no effect on Tracker, Lookout and Oracle results.
**Recommendation:** say that a frame only changes alignment results. Also confirm that frame and forge can target different players on the same night; the harness already allows it.
> Change the Fabricator's text to: "They appear Evil to any role that learns alignments (e.g. the Sheriff) that night; it has no other effect on results. Framing and forging may target different players."

## 7. Katana vote with two Yakuza (a balance choice)

With two Yakuza, one vote out of two isn't a majority, so one teammate who doesn't vote cancels the kill. The rules are right, and the harness already shows the votes and holds a revote. Several players were still caught out.
**Recommendation:** spell it out. Optionally, let the current holder's vote break a tie. That would help the Yakuza, who keep losing.
> Add to R8: "With two Yakuza, both must agree. (Optional: if the vote is tied, the current Katana holder's vote decides.)"

## No rule change needed

- **Medic Standard protection with a token** (Grace): the rule is clear; this was player confusion. Checking night actions for contradictions like this is on the later list.
- **Whether the Executioner leaving counts for the stall rule** (Grace): R14 already says it doesn't.
- **Win timing when the Executioner leaves** (Heidi): R1's win check already covers it.
