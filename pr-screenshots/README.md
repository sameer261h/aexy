# Screenshots by pull request

Captured 25 July 2026 against the running local stack, signed in as the real
Google-authenticated test account **obeytheproletariat@gmail.com** (Slavoj
Zizhad) in **Alex's Workspace** — the workspace with the working Slack
connection. No generated tokens; this reuses that signed-in session.

| File | Pull request | What it proves |
|---|---|---|
| `pr1-slack-connected.png` | Slack connect security | Integrations screen with Slack showing connected, reached through the authenticated path |
| `pr2-filter-panel.png` | Records & lists contract | The filter panel on a record grid — filters now reach the server instead of being dropped |
| `pr3-crm-people-grid.png` | Grid & board | The record grid the membership control lives on |
| `pr3-deals-board.png` | Grid & board | **Strong shot.** Board with all six stages, cards carrying values, a live "Drop records here" target, and a weighted forecast |
| `pr3-lists-dropdown.png` | Grid & board | The lists control reachable from the grid |
| `pr4-sequences-list.png` | Sequences | Sequences listing reached from CRM navigation, showing enrolment counts |
| `pr5-trigger-palette.png` | Triggers | **Strong shot.** The palette listing every trigger this work delivered — added to and removed from list, daily and weekly schedule, date approaching and passed, form submitted, email opened and clicked |
| `pr5-automations-list.png` | Triggers | The automations index |
| `pr6-automation-builder.png` | Action steps | The builder canvas |
| `pr6-test-run-skipped.png` | Action steps | **The most important shot in the set.** A completed test run reporting one succeeded, zero errors and **one skipped**, with "This was a dry run. No actual actions were performed." Before this fix that Slack step sent a real message |
| `pr7-run-history.png` | Email durability | Run history listing each run and its outcome |
| `pr8-gtm-compliance.png` | Outreach compliance | The compliance screen |

## Data created to make these possible

The deals board had no pipeline configured, so the board was an empty prompt.
A default sales pipeline was created against the existing stage field, adopting
the six stages already in use rather than inventing new ones. Nothing else was
seeded — every record, automation and sequence shown already existed.

## Not captured, and why

- **Error messages across 55 screens** — fifty-five identical one-line changes.
  A screenshot of one message proves nothing the diff does not.
- **The duplicate-record guard** — needs a field marked unique and a deliberate
  collision to trigger. Worth adding by hand if the reviewer asks for it.
- The run history shown is genuine but is evidence of outcomes being recorded,
  not specifically of a repeat send being refused, which has unit-test coverage
  instead.
