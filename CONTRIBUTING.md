## Contributing

Thanks for your interest in contributing to CtxVault, local memory infrastructure for AI agents!

Contributions are welcome, and if you find CtxVault useful, leaving a star is the simplest way to support the project 🌟.

### Where to start

- Issues labelled [`good first issue`](https://github.com/Filippo-Venturini/ctxvault/labels/good%20first%20issue) are small and self-contained.
- Issues labelled [`help wanted`](https://github.com/Filippo-Venturini/ctxvault/labels/help%20wanted) are open to anyone but need more context.
- Found a bug or have an idea? Open an issue and we can discuss it from there.

### Workflow

1. **Comment on the issue before you start**, so it can be assigned to you and nobody duplicates the work.
2. **Design first for larger changes.** If the issue asks for a design discussion, post your approach there and wait for agreement before writing code.
3. **Open a pull request** from a branch in your fork. Link the issue with `Closes #N`, or `Part of #N` if more PRs will follow. The maintainer may retarget the PR to the development branch; you don't need to do anything.
4. **Keep it in scope.** A PR does what its issue describes. Unrelated fixes and refactors go in their own PR.

### What a PR needs

- Tests for the new behavior, and the full suite passing (`pytest`).
- Docs updated when behavior or an interface changes (`docs/`, and the README where relevant).
- A CHANGELOG entry under `Unreleased` when the change is user-visible (`CHANGELOG.md`, Keep a Changelog format).
- A feature exposed on one interface (CLI, HTTP, MCP, Python client) is exposed on the others too, unless the issue says otherwise.
- A vault created by an earlier release must keep working: storage changes need a migration and a test for it.

### UI changes

The memory viewer has an existing visual language. A change should look like it was always there.

- **Do exactly what the issue asks.** No extra panels, badges, counters, tooltips, empty states or settings. If something seems missing, comment on the issue instead of adding it.
- **No duplicated information.** A value appears once, where the reader looks for it.
- **No filler text.** No captions, subtitles or labels that restate what the element already shows. If a label can be removed without losing meaning, remove it.
- **Reuse what exists.** Use the components, spacing, colors and typography already there. No new colors, icons, emoji, gradients, shadows or card styles.
- **Raw values over decoration.** Show the timestamp, the reason, the id. No status pills or icons where plain text does the job.
- **Screenshots in the PR:** before and after, same data, light and dark. UI PRs without them won't be reviewed.

### Development setup

```bash
git clone https://github.com/Filippo-Venturini/ctxvault
cd ctxvault
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```
