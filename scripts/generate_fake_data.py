"""Generate deliberately messy CSV data for Customers A, B, and C."""

from __future__ import annotations

import argparse
import csv
import random
from collections import Counter
from datetime import date, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "generated"


A_NAMES = [
    "Alex Johnson", "Taylor Smith", "Jordan Lee", "Morgan Brown",
    "Casey Davis", "Riley Wilson", "Avery Clark", "Jamie Martin",
]
B_NAMES = [
    "Budi Santoso", "Siti Rahma", "Andi Wijaya", "Dewi Lestari",
    "Rizky Pratama", "Putri Ayu", "Agus Setiawan", "Nadia Safitri",
]
C_NAMES = [
    "Anna Müller", "Lukas Schmidt", "Sophie Weber", "Jonas Fischer",
    "Mia Wagner", "Leon Becker", "Emma Hoffmann", "Paul Schäfer",
]


def add_duplicates(rows: list[dict[str, str]], total_rows: int) -> list[dict[str, str]]:
    """Append five exact copies so duplicate-row checks always have examples."""
    duplicate_sources = [5, 12, 19, 26, 33]
    for index in duplicate_sources:
        if len(rows) >= total_rows:
            break
        rows.append(rows[index].copy())
    return rows


def dirty_date(value: date, customer: str, index: int) -> str:
    """Return valid, inconsistent, missing, and invalid date strings."""
    case = index % 12
    if case == 0:
        return ""
    if case == 1:
        return "N/A"
    if case == 2:
        return "null"
    if case == 3:
        return "invalid_date"
    if case == 4:
        return {"A": "02/30/2024", "B": "31-02-2024", "C": "31.02.2024"}[customer]

    if customer == "A":
        formats = ["%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"]
    elif customer == "B":
        formats = ["%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"]
    else:
        formats = ["%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"]
    return value.strftime(formats[index % len(formats)])


def dirty_phone(customer: str, index: int) -> str:
    """Return multiple phone formats plus missing-value markers."""
    case = index % 9
    if case == 0:
        return ""
    if case == 1:
        return "N/A"
    if case == 2:
        return "null"

    number = 1000000 + index * 137
    if customer == "A":
        area = 200 + index % 700
        return [
            f"({area}) 555-{number % 10000:04d}",
            f"{area}-555-{number % 10000:04d}",
            f"+1 {area} 555 {number % 10000:04d}",
        ][case % 3]
    if customer == "B":
        return [
            f"0812-{number % 10000:04d}-{(number + 31) % 10000:04d}",
            f"+62 812 {number % 10000:04d} {(number + 31) % 10000:04d}",
            f"62812{number % 100000000:08d}",
        ][case % 3]
    return [
        f"030 {number % 10000000:07d}",
        f"+49 30 {number % 10000000:07d}",
        f"0049-30-{number % 10000000:07d}",
    ][case % 3]


def dirty_email(name: str, index: int, domain: str) -> str:
    if index % 17 == 0:
        return ""
    if index % 19 == 0:
        return "N/A"
    if index % 23 == 0:
        return "null"
    simple_name = (
        name.lower()
        .replace(" ", ".")
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    return f"{simple_name}{index + 1}@{domain}"


def customer_a_rows(count: int, rng: random.Random) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    tiers = ["Gold", "gold", "GOLD", "Silver", "silver", "Bronze", "BRONZE"]
    for i in range(count - 5):
        name = rng.choice(A_NAMES)
        rows.append({
            "cust_id": f"C{1001 + i}",
            "full_name": name,
            "email_addr": dirty_email(name, i, "example.com"),
            "phone": dirty_phone("A", i),
            "signup_dt": dirty_date(date(2023, 1, 5) + timedelta(days=i * 9), "A", i),
            "loyalty_tier": tiers[i % len(tiers)],
        })
    return add_duplicates(rows, count)


def customer_b_rows(count: int, rng: random.Random) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    segments = ["Premium", "premium", "PREMIUM", "Regular", "regular", "REGULAR"]
    for i in range(count - 5):
        name = rng.choice(B_NAMES)
        rows.append({
            "id_pelanggan": f"P{2001 + i}",
            "nama_lengkap": name,
            "email": dirty_email(name, i, "contoh.id"),
            "no_hp": dirty_phone("B", i),
            "tgl_daftar": dirty_date(date(2023, 2, 10) + timedelta(days=i * 8), "B", i),
            "segmen": segments[i % len(segments)],
        })
    return add_duplicates(rows, count)


def customer_c_rows(count: int, rng: random.Random) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    groups = ["A", "a", "B", "b", "C", "c"]
    for i in range(count - 5):
        name = rng.choice(C_NAMES)
        rows.append({
            "Kundennummer": f"K{3001 + i}",
            "Name1": name,
            "EMail": dirty_email(name, i, "beispiel.de"),
            "Telefon": dirty_phone("C", i),
            "Erfassungsdatum": dirty_date(date(2023, 3, 15) + timedelta(days=i * 7), "C", i),
            "Kundengruppe": groups[i % len(groups)],
        })
    return add_duplicates(rows, count)


def dirty_customer_reference(prefix: str, first_number: int, customer_count: int, index: int) -> str:
    if index % 29 == 0:
        return ""
    if index % 31 == 0:
        return "null"
    if index % 37 == 0:
        return f"{prefix}9999"  # Orphan reference on purpose.
    return f"{prefix}{first_number + index % customer_count}"


def dirty_amount(customer: str, index: int, rng: random.Random) -> str:
    if index % 21 == 0:
        return ""
    if index % 22 == 0:
        return "N/A"
    if index % 23 == 0:
        return "null"
    value = rng.uniform(12, 850) if customer != "B" else rng.randint(50_000, 5_000_000)
    if customer == "B":
        return str(int(value))
    if customer == "C":
        return f"{value:.2f}".replace(".", ",")
    return f"{value:.2f}"


def order_rows(customer: str, count: int, rng: random.Random) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    settings = {
        "A": {
            "headers": ("order_no", "cust_id", "order_dt", "total_amt", "currency", "status"),
            "order_prefix": "O", "customer_prefix": "C", "first_customer": 1001,
            "first_order": 5001, "currency": "USD",
            "statuses": ["paid", "Paid", "PAID", "shipped", "SHIPPED", "cancelled", "CANCELLED", "pending"],
        },
        "B": {
            "headers": ("no_pesanan", "id_pelanggan", "tgl_pesanan", "total_harga", "mata_uang", "status_pesanan"),
            "order_prefix": "PS", "customer_prefix": "P", "first_customer": 2001,
            "first_order": 6001, "currency": "IDR",
            "statuses": ["dibayar", "Dibayar", "DIBAYAR", "dikirim", "DIKIRIM", "dibatalkan", "DIBATALKAN", "menunggu"],
        },
        "C": {
            "headers": ("Bestellnummer", "Kundennummer", "Bestelldatum", "Betrag", "Währung", "StatusCode"),
            "order_prefix": "B", "customer_prefix": "K", "first_customer": 3001,
            "first_order": 7001, "currency": "EUR",
            "statuses": ["BEZ", "bez", "Bez", "VERS", "vers", "STOR", "stor", "OFF"],
        },
    }[customer]

    order_field, customer_field, date_field, amount_field, currency_field, status_field = settings["headers"]
    for i in range(count - 5):
        rows.append({
            order_field: f"{settings['order_prefix']}{settings['first_order'] + i}",
            customer_field: dirty_customer_reference(
                settings["customer_prefix"], settings["first_customer"], count - 5, i
            ),
            date_field: dirty_date(date(2024, 1, 3) + timedelta(days=i * 4), customer, i + 5),
            amount_field: dirty_amount(customer, i, rng),
            currency_field: settings["currency"],
            status_field: settings["statuses"][i % len(settings["statuses"])],
        })
    return add_duplicates(rows, count)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def data_design_note(row_count: int) -> str:
    return f"""# Task 6 – Synthetic Data Design Note

The generator creates {row_count} rows in each CSV. The files copy the field styles of the three example customers, but the people, orders, and values are synthetic.

## Customer A – U.S. e-commerce

| File | Source field | Expected business meaning |
|---|---|---|
| customers | `cust_id` | Unique customer identifier |
| customers | `full_name` | Customer's full name |
| customers | `email_addr` | Email address |
| customers | `phone` | Phone number |
| customers | `signup_dt` | Customer registration date |
| customers | `loyalty_tier` | Loyalty level: Gold, Silver, or Bronze |
| orders | `order_no` | Unique order identifier |
| orders | `cust_id` | Customer identifier linking the order to a customer |
| orders | `order_dt` | Order date |
| orders | `total_amt` | Total order amount |
| orders | `currency` | Currency code, normally USD |
| orders | `status` | Order status |

## Customer B – Southeast Asia / Indonesia

| File | Source field | Expected business meaning |
|---|---|---|
| customers | `id_pelanggan` | Customer identifier (`pelanggan` = customer) |
| customers | `nama_lengkap` | Full name |
| customers | `email` | Email address |
| customers | `no_hp` | Mobile phone number |
| customers | `tgl_daftar` | Registration date (`tgl` = date) |
| customers | `segmen` | Customer segment |
| orders | `no_pesanan` | Order identifier |
| orders | `id_pelanggan` | Customer identifier linking the order to a customer |
| orders | `tgl_pesanan` | Order date |
| orders | `total_harga` | Total price |
| orders | `mata_uang` | Currency code, normally IDR |
| orders | `status_pesanan` | Order status |

## Customer C – Europe / Germany / SAP style

| File | Source field | Expected business meaning |
|---|---|---|
| customers | `Kundennummer` | Customer number |
| customers | `Name1` | Customer name |
| customers | `EMail` | Email address |
| customers | `Telefon` | Phone number |
| customers | `Erfassungsdatum` | Record creation or registration date |
| customers | `Kundengruppe` | Customer group |
| orders | `Bestellnummer` | Order number |
| orders | `Kundennummer` | Customer number linking the order to a customer |
| orders | `Bestelldatum` | Order date |
| orders | `Betrag` | Order amount; comma decimal format may appear |
| orders | `Währung` | Currency code, normally EUR |
| orders | `StatusCode` | SAP-style order status code |

## Deliberate data-quality problems

- Five exact duplicate rows in every CSV.
- Blank values plus the text markers `N/A` and `null`.
- Several valid date formats, impossible dates, and `invalid_date`.
- Local, international, compact, and missing phone numbers.
- Status and category values with inconsistent uppercase/lowercase.
- Some orders with missing, null, or unknown customer references.
- Some missing or non-numeric order amounts.

This note is the answer key: despite different languages and names, the three datasets describe the same main concepts—customer ID, name, contact details, registration date, order ID, order date, amount, currency, and status.
"""


def validate_file(path: Path, expected_rows: int) -> dict[str, int]:
    with path.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    if len(rows) != expected_rows:
        raise ValueError(f"{path.name}: expected {expected_rows} rows, found {len(rows)}")

    row_signatures = [tuple(row.items()) for row in rows]
    duplicate_count = sum(count - 1 for count in Counter(row_signatures).values() if count > 1)
    values = [value for row in rows for value in row.values()]
    summary = {
        "rows": len(rows),
        "duplicates": duplicate_count,
        "blank_values": sum(value == "" for value in values),
        "sentinel_values": sum(value.lower() in {"n/a", "null"} for value in values),
        "invalid_dates": sum(
            value == "invalid_date" or value in {"02/30/2024", "31-02-2024", "31.02.2024"}
            for value in values
        ),
    }
    if min(summary["duplicates"], summary["blank_values"], summary["sentinel_values"], summary["invalid_dates"]) < 1:
        raise ValueError(f"{path.name}: a required data-quality issue is missing: {summary}")
    return summary


def generate(output_dir: Path, row_count: int, seed: int) -> None:
    if not 50 <= row_count <= 100:
        raise ValueError("--rows must be between 50 and 100")

    output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    datasets = {
        "customer_a_customers.csv": customer_a_rows(row_count, rng),
        "customer_a_orders.csv": order_rows("A", row_count, rng),
        "customer_b_customers.csv": customer_b_rows(row_count, rng),
        "customer_b_orders.csv": order_rows("B", row_count, rng),
        "customer_c_customers.csv": customer_c_rows(row_count, rng),
        "customer_c_orders.csv": order_rows("C", row_count, rng),
    }

    for filename, rows in datasets.items():
        write_csv(output_dir / filename, rows)
    (output_dir / "data_design_note.md").write_text(data_design_note(row_count), encoding="utf-8")

    print(f"Generated synthetic data in {output_dir}")
    for filename in datasets:
        summary = validate_file(output_dir / filename, row_count)
        print(
            f"- {filename}: {summary['rows']} rows, {summary['duplicates']} duplicates, "
            f"{summary['blank_values']} blanks, {summary['sentinel_values']} N/A/null values, "
            f"{summary['invalid_dates']} invalid dates"
        )
    print("- data_design_note.md: field meanings and expected concepts")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=75, help="Rows per CSV (50-100; default: 75)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    generate(args.output_dir, args.rows, args.seed)


if __name__ == "__main__":
    main()
