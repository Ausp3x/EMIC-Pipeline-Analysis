# Processing Pipeline Guide

This project is organized to show the complete lineage from cached official
sources to country-level analysis files:

```text
1 Source Data -> 2 Processing Scripts -> 3 Processed Data -> 4 Country Analysis -> 6 Statistical Analysis
```

All commands below assume the current directory is the `Contest Data Analysis`
project root. Scripts use `project_paths.py`, so they do not depend on the
shell's current working directory once invoked.

## Standard Build

```powershell
python "2 Processing Scripts/build_imo_name_reference.py"
python "2 Processing Scripts/extract_emic_keystage2_results.py"
python "2 Processing Scripts/extract_emic_keystage3_results.py"
python "2 Processing Scripts/combine_emic_iwymic_contestants.py" --base-only
python "2 Processing Scripts/extract_apmo_imo_results.py"
python "2 Processing Scripts/combine_emic_iwymic_contestants.py"
python "2 Processing Scripts/review_duplicate_name_candidates.py"
python "2 Processing Scripts/build_contest_data_analysis.py"
python "2 Processing Scripts/audit_emic_name_outputs.py"
python "2 Processing Scripts/analyze_performance_signal.py"
python "2 Processing Scripts/build_statistical_analysis_report.py" --compile
```

The two combined-data passes are intentional. The first creates stable IDs
using only EMIC and IWYMIC. The higher-contest extractor matches APMO and IMO
records to those fixed IDs. The second combined pass attaches the validated
higher-contest histories.

## Script Responsibilities

| Script | Role | Primary output |
|---|---|---|
| `build_imo_name_reference.py` | Caches official IMO given-name and surname fields | `1 Source Data/Name References/IMO Name Reference.csv` |
| `extract_emic_keystage2_results.py` | Extracts, cleans, ranks, and audits EMIC | `3 Processed Data/EMIC/` |
| `extract_emic_keystage3_results.py` | Extracts, cleans, ranks, and audits IWYMIC | `3 Processed Data/IWYMIC/` |
| `combine_emic_iwymic_contestants.py` | Resolves cross-stage identities and attaches higher-contest histories | `3 Processed Data/Combined/` |
| `extract_apmo_imo_results.py` | Parses and matches official APMO and IMO appearances | `3 Processed Data/Higher Contests/` |
| `review_duplicate_name_candidates.py` | Produces the reviewed near-name and homonym report | `Duplicate Name Review.csv` |
| `audit_emic_name_outputs.py` | Validates names, histories, ranks, percentiles, progression rates, and conservation | Console pass/fail report |
| `build_contest_data_analysis.py` | Generates 42 country files per analysis folder and the country progression summary | `4 Country Analysis/` and `Master.csv` |
| `analyze_performance_signal.py` | Builds fixed-window cohorts, descriptive summaries, survival estimates, and forward-year predictive comparisons | `6 Statistical Analysis/` |
| `build_statistical_analysis_report.py` | Builds the consolidated LaTeX source and compiles the full PDF report | `6 Statistical Analysis/Full Analysis Report.tex` and `.pdf` |
| `project_paths.py` | Defines every canonical project path | Imported by the other scripts |

`emic_name_review.py` contains the shared reviewed surname, name-order,
canonical spelling, and duplicate-identity rules. It is code, not generated
data. `review_cross_stage_name_candidates.py` is an auxiliary scoring tool;
final dispositions are recorded by `review_duplicate_name_candidates.py`.

## Cached and Refreshed Runs

Normal runs reuse the files in `1 Source Data`. To force fresh downloads:

```powershell
python "2 Processing Scripts/extract_emic_keystage2_results.py" --refresh
python "2 Processing Scripts/extract_emic_keystage3_results.py" --refresh
python "2 Processing Scripts/extract_apmo_imo_results.py" --refresh
```

Refreshing can change source content if an official site has changed. Review
the generated changelogs and audits before accepting a refreshed build.

## Data Lineage

1. Cached official IMC HTML is parsed into one awarded appearance per row.
2. Exact duplicate source rows are removed, names and countries are reviewed,
   and medal-bucket ranks and percentiles are assigned.
3. Stage-specific appearances are grouped into conservative unique identities.
4. EMIC and IWYMIC identities are combined using reviewed aliases, chronology,
   country agreement, and one-to-one matching safeguards.
5. Official APMO and IMO rows are matched only to the fixed combined roster.
6. The duplicate review records a completed disposition for every candidate.
7. Country analysis and progression files are projected from the combined table.
8. The full audit independently checks all source, combined, and country-summary
   reconciliations and must pass.
9. The statistical-analysis stage derives one baseline observation per fixed
   identity, applies complete follow-up windows, and writes validated tables,
   model comparisons, survival summaries, and figures.
10. The report builder reads the validated analysis outputs, writes the LaTeX
    source, and compiles the consolidated PDF without recalculating results.

## Reproducibility Rules

- Do not manually edit generated files in `3 Processed Data` or `4 Country
  Analysis`; update a source rule or script and rebuild instead.
- Preserve global combined IDs. Country exports intentionally do not renumber.
- Keep raw cache filenames and Python filenames in `snake_case`; these are
  stable machine interfaces.
- Use Proper Case with spaces for folders and human-facing data filenames.
- Consult `Migration Map.csv` when tracing a path used before the 2026-07-23
  structure migration.
- Treat generated per-stage changelogs as part of the data provenance record.

## Completion Check

A clean build ends with:

- 2,008 EMIC appearances and 1,814 EMIC unique records.
- 1,900 IWYMIC appearances and 1,646 IWYMIC unique records.
- 3,112 combined roster identities and 348 cross-stage identities.
- 634 matched APMO appearances and 742 matched IMO appearances.
- 42 country CSVs in each of the five country-analysis folders.
- A 42-row `Winner Progression by Country.csv` that reconciles to individual histories.
- A passing `audit_emic_name_outputs.py` result.
- A 3,112-row analysis cohort, 12 analysis CSVs, six nonblank figures, and a
  passing `analyze_performance_signal.py` validation report.
- An 11-page `Full Analysis Report.pdf` compiled from the retained LaTeX source.
