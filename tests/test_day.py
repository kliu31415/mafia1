"""The day phase: nominations, trials, speaking budget and when the day ends."""

from llm import Model
from day import MAX_TRIALS_PER_DAY, TRIAL_BUDGET, chat_turn, message_cost, run_day, run_nomination, run_trial
from tests.conftest import TOWN4_GRUNT, VILLAGE5, ScriptedClient, votes


def test_nomination_needs_a_strict_majority_of_living_players(game_factory):
    # Alice nominates Bob; only Carol also votes Yes: 2 of 4 is not more than half.
    def decide(name, task, schema):
        return {"vote": name == "Carol"} if "vote" in schema["properties"] else None
    game, players = game_factory(VILLAGE5[:4], ScriptedClient(decide))
    assert run_nomination(game, players, game.player("Alice"), "Bob", rnd=1) == "failed"
    assert game.player("Bob").alive


def test_guilty_majority_executes(game_factory):
    game, players = game_factory(VILLAGE5, ScriptedClient(votes(guilty_for={"Bob"})))
    assert run_trial(game, players, game.player("Alice"), "Bob", rnd=1) == "executed"
    assert not game.player("Bob").alive


def test_clerk_rig_executes_despite_innocent_verdict(game_factory):
    game, players = game_factory(VILLAGE5[:4] + ["Clerk"])
    assert run_trial(game, players, game.player("Alice"), "Bob", rnd=1) == "innocent"
    game.rigged_day = game.day
    assert run_trial(game, players, game.player("Alice"), "Carol", rnd=1) == "executed"
    assert not game.player("Carol").alive


def test_prosecuted_player_goes_straight_to_trial(game_factory):
    game, players = game_factory(TOWN4_GRUNT, ScriptedClient(votes(guilty_for={"Erin"})))
    game.prosecutions.append("Erin")
    run_day(game, players)
    assert not game.player("Erin").alive
    assert any("prosecuted" in v for v in game.vote_record)


def test_day_ends_after_an_execution(game_factory):
    client = ScriptedClient(votes(guilty_for={"Bob"}, nominate={"Alice": "Bob", "Carol": "Dave"}))
    game, players = game_factory(TOWN4_GRUNT, client)
    run_day(game, players)
    assert not game.player("Bob").alive and game.player("Dave").alive


def test_private_messages_alone_dont_keep_the_day_going(game_factory):
    def decide(name, task, schema):
        if "private_messages" in schema["properties"]:
            to = schema["properties"]["private_messages"]["items"]["properties"]["to"]["enum"][0]
            return {"private_messages": [{"to": to, "text": "psst"}]}
        return None
    client = ScriptedClient(decide)
    game, players = game_factory(TOWN4_GRUNT, client)
    run_day(game, players)
    assert any(e.cat == "pm" for e in game.events)
    assert not any("round 2 " in task for _, task in client.asked)


def test_trial_turns_use_a_trial_budget_at_1x(game_factory):
    # Round 8 prices are 7.6x, so a broke player could say nothing; at trial prices the trial budget
    # pays for a short comment, and what's left of it doesn't carry over.
    def decide(name, task, schema):
        return {"public_message": "I lean Guilty."} if "public_message" in schema["properties"] else None
    game, players = game_factory(VILLAGE5, ScriptedClient(decide))
    for p in game.players:
        p.speaking_budget = 0.0
    run_trial(game, players, game.player("Alice"), "Bob", rnd=8)
    speakers = {e.fields["speaker"] for e in game.events if e.cat == "chat"}
    assert speakers == {p.name for p in game.players}
    assert all(p.speaking_budget == 0.0 for p in game.players)


def test_trial_turns_dip_into_the_regular_budget_past_the_trial_budget(game_factory):
    long = " ".join(["word"] * 200)  # 5.33 at 1x: the 3.00 trial budget, then 2.33 of the regular one

    def decide(name, task, schema):
        if "public_message" in schema["properties"] and name == "Carol":
            return {"public_message": long}
        return None
    game, players = game_factory(VILLAGE5, ScriptedClient(decide))
    for p in game.players:
        p.speaking_budget = 8.0
    run_trial(game, players, game.player("Alice"), "Bob", rnd=8)
    assert any(e.fields.get("message") == long for e in game.events if e.cat == "chat")
    assert abs(game.player("Carol").speaking_budget - (8.0 - (message_cost(200, 1, False) - TRIAL_BUDGET))) < 1e-9
    assert game.player("Dave").speaking_budget == 8.0


def always_nominate_never_convict(name, task, schema):
    """Every nomination passes and every trial ends Innocent; everyone nominates whenever they can."""
    if "vote" in schema["properties"]:
        return {"vote": "nominated" in task}  # Yes on nominations, Innocent at trials
    if "nominate" in schema["properties"]:
        others = [n for n in schema["properties"]["nominate"]["anyOf"][0]["enum"] if n != name]
        return {"nominate": others[0]}
    return None


def test_three_innocent_trials_end_the_day(game_factory):
    game, players = game_factory(TOWN4_GRUNT, ScriptedClient(always_nominate_never_convict))
    run_day(game, players)
    trials = [v for v in game.vote_record if "trial of" in v]
    assert len(trials) == MAX_TRIALS_PER_DAY and all(p.alive for p in game.players)
    assert "Three trials ended in Innocent verdicts. The day ends." in game.events[-1].text


def test_prosecutions_count_toward_the_trial_limit(game_factory):
    game, players = game_factory(TOWN4_GRUNT, ScriptedClient(always_nominate_never_convict))
    game.prosecutions.append("Erin")
    run_day(game, players)
    trials = [v for v in game.vote_record if "trial of" in v]
    assert len(trials) == MAX_TRIALS_PER_DAY and "trial of Erin" in trials[0]


def test_puppeteer_reads_and_writes_the_puppets_private_messages(game_factory):
    sent = set()

    def decide(name, task, schema):
        if "private_messages" not in schema["properties"]:
            return None
        key = ("Erin-as-Bob" if "You are puppeting Bob" in task else name)
        if key in sent or key not in ("Alice", "Erin-as-Bob"):
            return None
        sent.add(key)
        return {"private_messages": [{"to": "Bob" if key == "Alice" else "Carol", "text": f"from {key}"}],
                "claim": f"claim by {key}"}
    game, players = game_factory(TOWN4_GRUNT[:3] + ["Grunt", "Puppeteer"], ScriptedClient(decide))
    game.puppets_next = {"Bob": "Erin"}
    run_day(game, players)
    pms = {e.fields["message"]: e.visible_to for e in game.events if e.cat == "pm"}
    assert pms["from Alice"] == {"Alice", "Erin"}  # sent to Bob, read by his Puppeteer
    assert pms["from Erin-as-Bob"] == {"Erin", "Carol"}  # Bob's message, written by Erin
    # Bob's claim, set by Erin, is marked as hers in Bob's own history, like the messages she writes as him
    claim = next(e for e in game.events if e.cat == "claim" and e.fields["speaker"] == "Bob")
    assert claim.fields["puppeteer"] == "Erin" and "[Claim] Bob: claim by Erin-as-Bob [written by your Puppeteer" \
        in game.history_for("Bob")


def test_turns_go_around_the_circle_in_the_same_order_every_round(game_factory):
    def decide(name, task, schema):
        return {"public_message": "Hi."} if "public_message" in schema["properties"] else None
    client = ScriptedClient(decide)
    game, players = game_factory(TOWN4_GRUNT, client)
    run_day(game, players)
    rounds = [[p for p, task in client.asked if f"round {r} " in task] for r in (1, 2)]
    seats = [p.name for p in game.players]
    start = seats.index(rounds[0][0])
    assert rounds[0] == seats[start:] + seats[:start]
    assert rounds[1] == rounds[0]


def test_a_late_private_message_gets_one_last_turn_before_a_silent_round_ends_the_day(game_factory):
    # Alice privately asks Bob something; nobody speaks publicly, so the round is silent. Bob gets
    # one last turn and answers publicly, which keeps the day going into round 2.
    def decide(name, task, schema):
        if "private_messages" not in schema["properties"]:
            return None
        if name == "Alice" and "round 1 " in task and "last turn" not in task:
            return {"private_messages": [{"to": "Bob", "text": "are you the Sheriff?"}]}
        if name == "Bob" and "last turn" in task:
            return {"public_message": "Yes, and Dave is Evil."}
        return None
    client = ScriptedClient(decide)
    game, players = game_factory(TOWN4_GRUNT, client)
    run_day(game, players)
    last_turns = [who for who, task in client.asked if "last turn" in task]
    assert last_turns == ["Bob"]
    assert any("round 2 " in task for _, task in client.asked)
    assert "Alice -> Bob (1)" in game.public_ledger()


def test_players_can_update_their_will_on_a_day_turn(game_factory):
    def decide(name, task, schema):
        if name == "Alice" and "private_messages" in schema["properties"]:
            return {"last_will": "I claimed Medic today."}
        return None
    game, players = game_factory(TOWN4_GRUNT, ScriptedClient(decide))
    run_day(game, players)
    assert game.player("Alice").last_will == "I claimed Medic today."
    assert game.player("Bob").last_will == ""  # null keeps the will as it was


def test_claims_are_listed_in_the_ledger_with_earlier_ones_they_changed_from(game_factory):
    def decide(name, task, schema):
        if name == "Alice" and "claim" in schema["properties"]:
            return {"claim": "Vanilla Villager" if "Day 1," in task else "Medic. N1: protected Bob"}
        return None
    game, players = game_factory(TOWN4_GRUNT, ScriptedClient(decide))
    run_day(game, players)
    assert "- Alice: Day 1: Vanilla Villager\n" in game.public_ledger()
    game.day = 2
    run_day(game, players)
    assert "- Alice: Day 2: Medic. N1: protected Bob (earlier: Day 1: Vanilla Villager)" in game.public_ledger()
    assert list(game.claim_record) == ["Alice"]  # null claims change nothing
    game.log.txt.flush()  # the transcript shows each new claim once (the log review reads it)
    txt = game.log.path.with_suffix(".txt").read_text(encoding="utf-8")
    assert txt.count("[Claim] Alice: Vanilla Villager") == 1 and "[Claim] Alice: Medic. N1: protected Bob" in txt


def test_yakuza_see_their_own_and_teammates_tokens_left(game_factory):
    from players import role_briefing
    game, _ = game_factory(["Mortician", "Ballot Stuffer", "Grunt", "Vanilla Villager", "Vanilla Villager"])
    game.player("Bob").tokens["ballot"] = 1
    briefing = role_briefing(game, game.player("Alice"))
    assert "You have 2 mortician tokens left." in briefing
    assert "Bob (Ballot Stuffer, 1 ballot token left)" in briefing and "Carol (Grunt)" in briefing


def test_a_message_over_budget_is_cut_or_dropped_and_the_sender_is_told(game_factory):
    from day import chat_turn
    msg = {"public_message": "word " * 60, "private_messages": [{"to": "Carol", "text": "psst " * 60}]}
    game, players = game_factory(VILLAGE5, ScriptedClient(lambda name, task, schema: msg if name == "Alice" else None))
    game.player("Alice").speaking_budget = 0.5
    chat_turn(game, players, game.player("Alice"), rnd=1, can_nominate=False)
    told = [e.text for e in game.events if e.visible_to == {"Alice"}]  # public words cost more than private ones
    assert "Your public message was not sent: over budget." in told
    assert any(t.startswith("Your private message to Carol was cut to") for t in told)


def test_every_round_allows_a_short_public_message_and_a_nomination():
    # A round where nobody can afford to speak publicly is dead weight (round 8 was, at 1.5x per round).
    from day import BUDGET_MAX, MAX_DAY_ROUNDS, NOMINATION_COST, round_multiplier
    assert message_cost(10, MAX_DAY_ROUNDS, False) + NOMINATION_COST * round_multiplier(MAX_DAY_ROUNDS) <= BUDGET_MAX


def test_ledger_dates_night_deaths_by_their_night_and_a_quiet_night_is_announced(game_factory):
    game, players = game_factory(TOWN4_GRUNT)
    game.phase = "night"
    game.kill("Alice", "Katana")
    game.day = 2
    run_day(game, players)
    assert "- Night 1: Alice (" in game.public_ledger()
    game.day = 3
    run_day(game, players)
    assert sum(e.text == "Nobody died last night." for e in game.events) == 1


def test_the_accused_speaks_first_and_last(game_factory):
    def decide(name, task, schema):
        return {"public_message": "words"} if "public_message" in schema["properties"] else None
    game, players = game_factory(VILLAGE5, ScriptedClient(decide))
    run_trial(game, players, game.player("Alice"), "Bob", rnd=1)
    speakers = [e.fields["speaker"] for e in game.events if e.cat == "chat"]
    assert speakers[0] == speakers[-1] == "Bob" and speakers.count("Bob") == 2 and len(speakers) == 6


def test_a_new_claim_shows_in_everyones_history_and_a_name_prefix_is_dropped(game_factory):
    def decide(name, task, schema):
        if "public_message" in schema["properties"] and name == "Alice":
            return {"public_message": "Alice: I'm the Sheriff.", "claim": "Sheriff. N1: Bob Not Evil"}
        return None
    game, players = game_factory(VILLAGE5, ScriptedClient(decide))
    alice = game.player("Alice")
    alice.speaking_budget = 8.0
    alice.model = Model.SONNET_5_5
    chat_turn(game, players, alice, rnd=1, can_nominate=False)  # only Haiku's name prefix is stripped (a hack)
    alice.model = Model.HAIKU_5_5
    chat_turn(game, players, alice, rnd=1, can_nominate=False)  # the same claim isn't repeated
    claims = [e for e in game.events if e.cat == "claim"]
    assert len(claims) == 1 and claims[0].text == "[Claim] Alice: Sheriff. N1: Bob Not Evil"
    assert "[Claim] Alice" in game.history_for("Bob")
    assert ([e.fields["message"] for e in game.events if e.cat == "chat"]
            == ["Alice: I'm the Sheriff.", "I'm the Sheriff."])


def test_each_day_states_the_living_count_and_nomination_threshold(game_factory):
    game, players = game_factory(TOWN4_GRUNT)
    run_day(game, players)
    assert any(e.text.startswith("5 players are alive, so a nomination needs 3 Yes votes") for e in game.events)


def test_half_the_budget_left_carries_into_the_next_day(game_factory):
    import re
    from day import BUDGET_PER_ROUND
    seen: dict[str, str] = {}

    def decide(name, task, schema):
        if "Your speaking budget is" in task:
            seen.setdefault(name, task)
        return None
    game, players = game_factory(TOWN4_GRUNT, ScriptedClient(decide))
    game.player("Alice").speaking_budget = 8.0
    game.player("Bob").speaking_budget = 2.0
    run_day(game, players)
    budget = {n: float(m[1]) for n, t in seen.items() if (m := re.search(r"budget is ([\d.]+)", t))}
    assert budget["Alice"] == 4.0 + BUDGET_PER_ROUND
    assert budget["Bob"] == 1.0 + BUDGET_PER_ROUND
    assert budget["Carol"] == BUDGET_PER_ROUND


def test_a_symbol_only_claim_keeps_the_old_one_and_a_cut_will_says_so(game_factory):
    # Sol wrote "/" for "no change" and wills over the cap (game_20261009_152409_117630).
    def decide(name, task, schema):
        if name == "Alice" and "claim" in schema["properties"]:
            return ({"claim": "Sheriff", "last_will": "word " * 400} if "Day 1," in task
                    else {"claim": "/" if "Day 2," in task else "null", "last_will": "null"})
        return None
    game, players = game_factory(TOWN4_GRUNT, ScriptedClient(decide))
    run_day(game, players)
    game.day = 2
    run_day(game, players)
    game.day = 3
    run_day(game, players)
    assert [c for _, c in game.claim_record["Alice"]] == ["Sheriff"]
    assert game.player("Alice").last_will.count("word") == 300
    assert any("your last will was over 300 words" in e.text for e in game.events if e.visible_to == {"Alice"})


def test_a_claim_that_only_drops_a_period_is_not_a_new_claim():
    from day import same_claim
    assert same_claim("Sheriff. N1: Carol Evil.", "sheriff. N1:  Carol Evil")
    assert not same_claim("Sheriff. N1: Carol Evil", "Sheriff. N1: Carol Not Evil")
