# Multilingual Data Onboarding Agent

A Python prototype that profiles CSV files, uses an LLM to recognize business
fields across English, Indonesian, and German/SAP-style schemas, and recommends
a unified customer and order data model.

## Why this project exists

New customer data rarely arrives with consistent field names or formats. One
system may use `cust_id`, another `id_pelanggan`, and another `Kundennummer` for
the same customer-ID concept. Repeating field discovery, mapping, and schema
design manually makes onboarding slow and error-prone.

This project separates deterministic work from semantic judgment:

```text
CSV files
   ↓
Python CSV profiler
   ↓
Compact profile JSON
   ↓
LLM FieldAnalyzer
   ↓
Validated semantic analysis
   ↓
Deterministic SchemaRecommender
   ↓
Unified customer and order schemas
```

The full CSV is processed locally. Only the compact profile is sent to the LLM.

## Measured example results

| Evaluation | Result |
|---|---:|
| Customer A English fields | 12/12 |
| Customer B/C multilingual fields | 24/24 |
| B/C confidence checks | 24/24 |
| B/C evidence checks | 24/24 |
| Unified-schema validation | 12/12 |

These scores describe the small controlled example dataset in this repository.
They do not guarantee 100% accuracy on unseen production data.

## Features

- Profiles row counts, duplicate rows, inferred types, sample values, null rates,
  unique counts, top values, and useful field patterns.
- Returns structured, Pydantic-validated FieldAnalyzer JSON.
- Uses field names, sample values, and profile statistics as evidence.
- Handles English abbreviations and Indonesian and German/SAP-style fields.
- Measures results against explicit expected meanings.
- Creates separate `unified_customers` and `unified_orders` schemas.
- Records type, nullability, description, source coverage, and rationale for
  every unified field.
- Defines versioned data contracts for future mapping, ETL configuration, and
  data-dictionary modules.
- Includes an offline demonstration that reads saved results without API calls.

## Repository structure

```text
data/examples/week1/   Fictional public CSV examples
docs/                  Module contracts and change log
examples/results/      Curated, reproducible example outputs
outputs/               Local runtime outputs, ignored by Git
scripts/               Command-line entry points and evaluations
src/                   Reusable profiling, analysis, and schema code
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Add your API key to `.env`:

```text
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4.1-mini
```

Never commit `.env`.

## Run the CSV profiler

```bash
python scripts/profile_csv.py data/examples/week1/customer_a_customers.csv \
  --output outputs/customer_a_customers_profile.json
```

Run the deterministic profiler checks:

```bash
python scripts/test_csv_profiler.py
```

## Run the measured FieldAnalyzer evaluations

These commands use the OpenAI API:

```bash
python scripts/evaluate_customer_a.py
python scripts/evaluate_multilingual.py
```

The analyzer sends compact profiles containing fictional sample values. Review
your own data-governance rules before using real customer data.

## Generate and validate the unified schema

```bash
python scripts/recommend_schema.py
```

The SchemaRecommender is deterministic Python and does not call an LLM.

## Run the offline demonstration

After generating results—or after copying the curated example results to
`outputs/`—run:

```bash
python scripts/demo_week2.py
```

## Data-model decisions

- Customers and orders remain separate because the relationship is one-to-many.
- Names remain in `full_name`; automatic cultural name splitting is avoided.
- Original amounts and currencies are retained.
- `amount_usd` is a nullable calculated field.
- Raw order status is preserved beside a controlled status enum.
- `source_system` is required for provenance and ID collision safety.
- The resolved order `unified_customer_id` is nullable until matching succeeds.

## Privacy

All committed CSV records are fictional public examples created for this
portfolio repository. The original private source files, API keys, local
outputs, virtual environment, and submission archives are excluded.

## Roadmap

- Source-to-target MappingGenerator
- Mapping validation and review workflow
- ETLConfigGenerator
- DataDictionaryGenerator
- Larger multilingual evaluation sets
- Optional embedding-based candidate matching
