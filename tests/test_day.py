"""The day phase: nominations, trials, speaking budget and when the day ends."""

from day import MAX_TRIALS_PER_DAY, run_day, run_nomination, run_trial
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


def test_trial_comments_are_free_up_to_the_limit(game_factory):
    def decide(name, task, schema):
        return {"public_message": "I lean Guilty."} if "public_message" in schema["properties"] else None
    game, players = game_factory(VILLAGE5, ScriptedClient(decide))
    for p in game.players:
        p.speaking_budget = 0.0
    run_trial(game, players, game.player("Alice"), "Bob", rnd=1)
    speakers = {e.fields["speaker"] for e in game.events if e.cat == "chat"}
    assert speakers == {p.name for p in game.players}
    assert all(p.speaking_budget == 0.0 for p in game.players)


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
        return {"private_messages": [{"to": "Bob" if key == "Alice" else "Carol", "text": f"from {key}"}]}
    game, players = game_factory(TOWN4_GRUNT[:3] + ["Grunt", "Puppeteer"], ScriptedClient(decide))
    game.puppets_next = {"Bob": "Erin"}
    run_day(game, players)
    pms = {e.fields["message"]: e.visible_to for e in game.events if e.cat == "pm"}
    assert pms["from Alice"] == {"Alice", "Erin"}  # sent to Bob, read by his Puppeteer
    assert pms["from Erin-as-Bob"] == {"Erin", "Carol"}  # Bob's message, written by Erin
