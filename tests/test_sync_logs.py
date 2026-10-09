"""Moving logs between machines through a `logs` branch (sync_logs.py), against a local bare remote."""

import json
import subprocess

import pytest

import sync_logs


def run(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def machines(tmp_path, monkeypatch):
    """Two clones (cloud, pc) of one bare remote whose main has a commit."""
    for k, v in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                 "GIT_COMMITTER_EMAIL": "t@t"}.items():
        monkeypatch.setenv(k, v)
    remote = tmp_path / "remote.git"
    run(tmp_path, "init", "--bare", "-b", "main", str(remote))
    seed = tmp_path / "seed"
    run(tmp_path, "clone", str(remote), str(seed))
    (seed / "code.py").write_text("x = 1\n")
    run(seed, "add", ".")
    run(seed, "commit", "-m", "code")
    run(seed, "push", "origin", "HEAD:main")
    out = {}
    for name in ("cloud", "pc"):
        run(tmp_path, "clone", str(remote), str(tmp_path / name))
        out[name] = sync_logs.Repo(tmp_path / name)
    return out


def test_logs_go_from_the_cloud_to_the_pc_without_touching_main(machines):
    cloud, pc = machines["cloud"], machines["pc"]
    logs = cloud.root / "logs"
    logs.mkdir()
    (logs / "game_1.jsonl").write_bytes(b'{"kind": "result"}\r\n')  # bytes kept exactly, CRLF included
    (logs / "game_1.html").write_text("<html>")
    (logs / "mock_2.jsonl").write_text("mock")
    (logs / "game_1.jsonl.lock").write_text("")
    assert sorted(sync_logs.push(cloud, logs)) == ["README.md", "logs/game_1.html", "logs/game_1.jsonl"]
    assert sync_logs.push(cloud, logs) == []  # nothing new
    assert cloud.git("status", "--porcelain").decode() == "?? logs/\n"
    assert cloud.git("rev-parse", "--abbrev-ref", "HEAD").decode().strip() == "main"

    (pc.root / "logs").mkdir()
    (pc.root / "logs" / "game_1.html").write_text("resumed here")
    written, kept = sync_logs.pull(pc, pc.root / "logs")
    assert [w.name for w in written] == ["game_1.jsonl"] and kept == ["game_1.html"]
    assert (pc.root / "logs" / "game_1.jsonl").read_bytes() == b'{"kind": "result"}\r\n'
    assert (pc.root / "logs" / "game_1.html").read_text() == "resumed here"
    assert not (pc.root / "logs" / "mock_2.jsonl").exists()
    assert pc.git("ls-tree", "-r", "--name-only", "HEAD").decode().split() == ["code.py"]


def test_shared_files_are_merged_and_pushes_from_two_machines_both_land(machines):
    a, b = machines["cloud"], machines["pc"]
    for repo, game, reviewed in ((a, "game_a", {"game_a": ["1:crash"], "old": ["2:api_retry"]}),
                                     (b, "game_b", {"old": ["5:player_error"], "older": 3})):
        logs = repo.root / "logs"
        logs.mkdir()
        (logs / f"{game}.jsonl").write_text("{}\n")
        (logs / "lessons.jsonl").write_text(f'{{"game": "{game}"}}\n')
        (logs / "alerts_reviewed.json").write_text(json.dumps(reviewed))
    sync_logs.push(a, a.root / "logs")
    sync_logs.push(b, b.root / "logs")  # merged with what a pushed, not replacing it
    sync_logs.pull(a, a.root / "logs")
    logs = a.root / "logs"
    assert (logs / "game_b.jsonl").exists()
    assert (logs / "lessons.jsonl").read_text().splitlines() == ['{"game": "game_a"}', '{"game": "game_b"}']
    assert json.loads((logs / "alerts_reviewed.json").read_text()) == {"game_a": ["1:crash"], "old": ["2:api_retry", "5:player_error"],
                                                                 "older": []}


def test_tips_published_on_the_pc_reach_cloud_games(machines):
    cloud, pc = machines["cloud"], machines["pc"]
    (pc.root / "tips").mkdir()
    (pc.root / "tips" / "tips.md").write_text("## Everyone\n- Count votes.\n")
    (pc.root / "tips" / "tips_notebook.json").write_text("{}")
    (pc.root / "tips" / "tips.md.lock").write_text("")
    assert sorted(sync_logs.put_tips(pc, pc.root / "tips")) == ["README.md", "tips/tips.md", "tips/tips_notebook.json"]
    written, kept = sync_logs.get_tips(cloud, cloud.root / "tips")
    assert sorted(w.name for w in written) == ["tips.md", "tips_notebook.json"] and kept == []
    (cloud.root / "tips" / "tips.md").write_text("edited")
    assert sync_logs.get_tips(cloud, cloud.root / "tips") == ([], ["tips.md"])
    assert sync_logs.get_tips(cloud, cloud.root / "tips", force=True)[0] == [cloud.root / "tips" / "tips.md"]


def test_a_log_pushed_again_after_the_game_went_on_replaces_the_earlier_copy(machines):
    cloud, pc = machines["cloud"], machines["pc"]
    logs = cloud.root / "logs"
    logs.mkdir()
    (logs / "game_1.jsonl").write_text('{"kind": "setup"}\n')  # pushed mid-game
    sync_logs.push(cloud, logs)
    sync_logs.pull(pc, pc.root / "logs")
    (logs / "game_1.jsonl").write_text('{"kind": "setup"}\n{"kind": "result"}\n')
    sync_logs.push(cloud, logs)
    written, kept = sync_logs.pull(pc, pc.root / "logs")
    assert [w.name for w in written] == ["game_1.jsonl"] and kept == []
    assert (pc.root / "logs" / "game_1.jsonl").read_text().endswith('{"kind": "result"}\n')


def test_a_re_pushed_game_s_other_files_follow_its_log_but_another_game_s_dont(machines):
    cloud, pc = machines["cloud"], machines["pc"]
    logs = cloud.root / "logs"
    logs.mkdir()
    for name, text in [("game_1.jsonl", '{"kind": "setup"}\n'), ("game_1.html", "day 1"),
                       ("game_1_feedback.md", "early"), ("game_1_2.html", "another game")]:
        (logs / name).write_text(text)
    sync_logs.push(cloud, logs)
    sync_logs.pull(pc, pc.root / "logs")
    (pc.root / "logs" / "game_1_2.html").write_text("regenerated here")
    (logs / "game_1.jsonl").write_text('{"kind": "setup"}\n{"kind": "result"}\n')
    (logs / "game_1.html").write_text("final")
    (logs / "game_1_feedback.md").write_text("late")
    (logs / "game_1_2.html").write_text("another game, later")
    sync_logs.push(cloud, logs)
    written, kept = sync_logs.pull(pc, pc.root / "logs")
    assert sorted(w.name for w in written) == ["game_1.html", "game_1.jsonl", "game_1_feedback.md"]
    assert kept == ["game_1_2.html"]  # game_1_2 is its own game, whose log wasn't continued
    assert (pc.root / "logs" / "game_1.html").read_text() == "final"


def test_a_game_pushes_its_logs_in_the_cloud_and_publishes_the_tips_on_the_pc(machines, capsys):
    cloud, pc = machines["cloud"], machines["pc"]
    (cloud.root / "logs").mkdir()
    (cloud.root / "logs" / "game_1.jsonl").write_text("{}\n")
    sync_logs.after_game(cloud.root / "logs", None, cloud=True, repo=cloud)
    (pc.root / "tips").mkdir()
    (pc.root / "tips" / "tips.md").write_text("## Everyone\n- Count votes.\n")
    sync_logs.after_game(pc.root / "logs", pc.root / "tips", cloud=False, repo=pc)
    files = cloud.files(cloud.fetch(), "logs") | cloud.files(cloud.fetch(), "tips")
    assert sorted(files) == ["logs/game_1.jsonl", "tips/tips.md"]
    assert "ALERT" not in capsys.readouterr().err

    broken = sync_logs.Repo(cloud.root, remote="nowhere")
    sync_logs.after_game(cloud.root / "logs", None, cloud=True, repo=broken)  # reported, not raised
    assert "ALERT sync_error: pushing the logs failed" in capsys.readouterr().err


def test_cloud_games_sync_and_leave_the_tips_notebook_alone(monkeypatch):
    import sys

    import mafia
    calls = []
    monkeypatch.setattr(mafia, "play_game", lambda client, *a, **kw: calls.append(("play", kw["update_tips"])))
    monkeypatch.setattr(mafia, "OpenRouterClient", lambda *a, **kw: None)
    monkeypatch.setattr(mafia, "load_api_key", lambda: "key")
    monkeypatch.setattr(sync_logs, "after_game", lambda log_dir, tips_dir, cloud: calls.append(("sync", tips_dir, cloud)))
    for cloud, argv, expected in [
            ("true", [], [("play", None), ("sync", None, True)]),
            ("", [], [("play", mafia.DEFAULT_TIPS), ("sync", mafia.DEFAULT_TIPS.parent, False)]),
            ("", ["--no-sync"], [("play", mafia.DEFAULT_TIPS)]),
            ("", ["--mock"], [("play", mafia.MOCK_TIPS)])]:
        monkeypatch.setenv("CLAUDE_CODE_REMOTE", cloud)
        monkeypatch.setattr(sys, "argv", ["mafia.py", *argv])
        calls.clear()
        mafia.main()
        assert calls == expected
