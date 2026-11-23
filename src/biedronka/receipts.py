"""Pure logic: date windows, e-receipt decoding, monthly files, reconciliation.

No network and no browser here, so every function is testable with plain data.
Money stays in integer grosze (1149 = 11.49 zl) exactly as the receipt carries it.
"""

import base64
import json
from datetime import date, datetime, timedelta
from pathlib import Path


def month_windows(since: date, until: date):
    """Yield (begin, end) per calendar month, widened by one day on each side.

    The overlap makes the listing safe whether the server treats end_data as
    inclusive or exclusive, and whatever timezone it filters in. Duplicates
    are removed later by receipt Id.
    """
    start = since.replace(day=1)
    while start <= until:
        nxt = (start + timedelta(days=32)).replace(day=1)
        yield start - timedelta(days=1), min(nxt, until + timedelta(days=1))
        start = nxt


def split_window(begin: date, end: date):
    """Halve a window that came back with more than one page."""
    if begin >= end:
        raise ValueError(f"cannot split a one-day window {begin}")
    mid = begin + (end - begin) / 2
    return (begin, mid), (mid + timedelta(days=1), end)


def month_key(receipt: dict) -> str:
    """'2025-07' from the listing's local DateTime.

    Never bucket by the payload's zakSprzed: it is UTC, so a receipt from
    23:30 local time on the last day of a month would land in the next month.
    """
    return datetime.fromisoformat(receipt["DateTime"]).strftime("%Y-%m")


def decode_e_receipt(raw: dict) -> dict:
    """Return the fiscal document from a downloaded e-receipt JSON.

    `data` is a JWS (header.payload.signature, base64url); the payload is the
    JPK_KASA_PARAGON document. The signature is not verified.
    """
    payload = raw["data"].split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))["dokument"]


def reconcile(listing: dict, doc: dict) -> list[str]:
    """Return every mismatch between the items, the receipt totals and the listing.

    Empty list = the receipt adds up. A mismatch is a finding, not noise.
    """
    p = doc["paragon"]
    items = sum(pos["towar"]["brutto"] for pos in p["pozycja"] if "towar" in pos)
    gross = p["podsum"]["sumaBrutto"]
    deposit = (p.get("opak") or {}).get("wart", 0)
    paid = p["total"]["zaplZwrot"]
    listed = round(listing["TotalValue"] * 100)
    problems = []
    if items != gross:
        problems.append(f"items {items} != sumaBrutto {gross}")
    if gross + deposit != paid:
        problems.append(f"sumaBrutto {gross} + deposit {deposit} != paid {paid}")
    if paid != listed:
        problems.append(f"paid {paid} != listing TotalValue {listed}")
    return problems


LISTING_FIELDS = ("Id", "Number", "DateTime", "TotalValue", "Discount", "Store", "Address")


def build_month(month: str, listings: list[dict], raw_dir: Path) -> tuple[dict, dict]:
    """Build one monthly file from the listing rows and the raw downloads.

    Returns (month_doc, problems_by_id). CustomerId is dropped on purpose.
    """
    receipts, problems = [], {}
    for row in sorted(listings, key=lambda r: r["DateTime"]):
        rid = row["Id"]
        rec = {k: row.get(k) for k in LISTING_FIELDS}
        rec["receipt"] = None
        jpath, ppath = raw_dir / "json" / f"{rid}.json", raw_dir / "pdf" / f"{rid}.pdf"
        if jpath.exists():
            rec["kind"], rec["source"] = "e-receipt", f"raw/json/{rid}.json"
            try:
                doc = decode_e_receipt(json.loads(jpath.read_text()))
                rec["receipt"] = doc["paragon"]
                if found := reconcile(row, doc):
                    problems[rid] = found
            except (KeyError, IndexError, ValueError) as e:
                problems[rid] = [f"cannot parse: {e!r}"]
        elif ppath.exists():
            # ponytail: scanned PDF, no text layer; items need OCR (tracked as a ticket)
            rec["kind"], rec["source"] = "pdf-only", f"raw/pdf/{rid}.pdf"
        else:
            rec["kind"], rec["source"] = "missing", None
            problems[rid] = ["no raw file downloaded"]
        receipts.append(rec)
    return {"month": month, "count": len(receipts), "receipts": receipts}, problems
