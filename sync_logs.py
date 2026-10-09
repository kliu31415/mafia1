"""Moves game logs between machines through the repo's `logs` branch, so games can run in the cloud
(Claude Code on the web, whose sandbox is deleted afterwards) and still end up in logs/ on Kevin's PC.

The `logs` branch holds only logs/ and tips/ (no code), so main stays clean. Nothing here checks out
that branch or touches the working tree's tracked files: commits are built with git plumbing in a
temporary index and pushed, and pulled files are read straight from the fetched commit. That makes it
safe to run from the main checkout on any branch, with uncommitted changes.

Tips: the notebook on the PC (tips/) stays the one source of truth. Cloud games play with a copy of its
sheet and don't update it (mafia.py turns that off in the cloud); `pull` on the PC adds their lessons to the
notebook (the same `tips.py build` a PC game runs when it ends) and publishes the new sheet for later cloud
games. mafia.py also calls after_game when a live game ends or stops: a cloud game pushes its logs, and a
PC game publishes the sheet it just updated.

Files merged rather than copied: logs/lessons.jsonl (lines from every machine, each kept once) and
logs/alerts_reviewed.json (a problem counts as reviewed once any machine reviewed it).
Mock games, lock and temporary files are never synced.

Usage:
    uv run sync_logs.py tips              # cloud, before games: tips/ from the branch (the PC's latest sheet)
    uv run sync_logs.py push              # cloud, after games: push new files in logs/ to the branch
    uv run sync_logs.py pull              # PC: copy new logs into logs/, add their lessons to the tips
                                          # notebook, then publish the new tips sheet to the branch
    uv run sync_logs.py pull --no-tips    # PC: only copy the logs
"""

import argparse
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BRANCH = "logs"
REMOTE = "origin"
TIPS_FILES = ("tips.md", "tips_notebook.json", "tips_notebook.md")
README = (b"# Game logs\n\nThis branch holds game logs (logs/) and the tips sheet (tips/), not code. It is written by\n"
          b"`uv run sync_logs.py` on main; see that file's docstring.\n")
PUSH_TRIES = 6  # another machine pushing at the same moment makes a push fail; it is rebuilt and retried


def merge_lessons(ours: bytes, theirs: bytes) -> bytes:
    """Lines of both, each once: theirs (the branch's) in order, then lines only ours has."""
    seen = set(theirs.splitlines())
    extra = [line for line in ours.splitlines() if line.strip() and line not in seen]
    base = theirs if not theirs or theirs.endswith(b"\n") else theirs + b"\n"
    return base + b"".join(line + b"\n" for line in extra)


def merge_reviewed(ours: bytes, theirs: bytes) -> bytes:
    """Game id -> the ids of its problems reviewed (alerts.py); either side's review counts."""
    merged: dict[str, list] = {}
    for side in (theirs, ours):
        for game, ids in json.loads(side or b"{}").items():
            ids = ids if isinstance(ids, list) else []  # an old-format count means nothing now
            merged[game] = sorted(set(merged.get(game, [])) | set(ids))
    return json.dumps(merged, indent=1, sort_keys=True).encode()


MERGED = {"lessons.jsonl": merge_lessons, "alerts_reviewed.json": merge_reviewed}


class Repo:
    def __init__(self, root: Path = ROOT, remote: str = REMOTE, branch: str = BRANCH):
        self.root, self.remote, self.branch = root, remote, branch
        self.tracking = f"refs/remotes/{remote}/{branch}"

    def git(self, *args: str, input: bytes | None = None, env: dict | None = None, check: bool = True) -> bytes:
        r = subprocess.run(["git", *args], cwd=self.root, input=input, capture_output=True,
                           env={**os.environ, **env} if env else None)
        if check and r.returncode:
            raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.decode(errors='replace').strip()}")
        return r.stdout

    def fetch(self) -> str | None:
        """The branch's latest commit on the remote (fetched), or None if it doesn't exist yet."""
        if not self.git("ls-remote", "--heads", self.remote, self.branch).strip():
            return None
        self.git("fetch", "--quiet", self.remote, f"+refs/heads/{self.branch}:{self.tracking}")
        return self.git("rev-parse", self.tracking).decode().strip()

    def files(self, commit: str | None, prefix: str) -> dict[str, str]:
        """Path -> blob id of the files under prefix/ in commit."""
        if commit is None:
            return {}
        out = self.git("ls-tree", "-r", "-z", commit, "--", prefix + "/").decode()
        entries = (e.split("\t", 1) for e in out.split("\0") if e)
        return {path: meta.split()[2] for meta, path in entries}

    def blob(self, blob_id: str) -> bytes:
        return self.git("cat-file", "blob", blob_id)

    def commit(self, parent: str | None, files: dict[str, bytes], message: str) -> str | None:
        """A commit of parent's tree plus `files` (path -> content), or None if that changes nothing."""
        index = Path(self.git("rev-parse", "--absolute-git-dir").decode().strip()) / f"sync_logs_{os.getpid()}.index"
        env = {"GIT_INDEX_FILE": str(index)}
        try:
            self.git("read-tree", *([parent] if parent else ["--empty"]), env=env)
            for path, content in sorted(files.items()):
                blob_id = self.git("hash-object", "-w", "--no-filters", "--stdin", input=content).decode().strip()
                self.git("update-index", "--add", "--cacheinfo", f"100644,{blob_id},{path}", env=env)
            tree = self.git("write-tree", env=env).decode().strip()
        finally:
            index.unlink(missing_ok=True)
        if parent and tree == self.git("rev-parse", f"{parent}^{{tree}}").decode().strip():
            return None
        return self.git("commit-tree", tree, *(["-p", parent] if parent else []), "-m", message).decode().strip()

    def publish(self, gather, message: str) -> tuple[str | None, list[str]]:
        """Pushes a commit of gather(parent) -> {path: content} onto the branch, retrying from the new
        head when another machine pushed first. Returns (commit or None if nothing changed, paths sent)."""
        for _ in range(PUSH_TRIES):
            parent = self.fetch()
            files = gather(parent) | ({} if parent else {"README.md": README})
            commit = self.commit(parent, files, message)
            if commit is None:
                return None, []
            r = subprocess.run(["git", "push", "--quiet", self.remote, f"{commit}:refs/heads/{self.branch}"],
                               cwd=self.root, capture_output=True)
            if r.returncode == 0:
                self.git("update-ref", self.tracking, commit)
                changed = self.git("diff-tree", "-r", "--name-only", "--no-commit-id", "--root", commit,
                                   *([parent] if parent else [])).decode().split()
                return commit, changed
            err = r.stderr.decode(errors="replace")
            if "fetch first" not in err and "non-fast-forward" not in err:  # not a race: no use retrying
                raise RuntimeError(f"git push to {self.remote} {self.branch} failed: {err.strip()}")
        raise RuntimeError(f"git push to {self.remote} {self.branch} kept losing races with other pushes")


def syncable(path: Path) -> bool:
    """Game outputs worth keeping: not mock games, locks or half-written temporary files."""
    return (path.is_file() and not path.name.startswith("mock")
            and path.suffix not in (".lock", ".tmp") and not path.name.endswith(".ckpt.tmp"))


def push(repo: Repo, log_dir: Path) -> list[str]:
    """Sends every log file in log_dir (top level) the branch doesn't have, and merges the shared
    files into the branch's copies. Returns the paths that changed on the branch."""
    def gather(parent: str | None) -> dict[str, bytes]:
        theirs = repo.files(parent, "logs")
        out = {}
        for p in sorted(log_dir.iterdir()) if log_dir.is_dir() else []:
            if not syncable(p):
                continue
            key = f"logs/{p.name}"
            data = p.read_bytes()
            if p.name in MERGED:
                data = MERGED[p.name](data, repo.blob(theirs[key]) if key in theirs else b"")
            out[key] = data
        return out
    return repo.publish(gather, f"Logs from {platform.node()}")[1]


def pull(repo: Repo, log_dir: Path) -> tuple[list[Path], list[str]]:
    """Copies the branch's log files that log_dir lacks, and merges the shared ones into log_dir.
    A local file that differs from the branch's copy is kept (e.g. a cloud game resumed here), unless the
    branch's copy just continues it (a log pushed again after the game went on); then that game's other
    files (.txt, .html, feedback, ...) are replaced too, since they were written from the older log.
    Returns (files written, names kept because they differ)."""
    head = repo.fetch()
    written, kept = [], []
    log_dir.mkdir(parents=True, exist_ok=True)
    continued: list[str] = []  # stems of local game logs the branch's copy continues
    # Game logs first, so the files written from them know whether their log was continued.
    for path, blob_id in sorted(repo.files(head, "logs").items(), key=lambda x: not x[0].endswith(".jsonl")):
        name = path.split("/", 1)[1]
        if "/" in name:
            continue
        local = log_dir / name
        theirs = repo.blob(blob_id)
        if name in MERGED:
            data = MERGED[name](local.read_bytes() if local.exists() else b"", theirs)
            if local.exists() and data == local.read_bytes():
                continue
        elif local.exists():
            ours = local.read_bytes()
            if ours == theirs:
                continue
            if name.endswith(".jsonl") and theirs.startswith(ours):  # an earlier copy (e.g. pushed mid-game)
                continued.append(name.removesuffix(".jsonl"))
            elif not any(re.match(re.escape(stem) + r"(\.|_[a-z])", name) for stem in continued):
                kept.append(name)
                continue
            data = theirs
        else:
            data = theirs
        tmp = local.with_name(local.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, local)
        written.append(local)
    return written, kept


def in_cloud() -> bool:
    """Running in Claude Code on the web, whose sandbox (with any log not pushed) is deleted afterwards."""
    return os.environ.get("CLAUDE_CODE_REMOTE") == "true"


def after_game(log_dir: Path, tips_dir: Path | None, cloud: bool, repo: Repo | None = None) -> None:
    """What a live game does when it ends or stops (mafia.py --sync): in the cloud, push its logs; on the
    PC, publish the tips sheet it updated in tips_dir (None if it didn't), for later cloud games. Failures
    are printed as ALERT lines, never raised: the game itself is over and its log closed."""
    repo = repo or Repo()
    try:
        if cloud:
            changed = push(repo, log_dir)
            print(f"Pushed {len(changed)} log files to {repo.remote}/{repo.branch}")
        elif tips_dir and (tips_dir / "tips.md").exists():
            if put_tips(repo, tips_dir):
                print(f"Published the tips to {repo.remote}/{repo.branch}")
    except Exception as e:
        what = "pushing the logs" if cloud else "publishing the tips"
        print(f"ALERT sync_error: {what} failed: {type(e).__name__}: {e}"
              + ("; run `uv run sync_logs.py push` before the sandbox goes" if cloud else
                 "; `uv run sync_logs.py publish-tips` retries"), file=sys.stderr)


def get_tips(repo: Repo, tips_dir: Path, force: bool = False) -> tuple[list[Path], list[str]]:
    """Writes the branch's tips sheet and notebook into tips_dir. Files that exist here and differ are
    kept unless `force`. Returns (files written, names kept)."""
    head = repo.fetch()
    written, kept = [], []
    for path, blob_id in repo.files(head, "tips").items():
        name = path.split("/", 1)[1]
        if name not in TIPS_FILES:
            continue
        local, data = tips_dir / name, repo.blob(blob_id)
        if local.exists() and local.read_bytes() == data:
            continue
        if local.exists() and not force:
            kept.append(name)
            continue
        tips_dir.mkdir(parents=True, exist_ok=True)
        local.write_bytes(data)
        written.append(local)
    return written, kept


def put_tips(repo: Repo, tips_dir: Path) -> list[str]:
    """Publishes the tips sheet and notebook here for cloud games. Returns the paths that changed."""
    files = {f"tips/{n}": (tips_dir / n).read_bytes() for n in TIPS_FILES if (tips_dir / n).exists()}
    return repo.publish(lambda parent: files, "Tips sheet and notebook")[1] if files else []


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("push", help="push new files in logs/ to the logs branch (after cloud games)")
    p = sub.add_parser("pull", help="copy new logs from the branch into logs/, update the tips and publish them")
    p.add_argument("--no-tips", action="store_true", help="only copy the logs: don't add their lessons to the tips "
                   "notebook (an Opus call per game) or publish the sheet")
    p.add_argument("--tips-model", default="opus-5.5", help="model[:effort] that updates the tips notebook")
    t = sub.add_parser("tips", help="tips/ from the branch, for cloud games (before games)")
    t.add_argument("--force", action="store_true", help="overwrite local tips files that differ")
    sub.add_parser("publish-tips", help="publish tips/ here to the branch (pull does this after updating them)")
    args = ap.parse_args()
    repo, log_dir, tips_dir = Repo(), ROOT / "logs", ROOT / "tips"
    try:
        if args.cmd == "push":
            changed = push(repo, log_dir)
            print(f"Pushed {len(changed)} files to {repo.remote}/{repo.branch}" + "".join(f"\n  {c}" for c in changed)
                  if changed else f"Nothing new to push to {repo.remote}/{repo.branch}")
        elif args.cmd == "pull":
            written, kept = pull(repo, log_dir)
            print(f"Copied {len(written)} files into {log_dir}" + "".join(f"\n  {w.name}" for w in written))
            for name in kept:
                print(f"ALERT sync_error: kept {name}: the local copy differs from the branch's (not overwritten)")
            # every game, not just the new ones: build skips games it has, and retries ones a failed build missed
            games = sorted(log_dir.glob("game_*.jsonl"))
            if any(w.name.startswith("game_") and w.suffix == ".jsonl" for w in written) and not args.no_tips:
                update_tips(games, tips_dir, args.tips_model)
            if not args.no_tips:
                changed = put_tips(repo, tips_dir)
                print(f"Published the tips to {repo.remote}/{repo.branch}" if changed else "Tips on the branch are "
                      "up to date" if (tips_dir / "tips.md").exists() else f"No tips sheet in {tips_dir} to publish")
        elif args.cmd == "tips":
            written, kept = get_tips(repo, tips_dir, args.force)
            print(f"Tips from {repo.remote}/{repo.branch}: " + (", ".join(str(w) for w in written) or "nothing new"))
            for name in kept:
                print(f"  kept {name}: the local copy differs (use --force to overwrite)")
        elif args.cmd == "publish-tips":
            print("Published" if put_tips(repo, tips_dir) else "Nothing new to publish")
    except RuntimeError as e:
        print(f"ALERT sync_error: {e}", file=sys.stderr)
        sys.exit(1)


def update_tips(games: list[Path], tips_dir: Path, model: str) -> None:
    """Adds the pulled games' lessons to the tips notebook, as a game run here does when it ends."""
    import tips
    from llm import OpenRouterClient, load_api_key, parse_model_spec
    client = OpenRouterClient(load_api_key())
    client.on_error = tips.print_alert
    try:
        tips.build(games, tips_dir / "tips.md", client, parse_model_spec(model), 800)
    except tips.NoNewGames as e:
        print(e)


if __name__ == "__main__":
    main()
