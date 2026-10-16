# Portable examples

These reviewed draft mappings and Customer A field analysis describe the
fictional teaching CSVs in `data/examples/week1/`. They contain no API keys,
credentials, validation logs, or machine-specific absolute paths.

- `mappings/`: six customer/order YAMLs retained as deterministic test fixtures.
- `field-analysis/customer_a.json`: structured source analysis for the offline
  Customer A walkthrough.
- The shared reviewed schema is `schemas/unified-schema.json`.

They support a clean-checkout demo and offline tests. They are not fresh LLM
results, production-ready mappings, or approval to load data. Generated IDs,
phone normalization, lookups, unapproved rates, and decimal commas retain
manual-review flags. New live runs go into ignored `outputs/`, not this folder.
