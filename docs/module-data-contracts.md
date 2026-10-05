# Module Data Contracts — MVP Version 1.0

## Why these contracts exist

A data contract is an agreement about what one module receives and what it
must return. Defining these agreements now prevents Week 4 from becoming a
collection of scripts with incompatible filenames or JSON shapes.

The machine-readable version is `docs/module-data-contracts.json`. That file is
the detailed source of truth; this note is the easier human explanation.

## Shared rules

- CSV and JSON files use UTF-8.
- Source field names remain unchanged; unified target names use `snake_case`.
- JSON written to disk must be valid, parseable JSON.
- Fatal errors do not overwrite a previous good output and cause a non-zero
  command-line exit.
- Warnings allow output generation but must be recorded for review.
- Diagnostics use a sidecar named `<output>.diagnostics.json` with:
  `contract_version`, `module`, `status`, `errors`, and `warnings`.
- Every error records `code`, `message`, `location`, and `retryable`.
- Every warning records `code`, `message`, `location`, and
  `suggested_action`.

## Module summary

| Module | Main input | Main output | LLM dependency |
|---|---|---|---|
| FieldAnalyzer | CSV profile | Field-analysis JSON | Yes, for semantic judgment |
| SchemaRecommender | Analyses from A–C | Unified-schema JSON | No; deterministic Python |
| MappingGenerator | One analysis + unified schema | Source-to-target mapping JSON | Yes for draft; code validates |
| ETLConfigGenerator | Accepted mapping + schema | ETL configuration JSON | No |
| DataDictionaryGenerator | Schema + accepted mappings | JSON and Markdown dictionary | No |

## 1. FieldAnalyzer

**Input paths**

- CSV: `data/examples/week1/<source>_<table>.csv`
- Profile: `outputs/<csv-stem>_profile.json`

The profile requires file and row information plus a `fields` array. Each
profiled field requires its name, inferred type, samples, null count/rate,
unique count, top values, and pattern flags.

**Output path:** `outputs/<csv-stem>-analysis.json`

Required output fields are `file_name`, `table_type`, `table_confidence`, and
`fields`. Every analyzed field requires `field_name`, `semantic_type`,
`description`, `confidence`, and `evidence`.

The LLM performs semantic judgment. Ordinary Python validates the profile,
enforces structured output, verifies every field appears exactly once, and
preserves source order. Typical warnings are low confidence and an `unknown`
semantic type.

## 2. SchemaRecommender

**Input paths**

- `outputs/customer-a-field-analysis.json`
- `outputs/multilingual-field-analysis.json`

**Output paths**

- Schema: `outputs/unified-schema.json`
- Validation: `outputs/unified-schema-validation.json`

The schema requires `schema_version`, `modeling_decisions`, and `tables`.
Every table requires its name, grain, primary key, and fields. Every schema
field requires type, nullable setting, description, source coverage, and
rationale.

This module does not require an LLM. Its policies are explicit Python so the
same accepted analyses always produce the same schema.

## 3. MappingGenerator

**Inputs**

- One `outputs/<csv-stem>-analysis.json`
- `outputs/unified-schema.json`

**Output path:** `outputs/mappings/<source>-<table>-mapping.json`

The output requires mapping version, source system/file, table type, target
table, mappings, unmapped source fields, and unmapped target fields. Every
mapping requires source field, target field, transformation, confidence,
evidence, and status (`accepted`, `needs_review`, or `rejected`).

The LLM drafts mappings because this requires judgment. Plain code must reject
unknown fields, duplicate target mappings, invalid transformations, and missing
required targets. Low-confidence or ambiguous mappings become warnings rather
than being silently accepted.

## 4. ETLConfigGenerator

**Inputs**

- `outputs/mappings/<source>-<table>-mapping.json`
- `outputs/unified-schema.json`

**Output path:**
`outputs/etl-configs/<source>-<table>-etl-config.json`

The config requires version, source system/file, target table, read options,
field mappings, validation rules, and reject policy. Each field mapping requires
source field, target field, and transformation.

No LLM is required. Accepted mappings and schema types already contain the
needed facts. Plain code validates types and prevents unreviewed mappings from
entering an ETL config.

## 5. DataDictionaryGenerator

**Inputs**

- `outputs/unified-schema.json`
- All accepted `outputs/mappings/*-mapping.json` files

**Outputs**

- `outputs/data-dictionary.json`
- `outputs/data-dictionary.md`

Every dictionary field requires name, type, nullable setting, description,
source lineage, and transformation notes. The Markdown version must explain
both unified tables, source lineage, and known limitations.

No LLM is required because descriptions, rationales, and lineage are already
structured. Code should render them consistently and warn when lineage is
partial.

## Contract changes

Later tasks may refine these contracts. Any change must update the contract
version and be recorded in `docs/module-contract-change-log.md`. Adding an
optional field is normally compatible; renaming or removing a required field
is a breaking change.
