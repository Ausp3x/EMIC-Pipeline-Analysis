#!/usr/bin/env python3
"""Analyze whether early EMIC/IWYMIC performance predicts APMO/IMO success."""

from __future__ import annotations

import hashlib
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "emic-statistical-analysis-matplotlib"),
)
import matplotlib

matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
import numpy as np
import pandas as pd

from project_paths import (
    COMBINED_MASTER_PATH,
    COUNTRY_PROGRESSION_SUMMARY_PATH,
    MASTER_COPY_PATH,
    PROJECT_ROOT,
    STATISTICAL_ANALYSIS_DIR,
)


DATA_END_YEAR = 2026
WINDOWS = (3, 5)
PRIMARY_WINDOW = 5
CONTEST_START_YEAR = {"apmo": 2016, "imo": 2013}
DESTINATIONS = ("apmo", "imo")
STAGES = ("EMIC", "IWYMIC")
HIGHER_MEDALS = {"Gold", "Silver", "Bronze"}
HIGHER_AWARDS = HIGHER_MEDALS | {"Honourable Mention"}
HIGHER_RESULTS = HIGHER_AWARDS | {"None"}
BASELINE_MEDAL_ORDER = ["Merit", "Bronze", "Silver", "Gold"]
OUTCOME_ORDER = [
    "No appearance",
    "No award",
    "Honourable Mention",
    "Bronze",
    "Silver",
    "Gold",
]
OUTCOME_SCORE = {value: index for index, value in enumerate(OUTCOME_ORDER)}
FIXED_BANDS = ["Below 25%", "25-50%", "50-75%", "75-100%"]
L2_PENALTY = 1.0
BOOTSTRAP_REPLICATES = 300
CURVE_BOOTSTRAP_REPLICATES = 80
RANDOM_SEED = 20260723

ANALYSIS_DIR = STATISTICAL_ANALYSIS_DIR
FIGURES_DIR = ANALYSIS_DIR / "Figures"
COHORT_PATH = ANALYSIS_DIR / "Analysis Cohort.csv"
DESCRIPTIVE_PATH = ANALYSIS_DIR / "Descriptive Progression Summary.csv"
SIGNAL_BANDS_PATH = ANALYSIS_DIR / "Performance Band Summary.csv"
SIGNAL_CURVES_PATH = ANALYSIS_DIR / "Adjusted Signal Curves.csv"
TRANSITIONS_PATH = ANALYSIS_DIR / "Outcome Transition Summary.csv"
SURVIVAL_PATH = ANALYSIS_DIR / "Survival Summary.csv"
COUNTRY_INTERVALS_PATH = ANALYSIS_DIR / "Country Progression Intervals.csv"
COHORT_COVERAGE_PATH = ANALYSIS_DIR / "Cohort Coverage.csv"
MODEL_PREDICTIONS_PATH = ANALYSIS_DIR / "Model Predictions.csv"
MODEL_RESULTS_PATH = ANALYSIS_DIR / "Model Results.csv"
MODEL_COMPARISON_PATH = ANALYSIS_DIR / "Model Comparison.csv"
CALIBRATION_PATH = ANALYSIS_DIR / "Calibration Summary.csv"
REPORT_PATH = ANALYSIS_DIR / "Analysis Report.md"
CHANGELOG_PATH = ANALYSIS_DIR / "Analysis Changelog.txt"
PUBLICATION_REPORT_PATHS = {
    ANALYSIS_DIR / "Full Analysis Report.tex",
    ANALYSIS_DIR / "Full Analysis Report.pdf",
}

FIGURE_PATHS = {
    "signal": FIGURES_DIR / "01 Performance Signal Curves.png",
    "transitions": FIGURES_DIR / "02 Outcome Transitions.png",
    "survival": FIGURES_DIR / "03 Cumulative Award Incidence.png",
    "countries": FIGURES_DIR / "04 Country Progression Rates.png",
    "models": FIGURES_DIR / "05 Model Comparison and Calibration.png",
    "coverage": FIGURES_DIR / "06 Cohort Coverage.png",
}

BLUE = "#3569A8"
TEAL = "#2A9D8F"
ORANGE = "#D97745"
GOLD = "#D7A928"
PURPLE = "#7A6FA8"
GRAY = "#7A7F87"
LIGHT_GRAY = "#D9DDE3"
GRID = "#D6D9DE"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def history_values(value: object) -> list[str]:
    if value is None or pd.isna(value):
        return []
    return [part for part in str(value).split(";") if part]


def parse_years(value: object) -> list[int]:
    return [int(part) for part in history_values(value)]


def parse_mapped(value: object, cast: type = str) -> dict[int, object]:
    output: dict[int, object] = {}
    for part in history_values(value):
        if ":" not in part:
            raise RuntimeError(f"Malformed mapped history value: {part!r}")
        year_text, mapped_value = part.split(":", 1)
        output[int(year_text)] = cast(mapped_value)
    return output


def validate_history_alignment(row: pd.Series, prefix: str) -> None:
    years = parse_years(row[f"{prefix}_years"])
    count = int(row[f"{prefix}_appearance_count"])
    if count != len(years):
        raise RuntimeError(
            f"Master row {row['id']} has {prefix} count {count}, years {years}"
        )
    if years != sorted(set(years)):
        raise RuntimeError(
            f"Master row {row['id']} has unsorted/duplicate {prefix} years"
        )
    for suffix, cast in (
        ("medals_by_year", str),
        ("rank_averages_by_year", float),
        ("percentiles_by_year", float),
    ):
        mapped = parse_mapped(row[f"{prefix}_{suffix}"], cast)
        if list(mapped) != years:
            raise RuntimeError(
                f"Master row {row['id']} has misaligned {prefix}_{suffix}"
            )


def best_result(years: list[int], medals: dict[int, object]) -> str:
    if not years:
        return "No appearance"
    awards = [str(medals[year]) for year in years]
    recognized = [award for award in awards if award in HIGHER_AWARDS]
    if not recognized:
        return "No award"
    return max(recognized, key=lambda value: OUTCOME_SCORE[value])


def fixed_band(percentile: float) -> str:
    if percentile < 0.25:
        return "Below 25%"
    if percentile < 0.50:
        return "25-50%"
    if percentile < 0.75:
        return "50-75%"
    return "75-100%"


def build_analysis_cohort(master: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for _, row in master.iterrows():
        for prefix in ("emic", "iwymic", "apmo", "imo"):
            validate_history_alignment(row, prefix)

        stage_events: list[tuple[int, str, str, float, float]] = []
        for prefix, stage in (("emic", "EMIC"), ("iwymic", "IWYMIC")):
            years = parse_years(row[f"{prefix}_years"])
            medals = parse_mapped(row[f"{prefix}_medals_by_year"], str)
            ranks = parse_mapped(row[f"{prefix}_rank_averages_by_year"], float)
            percentiles = parse_mapped(
                row[f"{prefix}_percentiles_by_year"], float
            )
            stage_events.extend(
                (
                    year,
                    stage,
                    str(medals[year]),
                    float(ranks[year]),
                    float(percentiles[year]),
                )
                for year in years
            )
        if not stage_events:
            raise RuntimeError(f"Master row {row['id']} has no baseline event")
        stage_events.sort(key=lambda event: (event[0], 0 if event[1] == "EMIC" else 1))
        baseline_year, baseline_stage, baseline_medal, baseline_rank, baseline_pct = (
            stage_events[0]
        )
        if not 0 <= baseline_pct <= 1:
            raise RuntimeError(
                f"Master row {row['id']} has invalid percentile {baseline_pct}"
            )

        record: dict[str, object] = {
            "id": int(row["id"]),
            "name_clean": row["name_clean"],
            "country_clean": row["country_clean"],
            "baseline_stage": baseline_stage,
            "baseline_year": baseline_year,
            "baseline_medal": baseline_medal,
            "baseline_rank_average": baseline_rank,
            "baseline_percentile": baseline_pct,
            "baseline_performance_band": fixed_band(baseline_pct),
            "available_follow_up_years": DATA_END_YEAR - baseline_year,
            "emic_appearance_count": int(row["emic_appearance_count"]),
            "iwymic_appearance_count": int(row["iwymic_appearance_count"]),
        }

        for prefix in DESTINATIONS:
            years = parse_years(row[f"{prefix}_years"])
            medals = parse_mapped(row[f"{prefix}_medals_by_year"], str)
            percentiles = parse_mapped(
                row[f"{prefix}_percentiles_by_year"], float
            )
            unknown = sorted(
                {str(value) for value in medals.values()} - HIGHER_RESULTS
            )
            if unknown:
                raise RuntimeError(
                    f"Master row {row['id']} has unknown {prefix} results {unknown}"
                )
            later_years = [year for year in years if year > baseline_year]
            later_award_years = [
                year for year in later_years if str(medals[year]) in HIGHER_AWARDS
            ]
            later_medal_years = [
                year for year in later_years if str(medals[year]) in HIGHER_MEDALS
            ]
            record[f"{prefix}_later_participated"] = int(bool(later_years))
            record[f"{prefix}_later_award"] = int(bool(later_award_years))
            record[f"{prefix}_later_medal"] = int(bool(later_medal_years))
            record[f"{prefix}_first_later_participation_year"] = (
                min(later_years) if later_years else pd.NA
            )
            record[f"{prefix}_first_later_award_year"] = (
                min(later_award_years) if later_award_years else pd.NA
            )
            record[f"{prefix}_first_later_medal_year"] = (
                min(later_medal_years) if later_medal_years else pd.NA
            )
            record[f"{prefix}_best_later_result"] = best_result(
                later_years, medals
            )
            record[f"{prefix}_best_later_percentile"] = (
                max(float(percentiles[year]) for year in later_years)
                if later_years
                else pd.NA
            )
            record[f"{prefix}_time_to_first_award"] = (
                min(later_award_years) - baseline_year
                if later_award_years
                else pd.NA
            )
            record[f"{prefix}_survival_eligible"] = int(
                baseline_year + 1 >= CONTEST_START_YEAR[prefix]
            )

            for window in WINDOWS:
                eligible = (
                    baseline_year + 1 >= CONTEST_START_YEAR[prefix]
                    and baseline_year + window <= DATA_END_YEAR
                )
                window_years = [
                    year
                    for year in years
                    if baseline_year < year <= baseline_year + window
                ]
                award_years = [
                    year
                    for year in window_years
                    if str(medals[year]) in HIGHER_AWARDS
                ]
                medal_years = [
                    year
                    for year in window_years
                    if str(medals[year]) in HIGHER_MEDALS
                ]
                record[f"{prefix}_{window}y_eligible"] = int(eligible)
                record[f"{prefix}_{window}y_participated"] = (
                    int(bool(window_years)) if eligible else pd.NA
                )
                record[f"{prefix}_{window}y_award"] = (
                    int(bool(award_years)) if eligible else pd.NA
                )
                record[f"{prefix}_{window}y_medal"] = (
                    int(bool(medal_years)) if eligible else pd.NA
                )
                record[f"{prefix}_{window}y_best_result"] = (
                    best_result(window_years, medals) if eligible else pd.NA
                )
        records.append(record)

    cohort = pd.DataFrame(records).sort_values("id").reset_index(drop=True)
    for column in cohort.columns:
        if column.endswith("_year") or column.endswith("_years"):
            if column not in {"available_follow_up_years"}:
                cohort[column] = cohort[column].astype("Int64")
    return cohort


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return math.nan, math.nan
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / total + z * z / (4 * total * total)
        )
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def build_descriptive_summary(cohort: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for scope in ("All", *STAGES):
        scoped = cohort if scope == "All" else cohort[cohort["baseline_stage"] == scope]
        for band in FIXED_BANDS:
            subset = scoped[scoped["baseline_performance_band"] == band]
            if subset.empty:
                continue
            record: dict[str, object] = {
                "baseline_stage": scope,
                "performance_band": band,
                "contestants": len(subset),
            }
            for prefix in DESTINATIONS:
                for outcome in ("award", "medal"):
                    count = int(subset[f"{prefix}_later_{outcome}"].sum())
                    record[f"later_{prefix}_{outcome}_recipients"] = count
                    record[f"later_{prefix}_{outcome}_percent"] = 100 * count / len(subset)
            rows.append(record)
    return pd.DataFrame(rows)


def build_performance_band_summary(cohort: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for prefix in DESTINATIONS:
        eligible = cohort[cohort[f"{prefix}_{PRIMARY_WINDOW}y_eligible"] == 1]
        for stage in STAGES:
            stage_rows = eligible[eligible["baseline_stage"] == stage].copy()
            if stage_rows.empty:
                continue
            stage_rows["quintile"] = pd.qcut(
                stage_rows["baseline_percentile"].rank(method="first"),
                q=5,
                labels=False,
            )
            for outcome in ("award", "medal"):
                target = f"{prefix}_{PRIMARY_WINDOW}y_{outcome}"
                for quintile, group in stage_rows.groupby("quintile", sort=True):
                    count = int(group[target].sum())
                    total = len(group)
                    lower, upper = wilson_interval(count, total)
                    rows.append(
                        {
                            "destination": prefix.upper(),
                            "baseline_stage": stage,
                            "outcome": outcome,
                            "quintile": int(quintile) + 1,
                            "percentile_min": group["baseline_percentile"].min(),
                            "percentile_max": group["baseline_percentile"].max(),
                            "percentile_mean": group["baseline_percentile"].mean(),
                            "contestants": total,
                            "events": count,
                            "event_rate": count / total,
                            "wilson_lower": lower,
                            "wilson_upper": upper,
                        }
                    )
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class DesignSpec:
    countries: tuple[str, ...]
    year_mean: float
    year_scale: float
    include_stage: bool


def make_design_spec(data: pd.DataFrame, *, include_stage: bool) -> DesignSpec:
    year_scale = float(data["baseline_year"].std(ddof=0))
    return DesignSpec(
        countries=tuple(sorted(data["country_clean"].unique())),
        year_mean=float(data["baseline_year"].mean()),
        year_scale=year_scale if year_scale > 0 else 1.0,
        include_stage=include_stage,
    )


def design_matrix(
    data: pd.DataFrame,
    spec: DesignSpec,
    *,
    include_performance: bool,
    forced_percentile: float | None = None,
) -> np.ndarray:
    columns: list[np.ndarray] = [np.ones(len(data), dtype=float)]
    year_values = data["baseline_year"].to_numpy(dtype=float)
    columns.append((year_values - spec.year_mean) / spec.year_scale)
    stage_indicator = (
        (data["baseline_stage"] == "IWYMIC").to_numpy(dtype=float)
        if spec.include_stage
        else np.zeros(len(data), dtype=float)
    )
    if spec.include_stage:
        columns.append(stage_indicator)
    for country in spec.countries[1:]:
        columns.append((data["country_clean"] == country).to_numpy(dtype=float))
    if include_performance:
        percentile = (
            np.full(len(data), forced_percentile, dtype=float)
            if forced_percentile is not None
            else data["baseline_percentile"].to_numpy(dtype=float)
        )
        scaled = (percentile - 0.65) / 0.15
        columns.extend((scaled, scaled * scaled))
        if spec.include_stage:
            columns.append(scaled * stage_indicator)
    return np.column_stack(columns)


def sigmoid(values: np.ndarray) -> np.ndarray:
    output = np.empty_like(values, dtype=float)
    positive = values >= 0
    output[positive] = 1 / (1 + np.exp(-values[positive]))
    exp_values = np.exp(values[~positive])
    output[~positive] = exp_values / (1 + exp_values)
    return output


def logistic_objective(
    matrix: np.ndarray,
    target: np.ndarray,
    coefficients: np.ndarray,
    penalty: float,
) -> float:
    probabilities = np.clip(sigmoid(matrix @ coefficients), 1e-12, 1 - 1e-12)
    loss = -np.sum(
        target * np.log(probabilities) + (1 - target) * np.log(1 - probabilities)
    )
    return float(loss + 0.5 * penalty * np.sum(coefficients[1:] ** 2))


def fit_ridge_logistic(
    matrix: np.ndarray,
    target: np.ndarray,
    penalty: float = L2_PENALTY,
    max_iterations: int = 100,
) -> np.ndarray:
    if len(np.unique(target)) != 2:
        raise RuntimeError("Logistic regression target must contain both classes")
    coefficients = np.zeros(matrix.shape[1], dtype=float)
    mean_target = np.clip(target.mean(), 1e-6, 1 - 1e-6)
    coefficients[0] = math.log(mean_target / (1 - mean_target))
    penalty_diagonal = np.ones(matrix.shape[1], dtype=float)
    penalty_diagonal[0] = 0.0
    current_objective = logistic_objective(
        matrix, target, coefficients, penalty
    )
    for _ in range(max_iterations):
        probabilities = np.clip(sigmoid(matrix @ coefficients), 1e-8, 1 - 1e-8)
        weights = probabilities * (1 - probabilities)
        gradient = matrix.T @ (probabilities - target)
        gradient += penalty * penalty_diagonal * coefficients
        hessian = matrix.T @ (weights[:, None] * matrix)
        hessian += np.diag(penalty * penalty_diagonal + 1e-8)
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError:
            step = np.linalg.lstsq(hessian, gradient, rcond=None)[0]
        step_scale = 1.0
        candidate = coefficients - step
        candidate_objective = logistic_objective(
            matrix, target, candidate, penalty
        )
        while candidate_objective > current_objective and step_scale > 1e-4:
            step_scale *= 0.5
            candidate = coefficients - step_scale * step
            candidate_objective = logistic_objective(
                matrix, target, candidate, penalty
            )
        if np.max(np.abs(candidate - coefficients)) < 1e-8:
            coefficients = candidate
            break
        coefficients = candidate
        current_objective = candidate_objective
    return coefficients


def average_precision(target: np.ndarray, scores: np.ndarray) -> float:
    positives = int(target.sum())
    if positives == 0:
        return math.nan
    order = np.argsort(-scores, kind="mergesort")
    sorted_target = target[order]
    precision = np.cumsum(sorted_target) / np.arange(1, len(target) + 1)
    return float(precision[sorted_target == 1].sum() / positives)


def roc_auc(target: np.ndarray, scores: np.ndarray) -> float:
    positives = int(target.sum())
    negatives = len(target) - positives
    if positives == 0 or negatives == 0:
        return math.nan
    ranks = pd.Series(scores).rank(method="average").to_numpy(dtype=float)
    rank_sum = ranks[target == 1].sum()
    return float(
        (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)
    )


def prediction_metrics(target: np.ndarray, scores: np.ndarray) -> dict[str, float]:
    clipped = np.clip(scores, 1e-12, 1 - 1e-12)
    return {
        "average_precision": average_precision(target, clipped),
        "roc_auc": roc_auc(target, clipped),
        "brier_score": float(np.mean((clipped - target) ** 2)),
        "log_loss": float(
            -np.mean(target * np.log(clipped) + (1 - target) * np.log(1 - clipped))
        ),
    }


def temporal_predictions(
    cohort: pd.DataFrame,
    prefix: str,
    outcome: str,
) -> pd.DataFrame:
    eligible = cohort[cohort[f"{prefix}_{PRIMARY_WINDOW}y_eligible"] == 1].copy()
    target_column = f"{prefix}_{PRIMARY_WINDOW}y_{outcome}"
    years = sorted(int(year) for year in eligible["baseline_year"].unique())
    prediction_rows: list[pd.DataFrame] = []
    for test_year in years[3:]:
        train = eligible[eligible["baseline_year"] < test_year]
        test = eligible[eligible["baseline_year"] == test_year]
        target_train = train[target_column].to_numpy(dtype=float)
        if len(test) == 0 or target_train.sum() < 8 or (
            len(target_train) - target_train.sum()
        ) < 8:
            continue
        spec = make_design_spec(train, include_stage=True)
        fold = test[
            ["id", "country_clean", "baseline_stage", "baseline_year"]
        ].copy()
        fold["destination"] = prefix.upper()
        fold["outcome"] = outcome
        fold["train_start_year"] = int(train["baseline_year"].min())
        fold["train_through_year"] = test_year - 1
        fold["test_year"] = test_year
        fold["actual"] = test[target_column].to_numpy(dtype=int)
        for model, include_performance in (
            ("Baseline", False),
            ("Performance", True),
        ):
            train_matrix = design_matrix(
                train,
                spec,
                include_performance=include_performance,
            )
            test_matrix = design_matrix(
                test,
                spec,
                include_performance=include_performance,
            )
            coefficients = fit_ridge_logistic(train_matrix, target_train)
            fold[f"{model.lower()}_probability"] = sigmoid(
                test_matrix @ coefficients
            )
        prediction_rows.append(fold)
    if not prediction_rows:
        raise RuntimeError(
            f"No temporal validation folds available for {prefix} {outcome}"
        )
    return pd.concat(prediction_rows, ignore_index=True)


def bootstrap_metric_differences(
    predictions: pd.DataFrame,
    seed: int,
) -> dict[str, tuple[float, float]]:
    rng = np.random.default_rng(seed)
    countries = predictions["country_clean"].unique()
    values: dict[str, list[float]] = {
        "average_precision": [],
        "roc_auc": [],
        "brier_improvement": [],
        "log_loss_improvement": [],
    }
    grouped = {
        country: predictions.index[predictions["country_clean"] == country].to_numpy()
        for country in countries
    }
    for _ in range(BOOTSTRAP_REPLICATES):
        sampled_countries = rng.choice(countries, size=len(countries), replace=True)
        indices = np.concatenate([grouped[country] for country in sampled_countries])
        sample = predictions.loc[indices]
        target = sample["actual"].to_numpy(dtype=int)
        if len(np.unique(target)) != 2:
            continue
        baseline = prediction_metrics(
            target, sample["baseline_probability"].to_numpy(dtype=float)
        )
        performance = prediction_metrics(
            target, sample["performance_probability"].to_numpy(dtype=float)
        )
        values["average_precision"].append(
            performance["average_precision"] - baseline["average_precision"]
        )
        values["roc_auc"].append(performance["roc_auc"] - baseline["roc_auc"])
        values["brier_improvement"].append(
            baseline["brier_score"] - performance["brier_score"]
        )
        values["log_loss_improvement"].append(
            baseline["log_loss"] - performance["log_loss"]
        )
    return {
        metric: (
            float(np.quantile(metric_values, 0.025)),
            float(np.quantile(metric_values, 0.975)),
        )
        for metric, metric_values in values.items()
        if metric_values
    }


def build_model_outputs(
    cohort: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    predictions = pd.concat(
        [
            temporal_predictions(cohort, prefix, outcome)
            for prefix in DESTINATIONS
            for outcome in ("award", "medal")
        ],
        ignore_index=True,
    )
    result_rows: list[dict[str, object]] = []
    comparison_rows: list[dict[str, object]] = []
    calibration_rows: list[dict[str, object]] = []
    for group_index, ((destination, outcome), group) in enumerate(
        predictions.groupby(["destination", "outcome"], sort=True)
    ):
        target = group["actual"].to_numpy(dtype=int)
        metrics_by_model: dict[str, dict[str, float]] = {}
        for model in ("Baseline", "Performance"):
            scores = group[f"{model.lower()}_probability"].to_numpy(dtype=float)
            metrics = prediction_metrics(target, scores)
            metrics_by_model[model] = metrics
            result_rows.append(
                {
                    "destination": destination,
                    "outcome": outcome,
                    "model": model,
                    "validation": "forward baseline-year validation",
                    "test_years": ";".join(
                        str(year) for year in sorted(group["test_year"].unique())
                    ),
                    "predictions": len(group),
                    "events": int(target.sum()),
                    "event_rate": target.mean(),
                    "average_precision": metrics["average_precision"],
                    "roc_auc": metrics["roc_auc"],
                    "brier_score": metrics["brier_score"],
                    "log_loss": metrics["log_loss"],
                    "l2_penalty": L2_PENALTY,
                }
            )

            calibration_group = group.copy()
            calibration_group["probability"] = scores
            calibration_group["bin"] = pd.qcut(
                calibration_group["probability"].rank(method="first"),
                q=5,
                labels=False,
            )
            for bin_index, bin_rows in calibration_group.groupby("bin", sort=True):
                successes = int(bin_rows["actual"].sum())
                total = len(bin_rows)
                lower, upper = wilson_interval(successes, total)
                calibration_rows.append(
                    {
                        "destination": destination,
                        "outcome": outcome,
                        "model": model,
                        "bin": int(bin_index) + 1,
                        "contestants": total,
                        "events": successes,
                        "mean_predicted_probability": bin_rows["probability"].mean(),
                        "observed_rate": successes / total,
                        "wilson_lower": lower,
                        "wilson_upper": upper,
                    }
                )

        intervals = bootstrap_metric_differences(
            group, RANDOM_SEED + group_index
        )
        baseline = metrics_by_model["Baseline"]
        performance = metrics_by_model["Performance"]
        comparison_rows.append(
            {
                "destination": destination,
                "outcome": outcome,
                "predictions": len(group),
                "events": int(target.sum()),
                "delta_average_precision": performance["average_precision"]
                - baseline["average_precision"],
                "delta_average_precision_lower": intervals["average_precision"][0],
                "delta_average_precision_upper": intervals["average_precision"][1],
                "delta_roc_auc": performance["roc_auc"] - baseline["roc_auc"],
                "delta_roc_auc_lower": intervals["roc_auc"][0],
                "delta_roc_auc_upper": intervals["roc_auc"][1],
                "brier_improvement": baseline["brier_score"]
                - performance["brier_score"],
                "brier_improvement_lower": intervals["brier_improvement"][0],
                "brier_improvement_upper": intervals["brier_improvement"][1],
                "log_loss_improvement": baseline["log_loss"]
                - performance["log_loss"],
                "log_loss_improvement_lower": intervals["log_loss_improvement"][0],
                "log_loss_improvement_upper": intervals["log_loss_improvement"][1],
                "bootstrap_unit": "country",
                "bootstrap_replicates": BOOTSTRAP_REPLICATES,
            }
        )
    return (
        predictions,
        pd.DataFrame(result_rows),
        pd.DataFrame(comparison_rows),
        pd.DataFrame(calibration_rows),
    )


def adjusted_signal_curves(cohort: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    grid = np.linspace(0.30, 0.98, 50)
    rng = np.random.default_rng(RANDOM_SEED)
    for prefix in DESTINATIONS:
        eligible = cohort[cohort[f"{prefix}_{PRIMARY_WINDOW}y_eligible"] == 1]
        target_column = f"{prefix}_{PRIMARY_WINDOW}y_award"
        for stage in STAGES:
            subset = eligible[eligible["baseline_stage"] == stage].copy()
            target = subset[target_column].to_numpy(dtype=float)
            spec = make_design_spec(subset, include_stage=False)
            matrix = design_matrix(subset, spec, include_performance=True)
            coefficients = fit_ridge_logistic(matrix, target)
            estimates = np.array(
                [
                    sigmoid(
                        design_matrix(
                            subset,
                            spec,
                            include_performance=True,
                            forced_percentile=value,
                        )
                        @ coefficients
                    ).mean()
                    for value in grid
                ]
            )

            countries = subset["country_clean"].unique()
            grouped = {
                country: subset[subset["country_clean"] == country]
                for country in countries
            }
            bootstrap_estimates: list[np.ndarray] = []
            for _ in range(CURVE_BOOTSTRAP_REPLICATES):
                sampled = rng.choice(countries, size=len(countries), replace=True)
                bootstrap = pd.concat(
                    [grouped[country] for country in sampled], ignore_index=True
                )
                bootstrap_target = bootstrap[target_column].to_numpy(dtype=float)
                if len(np.unique(bootstrap_target)) != 2:
                    continue
                bootstrap_matrix = design_matrix(
                    bootstrap, spec, include_performance=True
                )
                bootstrap_coefficients = fit_ridge_logistic(
                    bootstrap_matrix, bootstrap_target
                )
                bootstrap_estimates.append(
                    np.array(
                        [
                            sigmoid(
                                design_matrix(
                                    subset,
                                    spec,
                                    include_performance=True,
                                    forced_percentile=value,
                                )
                                @ bootstrap_coefficients
                            ).mean()
                            for value in grid
                        ]
                    )
                )
            bootstrap_array = np.vstack(bootstrap_estimates)
            lower = np.quantile(bootstrap_array, 0.025, axis=0)
            upper = np.quantile(bootstrap_array, 0.975, axis=0)
            for value, estimate, low, high in zip(
                grid, estimates, lower, upper, strict=True
            ):
                rows.append(
                    {
                        "destination": prefix.upper(),
                        "baseline_stage": stage,
                        "baseline_percentile": value,
                        "adjusted_probability": estimate,
                        "bootstrap_lower": low,
                        "bootstrap_upper": high,
                        "eligible_contestants": len(subset),
                        "events": int(target.sum()),
                        "bootstrap_replicates": len(bootstrap_estimates),
                    }
                )
    return pd.DataFrame(rows)


def build_transition_summary(cohort: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for prefix in DESTINATIONS:
        eligible = cohort[cohort[f"{prefix}_{PRIMARY_WINDOW}y_eligible"] == 1]
        for stage in STAGES:
            stage_rows = eligible[eligible["baseline_stage"] == stage]
            for baseline_medal in BASELINE_MEDAL_ORDER:
                medal_rows = stage_rows[stage_rows["baseline_medal"] == baseline_medal]
                if medal_rows.empty:
                    continue
                for outcome in OUTCOME_ORDER:
                    count = int(
                        (medal_rows[f"{prefix}_{PRIMARY_WINDOW}y_best_result"] == outcome).sum()
                    )
                    rows.append(
                        {
                            "destination": prefix.upper(),
                            "baseline_stage": stage,
                            "baseline_medal": baseline_medal,
                            "later_outcome": outcome,
                            "contestants": len(medal_rows),
                            "count": count,
                            "percentage": 100 * count / len(medal_rows),
                        }
                    )
    return pd.DataFrame(rows)


def build_survival_summary(cohort: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for prefix in DESTINATIONS:
        eligible = cohort[cohort[f"{prefix}_survival_eligible"] == 1]
        for band in FIXED_BANDS:
            group = eligible[eligible["baseline_performance_band"] == band]
            if group.empty:
                continue
            event_times = group[f"{prefix}_time_to_first_award"]
            follow_up = group["available_follow_up_years"].to_numpy(dtype=int)
            observed_times = np.array(
                [
                    int(event_time) if not pd.isna(event_time) else int(censor_time)
                    for event_time, censor_time in zip(
                        event_times, follow_up, strict=True
                    )
                ]
            )
            events = (~event_times.isna()).to_numpy(dtype=bool)
            survival = 1.0
            greenwood = 0.0
            max_time = int(follow_up.max())
            for year_since_baseline in range(1, max_time + 1):
                at_risk = int((observed_times >= year_since_baseline).sum())
                event_count = int(
                    (
                        events
                        & (observed_times == year_since_baseline)
                    ).sum()
                )
                if at_risk > 0:
                    survival *= 1 - event_count / at_risk
                    if event_count > 0 and at_risk > event_count:
                        greenwood += event_count / (
                            at_risk * (at_risk - event_count)
                        )
                standard_error = survival * math.sqrt(greenwood)
                survival_lower = max(0.0, survival - 1.96 * standard_error)
                survival_upper = min(1.0, survival + 1.96 * standard_error)
                rows.append(
                    {
                        "destination": prefix.upper(),
                        "performance_band": band,
                        "group_contestants": len(group),
                        "year_since_baseline": year_since_baseline,
                        "at_risk": at_risk,
                        "events": event_count,
                        "cumulative_award_probability": 1 - survival,
                        "lower_95": 1 - survival_upper,
                        "upper_95": 1 - survival_lower,
                    }
                )
    return pd.DataFrame(rows)


def build_country_intervals(cohort: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    countries = sorted(cohort["country_clean"].unique())
    for prefix in DESTINATIONS:
        eligible = cohort[cohort[f"{prefix}_{PRIMARY_WINDOW}y_eligible"] == 1]
        for country in countries:
            group = eligible[eligible["country_clean"] == country]
            for outcome in ("award", "medal"):
                total = len(group)
                count = int(group[f"{prefix}_{PRIMARY_WINDOW}y_{outcome}"].sum())
                lower, upper = wilson_interval(count, total)
                rows.append(
                    {
                        "destination": prefix.upper(),
                        "country_clean": country,
                        "outcome": outcome,
                        "eligible_contestants": total,
                        "events": count,
                        "event_rate": count / total if total else math.nan,
                        "wilson_lower": lower,
                        "wilson_upper": upper,
                    }
                )
    return pd.DataFrame(rows)


def build_cohort_coverage(cohort: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (year, stage), group in cohort.groupby(
        ["baseline_year", "baseline_stage"], sort=True
    ):
        rows.append(
            {
                "baseline_year": int(year),
                "baseline_stage": stage,
                "contestants": len(group),
                "available_follow_up_years": DATA_END_YEAR - int(year),
                "apmo_3y_eligible": int(group["apmo_3y_eligible"].sum()),
                "apmo_5y_eligible": int(group["apmo_5y_eligible"].sum()),
                "imo_3y_eligible": int(group["imo_3y_eligible"].sum()),
                "imo_5y_eligible": int(group["imo_5y_eligible"].sum()),
            }
        )
    return pd.DataFrame(rows)


def configure_plots() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "axes.edgecolor": "#6C7178",
            "axes.linewidth": 0.8,
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 0.6,
            "grid.alpha": 0.7,
            "legend.frameon": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )


def save_figure(figure: plt.Figure, path: Path) -> None:
    figure.savefig(path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def plot_signal_curves(
    bands: pd.DataFrame,
    curves: pd.DataFrame,
) -> None:
    figure, axes = plt.subplots(2, 2, figsize=(13, 8), sharex=True)
    for row_index, stage in enumerate(STAGES):
        for column_index, destination in enumerate(("APMO", "IMO")):
            axis = axes[row_index, column_index]
            curve = curves[
                (curves["destination"] == destination)
                & (curves["baseline_stage"] == stage)
            ]
            raw = bands[
                (bands["destination"] == destination)
                & (bands["baseline_stage"] == stage)
                & (bands["outcome"] == "award")
            ]
            axis.fill_between(
                curve["baseline_percentile"].to_numpy(dtype=float),
                curve["bootstrap_lower"].to_numpy(dtype=float),
                curve["bootstrap_upper"].to_numpy(dtype=float),
                color=BLUE,
                alpha=0.16,
                linewidth=0,
            )
            axis.plot(
                curve["baseline_percentile"],
                curve["adjusted_probability"],
                color=BLUE,
                linewidth=2,
                label="Country/Year-Adjusted Curve",
            )
            lower_error = raw["event_rate"] - raw["wilson_lower"]
            upper_error = raw["wilson_upper"] - raw["event_rate"]
            axis.errorbar(
                raw["percentile_mean"],
                raw["event_rate"],
                yerr=np.vstack((lower_error, upper_error)),
                fmt="o",
                color=ORANGE,
                ecolor=ORANGE,
                capsize=3,
                label="Raw Quintile Rate (95% CI)",
                zorder=3,
            )
            for _, point in raw.iterrows():
                axis.annotate(
                    f"n={int(point['contestants'])}",
                    (point["percentile_mean"], point["wilson_upper"]),
                    xytext=(0, 5),
                    textcoords="offset points",
                    ha="center",
                    va="bottom",
                    fontsize=8,
                    color="#555B63",
                    bbox={
                        "boxstyle": "round,pad=0.12",
                        "facecolor": "white",
                        "edgecolor": "none",
                        "alpha": 0.82,
                    },
                )
            axis.set_title(f"{stage} to {destination}")
            axis.set_xlim(0.28, 1.0)
            axis.set_ylim(bottom=0)
            axis.xaxis.set_major_formatter(PercentFormatter(1.0))
            axis.yaxis.set_major_formatter(PercentFormatter(1.0))
            axis.set_xlabel("Baseline Contest Percentile")
            axis.set_ylabel("Award Within Five Years")
            axis.spines[["top", "right"]].set_visible(False)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    figure.legend(
        handles,
        labels,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.055),
        ncol=2,
    )
    figure.suptitle(
        "Five-Year Higher-Contest Award Probability Rises With Baseline Performance",
        fontsize=15,
        fontweight="bold",
    )
    figure.text(
        0.5,
        0.012,
        "Raw points use equal-sized performance groups; adjusted curves control for baseline year and country. Award includes Honourable Mention.",
        ha="center",
        fontsize=9,
        color="#555B63",
    )
    figure.tight_layout(rect=(0, 0.13, 1, 0.94))
    save_figure(figure, FIGURE_PATHS["signal"])


def plot_transitions(transitions: pd.DataFrame) -> None:
    colors = {
        "No appearance": LIGHT_GRAY,
        "No award": GRAY,
        "Honourable Mention": PURPLE,
        "Bronze": "#A87044",
        "Silver": "#A9B0BA",
        "Gold": "#E0B62F",
    }
    figure, axes = plt.subplots(2, 2, figsize=(13, 8), sharex=True)
    for row_index, stage in enumerate(STAGES):
        for column_index, destination in enumerate(("APMO", "IMO")):
            axis = axes[row_index, column_index]
            panel = transitions[
                (transitions["destination"] == destination)
                & (transitions["baseline_stage"] == stage)
            ]
            medals = [
                medal
                for medal in BASELINE_MEDAL_ORDER
                if medal in set(panel["baseline_medal"])
            ]
            left = np.zeros(len(medals))
            for outcome in OUTCOME_ORDER:
                values = np.array(
                    [
                        float(
                            panel[
                                (panel["baseline_medal"] == medal)
                                & (panel["later_outcome"] == outcome)
                            ]["percentage"].iloc[0]
                        )
                        / 100
                        for medal in medals
                    ]
                )
                bars = axis.barh(
                    medals,
                    values,
                    left=left,
                    color=colors[outcome],
                    edgecolor="white",
                    linewidth=0.5,
                    label=outcome,
                )
                for bar, value in zip(bars, values, strict=True):
                    if value >= 0.08:
                        axis.text(
                            bar.get_x() + bar.get_width() / 2,
                            bar.get_y() + bar.get_height() / 2,
                            f"{value:.0%}",
                            ha="center",
                            va="center",
                            fontsize=8,
                            color="#22252A",
                        )
                left += values
            for index, medal in enumerate(medals):
                denominator = int(
                    panel[panel["baseline_medal"] == medal]["contestants"].iloc[0]
                )
                axis.text(
                    1.01,
                    index,
                    f"n={denominator}",
                    va="center",
                    fontsize=8,
                    color="#555B63",
                )
            axis.set_title(f"{stage} to {destination}")
            axis.set_xlim(0, 1.10)
            axis.xaxis.set_major_formatter(PercentFormatter(1.0))
            axis.set_xlabel("Five-Year Outcome Distribution")
            axis.set_ylabel("Baseline Award")
            axis.grid(axis="y", visible=False)
            axis.spines[["top", "right", "left"]].set_visible(False)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="lower center", ncol=6)
    figure.suptitle(
        "Baseline Award Tier and Five-Year APMO/IMO Outcomes",
        fontsize=15,
        fontweight="bold",
    )
    figure.tight_layout(rect=(0, 0.08, 1, 0.94))
    save_figure(figure, FIGURE_PATHS["transitions"])


def plot_survival(survival: pd.DataFrame) -> None:
    band_colors = {
        "25-50%": ORANGE,
        "50-75%": TEAL,
        "75-100%": BLUE,
        "Below 25%": GRAY,
    }
    figure, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    for axis, destination in zip(axes, ("APMO", "IMO"), strict=True):
        panel = survival[survival["destination"] == destination]
        for band in FIXED_BANDS:
            line = panel[panel["performance_band"] == band]
            if line.empty:
                continue
            label = f"{band} (n={int(line['group_contestants'].iloc[0])})"
            axis.plot(
                line["year_since_baseline"],
                line["cumulative_award_probability"],
                linewidth=2,
                color=band_colors[band],
                label=label,
            )
            axis.fill_between(
                line["year_since_baseline"].to_numpy(dtype=float),
                line["lower_95"].to_numpy(dtype=float),
                line["upper_95"].to_numpy(dtype=float),
                color=band_colors[band],
                alpha=0.12,
                linewidth=0,
            )
        axis.set_title(destination)
        axis.set_xlabel("Years After First EMIC/IWYMIC Award")
        axis.set_ylabel("Cumulative Probability of an Award")
        axis.yaxis.set_major_formatter(PercentFormatter(1.0))
        axis.set_ylim(bottom=0)
        axis.set_xlim(left=1)
        axis.legend(loc="upper left")
        axis.spines[["top", "right"]].set_visible(False)
    figure.suptitle(
        "Time to First Later APMO/IMO Award by Baseline Performance",
        fontsize=15,
        fontweight="bold",
    )
    figure.text(
        0.5,
        0.01,
        f"Kaplan-Meier-style cumulative incidence with right-censoring at {DATA_END_YEAR}; APMO baselines before 2015 are excluded because complete results begin in 2016.",
        ha="center",
        fontsize=9,
        color="#555B63",
    )
    figure.tight_layout(rect=(0, 0.07, 1, 0.93))
    save_figure(figure, FIGURE_PATHS["survival"])


def plot_country_intervals(country_data: pd.DataFrame) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(15, 12))
    for axis, destination, color in zip(
        axes, ("APMO", "IMO"), (TEAL, BLUE), strict=True
    ):
        panel = country_data[
            (country_data["destination"] == destination)
            & (country_data["outcome"] == "award")
            & (country_data["eligible_contestants"] >= 10)
        ].sort_values("event_rate")
        positions = np.arange(len(panel))
        rates = panel["event_rate"].to_numpy(dtype=float)
        lower = panel["wilson_lower"].to_numpy(dtype=float)
        upper = panel["wilson_upper"].to_numpy(dtype=float)
        axis.errorbar(
            rates,
            positions,
            xerr=np.vstack(
                (
                    np.maximum(0.0, rates - lower),
                    np.maximum(0.0, upper - rates),
                )
            ),
            fmt="o",
            color=color,
            ecolor=color,
            alpha=0.9,
            capsize=2,
        )
        axis.set_yticks(positions, panel["country_clean"])
        for position, (_, row) in enumerate(panel.iterrows()):
            axis.text(
                min(upper[position] + 0.012, 0.97),
                position,
                f"n={int(row['eligible_contestants'])}",
                va="center",
                fontsize=8,
                color="#555B63",
            )
        axis.set_title(f"{destination}: Five-Year Award Rate")
        axis.set_xlabel("Award Recipients / Eligible EMIC-IWYMIC Cohort")
        axis.xaxis.set_major_formatter(PercentFormatter(1.0))
        axis.set_xlim(left=0)
        axis.grid(axis="y", visible=False)
        axis.spines[["top", "right", "left"]].set_visible(False)
    figure.suptitle(
        "Country Progression Rates Require Uncertainty and Denominator Context",
        fontsize=15,
        fontweight="bold",
    )
    figure.text(
        0.5,
        0.01,
        "Wilson 95% intervals; countries with fewer than 10 eligible contestants are omitted from this figure but retained in the CSV.",
        ha="center",
        fontsize=9,
        color="#555B63",
    )
    figure.tight_layout(rect=(0, 0.04, 1, 0.95), w_pad=3)
    save_figure(figure, FIGURE_PATHS["countries"])


def plot_models(
    comparison: pd.DataFrame,
    calibration: pd.DataFrame,
) -> None:
    figure, axes = plt.subplots(2, 2, figsize=(13, 9))
    labels = [
        f"{row.destination} {row.outcome}"
        for row in comparison.itertuples(index=False)
    ]
    positions = np.arange(len(comparison))

    axis = axes[0, 0]
    estimates = comparison["delta_average_precision"].to_numpy(dtype=float)
    lower = comparison["delta_average_precision_lower"].to_numpy(dtype=float)
    upper = comparison["delta_average_precision_upper"].to_numpy(dtype=float)
    axis.errorbar(
        estimates,
        positions,
        xerr=np.vstack((estimates - lower, upper - estimates)),
        fmt="o",
        color=BLUE,
        ecolor=BLUE,
        capsize=3,
    )
    axis.axvline(0, color=GRAY, linewidth=1)
    axis.set_yticks(positions, labels)
    axis.set_title("Added Performance Signal: Average Precision")
    axis.set_xlabel("Performance Model Minus Baseline Model")
    axis.grid(axis="y", visible=False)
    axis.spines[["top", "right", "left"]].set_visible(False)

    axis = axes[0, 1]
    estimates = comparison["brier_improvement"].to_numpy(dtype=float)
    lower = comparison["brier_improvement_lower"].to_numpy(dtype=float)
    upper = comparison["brier_improvement_upper"].to_numpy(dtype=float)
    axis.errorbar(
        estimates,
        positions,
        xerr=np.vstack((estimates - lower, upper - estimates)),
        fmt="o",
        color=TEAL,
        ecolor=TEAL,
        capsize=3,
    )
    axis.axvline(0, color=GRAY, linewidth=1)
    axis.set_yticks(positions, labels)
    axis.set_title("Added Performance Signal: Brier Improvement")
    axis.set_xlabel("Baseline Brier Minus Performance Brier")
    axis.grid(axis="y", visible=False)
    axis.spines[["top", "right", "left"]].set_visible(False)

    for axis, destination in zip(axes[1], ("APMO", "IMO"), strict=True):
        panel = calibration[
            (calibration["destination"] == destination)
            & (calibration["outcome"] == "award")
        ]
        axis.plot([0, 0.35], [0, 0.35], color=GRAY, linewidth=1, linestyle="--")
        for model, color, marker in (
            ("Baseline", GRAY, "s"),
            ("Performance", BLUE, "o"),
        ):
            line = panel[panel["model"] == model]
            axis.plot(
                line["mean_predicted_probability"],
                line["observed_rate"],
                marker=marker,
                color=color,
                linewidth=1.8,
                label=model,
            )
        axis.set_title(f"{destination} Award Calibration")
        axis.set_xlabel("Mean Predicted Probability")
        axis.set_ylabel("Observed Five-Year Award Rate")
        axis.xaxis.set_major_formatter(PercentFormatter(1.0))
        axis.yaxis.set_major_formatter(PercentFormatter(1.0))
        axis.set_xlim(0, 0.35)
        axis.set_ylim(0, 0.35)
        axis.legend()
        axis.spines[["top", "right"]].set_visible(False)

    figure.suptitle(
        "Out-of-Time Predictive Value and Calibration",
        fontsize=15,
        fontweight="bold",
    )
    figure.text(
        0.5,
        0.01,
        "Baseline model: country, stage, and baseline year. Performance model adds baseline percentile, curvature, and a stage interaction. Intervals use country-cluster bootstrap resampling.",
        ha="center",
        fontsize=9,
        color="#555B63",
    )
    figure.tight_layout(rect=(0, 0.05, 1, 0.94))
    save_figure(figure, FIGURE_PATHS["models"])


def plot_cohort_coverage(coverage: pd.DataFrame) -> None:
    pivot = coverage.pivot(
        index="baseline_year", columns="baseline_stage", values="contestants"
    ).fillna(0)
    years = pivot.index.to_numpy(dtype=int)
    figure, axes = plt.subplots(
        2,
        1,
        figsize=(13, 7),
        sharex=True,
        gridspec_kw={"height_ratios": [2.2, 1]},
    )
    axes[0].bar(years, pivot.get("EMIC", 0), color=TEAL, label="EMIC")
    axes[0].bar(
        years,
        pivot.get("IWYMIC", 0),
        bottom=pivot.get("EMIC", 0),
        color=BLUE,
        label="IWYMIC",
    )
    axes[0].set_ylabel("Baseline Contestants")
    axes[0].set_title("Baseline Cohort Size by First Award Year")
    axes[0].legend()
    axes[0].spines[["top", "right"]].set_visible(False)

    follow_up = DATA_END_YEAR - years
    axes[1].plot(years, follow_up, marker="o", color=ORANGE, linewidth=2)
    axes[1].axhline(5, color=GRAY, linestyle="--", linewidth=1)
    axes[1].axvspan(2012.5, 2014.5, color=LIGHT_GRAY, alpha=0.6)
    axes[1].axvspan(
        DATA_END_YEAR - PRIMARY_WINDOW + 0.5,
        max(years) + 0.5,
        color=LIGHT_GRAY,
        alpha=0.6,
    )
    axes[1].annotate(
        "APMO Baseline Not Fully Observed",
        (2013.5, max(follow_up) - 3.0),
        ha="center",
        va="center",
        fontsize=8,
        color="#555B63",
        bbox={
            "boxstyle": "round,pad=0.2",
            "facecolor": "white",
            "edgecolor": "none",
            "alpha": 0.9,
        },
    )
    axes[1].annotate(
        "Under Five Years of Follow-Up",
        ((DATA_END_YEAR - PRIMARY_WINDOW + max(years)) / 2, 1.0),
        ha="center",
        va="center",
        fontsize=8,
        color="#555B63",
        bbox={
            "boxstyle": "round,pad=0.2",
            "facecolor": "white",
            "edgecolor": "none",
            "alpha": 0.9,
        },
    )
    axes[1].set_ylabel("Available Follow-Up (Years)", labelpad=8)
    axes[1].set_xlabel("Baseline Year")
    axes[1].set_ylim(0, max(follow_up) + 1)
    axes[1].spines[["top", "right"]].set_visible(False)
    figure.suptitle(
        "Cohort Coverage Determines Which Observations Support Five-Year Outcomes",
        fontsize=15,
        fontweight="bold",
    )
    figure.align_ylabels(axes)
    figure.tight_layout(rect=(0, 0, 1, 0.94), h_pad=1.4)
    save_figure(figure, FIGURE_PATHS["coverage"])


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, lineterminator="\n", na_rep="")


def validate_analysis(
    master: pd.DataFrame,
    cohort: pd.DataFrame,
    progression: pd.DataFrame,
    signal_bands: pd.DataFrame,
    transitions: pd.DataFrame,
    survival: pd.DataFrame,
    country_intervals: pd.DataFrame,
    predictions: pd.DataFrame,
    model_results: pd.DataFrame,
    model_comparison: pd.DataFrame,
    calibration: pd.DataFrame,
) -> list[str]:
    checks: list[str] = []
    if len(master) != 3112 or len(cohort) != 3112:
        raise RuntimeError(
            f"Expected 3112 master/cohort rows, found {len(master)}/{len(cohort)}"
        )
    if cohort["id"].tolist() != list(range(1, 3113)):
        raise RuntimeError("Analysis cohort IDs are not sequential")
    if cohort["country_clean"].nunique() != 42:
        raise RuntimeError("Analysis cohort does not contain exactly 42 countries")
    if not cohort["baseline_percentile"].between(0, 1).all():
        raise RuntimeError("Baseline percentiles fall outside [0, 1]")
    checks.append("3,112 unique IDs and 42 countries conserved from Master.csv")

    progression_by_country = progression.set_index("country_clean")
    for country, group in cohort.groupby("country_clean"):
        source = progression_by_country.loc[country]
        comparisons = {
            "emic_iwymic_unique_award_recipients": len(group),
            "later_apmo_award_recipients": int(group["apmo_later_award"].sum()),
            "later_apmo_medalists": int(group["apmo_later_medal"].sum()),
            "later_imo_award_recipients": int(group["imo_later_award"].sum()),
            "later_imo_medalists": int(group["imo_later_medal"].sum()),
        }
        for field, expected in comparisons.items():
            if int(source[field]) != expected:
                raise RuntimeError(
                    f"Progression mismatch for {country}, {field}: "
                    f"{source[field]} != {expected}"
                )
    checks.append("Unrestricted later-award counts reconcile country by country")

    for prefix in DESTINATIONS:
        for window in WINDOWS:
            eligible = cohort[f"{prefix}_{window}y_eligible"] == 1
            for outcome in ("participated", "award", "medal"):
                values = cohort.loc[eligible, f"{prefix}_{window}y_{outcome}"]
                if values.isna().any() or not values.isin([0, 1]).all():
                    raise RuntimeError(
                        f"Invalid {prefix} {window}y {outcome} outcomes"
                    )
            if not (
                cohort.loc[eligible, f"{prefix}_{window}y_medal"]
                <= cohort.loc[eligible, f"{prefix}_{window}y_award"]
            ).all():
                raise RuntimeError(f"{prefix} medal exceeds award")
            if not (
                cohort.loc[eligible, f"{prefix}_{window}y_award"]
                <= cohort.loc[eligible, f"{prefix}_{window}y_participated"]
            ).all():
                raise RuntimeError(f"{prefix} award exceeds participation")
    checks.append("Three- and five-year outcome nesting and eligibility validated")

    for (destination, stage, outcome), group in signal_bands.groupby(
        ["destination", "baseline_stage", "outcome"]
    ):
        expected = len(
            cohort[
                (cohort["baseline_stage"] == stage)
                & (cohort[f"{destination.lower()}_5y_eligible"] == 1)
            ]
        )
        if int(group["contestants"].sum()) != expected:
            raise RuntimeError(
                f"Signal bands do not conserve {destination}/{stage}/{outcome}"
            )
    checks.append("Performance-band denominators conserve eligible cohorts")

    transition_totals = transitions.groupby(
        ["destination", "baseline_stage", "baseline_medal"]
    )["percentage"].sum()
    if not np.allclose(transition_totals.to_numpy(), 100.0, atol=1e-8):
        raise RuntimeError("Outcome transition percentages do not sum to 100")
    checks.append("Every outcome-transition distribution sums to 100%")

    for (_, _), group in survival.groupby(["destination", "performance_band"]):
        probabilities = group.sort_values("year_since_baseline")[
            "cumulative_award_probability"
        ].to_numpy(dtype=float)
        if np.any(np.diff(probabilities) < -1e-12):
            raise RuntimeError("Cumulative incidence is not monotonic")
    checks.append("Cumulative award-incidence curves are monotonic")

    if len(country_intervals) != 42 * 2 * 2:
        raise RuntimeError("Country interval table has an unexpected row count")
    checks.append("Country intervals cover 42 countries, two contests, two outcomes")

    if predictions.duplicated(["destination", "outcome", "id"]).any():
        raise RuntimeError("Out-of-time predictions contain duplicate identities")
    probability_columns = ["baseline_probability", "performance_probability"]
    for column in probability_columns:
        if not predictions[column].between(0, 1).all():
            raise RuntimeError(f"Prediction column {column} falls outside [0, 1]")
    if not (predictions["test_year"] > predictions["train_through_year"]).all():
        raise RuntimeError("Temporal prediction fold leaks test years into training")
    if len(model_results) != 8 or len(model_comparison) != 4:
        raise RuntimeError("Model result tables have unexpected row counts")
    if len(calibration) != 40:
        raise RuntimeError("Calibration table has unexpected row count")
    checks.append("Forward-year predictions, metrics, and calibration validated")

    for path in FIGURE_PATHS.values():
        if not path.exists() or path.stat().st_size < 20_000:
            raise RuntimeError(f"Figure is missing or unexpectedly small: {path}")
        pixels = mpimg.imread(path)
        if pixels.shape[0] < 500 or pixels.shape[1] < 700:
            raise RuntimeError(f"Figure dimensions are too small: {path}")
        if float(np.std(pixels[..., :3])) < 0.01:
            raise RuntimeError(f"Figure appears blank: {path}")
    checks.append("All six PNG figures are nonblank and meet minimum dimensions")
    return checks


def markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    labels = [column.replace("_", " ").title() for column in columns]
    lines = ["| " + " | ".join(labels) + " |", "|" + "---|" * len(columns)]
    for _, row in frame[columns].iterrows():
        values: list[str] = []
        for column in columns:
            value = row[column]
            if isinstance(value, (float, np.floating)):
                values.append(f"{value:.3f}")
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_report(
    cohort: pd.DataFrame,
    descriptive: pd.DataFrame,
    model_results: pd.DataFrame,
    comparison: pd.DataFrame,
) -> None:
    overall = descriptive[descriptive["baseline_stage"] == "All"].copy()
    overall = overall[overall["performance_band"] != "Below 25%"]
    overall["later_apmo_award_percent"] = overall[
        "later_apmo_award_percent"
    ].round(1)
    overall["later_imo_award_percent"] = overall[
        "later_imo_award_percent"
    ].round(1)
    model_display = model_results[
        [
            "destination",
            "outcome",
            "model",
            "predictions",
            "events",
            "average_precision",
            "roc_auc",
            "brier_score",
        ]
    ].copy()
    comparison_display = comparison[
        [
            "destination",
            "outcome",
            "delta_average_precision",
            "delta_average_precision_lower",
            "delta_average_precision_upper",
            "brier_improvement",
            "brier_improvement_lower",
            "brier_improvement_upper",
        ]
    ].copy()
    apmo_eligible = int(cohort["apmo_5y_eligible"].sum())
    imo_eligible = int(cohort["imo_5y_eligible"].sum())
    lines = [
        "# EMIC/IWYMIC Performance Signal Analysis",
        "",
        f"Generated {date.today().isoformat()} from the reviewed {len(cohort):,}-identity master roster.",
        "",
        "## Question",
        "",
        "Among named EMIC/IWYMIC award recipients, does stronger performance at the first observed stage contest predict later APMO/IMO participation and awards? This is a predictive association study, not a causal estimate of contest impact.",
        "",
        "## Cohort And Outcomes",
        "",
        "- Unit: one reviewed contestant identity.",
        "- Baseline: earliest EMIC or IWYMIC award year and its percentile.",
        "- Headline window: five calendar years after baseline.",
        f"- Five-year eligible samples: {apmo_eligible:,} for APMO and {imo_eligible:,} for IMO.",
        "- APMO baseline years begin in 2015 because complete contestant-level results begin in 2016.",
        "- Award means Gold, Silver, Bronze, or Honourable Mention; medal excludes Honourable Mention.",
        "- Same-year and earlier higher-contest results are never outcomes.",
        "",
        "## Unadjusted Descriptive Signal",
        "",
        f"The unrestricted through-{DATA_END_YEAR} rates increase across the observed baseline-percentile bands:",
        "",
        markdown_table(
            overall,
            [
                "performance_band",
                "contestants",
                "later_apmo_award_percent",
                "later_imo_award_percent",
            ],
        ),
        "",
        "The result pages contain award recipients only, so there are no observations in the bottom quarter of the complete contestant field. The table cannot compare named winners with unnamed non-awardees.",
        "",
        "## Out-Of-Time Predictive Models",
        "",
        "The baseline ridge-logistic model uses country, stage, and baseline year. The performance model adds baseline percentile, a quadratic term, and a percentile-by-stage interaction. Each test cohort is predicted only from earlier baseline years.",
        "",
        markdown_table(
            model_display,
            [
                "destination",
                "outcome",
                "model",
                "predictions",
                "events",
                "average_precision",
                "roc_auc",
                "brier_score",
            ],
        ),
        "",
        "Incremental performance-model results (positive values favor adding baseline performance):",
        "",
        markdown_table(
            comparison_display,
            [
                "destination",
                "outcome",
                "delta_average_precision",
                "delta_average_precision_lower",
                "delta_average_precision_upper",
                "brier_improvement",
                "brier_improvement_lower",
                "brier_improvement_upper",
            ],
        ),
        "",
        "Country-cluster bootstrap intervals quantify uncertainty in the metric differences. Predictive lift should be judged jointly with calibration and not only by whether one interval crosses zero.",
        "",
        "## Figures",
        "",
        "1. `Figures/01 Performance Signal Curves.png`: raw quintile rates and country/year-adjusted curves.",
        "2. `Figures/02 Outcome Transitions.png`: baseline award tiers to five-year outcome classes.",
        "3. `Figures/03 Cumulative Award Incidence.png`: time to first later award with right-censoring.",
        "4. `Figures/04 Country Progression Rates.png`: five-year country estimates with Wilson intervals.",
        "5. `Figures/05 Model Comparison and Calibration.png`: out-of-time lift and calibration.",
        "6. `Figures/06 Cohort Coverage.png`: cohort size and follow-up availability.",
        "",
        "## Interpretation Rules",
        "",
        "- A rising curve is evidence of association among EMIC/IWYMIC award recipients.",
        "- Improvement over the baseline model means performance adds predictive information beyond measured country, year, and stage variables.",
        "- A persistent association is not evidence that EMIC/IWYMIC participation caused later success.",
        "- Participation and conditional performance are separate processes; never encode a nonparticipant as having zero percentile.",
        "",
        "## Limitations",
        "",
        "- Non-awarded EMIC/IWYMIC contestants are unnamed and cannot be followed.",
        "- Country selection systems, training access, age, and prior preparation are unmeasured confounders.",
        "- IWYMIC total-participant denominators are estimated, so medal-tier analyses are an important sensitivity check.",
        "- The official APMO 2026 score-level report is complete but still marked preliminary; refresh the pipeline when the source becomes final.",
        "- Recent cohorts are right-censored; fixed-window models intentionally exclude cohorts without complete follow-up.",
        "- APMO 2013-2015 lacks complete contestant-level result tables and is excluded from complete-window outcomes.",
        "",
        "## Reproduction",
        "",
        "```powershell",
        'python "2 Processing Scripts/analyze_performance_signal.py"',
        "```",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_analysis_changelog(checks: list[str]) -> None:
    output_files = sorted(
        [
            path
            for path in ANALYSIS_DIR.rglob("*")
            if path.is_file()
            and path != CHANGELOG_PATH
            and path not in PUBLICATION_REPORT_PATHS
        ],
        key=lambda path: str(path.relative_to(ANALYSIS_DIR)),
    )
    lines = [
        "Statistical Analysis changelog",
        "",
        f"Build date: {date.today().isoformat()}",
        f"Master source: {MASTER_COPY_PATH.relative_to(PROJECT_ROOT)}",
        f"Master SHA-256: {sha256(MASTER_COPY_PATH)}",
        f"Combined source SHA-256: {sha256(COMBINED_MASTER_PATH)}",
        f"Country progression source SHA-256: {sha256(COUNTRY_PROGRESSION_SUMMARY_PATH)}",
        "",
        "Methodology:",
        "- Baseline is the earliest EMIC/IWYMIC award appearance.",
        "- Primary outcomes occur within five strictly later calendar years.",
        "- APMO complete-window cohorts require baseline year 2015 or later.",
        f"- Fixed-window eligibility requires the complete window to end by {DATA_END_YEAR}.",
        "- Forward-year ridge-logistic validation never trains on the test year or a later cohort.",
        "- Country-cluster bootstrap intervals use a fixed reproducible seed.",
        "- The official APMO 2026 score-level source is included with its preliminary status retained in project documentation.",
        "",
        "Validation:",
    ]
    lines.extend(f"- {check}: passed" for check in checks)
    lines.extend(["", "Generated files:"])
    for path in output_files:
        lines.append(
            f"- {path.relative_to(ANALYSIS_DIR)} | {path.stat().st_size} bytes | "
            f"SHA-256 {sha256(path)}"
        )
    CHANGELOG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> None:
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    configure_plots()

    master = pd.read_csv(MASTER_COPY_PATH, dtype=str, keep_default_na=False)
    combined_hash = sha256(COMBINED_MASTER_PATH)
    master_hash = sha256(MASTER_COPY_PATH)
    if combined_hash != master_hash:
        raise RuntimeError("Master.csv is not an exact copy of the combined roster")
    if master["id"].astype(int).tolist() != list(range(1, len(master) + 1)):
        raise RuntimeError("Master IDs are not sequential")
    progression = pd.read_csv(COUNTRY_PROGRESSION_SUMMARY_PATH)

    cohort = build_analysis_cohort(master)
    descriptive = build_descriptive_summary(cohort)
    signal_bands = build_performance_band_summary(cohort)
    predictions, model_results, model_comparison, calibration = build_model_outputs(
        cohort
    )
    signal_curves = adjusted_signal_curves(cohort)
    transitions = build_transition_summary(cohort)
    survival = build_survival_summary(cohort)
    country_intervals = build_country_intervals(cohort)
    coverage = build_cohort_coverage(cohort)

    write_csv(cohort, COHORT_PATH)
    write_csv(descriptive, DESCRIPTIVE_PATH)
    write_csv(signal_bands, SIGNAL_BANDS_PATH)
    write_csv(signal_curves, SIGNAL_CURVES_PATH)
    write_csv(transitions, TRANSITIONS_PATH)
    write_csv(survival, SURVIVAL_PATH)
    write_csv(country_intervals, COUNTRY_INTERVALS_PATH)
    write_csv(coverage, COHORT_COVERAGE_PATH)
    write_csv(predictions, MODEL_PREDICTIONS_PATH)
    write_csv(model_results, MODEL_RESULTS_PATH)
    write_csv(model_comparison, MODEL_COMPARISON_PATH)
    write_csv(calibration, CALIBRATION_PATH)

    plot_signal_curves(signal_bands, signal_curves)
    plot_transitions(transitions)
    plot_survival(survival)
    plot_country_intervals(country_intervals)
    plot_models(model_comparison, calibration)
    plot_cohort_coverage(coverage)

    checks = validate_analysis(
        master,
        cohort,
        progression,
        signal_bands,
        transitions,
        survival,
        country_intervals,
        predictions,
        model_results,
        model_comparison,
        calibration,
    )
    write_report(cohort, descriptive, model_results, model_comparison)
    write_analysis_changelog(checks)

    print(f"Wrote {COHORT_PATH.relative_to(PROJECT_ROOT)} ({len(cohort)} rows)")
    print(
        f"Five-year eligible cohorts: APMO {int(cohort['apmo_5y_eligible'].sum())}, "
        f"IMO {int(cohort['imo_5y_eligible'].sum())}"
    )
    print(
        f"Wrote {len(FIGURE_PATHS)} verified figures and "
        f"{len(list(ANALYSIS_DIR.glob('*.csv')))} analysis CSVs"
    )
    print(f"Wrote {REPORT_PATH.relative_to(PROJECT_ROOT)}")
    print("All statistical-analysis validation checks passed.")


if __name__ == "__main__":
    run()
