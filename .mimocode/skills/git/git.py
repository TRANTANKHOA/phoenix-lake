#!/usr/bin/env python3
"""Git lifecycle driver — high-level commands for common workflows."""

import subprocess
import sys
import json
from datetime import datetime


def run(cmd, check=True):
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def git(*args, check=True):
    r = run(["git"] + list(args), check=check)
    return r.stdout.strip() if r.returncode == 0 else ""


def git_json(*args):
    r = run(["git"] + list(args), check=False)
    return {"ok": r.returncode == 0, "out": r.stdout.strip(), "err": r.stderr.strip()}


def branch():
    return git("rev-parse", "--abbrev-ref", "HEAD")


# --- Commands ---

def cmd_status():
    raw = git("status", "--porcelain=v1")
    lines = [l for l in raw.splitlines() if l]
    staged, unstaged, untracked = [], [], []
    for l in lines:
        i, w, p = l[0], l[1], l[3:]
        if i != " " and i != "?":
            staged.append(p)
        elif w != " ":
            unstaged.append(p)
        elif i == "?" and w == "?":
            untracked.append(p)
    return {
        "branch": branch(),
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "clean": len(lines) == 0,
    }


def cmd_save(message=None):
    git("add", "-A")
    staged = git("diff", "--cached", "--stat")
    if not staged:
        return {"ok": False, "msg": "Nothing to commit"}
    if not message:
        message = auto_commit_message(staged)
    return git_json("commit", "-m", message)


def auto_commit_message(stat_output):
    """Generate a conventional commit message from staged file changes."""
    files = []
    adds = dels = 0
    for line in stat_output.splitlines():
        if "|" not in line or line.strip().startswith("|"):
            continue
        parts = line.split("|")
        files.append(parts[0].strip())
        nums = parts[1].strip()
        # Parse "10 +++" or "5 ---" or "3 ++--"
        for token in nums.split():
            if token.startswith("+"):
                adds += int(token[1:]) if token[1:].isdigit() else 0
            elif token.startswith("-"):
                dels += int(token[1:]) if token[1:].isdigit() else 0

    if not files:
        return "chore: update files"

    # Detect type from files
    doc_only = all(f.startswith("docs/") or f.endswith(".md") or f.endswith(".html") for f in files)
    test_only = all("test" in f.lower() or f.endswith(".test.") for f in files)
    config_only = all(f.startswith("config/") or f in (".gitignore", ".env.example") for f in files)
    ci_only = all(f.startswith(".github/") or f.startswith("ci/") for f in files)
    skill_only = all(".mimocode/" in f for f in files)

    if doc_only:
        typ = "docs"
    elif test_only:
        typ = "test"
    elif ci_only:
        typ = "ci"
    elif skill_only:
        typ = "chore"
    elif config_only:
        typ = "chore"
    elif adds > 0 and dels == 0:
        typ = "feat"
    elif adds == 0 and dels > 0:
        typ = "fix"
    else:
        typ = "refactor"

    # Generate scope from common prefix
    if len(files) == 1:
        scope = files[0].split("/")[0].split(".")[0]
    else:
        prefixes = [f.split("/")[0] for f in files]
        from collections import Counter
        most_common = Counter(prefixes).most_common(1)[0][0]
        scope = most_common

    # Subject from file count
    if len(files) == 1:
        name = files[0].split("/")[-1].rsplit(".", 1)[0]
        subject = f"update {name}"
    else:
        subject = f"update {len(files)} files in {scope}"

    return f"{typ}({scope}): {subject}"


def cmd_push(upstream=False, force=False):
    args = ["push", "origin", branch()]
    if upstream:
        args.insert(1, "-u")
    if force:
        args.append("--force-with-lease")
    return git_json(*args)


def cmd_pull(rebase=True):
    args = ["pull", "origin"]
    if rebase:
        args.append("--rebase")
    return git_json(*args)


def cmd_log(count=10):
    return git("log", f"-{count}", "--format=%h %ad %s", "--date=short")


def cmd_start(name):
    return git_json("checkout", "-b", name)


def cmd_switch(name):
    return git_json("checkout", name)


def cmd_merge(target):
    return git_json("merge", target)


def cmd_rebase(target):
    return git_json("rebase", target)


def cmd_rebase_abort():
    return git_json("rebase", "--abort")


def cmd_squash(count=2, message=None):
    if count < 2:
        return {"ok": False, "msg": "Need at least 2 commits"}
    shas = git("log", f"--max-count={count}", "--format=%H").splitlines()
    if len(shas) < count:
        return {"ok": False, "msg": f"Only {len(shas)} commits exist"}

    # Check if oldest is root
    parent = run(["git", "rev-parse", f"{shas[-1]}^"], check=False)
    if parent.returncode != 0:
        return cmd_squash_all(message)

    if not message:
        message = git("log", "--max-count=1", "--format=%s")
    git("reset", "--soft", parent.stdout.strip())
    return git_json("commit", "-m", message)


def cmd_squash_all(message=None):
    current = branch()
    if not message:
        message = git("log", "--reverse", "--format=%s", "HEAD").splitlines()[0]
    git("stash", "push", "-m", "squash backup")
    run(["git", "checkout", "--orphan", "__squash__"], check=False)
    run(["git", "add", "-A"], check=False)
    r = run(["git", "commit", "-m", message], check=False)
    if r.returncode != 0:
        run(["git", "checkout", current], check=False)
        git("stash", "pop")
        return {"ok": False, "msg": r.stderr.strip()}
    run(["git", "branch", "-M", current], check=False)
    git("stash", "pop", check=False)
    return {"ok": True, "sha": git("rev-parse", "--short", "HEAD")}


def cmd_diff(staged=False):
    args = ["diff"]
    if staged:
        args.append("--cached")
    return git(*args)


def cmd_stash(message=None):
    if message:
        return git("stash", "push", "-m", message)
    return git("stash", "push")


def cmd_stash_pop():
    return git("stash", "pop")


def cmd_tag(name, message=None):
    if message:
        return git("tag", "-a", name, "-m", message)
    return git("tag", name)


def cmd_revert(sha):
    return git_json("revert", sha, "--no-edit")


def cmd_reset(target="HEAD", mode="soft"):
    return git("reset", f"--{mode}", target)


def cmd_amend(message=None):
    git("add", "-A")
    if message:
        return git_json("commit", "--amend", "-m", message)
    # No message — auto-extend with staged files
    staged = git("diff", "--cached", "--stat")
    if not staged:
        return git_json("commit", "--amend", "--no-edit")
    old_msg = git("log", "--max-count=1", "--format=%B")
    old_subject = old_msg.splitlines()[0]
    new_files = [l.strip().split("|")[0].strip() for l in staged.splitlines() if "|" in l and not l.strip().startswith("|")]
    if new_files:
        file_summary = ", ".join(new_files[:5])
        if len(new_files) > 5:
            file_summary += f" (+{len(new_files) - 5} more)"
        message = f"{old_subject}\n\n- {file_summary}"
    else:
        message = old_subject
    return git_json("commit", "--amend", "-m", message)


COMMANDS = {
    "status":     lambda a: cmd_status(),
    "save":       lambda a: cmd_save(" ".join(a) if a else None),
    "push":       lambda a: cmd_push("-u" in a, "--force" in a),
    "pull":       lambda a: cmd_pull("--rebase" in a),
    "log":        lambda a: cmd_log(int(a[0]) if a else 10),
    "start":      lambda a: cmd_start(a[0]),
    "switch":     lambda a: cmd_switch(a[0]),
    "merge":      lambda a: cmd_merge(a[0]),
    "rebase":     lambda a: cmd_rebase(a[0]),
    "abort":      lambda a: cmd_rebase_abort(),
    "squash":     lambda a: cmd_squash(int(a[0]) if a else 2, " ".join(a[1:]) if len(a) > 1 else None),
    "squash-all": lambda a: cmd_squash_all(" ".join(a) if a else None),
    "diff":       lambda a: cmd_diff("--staged" in a),
    "stash":      lambda a: cmd_stash(" ".join(a) if a else None),
    "stash-pop":  lambda a: cmd_stash_pop(),
    "tag":        lambda a: cmd_tag(a[0], " ".join(a[1:]) if len(a) > 1 else None),
    "revert":     lambda a: cmd_revert(a[0]),
    "reset":      lambda a: cmd_reset(a[0] if a else "HEAD", a[1] if len(a) > 1 else "soft"),
    "amend":      lambda a: cmd_amend(" ".join(a) if a else None),
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: git.py <command> [args...]")
        print()
        print("Workflows:")
        print("  status              Show working tree status")
        print("  save [message]      Stage all + commit")
        print("  push [-u] [--force] Push to origin")
        print("  pull [--rebase]     Pull from origin (default: rebase)")
        print()
        print("Branching:")
        print("  start <name>        Create + switch to new branch")
        print("  switch <name>       Switch to existing branch")
        print("  merge <branch>      Merge branch into current")
        print("  rebase <branch>     Rebase onto branch")
        print("  abort               Abort in-progress rebase")
        print()
        print("History:")
        print("  log [count]         Show recent commits")
        print("  squash [N] [msg]    Squash last N commits (default: 2)")
        print("  squash-all [msg]    Squash ALL commits into root")
        print("  revert <sha>        Revert a commit")
        print("  reset [target]      Reset (soft/mixed/hard)")
        print("  amend [message]     Amend last commit with staged changes")
        print()
        print("Other:")
        print("  diff [--staged]     Show changes")
        print("  stash [message]     Stash working changes")
        print("  stash-pop           Apply + drop stash")
        print("  tag <name> [msg]    Create tag")
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd not in COMMANDS:
        print(f"Unknown: {cmd}", file=sys.stderr)
        sys.exit(1)

    result = COMMANDS[cmd](args)
    if result is not None:
        if isinstance(result, dict):
            print(json.dumps(result, indent=2))
        else:
            print(result)


if __name__ == "__main__":
    main()
