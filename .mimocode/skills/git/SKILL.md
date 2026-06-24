---
name: git
description: Use when performing git operations — committing, pushing, merging, rebasing, branching, stashing, or any git lifecycle management
---

# Git Lifecycle Driver

Drive git operations through `git.py` instead of raw git commands.

## Script Location

`.mimocode/skills/git/git.py`

## Core Principle

Always check status before acting. Use `save` instead of raw add/commit. Encode best practices — never force push main, always rebase before merge, squash messy history.

## Shorthand Triggers

When the user says any of these, execute the corresponding workflow:

| User says | Action |
|-----------|--------|
| `/git commit` | `status` → `save` (auto-generate message from staged files) |
| `/git push` | `status` → `push` (set upstream if new branch) |
| `/git push --force` | `push --force` (only if not main/master) |
| `/git pr` | `push -u` → open PR via `gh pr create` |
| `/git rebase` | `pull --rebase` → if conflicts, read files and resolve |
| `/git merge` | `pull` → `merge origin/<current-branch>` |
| `/git reset` | `reset HEAD --hard` (confirm if unstaged changes exist) |
| `/git reset --soft` | `reset HEAD~1 --soft` (undo last commit, keep changes) |
| `/git amend` | `amend` (add staged changes to last commit) |
| `/git amend "msg"` | `amend "msg"` (amend last commit with new message) |
| `/git squash` | `squash 2` (squash last 2 commits) |
| `/git squash N` | `squash N` (squash last N commits) |
| `/git squash-all` | `squash-all` (squash all into root commit) |
| `/git status` | `status` |
| `/git log` | `log` |
| `/git stash` | `stash` |
| `/git stash pop` | `stash-pop` |
| `/git diff` | `diff` |
| `/git branch` | `status` (shows branch) |
| `/git start <name>` | `start <name>` |
| `/git switch <name>` | `switch <name>` |
| `/git abort` | `abort` (abort rebase) |

## Best Practices Encoded

### Commit
- Always `status` before committing
- Auto-generate commit message from staged file names if user doesn't provide one
- Use conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`, `test:`
- Never commit `.env`, credentials, or secrets

### Push
- Check if branch has upstream; if not, use `push -u`
- Never force push `main` or `master` without explicit approval
- Use `--force-with-lease` (never raw `--force`)

### PR
- Push first, then use `gh pr create`
- PR title should match commit message
- Include summary of changes in PR body

### Rebase
- Always `pull --rebase` to stay current
- If conflicts: read conflicted files, resolve, `save`, rebase continues
- If stuck: `abort` and ask user

### Merge
- Pull latest first
- Merge into current branch from target
- Push after successful merge

### Reset
- `--soft` (default): undo commit, keep changes staged
- `--mixed`: undo commit, unstage changes
- `--hard`: discard everything (confirm first!)
- Always warn before `--hard` reset

### Squash
- `squash 2`: combine last 2 commits (most common)
- `squash N`: combine last N commits
- `squash-all`: nuclear option — all commits into one root commit
- After squash, may need `push --force`

## Commands Reference

```bash
python3 .mimocode/skills/git/git.py <command> [args...]
```

| Command | Usage | What it does |
|---------|-------|-------------|
| `status` | No args | Show branch, staged, unstaged, untracked |
| `save [message]` | Optional message | Stage all + commit |
| `push [-u] [--force]` | Flags | Push to origin |
| `pull [--rebase]` | Flag | Pull from origin (rebase by default) |
| `start <name>` | Branch name | Create + switch to new branch |
| `switch <name>` | Branch name | Switch to existing branch |
| `merge <branch>` | Branch name | Merge branch into current |
| `rebase <branch>` | Branch name | Rebase onto branch |
| `abort` | No args | Abort in-progress rebase |
| `log [count]` | Optional count | Show recent commits |
| `squash [N] [msg]` | Count + optional msg | Squash last N commits |
| `squash-all [msg]` | Optional message | Squash ALL into root |
| `diff [--staged]` | Flag | Show changes |
| `stash [message]` | Optional message | Stash working changes |
| `stash-pop` | No args | Apply + drop stash |
| `tag <name> [msg]` | Tag name + optional message | Create tag |
| `revert <sha>` | Commit SHA | Revert a commit |
| `reset [target] [mode]` | Target + mode | Reset (default: soft HEAD) |
| `amend [message]` | Optional message | Amend last commit with staged changes |

## Workflows

### Quick save and share
```bash
git.py status
git.py save "feat: add new endpoint"
git.py push
```

### Start new feature
```bash
git.py pull
git.py start feature-x
# ... work ...
git.py save "feat: implement feature x"
git.py push -u
```

### Finish feature (merge back)
```bash
git.py switch main
git.py pull
git.py switch feature-x
git.py rebase main
git.py switch main
git.py merge feature-x
git.py push
```

### Clean up before push
```bash
git.py log 5
git.py squash 3 "feat: complete feature x"
git.py push --force
```

### Nuclear: squash everything
```bash
git.py squash-all "feat: initial project setup"
git.py push --force
```
