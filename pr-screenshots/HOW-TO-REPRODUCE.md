# Reproducing the screenshots

## The short version

Two commands from the repo root:

    git checkout screenshot-integration
    ./pr-screenshots/capture.sh

Images land in `pr-screenshots/`. Re-running overwrites them. Takes about a
minute.

## What each part does

**`git checkout screenshot-integration`** — no single pull request branch
contains every change, so screenshots taken from one would miss the others. This
branch merges all nine and exists only for this purpose. The running stack serves
whatever is checked out, which is why this step comes first. Never push it as a
pull request.

**`./pr-screenshots/capture.sh`** — runs four steps and stops with a clear message
if any fails:

1. Checks the stack is actually up, so a failure reads as "the stack is down"
   rather than a confusing browser timeout.
2. Mints a token for the test account `obeytheproletariat@gmail.com` directly
   from the backend container. Nothing is copied out of a browser by hand and no
   session has to be alive first.
3. Runs `seed.py`, which creates the sales pipeline and the three sequences the
   screens need. It checks before creating, so running it repeatedly is safe and
   will not pile up duplicates.
4. Runs `capture.mjs`, which drives a headless browser at 1600x1000 in dark mode
   and saves one image per claim.

## Prerequisites

The stack must be running and the frontend dependencies installed — the capture
borrows Playwright from `frontend/node_modules`. Nothing else.

## If a shot fails

Each is independent, so one failure does not stop the rest; the script prints
`ok` or `FAIL` per image. A failure is almost always a control that moved or a
page that needed longer to settle. Open `capture.mjs`, find the entry, and adjust
its wait or its selector. The known outstanding one is the run-history panel,
whose control resists automated selection.

## Adding a shot

Add an entry to the `SHOTS` array in `capture.mjs`. Each takes a filename, a
path, an optional settle time, and an optional list of interactions. Follow an
existing entry — the test-run one is the most involved and shows how to click,
choose from a dropdown, and wait for a result.

## Publishing them

Screenshots are served to GitHub from the `pr-assets` branch. Commit the images
there, push, and reference them as
`https://raw.githubusercontent.com/sameer261h/aexy/pr-assets/pr-screenshots/<file>.png`.
Never commit an image into one of the nine code branches.
