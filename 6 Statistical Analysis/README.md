# Statistical Analysis

This folder tests whether performance at a contestant's first observed EMIC or
IWYMIC award appearance predicts later APMO or IMO success. It is an
association and prediction study, not a causal estimate of contest impact.

## Rebuild

Install the packages listed in `requirements.txt`, then run from the project
root:

```powershell
python "2 Processing Scripts/analyze_performance_signal.py"
python "2 Processing Scripts/build_statistical_analysis_report.py" --compile
```

The script reads `Master.csv` and `4 Country Analysis/Winner Progression by
Country.csv`. It recreates every generated CSV, figure, the report, and the
analysis changelog in this folder. The report builder then assembles the
validated outputs into a retained LaTeX source and compiled PDF.

## Primary Design

- One row per reviewed contestant identity.
- Baseline is the earliest EMIC or IWYMIC award appearance.
- The primary outcome window is five strictly later calendar years.
- APMO five-year cohorts begin with 2015 baselines because complete results
  begin in 2016.
- Award includes Honourable Mention; medal means Gold, Silver, or Bronze.
- Recent cohorts without complete follow-up are excluded from fixed-window
  models and retained with right-censoring in the time-to-event analysis.
- Higher-contest observations run through 2026. The official APMO 2026
  score-level report is complete but remains marked preliminary by its source.

## Main Outputs

- `Analysis Cohort.csv`: one modeling row per master identity.
- `Analysis Report.md`: design, results, interpretation, and limitations.
- `Full Analysis Report.tex` and `Full Analysis Report.pdf`: consolidated
  publication-ready report containing all six analyses and figures.
- `Descriptive Progression Summary.csv`: unrestricted observed progression by
  baseline-performance band.
- `Performance Band Summary.csv` and `Adjusted Signal Curves.csv`: raw and
  adjusted five-year signal-curve data.
- `Outcome Transition Summary.csv`: baseline award tier to later result class.
- `Survival Summary.csv`: right-censored time-to-first-award estimates.
- `Country Progression Intervals.csv`: five-year rates with Wilson intervals.
- `Model Predictions.csv`, `Model Results.csv`, `Model Comparison.csv`, and
  `Calibration Summary.csv`: forward-year predictive validation outputs.
- `Figures/`: six publication-ready PNG visualizations.
- `Analysis Changelog.txt`: source hashes, methodology, validation, and output
  hashes for the latest build.

Generated files should not be edited manually. Update the analysis script and
rebuild so the report, tables, figures, and checks remain synchronized. Update
the report builder when the consolidated report structure or prose changes.
