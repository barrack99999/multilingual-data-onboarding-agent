"""Small checks for the Week 2 CSV profiler."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.csv_profiler import profile_csv  # noqa: E402


def field(profile: dict, name: str) -> dict:
    return next(item for item in profile["fields"] if item["field_name"] == name)


def main() -> None:
    examples = PROJECT_ROOT / "data" / "examples" / "week1"

    a_customers = profile_csv(examples / "customer_a_customers.csv")
    assert a_customers["row_count"] == 4
    assert a_customers["duplicate_row_count"] == 0
    assert field(a_customers, "email_addr")["patterns"]["looks_like_email"]
    assert field(a_customers, "signup_dt")["patterns"]["looks_like_date"]

    a_orders = profile_csv(examples / "customer_a_orders.csv")
    assert field(a_orders, "total_amt")["inferred_type"] == "number"
    assert field(a_orders, "total_amt")["patterns"]["looks_like_amount"]
    assert field(a_orders, "status")["patterns"]["looks_like_status"]

    b_customers = profile_csv(examples / "customer_b_customers.csv")
    assert field(b_customers, "tgl_daftar")["patterns"]["looks_like_date"]

    c_orders = profile_csv(examples / "customer_c_orders.csv")
    assert field(c_orders, "Betrag")["inferred_type"] == "number"
    assert field(c_orders, "Bestelldatum")["patterns"]["looks_like_date"]

    print("CSV profiler tests: PASS")


if __name__ == "__main__":
    main()
