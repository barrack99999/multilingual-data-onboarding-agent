# Module Contract Change Log

## Version 1.0

- Initial MVP contracts agreed during Week 2, Task 5.
- Covered FieldAnalyzer, SchemaRecommender, MappingGenerator,
  ETLConfigGenerator, and DataDictionaryGenerator.
- Established shared JSON formatting, diagnostic objects, standard output paths,
  required fields, and LLM dependency boundaries.

Future changes must include the date, old behavior, new behavior, reason, and
whether the change is backward-compatible.

## Version 1.1 — 2026-10-09

- **Old behavior:** MappingGenerator was planned to write JSON files containing
  a `mappings` array with a small, loosely defined transformation object.
- **New behavior:** MappingGenerator writes Version 1 YAML files containing
  structured `rules`, typed transformation expressions, examples, evidence,
  confidence, status, and explicit manual-review information.
- Added `docs/week3-task1-mapping-format.md`,
  `docs/mapping-template.yaml`, and
  `schemas/mapping-format-v1.schema.json` as the mapping contract sources.
- ETLConfigGenerator and DataDictionaryGenerator now read accepted mapping YAML
  files rather than mapping JSON files.
- **Reason:** Week 3 requires a stable YAML mapping format with precisely
  defined transformations and an explicit fallback for unsupported operations.
- **Compatibility:** Breaking for the not-yet-implemented MappingGenerator
  output shape, but it does not invalidate existing Week 2 analysis or schema
  files because no Version 1 mapping outputs existed yet.

## Version 1.2 — 2026-10-09

- **Old behavior:** Mapping validation checked the rule structure and field
  references without executing transformations on source rows.
- **New behavior:** Added MappingValidator with report version 1.0, helper
  functions, per-rule and per-row execution outcomes, example checks, partial
  transformed rows, readiness information, and shared diagnostic sidecars.
- Marked MappingGenerator's existing implementation as implemented.
- Original-example reports go to `outputs/mapping-validation/`; synthetic
  stress-test reports use its `stress/` subfolder.
- Fixed currency rates are explicitly fictional test fixtures. Previews do
  not approve manual-review rules or substitute for dated production rates.
- **Reason:** Week 3 Task 3 must expose problems visible only when rules are
  executed, including missing translations, invalid dates/defaults, and unsafe
  name splitting.
- **Compatibility:** Additive. Existing analysis, schema, and Version 1 mapping
  YAML files remain unchanged. Rule execution may expose new warnings or
  failures without changing their stored mapping definitions.

## Version 1.3 — 2026-10-09

- **Old behavior:** Copy rules preserved nullable missing-value markers as
  strings, causing decimal validation failures on synthetic data.
- **New behavior:** Shared runtime missing-value policy 1.1 normalizes known
  markers according to target nullability, with warnings; `status_raw` is
  preserved. Required IDs still fail. Missing conversion amounts yield null
  rather than zero.
- Updated B/C status maps for casing variation and A/C date rules for the
  synthetic generator's documented formats. Recorded reviewed manual changes
  and prompt feedback in `docs/prompt-log.md`.
- Added before/after comparison reports and the reproduction script
  `scripts/report_mapping_validation.py`.
- **Reason:** Address measured runtime failures and retain explicit review
  flags for unsupported transformations and missing business policies.
- **Compatibility:** YAML structure stays at mapping version 1.0. There is a
  deliberate behavior change for nullable missing-marker values; consumers
  must apply the shared missing-value policy before checking target values.
  Baseline reports retain their historical contract version.

## Version 1.4 — 2026-10-09

- Implemented `src/etl_config_generator.py` and its CLI, producing JSON drafts
  without LLM or database dependencies.
- **Old behavior:** The planned ETL config was one file per source table with
  table-level fields at the top level.
- **New behavior:** ETL config version 2.0 is one file per customer, containing
  customer and order jobs. The agreed table-level fields remain within `jobs`.
- Added source-system and primary-validation inputs, with optional synthetic
  evidence. Mapping validation reports now include input fingerprints. Old or
  stale reports must be regenerated before creating an ETL config.
- Failed and unreviewed rules are retained as disabled `manual_review` entries
  with their proposed transformations and supporting validation evidence.
- Loading is disabled; write/duplicate handling, unresolved IDs and lookups,
  decimal commas, phone normalization, and real rates remain review decisions.
- **Reason:** Week 3 Task 5 requires one configuration per customer and must
  distinguish validated sample rules from executable production plans.
- **Compatibility:** Packaging changes are breaking for consumers expecting
  top-level per-table fields; read `jobs` instead. Schema version 1.1 and mapping
  version 1.0 remain unchanged. Report fingerprints are additive, but are
  mandatory for the new ETL generator. Historical validation results remain
  preserved as evidence, not used as current ETL inputs.

## Version 1.5 — 2026-10-16

- Implemented `src/data_dictionary_generator.py`, its CLI, and offline tests.
- **Old behavior:** The planned dictionary renderer read the schema and accepted
  mappings, producing JSON and Markdown with basic field documentation.
- **New behavior:** It also requires field-analysis JSON and documents all
  supplied mapping drafts, including manual-review rules and explicitly
  unmapped nullable targets. Source interpretations and evidence stay separate
  from schema-owned business definitions and mapping-owned transformations.
- Added table name, source fields/coverage, example values, and comments to
  each dictionary field; added summary, draft status, warnings, input hashes,
  and limitations to the dictionary document (dictionary version 1.0).
- **Reason:** Week 4 Task 1 requires a reviewable dictionary consistent with all
  three inputs, without hiding unresolved mappings or implying tested outputs.
- **Compatibility:** The existing planned JSON keys and output filenames are
  preserved; additional output fields are additive. The new required analysis
  input changes the planned call signature. No earlier dictionary implementation
  or generated dictionary existed. Schema, mapping, ETL and validation formats
  are unchanged; their existing diagnostics retain their historical versions.

## Version 1.6 — 2026-10-16

- Implemented the Python OnboardingAgent controller and root command-line
  entry point. Added run-log version 1.0 and an artifact export manifest.
- **Old behavior:** Modules were run independently with separate commands.
- **New behavior:** The controller executes them in order, preserving
  intermediate artifacts and logging per-stage outcomes, errors and warnings.
  It defaults to reviewed-schema reuse; schema generation is explicitly selected.
- Explicit analysis/mapping reuse is recorded rather than represented as live
  LLM generation. Runtime validation is always rerun. Output directories must
  be empty, and CSV changes between stages are rejected.
- SourceCoverage accepts arbitrary source labels. SchemaRecommender accepts
  optional `source_system` (or source metadata on analyses), and coverage checks
  accept expected sources. Missing concept coverage is advisory in generation;
  structural/modeling policy failures still stop it. The A/B/C legacy call and
  validator default remain available.
- **Reason:** The final workflow must handle a single customer or new customer
  without inventing A/B/C source coverage or redesigning the shared schema on
  every run. Review-required validation findings must not hide successful work.
- **Compatibility:** Existing module output formats remain unchanged. New
  controller artifacts and optional source arguments are additive. Coverage
  failures no longer prevent drafting a schema; warnings must be reviewed.

## Version 1.7 — 2026-10-16

- **Old behavior:** The default reviewed-schema input lived only in ignored
  `outputs/unified-schema.json`, so a new clone could not run the normal CLI.
- **New behavior:** The same reviewed schema is included at
  `schemas/unified-schema.json`; the controller and core module CLIs default
  to that location. Per-run copies and explicit `--schema` paths still work.
  SchemaRecommender's newly generated draft output path is unchanged.
- Added portable reviewed mapping fixtures and Customer A analysis under
  `examples/` for no-API verification. Offline tests create temporary synthetic
  CSVs instead of depending on ignored local output/data folders.
- **Reason:** A new developer must be able to clone, install the documented
  dependencies, and run a customer without earlier local artifacts.
- **Compatibility:** CLI default input path changes. Existing explicit paths,
  schema contents/version, mapping format, run-log format, ETL and dictionary
  output formats are unchanged. Historical evidence is preserved.
