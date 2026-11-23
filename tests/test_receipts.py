"""Synthetic data only. Never copy a real receipt in here: the repo is public."""

import base64
import json
from datetime import date, timedelta

import pytest

from biedronka.receipts import build_month, decode_e_receipt, month_key, month_windows, reconcile, split_window


def b64(obj) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


def paragon(items=(1149, 498), deposit=150):
    gross = sum(items)
    return {
        "pozycja": [{"towar": {"nazwa": f"Item{i}", "brutto": b, "cena": b, "ilosc": "1", "idStPTU": "C"}}
                    for i, b in enumerate(items)],
        "podsum": {"sumaBrutto": gross},
        "opak": {"wart": deposit},
        "total": {"zaplZwrot": gross + deposit},
    }


def raw_e_receipt(par):
    return {"protoVersion": "000", "data": f"{b64({'alg': 'RS256'})}.{b64({'dokument': {'paragon': par}})}.c2ln"}


def listing(rid="1", total=17.97, dt="2025-07-10T12:00:00+02:00", e=True):
    return {"Id": rid, "DateTime": dt, "TotalValue": total, "IsElectronicPrintoutRequested": e}


def test_decode_reads_jws_payload():
    assert decode_e_receipt(raw_e_receipt(paragon()))["paragon"]["podsum"]["sumaBrutto"] == 1647


def test_reconcile_passes_when_items_deposit_and_listing_agree():
    assert reconcile(listing(total=17.97), {"paragon": paragon()}) == []


def test_reconcile_reports_each_mismatch():
    par = paragon()
    par["podsum"]["sumaBrutto"] = 1000
    found = reconcile(listing(total=99.99), {"paragon": par})
    assert any("items" in f for f in found)
    assert any("listing" in f for f in found)


def test_month_key_uses_local_time_not_utc():
    # 23:30 local on 31 July is 21:30 UTC, still July; 00:30 local on 1 Aug is 22:30 UTC on 31 July.
    assert month_key(listing(dt="2025-07-31T23:30:00+02:00")) == "2025-07"
    assert month_key(listing(dt="2025-08-01T00:30:00+02:00")) == "2025-08"


def test_month_windows_overlap_and_cover_every_day():
    wins = list(month_windows(date(2025, 1, 15), date(2025, 3, 10)))
    assert wins[0] == (date(2024, 12, 31), date(2025, 2, 1))
    assert wins[-1] == (date(2025, 2, 28), date(2025, 3, 11))
    assert len(wins) == 3


def test_split_window_covers_both_halves_and_refuses_one_day():
    (a0, a1), (b0, b1) = split_window(date(2025, 1, 1), date(2025, 1, 31))
    assert (a0, b1) == (date(2025, 1, 1), date(2025, 1, 31)) and b0 == a1 + timedelta(days=1)
    with pytest.raises(ValueError):
        split_window(date(2025, 1, 1), date(2025, 1, 1))


def test_build_month_reports_missing_and_bad_receipts(tmp_path):
    (tmp_path / "json").mkdir()
    (tmp_path / "json" / "ok.json").write_text(json.dumps(raw_e_receipt(paragon())))
    (tmp_path / "json" / "bad.json").write_text(json.dumps({"data": "not-a-jws"}))
    (tmp_path / "pdf").mkdir()
    for rid in ("paper", "fallback"):
        (tmp_path / "pdf" / f"{rid}.pdf").write_bytes(b"%PDF")
    # "fallback" is an e-receipt whose JSON the site refused, so only its PDF exists.
    rows = [listing("ok"), listing("bad"), listing("gone"), listing("fallback"),
            {**listing("paper"), "IsElectronicPrintoutRequested": False, "CustomerId": "x"}]
    doc, problems = build_month("2025-07", rows, tmp_path)
    kinds = {r["Id"]: r["kind"] for r in doc["receipts"]}
    assert doc["count"] == 5
    assert set(problems) == {"bad", "gone"}
    assert kinds == {"ok": "e-receipt", "bad": "e-receipt", "gone": "missing", "fallback": "pdf-only", "paper": "pdf-only"}
    assert all("CustomerId" not in r for r in doc["receipts"])
