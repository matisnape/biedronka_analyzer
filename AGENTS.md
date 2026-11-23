# Agent guide: biedronka_analyzer

## TL;DR

- Python 3.11+, managed with `uv`. Run everything through `uv run`.
- The gate is `uv run pytest`. It must pass before every commit.
- **The repo is public. Receipt data is personal.** Nothing from `data/`, no real receipt, no store number tied to a date, no `CustomerId` and no `IDZ` value may land in a commit, an issue, a test fixture or a log you paste.
- Tasks live on the GitHub Project (see `.agents/stack.json`). One issue, one branch, one pull request.
- Anna is learning on this project. Explain the *why* of a choice in the PR description in plain language, and keep the code boring and readable over clever.

## Project overview

The `biedronka` command scrapes receipts from `moja.biedronka.pl` through a logged-in Chrome (CDP, port 9222) into `data/`, then builds one JSON file per month. The README explains the data layout and every term; read it first.

| Module | Rule |
|---|---|
| `src/biedronka/receipts.py` | Pure functions only. No network, no browser, no `print`. Everything here gets a unit test. |
| `src/biedronka/cli.py` | All I/O: Playwright, HTTP, files, output. Keep logic out of it; move logic into `receipts.py` and test it there. |

## Commands

```bash
uv sync                      # install
uv run pytest                # the gate
uv run biedronka build       # rebuild data/receipts/ from data/raw/, offline
uv run biedronka scrape      # needs the debug Chrome logged in; touches the live site
```

Run `scrape` only when the task needs live data. It is incremental and polite (a delay between downloads), but it is still traffic on someone else's site.

## Data rules

- `data/raw/` is the source of truth and may be the only copy (the site drops old receipts). Never delete or rewrite a raw file. Code that changes raw files needs Anna's explicit go.
- `data/receipts/` is derived. Change the builder and rerun `build`; never hand-edit the output.
- Money is integer grosze everywhere. Never convert to float for arithmetic.
- Bucket by the listing's local `DateTime`, never by the JPK `zakSprzed` (UTC).
- Tests use synthetic receipts built in the test file. Never copy a real receipt into `tests/`.

## Verification

- A claim that something works needs the check that could fail. For a parser or a reconciliation change, break the input on purpose once and show the test or `build` reporting it.
- `build` exits 1 and prints `PROBLEM <Id>` on any receipt that does not add up. Treat a new `PROBLEM` line as a finding to explain, not noise to filter.

## Git

- English for commits, issues, PR descriptions, code comments and docs.
- Short commit messages: one subject plus at most four body lines.
- Never use `--no-verify`.

## Tasks

Each GitHub issue is a user story in the style of `obsidian-calendaric`:

- **Story**: "As …, I want …, so that …".
- **Acceptance criteria** with ids `AC-<issue>.<n>`, each Given / When / Then. At least one covers a failure path.
- **Priority** (`must` / `should` / `could`), **Depends on**, **Open questions**.

Name the criterion id in the title of the test that settles it, for example `test_ac_4_2_reports_unreadable_pdf`.
