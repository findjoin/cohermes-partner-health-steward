# Issue tracker: Local Markdown

Issues and specs for this repo live as markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`.
- The spec is `.scratch/<feature-slug>/spec.md`.
- Implementation issues are one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`.
- Triage state is recorded as a `Status:` line near the top of each issue file. See `triage-labels.md` for the role strings.
- Comments and conversation history append to the bottom of the file under a `## Comments` heading.

## Publishing and reading

When a Skill says to publish to the issue tracker, create the required file under `.scratch/<feature-slug>/`. When it says to fetch a ticket, read the referenced file.

## Wayfinding

- Map: `.scratch/<effort>/map.md`.
- Child ticket: `.scratch/<effort>/issues/<NN>-<slug>.md` with `Type:`, `Status:`, and optional `Blocked by:` lines near the top.
- A ticket is unblocked when every listed blocker has `Status: resolved`.
- Claim a ticket by writing `Status: claimed` before work. Resolve it by appending `## Answer`, setting `Status: resolved`, and adding a concise context pointer to the map.
