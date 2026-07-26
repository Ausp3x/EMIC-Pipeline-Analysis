#!/usr/bin/env python3
"""Build and optionally compile the complete statistical analysis report."""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import subprocess
from datetime import date
from pathlib import Path

from project_paths import (
    HIGHER_AUDIT_PATH,
    MASTER_COPY_PATH,
    PROJECT_ROOT,
    STATISTICAL_ANALYSIS_DIR,
)


ANALYSIS_DIR = STATISTICAL_ANALYSIS_DIR
FIGURES_DIR = ANALYSIS_DIR / "Figures"
TEX_PATH = ANALYSIS_DIR / "Full Analysis Report.tex"
PDF_PATH = ANALYSIS_DIR / "Full Analysis Report.pdf"
CHANGELOG_PATH = ANALYSIS_DIR / "Analysis Changelog.txt"
TEMP_DIR = PROJECT_ROOT / "tmp" / "pdfs"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def number(value: str | float | int) -> float:
    return float(value)


def integer(value: str | float | int) -> int:
    return int(float(value))


def pct(value: str | float, decimals: int = 1) -> str:
    return f"{100 * number(value):.{decimals}f}\\%"


def points(value: str | float, decimals: int = 3) -> str:
    rounded = round(number(value), decimals)
    if rounded == 0:
        rounded = 0.0
    return f"{rounded:.{decimals}f}"


def latex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in value)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def table_rows(rows: list[list[str]]) -> str:
    return "\n".join(" & ".join(row) + r" \\" for row in rows)


def build_tex() -> str:
    master = read_csv(MASTER_COPY_PATH)
    higher_audit = read_csv(HIGHER_AUDIT_PATH)
    cohort = read_csv(ANALYSIS_DIR / "Analysis Cohort.csv")
    descriptive = read_csv(ANALYSIS_DIR / "Descriptive Progression Summary.csv")
    transitions = read_csv(ANALYSIS_DIR / "Outcome Transition Summary.csv")
    survival = read_csv(ANALYSIS_DIR / "Survival Summary.csv")
    countries = read_csv(ANALYSIS_DIR / "Country Progression Intervals.csv")
    model_results = read_csv(ANALYSIS_DIR / "Model Results.csv")
    comparison = read_csv(ANALYSIS_DIR / "Model Comparison.csv")

    contest_stats: dict[str, tuple[int, int]] = {}
    for prefix in ("emic", "iwymic", "apmo", "imo"):
        counts = [integer(row[f"{prefix}_appearance_count"]) for row in master]
        contest_stats[prefix] = (sum(count > 0 for count in counts), sum(counts))

    audit_2026 = {
        row["contest"]: row
        for row in higher_audit
        if integer(row["year"]) == 2026
    }
    five_year_eligible = {
        destination: sum(
            integer(row[f"{destination.lower()}_5y_eligible"]) == 1
            for row in cohort
        )
        for destination in ("APMO", "IMO")
    }

    overall = {
        row["performance_band"]: row
        for row in descriptive
        if row["baseline_stage"] == "All"
    }
    descriptive_table = table_rows(
        [
            [
                latex_escape(band),
                f"{integer(overall[band]['contestants']):,}",
                f"{number(overall[band]['later_apmo_award_percent']):.1f}\\%",
                f"{number(overall[band]['later_apmo_medal_percent']):.1f}\\%",
                f"{number(overall[band]['later_imo_award_percent']):.1f}\\%",
                f"{number(overall[band]['later_imo_medal_percent']):.1f}\\%",
            ]
            for band in ("25-50%", "50-75%", "75-100%")
        ]
    )

    transition_rates: dict[tuple[str, str, str], tuple[int, float]] = {}
    award_results = {"Honourable Mention", "Bronze", "Silver", "Gold"}
    for stage in ("EMIC", "IWYMIC"):
        for destination in ("APMO", "IMO"):
            for medal in ("Merit", "Bronze", "Silver", "Gold"):
                group = [
                    row
                    for row in transitions
                    if row["baseline_stage"] == stage
                    and row["destination"] == destination
                    and row["baseline_medal"] == medal
                ]
                transition_rates[(stage, destination, medal)] = (
                    integer(group[0]["contestants"]),
                    sum(
                        number(row["percentage"])
                        for row in group
                        if row["later_outcome"] in award_results
                    ),
                )
    transition_table = table_rows(
        [
            [
                stage,
                medal,
                f"{transition_rates[(stage, 'APMO', medal)][1]:.1f}\\%",
                f"{transition_rates[(stage, 'IMO', medal)][1]:.1f}\\%",
            ]
            for stage in ("EMIC", "IWYMIC")
            for medal in ("Merit", "Bronze", "Silver", "Gold")
        ]
    )

    survival_five = {
        (row["destination"], row["performance_band"]): row
        for row in survival
        if integer(row["year_since_baseline"]) == 5
    }
    survival_table = table_rows(
        [
            [
                destination,
                latex_escape(band),
                f"{integer(survival_five[(destination, band)]['group_contestants']):,}",
                pct(survival_five[(destination, band)]["cumulative_award_probability"]),
                pct(survival_five[(destination, band)]["lower_95"]),
                pct(survival_five[(destination, band)]["upper_95"]),
            ]
            for destination in ("APMO", "IMO")
            for band in ("25-50%", "50-75%", "75-100%")
        ]
    )

    country_rows: list[list[str]] = []
    for destination in ("APMO", "IMO"):
        eligible = [
            row
            for row in countries
            if row["destination"] == destination
            and row["outcome"] == "award"
            and integer(row["eligible_contestants"]) >= 30
        ]
        eligible.sort(key=lambda row: number(row["event_rate"]), reverse=True)
        for row in eligible[:5]:
            country_rows.append(
                [
                    destination,
                    latex_escape(row["country_clean"]),
                    f"{integer(row['eligible_contestants']):,}",
                    f"{integer(row['events']):,}",
                    pct(row["event_rate"]),
                    f"{pct(row['wilson_lower'])} to {pct(row['wilson_upper'])}",
                ]
            )
    country_table = table_rows(country_rows)

    model_table = table_rows(
        [
            [
                row["destination"],
                row["outcome"].title(),
                row["model"],
                f"{integer(row['predictions']):,}",
                f"{integer(row['events']):,}",
                points(row["average_precision"]),
                points(row["roc_auc"]),
                points(row["brier_score"]),
            ]
            for row in model_results
        ]
    )
    comparison_table = table_rows(
        [
            [
                row["destination"],
                row["outcome"].title(),
                points(row["delta_average_precision"]),
                f"{points(row['delta_average_precision_lower'])} to {points(row['delta_average_precision_upper'])}",
                points(row["delta_roc_auc"]),
                points(row["brier_improvement"]),
                f"{points(row['brier_improvement_lower'])} to {points(row['brier_improvement_upper'])}",
            ]
            for row in comparison
        ]
    )
    comparison_index = {
        (row["destination"], row["outcome"]): row for row in comparison
    }

    output_inventory = table_rows(
        [
            ["Analysis Cohort.csv", "One derived row per fixed identity"],
            ["Descriptive Progression Summary.csv", "Observed later outcomes by fixed performance band"],
            ["Performance Band Summary.csv", "Raw five-year quintile rates and Wilson intervals"],
            ["Adjusted Signal Curves.csv", "Country/year-adjusted probability curves"],
            ["Outcome Transition Summary.csv", "Baseline award tier to later result class"],
            ["Survival Summary.csv", "Right-censored cumulative award incidence"],
            ["Country Progression Intervals.csv", "Country rates and Wilson intervals"],
            ["Cohort Coverage.csv", "Baseline-year coverage and follow-up eligibility"],
            ["Model Predictions.csv", "Forward-year out-of-time probabilities"],
            ["Model Results.csv", "Predictive metrics by model and outcome"],
            ["Model Comparison.csv", "Incremental metrics with country bootstrap intervals"],
            ["Calibration Summary.csv", "Predicted and observed rates by probability bin"],
        ]
    )

    low_apmo = number(overall["25-50%"]["later_apmo_award_percent"])
    high_apmo = number(overall["75-100%"]["later_apmo_award_percent"])
    low_imo = number(overall["25-50%"]["later_imo_award_percent"])
    high_imo = number(overall["75-100%"]["later_imo_award_percent"])
    apmo_award = comparison_index[("APMO", "award")]
    imo_award = comparison_index[("IMO", "award")]
    apmo_medal = comparison_index[("APMO", "medal")]
    imo_medal = comparison_index[("IMO", "medal")]

    document = rf"""\documentclass[11pt]{{article}}
\usepackage[margin=0.72in]{{geometry}}
\usepackage[T1]{{fontenc}}
\usepackage[utf8]{{inputenc}}
\usepackage{{lmodern}}
\usepackage{{microtype}}
\usepackage{{amsmath}}
\usepackage{{graphicx}}
\usepackage{{booktabs}}
\usepackage{{tabularx}}
\usepackage{{array}}
\usepackage{{longtable}}
\usepackage{{xcolor}}
\usepackage{{hyperref}}
\usepackage{{fancyhdr}}
\usepackage{{caption}}
\usepackage{{enumitem}}
\usepackage{{float}}

\definecolor{{ReportBlue}}{{HTML}}{{356CAD}}
\definecolor{{ReportTeal}}{{HTML}}{{2F9E8F}}
\definecolor{{ReportOrange}}{{HTML}}{{D9773D}}
\definecolor{{ReportGray}}{{HTML}}{{555B63}}
\hypersetup{{colorlinks=true,linkcolor=ReportBlue,urlcolor=ReportBlue,citecolor=ReportBlue}}
\graphicspath{{{{Figures/}}}}
\setlength{{\parindent}}{{0pt}}
\setlength{{\parskip}}{{0.55em}}
\setlist[itemize]{{leftmargin=1.4em,itemsep=0.25em,topsep=0.3em}}
\captionsetup{{font=small,labelfont=bf}}
\pagestyle{{fancy}}
\fancyhf{{}}
\fancyhead[L]{{EMIC/IWYMIC Performance Signal Analysis}}
\fancyhead[R]{{Data Through 2026}}
\fancyfoot[C]{{\thepage}}
\renewcommand{{\headrulewidth}}{{0.4pt}}
\setlength{{\headheight}}{{14pt}}
\newcommand{{\keyresult}}[1]{{\par\noindent\colorbox{{ReportBlue!9}}{{\parbox{{0.96\linewidth}}{{#1}}}}\par}}
\newcolumntype{{Y}}{{>{{\raggedright\arraybackslash}}X}}

\begin{{document}}

\hypersetup{{pageanchor=false}}
\begin{{titlepage}}
\centering
\vspace*{{1.2in}}
{{\color{{ReportBlue}}\rule{{\textwidth}}{{1.5pt}}}}\\[0.55in]
{{\Huge\bfseries EMIC and IWYMIC Performance as a Signal for Later Olympiad Success\par}}
\vspace{{0.35in}}
{{\Large APMO and IMO Outcomes Through 2026\par}}
\vspace{{0.65in}}
{{\large Full Statistical Analysis Report\par}}
\vfill
\begin{{tabular}}{{rl}}
Fixed identity roster: & {len(master):,} contestants \\
EMIC/IWYMIC study years: & 2013 to 2023, excluding 2020 \\
Higher-contest endpoint: & 2026 \\
Generated: & {date.today().isoformat()} \\
\end{{tabular}}
\vfill
{{\color{{ReportBlue}}\rule{{\textwidth}}{{1.5pt}}}}
\end{{titlepage}}

\hypersetup{{pageanchor=true}}
\pagenumbering{{roman}}
\tableofcontents
\clearpage
\pagenumbering{{arabic}}

\section{{Executive Summary}}

This report asks whether stronger performance at a contestant's first observed EMIC or IWYMIC award appearance predicts later APMO or IMO success. The analysis finds a consistent predictive association among named EMIC/IWYMIC award recipients. It does not estimate a causal effect of participation.

\keyresult{{\textbf{{Main result.}} Adding baseline percentile to a country, contest-stage, and baseline-year model improves out-of-time average precision for all four outcomes. The improvement is {points(apmo_award['delta_average_precision'])} for APMO awards and {points(imo_award['delta_average_precision'])} for IMO awards. Both country-cluster bootstrap intervals remain above zero.}}

\begin{{itemize}}
\item In unrestricted follow-up through 2026, the APMO award rate rises from {low_apmo:.1f}\% in the 25-50\% baseline band to {high_apmo:.1f}\% in the 75-100\% band. The IMO rate rises from {low_imo:.1f}\% to {high_imo:.1f}\%.
\item At five years, the right-censored award incidence for the 75-100\% band is {pct(survival_five[('APMO', '75-100%')]['cumulative_award_probability'])} for APMO and {pct(survival_five[('IMO', '75-100%')]['cumulative_award_probability'])} for IMO. The corresponding 25-50\% rates are {pct(survival_five[('APMO', '25-50%')]['cumulative_award_probability'])} and {pct(survival_five[('IMO', '25-50%')]['cumulative_award_probability'])}.
\item Baseline award tier matters most clearly at IWYMIC. Within five years, {transition_rates[('IWYMIC', 'APMO', 'Gold')][1]:.1f}\% of IWYMIC Gold recipients earn an APMO award and {transition_rates[('IWYMIC', 'IMO', 'Gold')][1]:.1f}\% earn an IMO award.
\item Country remains important. Rates differ sharply across delegations, and many country intervals are wide. Performance is informative, but selection systems and training environments also shape outcomes.
\end{{itemize}}

\section{{Data Scope and 2026 Update}}

The identity universe is fixed by EMIC and IWYMIC. APMO and IMO records can enrich an existing identity but cannot add a new person. This design keeps the research question centered on former EMIC/IWYMIC contestants.

\begin{{table}}[H]
\centering
\caption{{Contest Coverage in the Fixed Roster}}
\begin{{tabular}}{{lrrl}}
\toprule
Contest & Roster Identities & Matched Appearances & Coverage \\
\midrule
EMIC & {contest_stats['emic'][0]:,} & {contest_stats['emic'][1]:,} & 2013 to 2023, excluding 2020 \\
IWYMIC & {contest_stats['iwymic'][0]:,} & {contest_stats['iwymic'][1]:,} & 2013 to 2023, excluding 2020 \\
APMO & {contest_stats['apmo'][0]:,} & {contest_stats['apmo'][1]:,} & 2016 to 2026 \\
IMO & {contest_stats['imo'][0]:,} & {contest_stats['imo'][1]:,} & 2013 to 2026 \\
\bottomrule
\end{{tabular}}
\end{{table}}

The official 2026 APMO report contains {integer(audit_2026['APMO']['parsed_participants']):,} contestants, of whom {integer(audit_2026['APMO']['matched_appearances']):,} match the fixed roster. The official 2026 IMO page contains {integer(audit_2026['IMO']['parsed_participants']):,} contestants, of whom {integer(audit_2026['IMO']['matched_appearances']):,} match the roster. All IMO official ranks reconcile with recomputed global score ties. All APMO award labels reconcile with the official cutoffs and country award limits.

\textbf{{APMO source status.}} The APMO 2026 score-level report is complete but the official site still labels it preliminary. The report is included because the user requested the current 2026 data. Its status is retained in the audit and changelog. A future refresh should be run after the official preliminary notice is removed.

\textbf{{APMO source anomaly.}} The APMO 2026 Vietnam rank-2 row displays problem scores totaling 18 and an official total of 25. The official total is retained for rank and award calculations. This is the only 2026 problem-total mismatch.

Official sources: \url{{https://www.apmo-official.org/year_report/2026}} and \url{{https://www.imo-official.org/results/individual/year/2026/}}.

\section{{Definitions and Methods}}

\subsection{{Baseline and Outcomes}}
\begin{{itemize}}
\item The unit of analysis is one reviewed contestant identity.
\item Baseline is the earliest EMIC or IWYMIC award appearance. EMIC breaks a same-year tie.
\item Baseline rank uses the average position of the full score tie. Percentile is $1 - \text{{rank average}}/\text{{participants}}$.
\item A later award is Gold, Silver, Bronze, or Honourable Mention. A later medal is Gold, Silver, or Bronze.
\item APMO and IMO outcomes must occur in a strictly later calendar year. Same-year and earlier results are excluded.
\item The primary prediction window is five calendar years. Complete-window eligibility requires all five years to be observable through 2026.
\end{{itemize}}

The complete five-year samples contain {five_year_eligible['APMO']:,} contestants for APMO and {five_year_eligible['IMO']:,} for IMO. APMO baselines before 2015 are excluded from complete-window analysis because complete contestant-level APMO data begin in 2016.

\subsection{{Analytical Components}}
\begin{{enumerate}}
\item Descriptive progression rates compare fixed baseline-percentile bands.
\item Raw quintiles and adjusted curves assess the continuous performance signal.
\item Outcome transitions connect baseline award tier to later result class.
\item Kaplan-Meier-style cumulative incidence handles right-censoring.
\item Country estimates use Wilson 95\% intervals.
\item Ridge-logistic models use forward baseline-year validation. Each test year is predicted only from earlier baseline years.
\item The baseline model uses country, stage, and baseline year. The performance model adds percentile, percentile squared, and a percentile-by-stage interaction.
\item Metric-difference intervals use 300 country-cluster bootstrap replicates with a fixed seed.
\end{{enumerate}}

\section{{Observed Progression by Baseline Performance}}

The unrestricted descriptive rates include every later record observed through 2026. They show the full observed progression but give older cohorts more follow-up time than recent cohorts.

\begin{{table}}[H]
\centering
\caption{{Unrestricted Progression Through 2026}}
\small
\begin{{tabular}}{{lrrrrr}}
\toprule
Baseline Band & Contestants & APMO Award & APMO Medal & IMO Award & IMO Medal \\
\midrule
{descriptive_table}
\bottomrule
\end{{tabular}}
\end{{table}}

The top band has about {high_apmo / low_apmo:.1f} times the APMO award rate and {high_imo / low_imo:.1f} times the IMO award rate of the 25-50\% band. These ratios are descriptive. The fixed-window models below provide the stronger predictive test.

\begin{{figure}}[H]
\centering
\includegraphics[width=\textwidth]{{01 Performance Signal Curves.png}}
\caption{{Raw five-year quintile rates and country/year-adjusted curves. Labels show quintile sample sizes.}}
\end{{figure}}

The adjusted curves rise most sharply near the upper end of the observed percentile range. IWYMIC performance has the steepest relationship with both APMO and IMO outcomes. The uncertainty bands widen near the extremes because fewer observations support those curve regions.

\section{{Baseline Award Tier and Later Result Class}}

Baseline medal tiers provide an ordinal sensitivity check that does not depend on the precision of the total-participant denominator. Higher baseline tiers generally lead to higher five-year award rates.

\begin{{table}}[H]
\centering
\caption{{Five-Year Higher-Contest Award Rate by Baseline Tier}}
\begin{{tabular}}{{llrr}}
\toprule
Stage & Baseline Tier & APMO Award & IMO Award \\
\midrule
{transition_table}
\bottomrule
\end{{tabular}}
\end{{table}}

\begin{{figure}}[H]
\centering
\includegraphics[width=\textwidth]{{02 Outcome Transitions.png}}
\caption{{Distribution of later outcomes within five years, grouped by first observed stage and award tier.}}
\end{{figure}}

The largest separation appears among IWYMIC recipients. IWYMIC Gold recipients have five-year award rates of {transition_rates[('IWYMIC', 'APMO', 'Gold')][1]:.1f}\% for APMO and {transition_rates[('IWYMIC', 'IMO', 'Gold')][1]:.1f}\% for IMO, compared with {transition_rates[('IWYMIC', 'APMO', 'Merit')][1]:.1f}\% and {transition_rates[('IWYMIC', 'IMO', 'Merit')][1]:.1f}\% for IWYMIC Merit recipients.

\section{{Timing of Later Awards}}

The time-to-event analysis retains incomplete recent cohorts by censoring each person at the end of 2026. It estimates the cumulative probability of receiving a later award among contestants whose outcome window begins within source coverage.

\begin{{table}}[H]
\centering
\caption{{Five-Year Cumulative Award Incidence}}
\small
\begin{{tabular}}{{llrrrr}}
\toprule
Destination & Baseline Band & Group & Estimate & Lower 95\% & Upper 95\% \\
\midrule
{survival_table}
\bottomrule
\end{{tabular}}
\end{{table}}

\begin{{figure}}[H]
\centering
\includegraphics[width=\textwidth]{{03 Cumulative Award Incidence.png}}
\caption{{Cumulative probability of a first later award with right-censoring at 2026.}}
\end{{figure}}

Most separation develops within the first five to seven years after baseline. The curves then flatten because few new awards occur at longer lags and fewer contestants remain under observation.

\section{{Country Context}}

Country rates reflect both contestant performance and delegation systems. They should not be read as isolated measures of national program quality. Small samples can produce high point estimates with wide intervals.

\begin{{table}}[H]
\centering
\caption{{Highest Five-Year Award Rates Among Countries With at Least 30 Eligible Contestants}}
\small
\begin{{tabular}}{{llrrrr}}
\toprule
Destination & Country & Eligible & Awards & Rate & Wilson 95\% Interval \\
\midrule
{country_table}
\bottomrule
\end{{tabular}}
\end{{table}}

\begin{{figure}}[H]
\centering
\includegraphics[width=0.88\textwidth]{{04 Country Progression Rates.png}}
\caption{{Five-year country award rates. The figure shows countries with at least 10 eligible contestants; the table above applies a stricter threshold of 30.}}
\end{{figure}}

The large country differences justify including country in the baseline model. They also show why raw cross-country comparisons can be misleading without denominator and uncertainty information.

\section{{Out-of-Time Predictive Models}}

Forward validation tests whether the model works on later cohorts. APMO predictions cover baseline years 2018, 2019, and 2021. IMO predictions cover 2016, 2017, 2018, 2019, and 2021. No model is trained on its test year or any later year.

\begin{{table}}[H]
\centering
\caption{{Out-of-Time Predictive Performance}}
\scriptsize
\begin{{tabular}}{{lllrrrrr}}
\toprule
Destination & Outcome & Model & Predictions & Events & Avg. Precision & ROC AUC & Brier \\
\midrule
{model_table}
\bottomrule
\end{{tabular}}
\end{{table}}

\begin{{table}}[H]
\centering
\caption{{Incremental Value of Adding Baseline Performance}}
\scriptsize
\begin{{tabular}}{{llrrrrr}}
\toprule
Destination & Outcome & $\Delta$ Avg. Precision & 95\% Interval & $\Delta$ ROC AUC & Brier Improvement & 95\% Interval \\
\midrule
{comparison_table}
\bottomrule
\end{{tabular}}
\end{{table}}

Average precision improves by {points(apmo_award['delta_average_precision'])} for APMO awards, {points(apmo_medal['delta_average_precision'])} for APMO medals, {points(imo_award['delta_average_precision'])} for IMO awards, and {points(imo_medal['delta_average_precision'])} for IMO medals. Every average-precision interval is above zero. Brier scores improve at the point estimate for all outcomes, although the IMO medal interval slightly crosses zero.

\begin{{figure}}[H]
\centering
\includegraphics[width=\textwidth]{{05 Model Comparison and Calibration.png}}
\caption{{Metric improvement and calibration for forward-year predictions. Positive improvement favors the performance model.}}
\end{{figure}}

The performance model improves ranking and discrimination. Calibration remains broadly reasonable, but the highest-risk bins contain fewer events and therefore show more variation. The model is useful for group-level signal assessment. It is not suitable for deterministic predictions about individual students.

\section{{Cohort Coverage}}

Coverage determines which observations can support a fixed five-year outcome. Baselines from 2021 now have a complete five-year window because the higher-contest endpoint is 2026. Baselines from 2022 and 2023 remain incomplete and are excluded from fixed-window models.

\begin{{figure}}[H]
\centering
\includegraphics[width=\textwidth]{{06 Cohort Coverage.png}}
\caption{{Baseline cohort sizes and available follow-up through 2026. Shading marks incomplete APMO source coverage and baselines with fewer than five follow-up years.}}
\end{{figure}}

The 2026 update increases the five-year eligible samples to {five_year_eligible['APMO']:,} for APMO and {five_year_eligible['IMO']:,} for IMO. This is a substantive gain over the 2025 endpoint because an additional baseline cohort enters both model evaluation and descriptive fixed-window analyses.

\section{{Answer to the Research Question}}

\keyresult{{\textbf{{Conclusion.}} Stronger EMIC/IWYMIC performance is a useful signal for later APMO and IMO success among named award recipients. The signal remains after adjustment for country, baseline year, and stage, and it improves prediction on later cohorts.}}

The evidence does not show that EMIC or IWYMIC participation causes later success. Strong contestants may already have better preparation, training access, selection opportunities, or prior mathematical development. The appropriate interpretation is predictive association.

The evidence is strongest when several views agree:
\begin{{itemize}}
\item Percentile curves rise with baseline performance.
\item Medal-tier transitions show the same ordering.
\item Time-to-event estimates separate early and remain ordered.
\item Out-of-time models improve when performance is added.
\item Country adjustment reduces, but does not remove, the signal.
\end{{itemize}}

\section{{Limitations}}
\begin{{itemize}}
\item EMIC/IWYMIC result pages name award recipients only. Unnamed non-awardees cannot be followed, so the study does not compare all participants.
\item Country selection, training access, age, and prior preparation are not observed.
\item IWYMIC total-participant denominators are estimated. Medal-tier results provide an important sensitivity check.
\item APMO 2013 to 2015 lacks complete contestant-level score tables and is excluded from complete-window outcomes.
\item APMO 2026 is preliminary and may change when finalized.
\item Recent cohorts are right-censored. Fixed-window models intentionally exclude incomplete follow-up.
\item Identity matching is conservative. Ambiguous common names remain unmatched, which can slightly understate progression.
\end{{itemize}}

\section{{Reproducibility and Output Inventory}}

Run the statistical pipeline and report builder from the project root:

\begin{{verbatim}}
python "2 Processing Scripts/analyze_performance_signal.py"
python "2 Processing Scripts/build_statistical_analysis_report.py" --compile
\end{{verbatim}}

\begin{{longtable}}{{p{{0.35\textwidth}}p{{0.58\textwidth}}}}
\caption{{Analysis Tables Used in This Report}}\\
\toprule
File & Role \\
\midrule
\endfirsthead
\toprule
File & Role \\
\midrule
\endhead
{output_inventory}
\bottomrule
\end{{longtable}}

The analysis code uses deterministic seeds for country-cluster bootstrap resampling. Generated tables, figures, the Markdown summary, this LaTeX source, the PDF, and source hashes are retained in \texttt{{6 Statistical Analysis}}.

\end{{document}}
"""
    if "\u2014" in document:
        raise RuntimeError("The report contains an em dash")
    return document


def update_changelog() -> None:
    if not CHANGELOG_PATH.exists():
        return
    marker = "\nPublication report:\n"
    existing = CHANGELOG_PATH.read_text(encoding="utf-8")
    existing = existing.split(marker, 1)[0].rstrip() + "\n"
    existing = "\n".join(
        line
        for line in existing.splitlines()
        if not line.startswith("- Full Analysis Report.")
    ).rstrip() + "\n"
    lines = ["", "Publication report:"]
    for path in (TEX_PATH, PDF_PATH):
        if path.exists():
            lines.append(
                f"- {path.name} | {path.stat().st_size} bytes | SHA-256 {sha256(path)}"
            )
    lines.append(
        "- Generated by 2 Processing Scripts/build_statistical_analysis_report.py"
    )
    CHANGELOG_PATH.write_text(
        existing + "\n".join(lines) + "\n", encoding="utf-8"
    )


def compile_pdf() -> None:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        "pdflatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        f"-output-directory={TEMP_DIR}",
        str(TEX_PATH),
    ]
    for _ in range(2):
        subprocess.run(command, cwd=ANALYSIS_DIR, check=True)
    compiled = TEMP_DIR / PDF_PATH.name
    if not compiled.exists():
        raise RuntimeError(f"LaTeX did not create {compiled}")
    shutil.copy2(compiled, PDF_PATH)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--compile",
        action="store_true",
        help="compile the generated LaTeX source with latexmk",
    )
    return parser.parse_args()


def run(*, compile_output: bool = False) -> None:
    document = build_tex()
    TEX_PATH.write_text(document, encoding="ascii")
    print(f"Wrote {TEX_PATH.relative_to(PROJECT_ROOT)}")
    if compile_output:
        compile_pdf()
        print(f"Wrote {PDF_PATH.relative_to(PROJECT_ROOT)}")
    update_changelog()


if __name__ == "__main__":
    run(compile_output=parse_args().compile)
