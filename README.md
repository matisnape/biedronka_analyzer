# biedronka_analyzer

Track how the prices of the products you buy at Biedronka change over time.

## TL;DR

- One command downloads every receipt from your Moja Biedronka account into `data/`.
- `data/` never leaves your machine. It is in `.gitignore`, and this repo is public.
- Today the project only collects data. Analysis, charts and product categorisation come later (see the GitHub Project board).

```bash
uv sync
uv run biedronka scrape     # list, download new receipts, build monthly files
uv run biedronka build      # rebuild monthly files from data/raw/ (no network)
uv run pytest               # unit tests, synthetic data only
```

## Glossary

| Term | Meaning |
|---|---|
| **Moja Biedronka** | Biedronka's loyalty site, `moja.biedronka.pl`. It lists your receipts under *Paragony*. |
| **E-receipt** (*e-paragon*) | A receipt the till sent electronically. The site offers it as JSON, with every line item. |
| **PDF-only receipt** | A paper receipt. The site offers only a "transaction history" PDF, and that PDF is a scanned image with no text. |
| **JPK_KASA** | The Polish tax office's standard format for till receipts. The e-receipt JSON carries one JPK_KASA document. |
| **JWS** | JSON Web Signature: `header.payload.signature`, each part base64url-encoded. The e-receipt JSON wraps the JPK_KASA document in one. |
| **CDP** | Chrome DevTools Protocol. The script uses it to borrow the session of a Chrome you already logged in to. |
| **Grosze** | 1/100 of a złoty. All amounts inside a receipt are integer grosze: `1149` = 11.49 zł. |

## Before the first run

1. Start Chrome with remote debugging on port 9222, for example:
   `open -na "Google Chrome" --args --remote-debugging-port=9222 --user-data-dir="$HOME/.chrome-debug"`
2. In that Chrome, log in to <https://moja.biedronka.pl>.
3. Run `uv run biedronka scrape`.

The script reuses the browser's cookies. It never asks for, sees, or stores your password.

## What a run does

1. **List.** It asks `POST /panel/ajax/paragons` for one calendar month at a time, each window widened by one day. A window that answers with more than one page is split in half until it fits on one page, because paging a long range returned duplicated and missing rows.
2. **Download.** For each receipt not yet on disk:
   - an e-receipt → `GET /panel/download/json/<Id>`;
   - a paper receipt → `GET /panel/download/<Id>` (PDF);
   - an e-receipt whose JSON the site refuses (`Błąd pobrania pliku`) → the PDF as well.
3. **Build.** It writes one file per month from the raw downloads.
4. **Check.** For every e-receipt it asserts that the items add up to the receipt's gross total, that gross plus bottle deposit equals the amount paid, and that the amount paid equals the total on the listing. A mismatch prints `PROBLEM <Id>` and the exit code becomes 1.

Runs are incremental. A second run downloads only new receipts and never deletes a local file. The site's history starts in November 2024 and may drop old receipts later, so the local archive can become the only copy.

## Data layout

```
data/
  raw/                         # source of truth, as downloaded
    list/2025-07.json          # listing rows for the month, keyed by Id; rows are only ever added
    json/<Id>.json             # e-receipt (JWS-wrapped JPK_KASA document)
    pdf/<Id>.pdf               # transaction-history PDF (scanned image)
  receipts/                    # derived; `biedronka build` recreates it at any time
    2025/2025-07.json
```

A monthly file looks like this (values shortened):

```json
{
  "month": "2025-07",
  "count": 11,
  "receipts": [
    {
      "Id": "2507...", "DateTime": "2025-07-03T18:00:00+02:00",
      "TotalValue": 4.99, "Discount": 0.0, "Store": "1234",
      "kind": "e-receipt",
      "source": "raw/json/2507....json",
      "receipt": { "pozycja": [ { "towar": { "nazwa": "Mleko 1l           C", "ilosc": "1", "cena": 499, "brutto": 499 } } ], "podsum": { "sumaBrutto": 499 } }
    },
    { "Id": "2507...", "kind": "pdf-only", "source": "raw/pdf/2507....pdf", "receipt": null }
  ]
}
```

- A receipt goes into the month of its **local** time from the listing. The JPK field `zakSprzed` is UTC and would move late-evening receipts into the wrong month.
- `receipt` is the JPK `paragon` block, unchanged. Field names are Polish: `pozycja` = line, `towar` = product, `nazwa` = name, `ilosc` = quantity, `cena` = unit price, `brutto` = line total, `rabat` = discount, `opak` = bottle deposit.
- Values are kept as the till wrote them, on purpose. `ilosc` is a string with a decimal comma (`"0,660"`), `nazwa` is padded and ends with the VAT letter, and `cena` is the price **before** a discount while `brutto` is after it. Cleaning this up is a separate ticket.
- `CustomerId` is dropped from the monthly files.

## Project layout

| Path | What it is |
|---|---|
| `src/biedronka/receipts.py` | Pure logic: date windows, JWS decoding, month bucketing, reconciliation. No network. |
| `src/biedronka/cli.py` | The `biedronka` command: browser session, listing, downloads, build. |
| `tests/test_receipts.py` | Unit tests on synthetic receipts. Never add a real receipt here. |
| `AGENTS.md` | Rules for coding agents working in this repo. |

## Work tracking

Tasks live on the GitHub Project linked from this repository. Each issue is a user story with Given/When/Then acceptance criteria.
