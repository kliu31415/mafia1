"""The day phase: speaking budget, chat turns, nominations and simultaneous votes."""

import json

from players import (LAST_WILL_SCHEMA, STR, VOTE_SCHEMA, Players, day_turn_schema, name_enum, nullable, obj,
                     truncate_words, word_count)
from state import CHAT, DEATH, NOMINATION, PHASE, PM, VOTE, Game, Player, majority


# Speaking budget. A message costs round_multiplier * (MESSAGE_BASE_COST + length_cost(words)),
# times PRIVATE_COST_FACTOR if private. Players earn BUDGET_PER_ROUND each round, carrying over up
# to BUDGET_MAX; the budget resets to 0 each day.
BUDGET_PER_ROUND = 3.0
BUDGET_MAX = 8.0
MESSAGE_BASE_COST = 1.0
PRIVATE_COST_FACTOR = 0.25
MAX_MESSAGE_WORDS = 800
FULL_PRICE_ROUNDS = 3  # rounds at 1x; each later round costs ROUND_COST_GROWTH times the previous
ROUND_COST_GROWTH = 2.0
MAX_DAY_ROUNDS = 10  # the day also ends after a full go-around in which nobody sends a message
FREE_DEFENSE_WORDS = 150  # the accused's first message on trial is free up to this length
MIN_TRUNCATED_WORDS = 3  # a message truncated below this is dropped instead
MAX_TRIALS_PER_DAY = 3
NOMINATION_COST = 1.0  # times the round multiplier, paid from the speaking budget; deters spam


LAST_WILL_WORDS = 300  # longer wills are truncated


def length_cost(words: int) -> float:
    """Cheap for short and medium messages, superlinear for long ones."""
    return words / 60 + (words / 200) ** 2


def round_multiplier(rnd: int) -> float:
    """rnd is 1-based."""
    return ROUND_COST_GROWTH ** max(0, rnd - FULL_PRICE_ROUNDS)


def message_cost(words: int, rnd: int, private: bool, free_words: int = 0) -> float:
    if words == 0:
        return 0.0
    cost = MESSAGE_BASE_COST + length_cost(words)
    if free_words:
        cost = 0.0 if words <= free_words else length_cost(words) - length_cost(free_words)
    return cost * round_multiplier(rnd) * (PRIVATE_COST_FACTOR if private else 1.0)


def price_table(rnd: int) -> str:
    rows = [f"  {w:>3} words: public {message_cost(w, rnd, False):.2f}, private {message_cost(w, rnd, True):.2f}"
            for w in (10, 25, 50, 100, 200, 400, MAX_MESSAGE_WORDS)]
    nxt = round_multiplier(rnd + 1)
    return (f"Message prices this round (round {rnd}, {round_multiplier(rnd):.2f}x; next round "
            f"{nxt:.2f}x):\n" + "\n".join(rows))


def run_day(game: Game, players: Players) -> None:
    game.phase = "day"
    game.emit(f"Day {game.day} begins.", cat=PHASE)
    game.announce_dawn()
    game.resolve_cardinal()
    if game.check_winner() is not None:
        return
    game.puppets, game.puppets_next = game.puppets_next, {}
    for puppet in list(game.puppets):
        if game.player(puppet).alive:
            game.emit("You are being puppeted today: you can't chat or see private messages, but you can "
                      "still nominate and vote.", [puppet])
        else:
            del game.puppets[puppet]

    # Last wills, written once at the beginning of each day (including day 1).
    task = (f"Write or update your last will (max {LAST_WILL_WORDS} words). If you die, it is revealed "
            "to ALL players, including other factions.")
    outs = players.ask_many([(p, task, LAST_WILL_SCHEMA, {"last_will": p.last_will}) for p in game.alive()])
    for p, out in zip(game.alive(), outs):
        will = out["last_will"]
        p.last_will = truncate_words(will, LAST_WILL_WORDS) if word_count(will) > LAST_WILL_WORDS else will

    for p in game.alive():
        p.speaking_budget = 0.0
    trials = 0
    # Prosecutions happen when nominations would start, before any chat. Round 1's budget is paid
    # out first so others can speak at the trial.
    prosecuted = [n for n in game.prosecutions if game.player(n).alive]
    game.prosecutions.clear()
    if prosecuted:
        for p in game.alive():
            p.speaking_budget = BUDGET_PER_ROUND
    for name in prosecuted:
        if trials >= MAX_TRIALS_PER_DAY or not game.player(name).alive:
            break
        nominator = game.rng.choice(game.alive())  # the rules pick a random "nominator"
        game.emit(f"{name} is being prosecuted and goes straight to trial.", cat=NOMINATION)
        game.vote_record.append(f"Day {game.day}: {name} was prosecuted (straight to trial)")
        if run_trial(game, players, nominator, name, rnd=1) == "executed":
            return
        trials += 1
    if trials >= MAX_TRIALS_PER_DAY:
        game.emit("Three trials ended in Innocent verdicts. The day ends.")
        return
    for rnd in range(1, MAX_DAY_ROUNDS + 1):
        for p in game.alive():
            if not (rnd == 1 and prosecuted):
                p.speaking_budget = min(BUDGET_MAX, p.speaking_budget + BUDGET_PER_ROUND)
        order = game.alive()
        game.rng.shuffle(order)
        active = False  # did anyone send a message or nominate this go-around?
        for p in order:
            if not p.alive:
                continue
            sent, nominee = chat_turn(game, players, p, rnd, can_nominate=trials < MAX_TRIALS_PER_DAY)
            active |= sent > 0 or nominee is not None
            if nominee:
                outcome = run_nomination(game, players, nominator=p, nominee=nominee, rnd=rnd)
                if outcome == "executed":
                    return  # an execution ends the day
                trials += outcome == "innocent"  # failed nominations don't count toward the limit
                if trials >= MAX_TRIALS_PER_DAY:
                    game.emit("Three trials ended in Innocent verdicts. The day ends.")
                    return
        if not active:
            game.emit("A full round passed with no messages. The day ends.")
            return
    game.emit("Discussion time is over. The day ends.")


def planned_messages(out: dict) -> list[tuple[str | None, str]]:
    """(recipient or None for public, text), public message first."""
    msgs: list[tuple[str | None, str]] = []
    if out.get("public_message"):
        msgs.append((None, out["public_message"]))
    msgs += [(pm["to"], pm["text"]) for pm in out.get("private_messages", []) if pm.get("text")]
    return msgs


def chat_turn(game: Game, players: Players, p: Player, rnd: int, can_nominate: bool,
              extra: str = "", free_defense: bool = False) -> tuple[int, str | None]:
    """One speaking turn. Returns (messages sent, nominee or None).

    If the planned messages cost more than the player's budget, they're warned and asked once to
    revise; anything still over budget is then truncated (later messages first) or dropped."""
    free_words = FREE_DEFENSE_WORDS if free_defense else 0

    def cost_of(i: int, to: str | None, words: int) -> float:
        return message_cost(words, rnd, private=to is not None, free_words=free_words if i == 0 and to is None else 0)

    nomination_fee = NOMINATION_COST * round_multiplier(rnd)

    def total_cost(out: dict) -> float:
        fee = nomination_fee if can_nominate and out.get("nominate") else 0.0
        return fee + sum(cost_of(i, to, min(word_count(t), MAX_MESSAGE_WORDS))
                         for i, (to, t) in enumerate(planned_messages(out)))

    task = (f"It is Day {game.day}, round {rnd} of at most {MAX_DAY_ROUNDS}. It's your turn. Your speaking "
            f"budget is {p.speaking_budget:.2f}; you earn {BUDGET_PER_ROUND:g} per round, carrying over "
            f"up to {BUDGET_MAX:g}, and it resets each day. You may send one public message and any "
            f"number of private messages (everyone sees who you messaged, but only the recipient sees "
            f"the contents), or nothing. Messages are "
            f"capped at {MAX_MESSAGE_WORDS} words. Prices grow each round after round {FULL_PRICE_ROUNDS}, "
            "so late messages are only worth it if important. The day ends after a full round where "
            "nobody sends a message.\n" + price_table(rnd) + "\n"
            + (f"Your first public message now is free up to {FREE_DEFENSE_WORDS} words; beyond that you "
               "pay only for the extra length.\n" if free_defense else "")
            + (f"You may nominate a player for trial, which stops chat for a vote. Nominating costs "
               f"{nomination_fee:.2f} from your budget this round and is paid before your messages.\n"
               if can_nominate else "")
            + extra)
    fallback = {"thoughts": "", "public_message": None, "private_messages": [], "nominate": None}
    writer = game.player(game.chat_controller(p.name))
    if writer is p:
        schema = day_turn_schema(game, p.name, can_nominate)
        out = players.ask(p, task, schema, fallback)
    else:
        # Puppeted: the Puppeteer writes p's messages (on p's budget); p still decides any nomination.
        task = (f"You are puppeting {p.name} today. This is {p.name}'s turn: the messages you write are "
                f"sent as {p.name}, and the budget below is {p.name}'s.\n" + task)
        schema = day_turn_schema(game, p.name, can_nominate=False)
        out = players.ask(writer, task, schema, fallback)
        if can_nominate:
            nominate_task = (f"It is Day {game.day}, round {rnd}, and your turn. You are puppeted, so you "
                             "can't chat, but you may nominate a player for trial (or null). Nominating costs "
                             f"{nomination_fee:.2f} from your budget ({p.speaking_budget:.2f}).")
            nominate_schema = obj(thoughts=STR, nominate=nullable(name_enum(game.alive_names())))
            out["nominate"] = players.ask(p, nominate_task, nominate_schema, {"nominate": None})["nominate"]
    planned = total_cost(out)
    if planned > p.speaking_budget + 1e-9:
        nominating = f" plus a nomination of {out['nominate']}" if can_nominate and out.get("nominate") else ""
        warning = (f"\n\nWARNING: your planned messages {json.dumps(planned_messages(out))}{nominating} "
                   f"cost {planned:.2f}, but your budget is {p.speaking_budget:.2f}. Revise them to fit. "
                   "If you still can't afford a nomination it won't happen, and messages over budget will "
                   "be truncated, starting with your last message.")
        game.log.write("budget_warning", player=p.name, planned=planned, budget=p.speaking_budget)
        nominee = out.get("nominate")
        out = players.ask(writer, task + warning, schema, fallback)
        if writer is not p:
            out["nominate"] = nominee

    nominee = out.get("nominate") if can_nominate else None
    if nominee:
        if nomination_fee <= p.speaking_budget + 1e-9:
            p.speaking_budget -= nomination_fee
        else:
            game.log.write("nomination_dropped", player=p.name, nominee=nominee, budget=p.speaking_budget)
            game.emit(f"You couldn't afford to nominate {nominee}.", [p.name])
            nominee = None
    sent = 0
    for i, (to, text) in enumerate(planned_messages(out)):
        if to is not None and to not in game.alive_names():
            continue
        words = min(word_count(text), MAX_MESSAGE_WORDS)
        while words > 0 and cost_of(i, to, words) > p.speaking_budget + 1e-9:
            words -= 1
        if words == 0 or (words < word_count(text) and words < MIN_TRUNCATED_WORDS):
            game.log.write("message_dropped", player=p.name, to=to, words=word_count(text))
            continue
        if words < word_count(text):
            text = truncate_words(text, words)
        p.speaking_budget -= cost_of(i, to, words)
        sent += 1
        if to is None:
            game.emit(f"{p.name} (public): {text}", cat=CHAT, speaker=p.name, message=text)
        else:
            # A puppeted player's private chat is read and written by their Puppeteer instead.
            game.emit(f"{p.name} -> {to} (private): {text}", [writer.name, game.chat_controller(to)],
                      cat=PM, speaker=p.name, to=to, message=text)
            # Everyone else sees that the message happened, but not its contents.
            game.emit(f"{p.name} sent {to} a private message.",
                      [q.name for q in game.players if q.name not in (p.name, to)], kind="notice")
    return sent, nominee


def run_nomination(game: Game, players: Players, nominator: Player, nominee: str, rnd: int) -> str:
    """Nomination vote, then trial and verdict. Returns "failed", "innocent" or "executed".
    Both votes are simultaneous: every voter decides without seeing the others, then all votes
    are revealed together."""
    game.emit(f"{nominator.name} nominated {nominee}. Everyone now votes Yes/No simultaneously.", cat=NOMINATION)
    others = [v for v in game.clockwise_from(nominator.name) if v is not nominator]
    task = (f"{nominator.name} nominated {nominee}. Vote true (Yes) to put them on trial, false (No) "
            "otherwise. Voting is simultaneous: you can't see anyone else's vote, and all votes are "
            f"revealed publicly once everyone has voted. {nominator.name} votes Yes automatically.")
    outs = players.ask_many([(v, task, VOTE_SCHEMA, {"thoughts": "", "vote": False}) for v in others])
    yes_voters = [nominator.name] + [v.name for v, o in zip(others, outs) if o["vote"]]
    no_voters = [v.name for v, o in zip(others, outs) if not o["vote"]]
    game.emit(f"Nomination votes on {nominee}: Yes - {', '.join(yes_voters)}; "
              f"No - {', '.join(no_voters) or 'nobody'}.", cat=VOTE)
    passed = majority(len(yes_voters), len(game.alive()))
    game.vote_record.append(f"Day {game.day}: {nominator.name} nominated {nominee}; Yes - {', '.join(yes_voters)}; "
                            f"No - {', '.join(no_voters) or 'nobody'}; {'passed' if passed else 'failed'}")
    if not passed:
        game.emit(f"The nomination of {nominee} failed ({len(yes_voters)} Yes).", cat=VOTE)
        return "failed"
    game.emit(f"{nominee} is put on trial ({len(yes_voters)} Yes).", cat=VOTE)
    return run_trial(game, players, nominator, nominee, rnd)


def run_trial(game: Game, players: Players, nominator: Player, nominee: str, rnd: int) -> str:
    """Defense, discussion, then a simultaneous Guilty/Innocent vote. Returns "innocent" or "executed".
    If a Clerk rigged today's vote, the accused is executed regardless; the rigging is announced
    only if the vote alone wouldn't have executed them."""
    accused = game.player(nominee)
    chat_turn(game, players, accused, rnd, can_nominate=False, free_defense=True,
              extra="You are on trial. Defend yourself; you speak first.")
    for p in game.clockwise_from(accused.name)[1:]:
        chat_turn(game, players, p, rnd, can_nominate=False, extra=f"{nominee} is on trial.")

    voters = game.alive()
    task = (f"{nominee} is on trial. Vote true for Guilty (execute), false for Innocent. Voting is "
            "simultaneous: you can't see anyone else's vote, and all votes are revealed publicly once "
            "everyone has voted.")
    outs = players.ask_many([(v, task, VOTE_SCHEMA, {"thoughts": "", "vote": False}) for v in voters])
    guilty = [v.name for v, o in zip(voters, outs) if o["vote"]]
    innocent = [v.name for v, o in zip(voters, outs) if not o["vote"]]
    game.emit(f"Trial votes on {nominee}: Guilty - {', '.join(guilty) or 'nobody'}; "
              f"Innocent - {', '.join(innocent) or 'nobody'}.", cat=VOTE)
    voted_guilty = majority(len(guilty), len(game.alive()))
    rigged = not voted_guilty and game.rigged_day == game.day
    verdict = "executed" if voted_guilty else "executed (Clerk-rigged)" if rigged else "Innocent"
    game.vote_record.append(f"Day {game.day}: trial of {nominee}; Guilty - {', '.join(guilty) or 'nobody'}; "
                            f"Innocent - {', '.join(innocent) or 'nobody'}; {verdict}")
    if voted_guilty or game.rigged_day == game.day:
        if not voted_guilty:
            game.emit(f"The vote was rigged by a Clerk: {nominee} is executed despite the Innocent verdict.",
                      cat=VOTE)
        game.emit(f"{nominee} is executed by hanging ({len(guilty)} Guilty).", cat=DEATH)
        game.kill(nominee, "executed by hanging", guilty_voters=guilty)
        return "executed"
    game.emit(f"{nominee} is found Innocent ({len(guilty)} Guilty).", cat=VOTE)
    return "innocent"
