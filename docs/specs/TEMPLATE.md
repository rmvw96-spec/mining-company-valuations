# Title: what the change does

Roadmap n · Status: Outstanding | In progress | Built YYYY-MM-DD · Depends on: roadmap items

Instructions for Claude Code. Follow CLAUDE.md; don't restate it here.

## Goal

Two to four sentences: the problem today and the outcome.

## Scope

- **In:** what this spec changes.
- **Out:** what it deliberately leaves alone, and why in a few words.

## Design

The rules, formulas, record files, columns, settings keys and Sheet ranges. Tables rather than prose. Describe the
end state, not the history of how it was reached (git has that). The evidence for a setting's value goes in a
comment beside the setting in `config/settings.toml`, not here.

## Acceptance criteria

Each criterion is pass or fail and names its proof: a test (`tests/test_x.py::test_y`, checked by
`tests/test_data_files.py`), a command and what its output shows, or "(user)" for a review the user does. Tick a
criterion only when its test passes or its command was run that day. A criterion that waits on the user or on
data not yet published starts with "(user)" or "(data)": an item whose only open criteria are those counts as
Built. When you tick one, update the item's row in the roadmap's status table (the same test checks they agree).

- [ ] A1. Observable statement. — `tests/test_x.py::test_y`
- [ ] A2. Observable statement. — `uv run python -m minerval <command>` shows ...
- [ ] A3. (user) The user has reviewed ...

## Decisions

- One line each, with who decided and when (the user, YYYY-MM-DD).

## Open questions

1. Asked as they come up; moved to Decisions once answered.

Length: up to about 1,500 words for a large item, about 600 for a small one.
