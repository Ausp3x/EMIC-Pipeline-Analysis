# EMIC Contestant Analysis

This workspace extracts EMIC/IWYMIC contestant rows from the official IMC
pages on chiuchang.org for 2013-2023, skipping 2020, then adds medal buckets,
rank-average, and percentile estimates. It also matches complete official APMO
and IMO results to that fixed contestant roster without importing
higher-contest-only names.

## Run

Run these commands from the `Contest Data Analysis` project root:

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

`build_imo_name_reference.py` refreshes the local copy of the IMO site's
separate given-name and surname fields. The extraction scripts can use the
existing `1 Source Data/Name References/IMO Name Reference.csv` without
refreshing it.

The first successful extraction caches official source files under
`1 Source Data/`. Use this when you want to force a fresh download:

```powershell
python "2 Processing Scripts/extract_emic_keystage2_results.py" --refresh
python "2 Processing Scripts/extract_emic_keystage3_results.py" --refresh
python "2 Processing Scripts/extract_apmo_imo_results.py" --refresh
```

The extraction and export scripts use only the Python standard library. The
statistical-analysis stage uses the pinned packages listed in
`6 Statistical Analysis/requirements.txt`.

## Project Structure

- `1 Source Data/`: cached official files and the IMO name reference.
- `2 Processing Scripts/`: extraction, cleaning, matching, validation, and
  export code. Python filenames retain `snake_case` for dependable imports.
- `3 Processed Data/`: EMIC, IWYMIC, combined, APMO, and IMO intermediate and
  final datasets with their generated audits and changelogs.
- `4 Country Analysis/`: five country-output folders, each containing one CSV
  for all 42 roster countries.
- `5 Documentation/`: the pipeline guide, data dictionary, and complete
  old-to-new migration map.
- `6 Statistical Analysis/`: reproducible person-level cohorts, descriptive
  tables, forward-year predictive models, Markdown and LaTeX reports, a compiled
  PDF, and six figures.
- `Master.csv`: an exact copy of the reviewed combined roster.
- `Changelog.txt`: project-level export and migration history.

## Outputs

`3 Processed Data/EMIC/` contains `EMIC Awarded Appearances.csv`, `EMIC Unique
Contestants.csv`, medal summaries and buckets, the participant audit, and the
generated EMIC changelog. `3 Processed Data/IWYMIC/` contains the corresponding
six IWYMIC files.

`3 Processed Data/Combined/EMIC and IWYMIC Unique Contestants.csv` is the
conservative 3,112-person identity table. It stores separate EMIC, IWYMIC,
APMO, and IMO history blocks while never importing higher-contest-only names.
The same folder contains `Duplicate Name Review.csv` and `Combined
Changelog.txt`.

`3 Processed Data/Higher Contests/` contains the APMO and IMO matched
appearance files, source audit, fuzzy match review, and generated changelog.

`4 Country Analysis/1 Master/` contains all roster identities by country.
`2 EMIC/`, `3 IWYMIC/`, `4 APMO/`, and `5 IMO/` contain the contest-specific
country subsets. Country files use readable names such as `EMIC - South
Africa.csv`; header-only files preserve the full 42-country structure when a
country has no matched contestant.

`4 Country Analysis/Winner Progression by Country.csv` summarizes, for every
country, the percentage of unique EMIC/IWYMIC award recipients who later
received an APMO or IMO award. It reports both any official award (including
Honourable Mention) and medal-only results (Gold, Silver, or Bronze), with the
underlying counts beside every percentage. "Later" means a strictly later
calendar year than the contestant's earliest EMIC/IWYMIC award year.

`6 Statistical Analysis/Analysis Report.md` and `Full Analysis Report.pdf`
evaluate whether baseline EMIC/IWYMIC performance predicts later APMO/IMO
awards and medals. The PDF is generated from `Full Analysis Report.tex` and
combines the methods, findings, tables, and all six figures. The primary
comparisons use complete five-year follow-up windows, forward-baseline-year
validation, country-aware baseline models, and country-cluster bootstrap
intervals. The survival summaries retain newer cohorts by right-censoring them
at the end of 2026. The official APMO 2026 score-level report is complete but
remains marked preliminary by its source.

## Extraction Logic

The official site treats EMIC as Keystage II and IWYMIC as Keystage III. The
Keystage II script keeps only Keystage II individual-result tables; the
Keystage III script keeps only Keystage III individual-result tables.

The result-page formats vary by year:

- Newer pages usually have `ID`, `Country`, `TeamName`, `Name`, `Medal`.
- Older pages may have `Country`, `TeamName`, `Name`, `Prize`.
- Some older pages have `ID`, `TeamName`, `Name`, `Prize`; in those cases the
  country is inferred by stripping the final team letter from the team name.
- The 2016 table has a blank medal header; the script treats the last column as
  the medal column when the other required columns are present.

Cleaning is intentionally conservative, with an extra reviewed pass for names
in both keystage outputs:

- Names are Unicode-normalized and whitespace-normalized.
- `name_clean` is canonicalized to first-name-last-name order for reviewed
  comma/order variants, and `name_last_first` stores the companion
  last-name-first display form.
- Mainland Chinese and Korean rows are normalized from family-name-first source
  order. Mainland Chinese given-name syllables are compacted (`Zhou Si Qi` ->
  `Siqi Zhou`), and Korean non-hyphenated given-name syllables are compacted
  the same way (`Kang Seung Ho` -> `Seungho Kang`).
- Japanese rows in the reviewed 2013-2015 source are given-name-first. Taiwan,
  Hong Kong, and Macau retain their delegation-specific comma/year conventions.
- Hong Kong and Macau names are not globally compacted because those official
  rows mix Cantonese spacing and English given names.
- Exact-token IMO references, explicit source commas, repeated cross-year
  identities, and reviewed country/year conventions establish surname
  boundaries. Every processed East Asian appearance is checked against the
  applicable source convention by `audit_emic_name_outputs.py`.
- `name_last_first` is a normalized sorting field. For naming systems without a
  Western hereditary surname, such as Mongolian patronymic names and the
  documented Indonesian mononym, it preserves the best source-established
  family-like component rather than inventing a legal surname.
- Title artifacts such as `Master`, `Miss`, `Mr`, and the observed typo `Maser`
  are stripped; alternate spellings are kept in `name_variants`.
- Matching keys are lowercase, accent-insensitive, and punctuation-insensitive.
- Countries are mostly preserved from the official page, with obvious aliases
  expanded, such as `USA` to `United States of America`.
- Country display names are normalized to the IMO country list, e.g. `China`
  becomes `People's Republic of China`, `Iran` becomes `Islamic Republic of
  Iran`, and `Korea` becomes `Republic of Korea`.
- International-team contestant countries are resolved from official team/ID
  clues where available and recorded in each keystage changelog.
- Display names and countries that appear in all caps on the official page are
  converted to proper case in the processed `*_clean` and variant columns.

## Combined Identity Logic

The combined builder starts from the two reviewed unique-contestant files. A
cross-stage merge requires the same normalized IMO country, a shared canonical
name or recorded variant, a mutual one-to-one match, and no overlapping contest
year. Token-order matching is available only as a secondary unique match; the
current build required no token-only merges.

Near-name matching is deliberately a review tool, not an automatic merge rule:

```powershell
python "2 Processing Scripts/review_cross_stage_name_candidates.py"
```

High-confidence spelling changes are added to the reviewed alias tables and
logged. Same-year homonyms, one-to-many candidates, and names with substantive
given-name, patronymic, or surname differences remain separate.

`audit_emic_name_outputs.py` checks name casing, `name_clean` versus
`name_last_first` components, source-convention surname placement, exact-token
IMO comparisons, history alignment, sequential IDs, and appearance-count
conservation across both stage files, both higher-contest support files, and
the combined file. It also independently recomputes every higher-contest
average rank and percentile from the supporting rank spans.

## Higher-Contest Logic

`extract_apmo_imo_results.py` parses complete official APMO score reports for
2016-2026 and official IMO individual results for 2013-2026. The APMO 2026
report is included with its official preliminary status retained. APMO 2013-2015
are not used because the public archive does not provide complete
contestant-level score tables for those editions, so global ranks and
percentiles cannot be reconstructed reliably.

The matcher searches only the fixed combined EMIC/IWYMIC roster. It accepts
same-country exact canonical/variant matches, unique token-order or
spacing-only matches, explicitly reviewed aliases, and stable IMO contestant
IDs after one identity has been established. Similar-looking fuzzy candidates
are written to the review CSV and do not merge automatically.

For APMO and IMO, ties are grouped globally by total score. The support files
retain `rank_start` and `rank_end`; the main CSV stores the requested
`rank_averages_by_year` and `percentiles_by_year`. A value of `None` in a
higher-contest medal history means the contestant appeared but received no
official award.

The two-pass combined build is intentional: `--base-only` first regenerates
the roster and stable IDs from EMIC/IWYMIC, the higher-contest extractor then
matches against that roster, and the final combined build attaches the
validated histories.

## Ranking Logic

For Keystage II, medal buckets are configured from the confirmed bucket-size
table. The script checks that each medal's bucket sizes sum to the number of
official rows parsed for that year and medal. One correction is applied to the
screenshot data: 2022 Silver is `[14, 12, 21]`, not `[14, 12, 20]`, because the
official table contains 47 Silver rows.

For Keystage III, no external bucket table was provided, so buckets are inferred
from official result order: within each medal, a new bucket begins when the
official displayed country ordering resets.

Ranks are assigned bucket by bucket in official result order:

- `rank_start` is the first position in the tied bucket.
- `rank_end` is the last position in the tied bucket.
- `rank_average = (rank_start + rank_end) / 2`.
- `percentile = 1 - rank_average / total_participants`.

For Keystage II, the total participant denominators are the researched totals:

```text
2013 294, 2014 323, 2015 308, 2016 262, 2017 299,
2018 314, 2019 255, 2021 312, 2022 288, 2023 308
```

## Audit Notes

The official result pages list awarded contestants, not every non-awarded
contestant. Therefore the total participant denominators are retained as the
externally researched totals; they cannot be independently derived from the
result tables alone.

For Keystage III, separate total participant denominators were not provided, so
the script estimates `total_participants` as `round_half_up(1.5 * total_awarded)`
from the project assumption that about two-thirds of contestants are awarded.

For 2015, the official HTML repeats five identical Merit rows. The processed
CSVs remove those exact duplicate source rows, which makes the 2015 summary
match the screenshot.
