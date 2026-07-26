# Data Dictionary

## Identity Fields

| Field | Meaning |
|---|---|
| `id` | Stable global row ID in the combined EMIC/IWYMIC roster. Country files preserve this ID. |
| `name_clean` | Reviewed canonical display name in given-name-first order. |
| `name_last_first` | Reviewed sortable display name in `Surname, Given names` form. |
| `name_first_last` | Requested country-export header populated from source `name_last_first`; it therefore also contains `Surname, Given names`. |
| `name_key` | Lowercase, accent-insensitive, punctuation-insensitive identity key. |
| `name_variants` | Semicolon-separated source or reviewed alternate spellings, excluding the canonical name. |
| `country_clean` | Country normalized to the IMO country-list naming convention. |
| `country_key` | Normalized country matching key. |

## Contest History Fields

Each combined contest block uses one of the prefixes `emic`, `iwymic`, `apmo`,
or `imo`.

| Field pattern | Meaning |
|---|---|
| `<contest>_appearance_count` | Number of matched appearances. |
| `<contest>_years` | Semicolon-separated, ascending contest years. |
| `<contest>_medals_by_year` | Entries such as `2022:Silver`, separated by semicolons. |
| `<contest>_rank_averages_by_year` | Average tied rank for each year. |
| `<contest>_percentiles_by_year` | `1 - rank_average / total_participants` for each year. |

Country master files rename `appearance_count` to `<CONTEST>_freq`. Individual
contest country files use the unprefixed fields `freq`, `years`,
`medals_by_year`, `rank_averages_by_year`, and `percentiles_by_year`.

An empty contest-history field means the roster identity has no reviewed
appearance in that dataset. `None` as a higher-contest medal value means the
contestant appeared but did not receive an official award.

## Appearance and Ranking Fields

| Field | Meaning |
|---|---|
| `contestant_id` | Official result-page contestant ID when available. |
| `year` | Contest year. The study covers 2013-2023 and omits postponed 2020 EMIC/IWYMIC. |
| `medal` | Normalized official award: Gold, Silver, Bronze, Merit, Honourable Mention, or None as applicable. |
| `medal_bucket_size` | Number of contestants sharing the inferred or confirmed tied award bucket. |
| `rank_start` | First global position in the tie span. |
| `rank_end` | Last global position in the tie span. |
| `rank_average` | `(rank_start + rank_end) / 2`. |
| `percentile` | `1 - rank_average / total_participants`. |
| `total_participants` | Denominator used for the percentile calculation. |
| `source_url` | Official page supporting the appearance. |

## Principal Datasets

### EMIC and IWYMIC Awarded Appearances

One row per awarded result after exact duplicate source rows are removed. These
files retain raw names, cleaned names, official IDs, medal buckets, rank spans,
percentiles, and source URLs.

### EMIC and IWYMIC Unique Contestants

One row per conservative stage identity. Appearance years and metrics are
stored in semicolon-separated history fields. Same-year same-name official-ID
homonyms and implausible same-stage age spans remain separate.

### EMIC and IWYMIC Unique Contestants (Combined)

The 3,112-row fixed identity universe used by the analysis. Every row has an
EMIC or IWYMIC history. APMO and IMO matches may enrich these rows but cannot
create new identities.

### Duplicate Name Review

All remaining broad near-name candidates, their similarity evidence, and a
completed review disposition. A retained homonym is not an unreviewed duplicate.

### APMO and IMO Matched Appearances

One official higher-contest appearance per row, linked by `combined_id` to the
fixed combined roster. The files preserve official names, IDs, scores, ranks,
matching method, and source URLs.

### Country Analysis

Exactly 42 CSVs exist in each folder. `1 Master` includes every roster identity
for the country. The four contest folders include only identities with at least
one appearance in that contest; a header-only file preserves the country when
there are no matched appearances.

### Winner Progression by Country

One row per roster country. The denominator
`emic_iwymic_unique_award_recipients` counts unique reviewed identities with
at least one EMIC or IWYMIC award result; this is every identity in the fixed
combined roster for that country.

`later_apmo_award_recipients` and `later_imo_award_recipients` count unique
people with a Gold, Silver, Bronze, or Honourable Mention result in a strictly
later calendar year than their earliest EMIC/IWYMIC award year. The medalist
columns apply the narrower Gold/Silver/Bronze definition. A person is counted
at most once in each numerator even after multiple later awards.

The four percent columns are numeric values on a 0-100 scale:
`100 * later unique recipients / EMIC-IWYMIC unique award recipients`.
Same-year and earlier higher-contest records are excluded. Current higher-
contest coverage ends in 2026, so percentages are descriptive and
right-censored for recent EMIC/IWYMIC cohorts. The official APMO 2026
score-level source remains preliminary.

## Participant Denominators

EMIC uses the researched participant totals recorded in the EMIC participant
audit. IWYMIC uses `round_half_up(1.5 * awarded_count)` because separate total
participant counts were unavailable. APMO and IMO use complete official
contestant-level result tables for the covered years.

## Statistical Analysis Fields

`6 Statistical Analysis/Analysis Cohort.csv` contains one row for each of the
3,112 fixed identities in `Master.csv`. It is a derived analysis table and does
not alter identity matching or import APMO/IMO-only contestants.

| Field or pattern | Meaning |
|---|---|
| `baseline_stage` | EMIC or IWYMIC contest supplying the earliest observed baseline award. EMIC breaks a same-year tie. |
| `baseline_year` | Earliest EMIC/IWYMIC award year for the identity. |
| `baseline_medal` | Award in that baseline appearance. |
| `baseline_rank_average` | Rank-average estimated for the baseline medal bucket. |
| `baseline_percentile` | Baseline percentile estimated from the contest participant denominator. |
| `baseline_performance_band` | Fixed percentile band: Below 25%, 25-50%, 50-75%, or 75-100%. |
| `available_follow_up_years` | Years from the baseline through the data endpoint, 2026. |
| `<contest>_later_participated` | Whether a strictly later APMO/IMO appearance is observed through 2026. |
| `<contest>_later_award` | Whether a strictly later Gold, Silver, Bronze, or Honourable Mention is observed. |
| `<contest>_later_medal` | Whether a strictly later Gold, Silver, or Bronze is observed. |
| `<contest>_<window>y_eligible` | Whether complete 3-year or 5-year follow-up is observable from the contest's coverage start through 2026. |
| `<contest>_<window>y_participated` | Participation during the complete follow-up window; missing when ineligible. |
| `<contest>_<window>y_award` | Any award during the complete follow-up window; missing when ineligible. |
| `<contest>_<window>y_medal` | Gold, Silver, or Bronze during the complete follow-up window; missing when ineligible. |
| `<contest>_<window>y_best_result` | Best result during the complete follow-up window; missing when ineligible. |

The primary predictive comparison uses the complete five-year window. Its
baseline model contains country, baseline stage, and baseline year. The
performance model adds baseline percentile, a squared percentile term, and a
percentile-by-stage interaction. Predictions are made only for a baseline year
after fitting on earlier baseline years, preventing future-cohort leakage.
Uncertainty for model improvement is estimated by resampling whole countries.

`No appearance` and `No award` are explicit outcome categories. A contestant
who did not reach APMO/IMO is never assigned a zero percentile. The cumulative
incidence summaries instead right-censor follow-up at the end of 2026.
