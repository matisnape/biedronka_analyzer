"""Scrape Moja Biedronka receipts through an already logged-in Chrome.

Chrome must run with remote debugging (port 9222) and have a tab logged in
to https://moja.biedronka.pl. The script reuses that session's cookies, so it
never sees or stores your password.

Data layout (all under data/, which git ignores):
  raw/list/YYYY-MM.json     listing rows for the month, merged by Id, never shrunk
  raw/json/<Id>.json        e-receipt as downloaded (signed JPK document)
  raw/pdf/<Id>.pdf          paper receipt: transaction-history PDF (scanned image)
  receipts/YYYY/YYYY-MM.json  derived monthly file, rebuilt from raw/ by `build`
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

from biedronka.receipts import build_month, month_key, month_windows, split_window

BASE = "https://moja.biedronka.pl"
LIST_URL = f"{BASE}/panel/ajax/paragons"


class SessionError(RuntimeError):
    """The site answered with something other than the expected file type."""


def find_page(browser):
    for ctx in browser.contexts:
        for page in ctx.pages:
            if page.url.startswith(BASE):
                return page
    page = browser.contexts[0].new_page()
    page.goto(f"{BASE}/panel/paragons")
    return page


def expect(resp, content_type: str, what: str):
    ct = resp.headers.get("content-type", "")
    if not resp.ok or content_type not in ct:
        raise SessionError(
            f"{what}: HTTP {resp.status}, content-type {ct!r}. "
            "Log in to moja.biedronka.pl in the debug Chrome and run again."
        )
    return resp


def list_window(page, begin: date, end: date) -> list[dict]:
    """List receipts in one window; split it until each answer is one page.

    Multi-page answers are never paged through: paging the full range
    returned duplicated and missing rows.
    """
    resp = page.request.post(LIST_URL, form={
        "page": "0", "begin_data": begin.isoformat(), "end_data": end.isoformat(),
        "order": "asc", "short": "0",
    })
    body = expect(resp, "json", f"listing {begin}..{end}").json()
    if (body.get("NumberOfPages") or 0) > 1:
        a, b = split_window(begin, end)
        return list_window(page, *a) + list_window(page, *b)
    return body["Receipts"] or []


def save_listing(data: Path, rows: list[dict]) -> dict[str, dict]:
    """Merge rows into raw/list/YYYY-MM.json by Id. Rows are never removed,
    because the site may drop old receipts and the local copy is then the only one."""
    by_month = defaultdict(dict)
    for r in rows:
        by_month[month_key(r)][r["Id"]] = r
    for month, fresh in by_month.items():
        path = data / "raw" / "list" / f"{month}.json"
        old = json.loads(path.read_text()) if path.exists() else {}
        old.update(fresh)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(old, ensure_ascii=False, indent=1, sort_keys=True))
    return {r["Id"]: r for r in rows}


# The site's answer when one file is unavailable (as opposed to a lost session).
FILE_ERROR = "Błąd pobrania pliku".encode()


def download(page, data: Path, rows: dict[str, dict], delay: float) -> int:
    """Fetch each receipt not yet on disk: the e-receipt JSON when there is one,
    otherwise the transaction-history PDF. Some e-receipts answer the JSON
    request with FILE_ERROR; those fall back to the PDF too."""
    fetched = 0
    for rid, row in sorted(rows.items(), key=lambda kv: kv[1]["DateTime"]):
        jpath, ppath = data / "raw" / "json" / f"{rid}.json", data / "raw" / "pdf" / f"{rid}.pdf"
        if jpath.exists() or ppath.exists():
            continue
        path, kind = ppath, "pdf"
        if row["IsElectronicPrintoutRequested"]:
            resp = page.request.get(f"{BASE}/panel/download/json/{rid}")
            if FILE_ERROR in resp.body():
                kind = "pdf (JSON unavailable)"
            else:
                path, kind, body = jpath, "json", expect(resp, "json", f"receipt {rid}").body()
        if path is ppath:
            body = expect(page.request.get(f"{BASE}/panel/download/{rid}"), "pdf", f"receipt {rid}").body()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        fetched += 1
        print(f"  {row['DateTime'][:10]} {rid} {kind}")
        time.sleep(delay)
    return fetched


def build(data: Path) -> int:
    """Rebuild every monthly file from raw/. Returns the number of problem receipts."""
    total, problems = 0, {}
    for path in sorted((data / "raw" / "list").glob("*.json")):
        month = path.stem
        doc, found = build_month(month, list(json.loads(path.read_text()).values()), data / "raw")
        out = data / "receipts" / month[:4] / f"{month}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
        total += doc["count"]
        problems.update(found)
    e = sum(1 for _ in (data / "raw" / "json").glob("*.json"))
    pdf = sum(1 for _ in (data / "raw" / "pdf").glob("*.pdf"))
    print(f"built: {total} receipts ({e} e-receipts, {pdf} PDF-only)")
    for rid, msgs in sorted(problems.items()):
        print(f"  PROBLEM {rid}: {'; '.join(msgs)}")
    return len(problems)


def scrape(args) -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(args.cdp)
        page = find_page(browser)
        rows = []
        for begin, end in month_windows(args.since, args.until):
            rows += list_window(page, begin, end)
        unique = save_listing(args.data, rows)
        print(f"listed: {len(unique)} receipts from {args.since} to {args.until}")
        print(f"downloaded: {download(page, args.data, unique, args.delay)} new files")
    return build(args.data)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="biedronka", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=Path("data"), help="data directory (default: data)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scrape", help="list, download new receipts, then build")
    s.add_argument("--since", type=date.fromisoformat, default=date(2024, 1, 1),
                   help="first day to list (default 2024-01-01; the site returns nothing older)")
    s.add_argument("--until", type=date.fromisoformat, default=date.today())
    s.add_argument("--cdp", default="http://localhost:9222", help="Chrome remote-debugging URL")
    s.add_argument("--delay", type=float, default=0.5, help="seconds between downloads")
    sub.add_parser("build", help="rebuild monthly files from raw/ without network")
    args = ap.parse_args(argv)
    try:
        problems = scrape(args) if args.cmd == "scrape" else build(args.data)
    except SessionError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
