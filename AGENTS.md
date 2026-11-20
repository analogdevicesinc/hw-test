# Agent instructions for hw-test

- For any task involving writing, running, debugging, or reviewing a
  hardware test (`tests/**`), use the
  [hw-test skill](.agents/skills/hw-test/SKILL.md) before doing anything
  else. It covers `LabgridClient`, board acquisition/release, artifact
  selection, base-vs-patched regression testing, and failure
  classification, all grounded in this repo's actual code and docs.
- **Installing the skill:** if your agent harness doesn't read
  `.agents/skills/**` directly, symlink or copy the `hw-test` directory
  into wherever it looks for skills. This is a per-checkout, local step —
  don't commit the copy.
- Inspect the repository before inventing an abstraction: `hw_tests/` and
  the existing `tests/**` already provide board selection, acquisition,
  artifact fetching, and SSH/console driving. Don't build a second
  hardware-allocation or artifact-fetching mechanism.
- Prefer the smallest targeted test/run over the whole suite. Never run
  `pytest tests` casually — it can reserve every matching board.
- Never hardcode a specific board/place (`labgrid_target`) unless the user
  explicitly asked for one; express hardware needs as capability tags
  (`needs = [...]`).
- Hardware acquired via `LabgridClient.acquire()` must always be released
  — use the `with` block as-is; don't leave a place acquired.
- The full task guides live under `docs/*.rst` (`docs/concepts.rst` is the
  best starting point); the skill teaches how to apply them to
  agent-driven tasks, not a replacement for them.
