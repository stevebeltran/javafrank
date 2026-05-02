# Agent rules

- Protect existing work first.
- Never overwrite, remove, or revert user changes unless explicitly asked.
- Never use destructive git commands such as `git reset --hard` or `git checkout --` unless explicitly asked.
- Before editing, check whether the repo is dirty and preserve unrelated modifications.
- Restrict edits to the smallest file set required for the requested task.
- If unrelated files are already modified, leave them alone.
- If a requested change would require touching shared code outside the stated scope, stop and ask first.
- Prefer targeted diffs over broad rewrites.
- Do not replace whole files when a small patch will do.
- If a feature is risky or overlaps in-progress work, recommend using a separate branch or `git worktree`.
- When finished, report exactly which files were changed.
- If tests or validation were not run, say so.

# Codex behavior request

Before making any file changes, read back a short plan and wait for confirmation unless the user explicitly says to proceed without a plan.

For small questions, answer directly.
For any task that would edit code, run tests, or touch files, summarize:

- what you think needs to change
- which files you expect to touch
- any risks or open questions

Then pause and wait for the user to approve the plan before editing.

# Recommended workflow

- One feature or fix per branch.
- Use `git worktree` for parallel features so each task has its own folder.
- Commit a checkpoint before starting a new feature if the current work matters.

# Prompting preference

When the user asks for changes, assume this scope unless told otherwise:

- Work only in files directly related to the requested feature.
- Preserve all other local modifications.
- Avoid opportunistic refactors.
