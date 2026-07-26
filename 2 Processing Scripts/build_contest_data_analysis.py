#!/usr/bin/env python3
"""Build country-level master and contest analysis CSVs from the combined roster."""

from __future__ import annotations

import csv
import hashlib
import shutil
from collections import defaultdict
from datetime import date
from pathlib import Path

from project_paths import (
    COMBINED_MASTER_PATH,
    COUNTRY_ANALYSIS_DIR,
    COUNTRY_PROGRESSION_SUMMARY_PATH,
    MASTER_COPY_PATH,
    PROJECT_CHANGELOG_PATH,
    PROJECT_ROOT,
)


ROOT = PROJECT_ROOT
SOURCE_PATH = COMBINED_MASTER_PATH
OUTPUT_ROOT = COUNTRY_ANALYSIS_DIR
CHANGELOG_PATH = PROJECT_CHANGELOG_PATH
EXPECTED_COUNTRY_COUNT = 42

MASTER_FIELDS = [
    "id",
    "name_clean",
    "name_first_last",
    "EMIC_freq",
    "EMIC_years",
    "IWYMIC_freq",
    "IWYMIC_years",
    "APMO_freq",
    "APMO_years",
    "IMO_freq",
    "IMO_years",
]

CONTEST_FIELDS = [
    "id",
    "name_clean",
    "name_first_last",
    "freq",
    "years",
    "medals_by_year",
    "rank_averages_by_year",
    "percentiles_by_year",
]

PROGRESSION_FIELDS = [
    "country_clean",
    "emic_iwymic_unique_award_recipients",
    "later_apmo_award_recipients",
    "emic_iwymic_to_apmo_award_percent",
    "later_apmo_medalists",
    "emic_iwymic_to_apmo_medal_percent",
    "later_imo_award_recipients",
    "emic_iwymic_to_imo_award_percent",
    "later_imo_medalists",
    "emic_iwymic_to_imo_medal_percent",
]

HIGHER_MEDALS = frozenset({"Gold", "Silver", "Bronze"})
HIGHER_AWARDS = HIGHER_MEDALS | {"Honourable Mention"}
HIGHER_RESULTS = HIGHER_AWARDS | {"None"}

CONTESTS = [
    ("2 EMIC", "EMIC", "emic"),
    ("3 IWYMIC", "IWYMIC", "iwymic"),
    ("4 APMO", "APMO", "apmo"),
    ("5 IMO", "IMO", "imo"),
]

REQUIRED_SOURCE_FIELDS = {
    "id",
    "name_clean",
    "name_last_first",
    "country_clean",
    *{
        f"{contest}_{field}"
        for contest in ("emic", "iwymic", "apmo", "imo")
        for field in (
            "appearance_count",
            "years",
            "medals_by_year",
            "rank_averages_by_year",
            "percentiles_by_year",
        )
    },
}


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def country_file_component(country: str) -> str:
    invalid = set('<>:"/\\|?*')
    value = "".join("-" if character in invalid else character for character in country)
    value = value.strip().rstrip(".")
    if not value:
        raise RuntimeError(f"Country cannot be converted to a filename: {country!r}")
    return value


def master_row(source: dict[str, str]) -> dict[str, str]:
    output = {
        "id": source["id"],
        "name_clean": source["name_clean"],
        # The requested output header uses the reviewed source's sortable form.
        "name_first_last": source["name_last_first"],
    }
    for display, prefix in (
        ("EMIC", "emic"),
        ("IWYMIC", "iwymic"),
        ("APMO", "apmo"),
        ("IMO", "imo"),
    ):
        output[f"{display}_freq"] = source[f"{prefix}_appearance_count"]
        output[f"{display}_years"] = source[f"{prefix}_years"]
    return output


def contest_row(source: dict[str, str], prefix: str) -> dict[str, str]:
    return {
        "id": source["id"],
        "name_clean": source["name_clean"],
        "name_first_last": source["name_last_first"],
        "freq": source[f"{prefix}_appearance_count"],
        "years": source[f"{prefix}_years"],
        "medals_by_year": source[f"{prefix}_medals_by_year"],
        "rank_averages_by_year": source[f"{prefix}_rank_averages_by_year"],
        "percentiles_by_year": source[f"{prefix}_percentiles_by_year"],
    }


def year_values(value: str) -> list[int]:
    return [int(part) for part in value.split(";") if part]


def award_history(source: dict[str, str], prefix: str) -> list[tuple[int, str]]:
    entries: list[tuple[int, str]] = []
    for value in source[f"{prefix}_medals_by_year"].split(";"):
        if not value:
            continue
        if ":" not in value:
            raise RuntimeError(
                f"Source row {source['id']} has malformed {prefix} award {value!r}"
            )
        year_text, award = value.split(":", 1)
        if award not in HIGHER_RESULTS:
            raise RuntimeError(
                f"Source row {source['id']} has unknown {prefix} award {award!r}"
            )
        entries.append((int(year_text), award))
    expected_years = year_values(source[f"{prefix}_years"])
    if [year for year, _ in entries] != expected_years:
        raise RuntimeError(
            f"Source row {source['id']} has misaligned {prefix} award history"
        )
    return entries


def first_stage_award_year(source: dict[str, str]) -> int:
    stage_years = year_values(source["emic_years"]) + year_values(
        source["iwymic_years"]
    )
    if not stage_years:
        raise RuntimeError(
            f"Source row {source['id']} has no EMIC or IWYMIC award year"
        )
    return min(stage_years)


def percent_string(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        raise RuntimeError("Progression percentage denominator must be positive")
    return f"{100 * numerator / denominator:.10f}".rstrip("0").rstrip(".")


def progression_row(
    country: str,
    sources: list[dict[str, str]],
) -> dict[str, str]:
    denominator = len(sources)
    counts = {
        "apmo_awards": 0,
        "apmo_medals": 0,
        "imo_awards": 0,
        "imo_medals": 0,
    }
    for source in sources:
        first_stage_year = first_stage_award_year(source)
        for prefix in ("apmo", "imo"):
            later_results = [
                award
                for year, award in award_history(source, prefix)
                if year > first_stage_year
            ]
            if any(award in HIGHER_AWARDS for award in later_results):
                counts[f"{prefix}_awards"] += 1
            if any(award in HIGHER_MEDALS for award in later_results):
                counts[f"{prefix}_medals"] += 1

    return {
        "country_clean": country,
        "emic_iwymic_unique_award_recipients": str(denominator),
        "later_apmo_award_recipients": str(counts["apmo_awards"]),
        "emic_iwymic_to_apmo_award_percent": percent_string(
            counts["apmo_awards"], denominator
        ),
        "later_apmo_medalists": str(counts["apmo_medals"]),
        "emic_iwymic_to_apmo_medal_percent": percent_string(
            counts["apmo_medals"], denominator
        ),
        "later_imo_award_recipients": str(counts["imo_awards"]),
        "emic_iwymic_to_imo_award_percent": percent_string(
            counts["imo_awards"], denominator
        ),
        "later_imo_medalists": str(counts["imo_medals"]),
        "emic_iwymic_to_imo_medal_percent": percent_string(
            counts["imo_medals"], denominator
        ),
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_history(source: dict[str, str], prefix: str) -> None:
    frequency = int(source[f"{prefix}_appearance_count"])
    years = [value for value in source[f"{prefix}_years"].split(";") if value]
    if frequency != len(years):
        raise RuntimeError(
            f"Source row {source['id']} has {prefix} frequency {frequency} "
            f"but years {years}"
        )


def validate_written_csv(
    path: Path,
    expected_fields: list[str],
    expected_rows: list[dict[str, str]],
) -> None:
    actual_fields, actual_rows = read_csv(path)
    if actual_fields != expected_fields:
        raise RuntimeError(
            f"{path.relative_to(ROOT)} fields differ: {actual_fields}"
        )
    if actual_rows != expected_rows:
        raise RuntimeError(f"{path.relative_to(ROOT)} rows differ from source projection")


def write_changelog(
    *,
    countries: list[str],
    file_components: dict[str, str],
    by_country: dict[str, list[dict[str, str]]],
    country_counts: dict[str, dict[str, int]],
    contest_totals: dict[str, dict[str, int]],
    progression_rows: list[dict[str, str]],
) -> None:
    source_hash = sha256(SOURCE_PATH)
    master_hash = sha256(MASTER_COPY_PATH)
    lines = [
        "Contest Data Analysis changelog",
        "",
        "Changelog:",
        f"- {date.today().isoformat()}: Created the country-level analysis export.",
        f"- {date.today().isoformat()}: Generated 42 CSVs in each of five folders (210 country CSVs total).",
        f"- {date.today().isoformat()}: Copied the reviewed combined roster byte-for-byte to Master.csv.",
        f"- {date.today().isoformat()}: Added source-projection, schema, row-count, filename, ID, and appearance-total validation.",
        f"- {date.today().isoformat()}: Migrated the complete project into a self-contained Proper Case folder structure with Source Data, Processing Scripts, Processed Data, Country Analysis, and Documentation.",
        f"- {date.today().isoformat()}: Renamed human-facing datasets and country exports for readability while retaining snake_case Python and raw-cache filenames for stable automation.",
        f"- {date.today().isoformat()}: Added Winner Progression by Country.csv with chronological EMIC/IWYMIC-to-APMO/IMO award and medal rates.",
        f"- {date.today().isoformat()}: Added a reproducible Statistical Analysis stage with complete-window cohorts, forward-year model validation, survival summaries, and six figures.",
        f"- {date.today().isoformat()}: Extended official higher-contest coverage through 2026 and added a consolidated LaTeX and PDF statistical report.",
        "",
        "Source:",
        f"- {SOURCE_PATH.relative_to(ROOT)}",
        f"- SHA-256: {source_hash}",
        f"- Master.csv SHA-256: {master_hash}",
        f"- Exact-copy verification: {'passed' if source_hash == master_hash else 'FAILED'}",
        "",
        "Output organization:",
        "- 4 Country Analysis/1 Master: every EMIC/IWYMIC roster identity in the country, with frequency and year summaries for all four contests.",
        "- 4 Country Analysis/2 EMIC: country identities with at least one EMIC appearance.",
        "- 4 Country Analysis/3 IWYMIC: country identities with at least one IWYMIC appearance.",
        "- 4 Country Analysis/4 APMO: country identities from the fixed EMIC/IWYMIC roster with at least one matched APMO appearance.",
        "- 4 Country Analysis/5 IMO: country identities from the fixed EMIC/IWYMIC roster with at least one matched IMO appearance.",
        "- 4 Country Analysis/Winner Progression by Country.csv: one row per roster country with later APMO and IMO award/medal counts and percentages.",
        "- 6 Statistical Analysis: generated cohort, descriptive and model tables, Markdown report, LaTeX source, compiled PDF, validation changelog, and six figures.",
        "- A header-only CSV is retained when a country has no matched contestant in a contest.",
        "",
        "Schemas:",
        "- 1 Master country files: " + ", ".join(MASTER_FIELDS),
        "- Contest country files: " + ", ".join(CONTEST_FIELDS),
        "- Winner progression summary: " + ", ".join(PROGRESSION_FIELDS),
        "- Master.csv preserves all source columns and source encoding exactly.",
        "",
        "Naming and identity conventions:",
        "- Country filenames use the readable form '<Contest> - <Country>.csv', e.g. EMIC - South Africa.csv.",
        "- Country display names are preserved in filenames unless a Windows-invalid filename character must be replaced.",
        "- id remains the global combined-roster ID; IDs are not renumbered within countries or contests.",
        "- name_clean is the reviewed given-name-first canonical display value.",
        "- The requested name_first_last output header is populated from the source name_last_first field and therefore contains the reviewed 'Surname, Given names' sortable value.",
        "- freq is the corresponding source appearance_count, not a newly computed score or rank.",
        "- years and all by-year fields are copied without alteration from the combined source.",
        "",
        "Winner progression conventions:",
        "- The denominator is the number of unique reviewed roster identities in the country; every roster identity has at least one EMIC or IWYMIC award result.",
        "- A higher-contest result is later only when its calendar year is strictly greater than the identity's earliest EMIC/IWYMIC award year; same-year and earlier results are excluded.",
        "- Award recipient means Gold, Silver, Bronze, or Honourable Mention. Medalist means Gold, Silver, or Bronze only.",
        "- Each identity is counted at most once per destination contest and outcome, regardless of repeat appearances or awards.",
        "- Percent columns are 0-100 numeric values: 100 * later unique recipients / EMIC-IWYMIC unique award recipients.",
        "- Source coverage currently ends in 2026; rates are descriptive and right-censored for recent EMIC/IWYMIC cohorts. The official APMO 2026 source remains preliminary.",
        "",
        "Validated totals:",
        f"- Countries: {len(countries)}",
        f"- Master identities: {sum(len(by_country[country]) for country in countries)}",
    ]
    for _, display, _ in CONTESTS:
        totals = contest_totals[display]
        lines.append(
            f"- {display}: {totals['contestants']} contestant rows, "
            f"{totals['appearances']} appearances"
        )

    progression_denominator = sum(
        int(row["emic_iwymic_unique_award_recipients"])
        for row in progression_rows
    )
    lines.extend(
        [
            f"- Progression denominator: {progression_denominator} unique EMIC/IWYMIC award recipients",
            f"- Later APMO award recipients: {sum(int(row['later_apmo_award_recipients']) for row in progression_rows)}",
            f"- Later APMO medalists: {sum(int(row['later_apmo_medalists']) for row in progression_rows)}",
            f"- Later IMO award recipients: {sum(int(row['later_imo_award_recipients']) for row in progression_rows)}",
            f"- Later IMO medalists: {sum(int(row['later_imo_medalists']) for row in progression_rows)}",
        ]
    )

    lines.extend(
        [
            "",
            "Per-country contestant rows:",
            "- Country | filename component | 1 Master | 2 EMIC | 3 IWYMIC | 4 APMO | 5 IMO",
        ]
    )
    for country in countries:
        counts = country_counts[country]
        lines.append(
            f"- {country} | {file_components[country]} | {counts['Master']} | "
            f"{counts['EMIC']} | {counts['IWYMIC']} | "
            f"{counts['APMO']} | {counts['IMO']}"
        )

    lines.extend(
        [
            "",
            "Validation results:",
            "- Exactly 42 distinct source countries: passed",
            "- Exactly 42 CSVs in every output folder: passed",
            "- Exactly 210 country CSVs overall: passed",
            "- Filename country components are non-empty and unique: passed",
            "- Every generated header matches its requested schema: passed",
            "- Every generated row exactly matches its combined-source projection: passed",
            "- All source IDs are unique and sequential: passed",
            "- Every master identity has an EMIC or IWYMIC history: passed",
            "- Contestant and appearance totals reconcile to the combined source: passed",
            "- Master.csv is an exact byte copy of the combined source: passed",
            "- Winner progression summary has exactly one validated row per country: passed",
            "- Winner progression counts and percentages reconcile to individual histories: passed",
        ]
    )
    CHANGELOG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> None:
    source_fields, source_rows = read_csv(SOURCE_PATH)
    missing = REQUIRED_SOURCE_FIELDS - set(source_fields)
    if missing:
        raise RuntimeError(f"Combined source is missing fields: {sorted(missing)}")
    source_rows.sort(key=lambda row: int(row["id"]))
    source_ids = [int(row["id"]) for row in source_rows]
    if source_ids != list(range(1, len(source_rows) + 1)):
        raise RuntimeError("Combined source IDs are not unique and sequential")

    for row in source_rows:
        for _, _, prefix in CONTESTS:
            validate_history(row, prefix)
        if not int(row["emic_appearance_count"]) and not int(
            row["iwymic_appearance_count"]
        ):
            raise RuntimeError(
                f"Combined source row {row['id']} has neither EMIC nor IWYMIC history"
            )

    by_country: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in source_rows:
        by_country[row["country_clean"]].append(row)
    countries = sorted(by_country)
    if len(countries) != EXPECTED_COUNTRY_COUNT:
        raise RuntimeError(
            f"Expected {EXPECTED_COUNTRY_COUNT} countries, found {len(countries)}"
        )

    file_components = {
        country: country_file_component(country) for country in countries
    }
    if len(set(file_components.values())) != len(file_components):
        raise RuntimeError(f"Country filename collision: {file_components}")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    output_groups = [("1 Master", "Master"), *[(folder, display) for folder, display, _ in CONTESTS]]
    folder_names = [folder for folder, _ in output_groups]
    for folder_name, file_prefix in output_groups:
        folder = OUTPUT_ROOT / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        expected_names = {
            f"{file_prefix} - {file_components[country]}.csv" for country in countries
        }
        for stale_path in folder.glob("*.csv"):
            if stale_path.name not in expected_names:
                stale_path.unlink()

    country_counts: dict[str, dict[str, int]] = {}
    contest_totals = {
        display: {"contestants": 0, "appearances": 0}
        for _, display, _ in CONTESTS
    }

    for country in countries:
        country_source = by_country[country]
        master_rows = [master_row(row) for row in country_source]
        master_path = (
            OUTPUT_ROOT
            / "1 Master"
            / f"Master - {file_components[country]}.csv"
        )
        write_csv(master_path, MASTER_FIELDS, master_rows)
        validate_written_csv(master_path, MASTER_FIELDS, master_rows)

        counts = {"Master": len(master_rows)}
        for folder_name, display, prefix in CONTESTS:
            contest_rows = [
                contest_row(row, prefix)
                for row in country_source
                if int(row[f"{prefix}_appearance_count"]) > 0
            ]
            contest_path = (
                OUTPUT_ROOT
                / folder_name
                / f"{display} - {file_components[country]}.csv"
            )
            write_csv(contest_path, CONTEST_FIELDS, contest_rows)
            validate_written_csv(contest_path, CONTEST_FIELDS, contest_rows)
            counts[display] = len(contest_rows)
            contest_totals[display]["contestants"] += len(contest_rows)
            contest_totals[display]["appearances"] += sum(
                int(row["freq"]) for row in contest_rows
            )
        country_counts[country] = counts

    for folder_name in folder_names:
        csv_paths = sorted((OUTPUT_ROOT / folder_name).glob("*.csv"))
        if len(csv_paths) != EXPECTED_COUNTRY_COUNT:
            raise RuntimeError(
                f"{folder_name} has {len(csv_paths)} CSVs, expected "
                f"{EXPECTED_COUNTRY_COUNT}"
            )

    progression_rows = [
        progression_row(country, by_country[country]) for country in countries
    ]
    write_csv(
        COUNTRY_PROGRESSION_SUMMARY_PATH,
        PROGRESSION_FIELDS,
        progression_rows,
    )
    validate_written_csv(
        COUNTRY_PROGRESSION_SUMMARY_PATH,
        PROGRESSION_FIELDS,
        progression_rows,
    )
    if len(progression_rows) != EXPECTED_COUNTRY_COUNT:
        raise RuntimeError(
            f"Progression summary has {len(progression_rows)} rows, expected "
            f"{EXPECTED_COUNTRY_COUNT}"
        )

    if sum(counts["Master"] for counts in country_counts.values()) != len(
        source_rows
    ):
        raise RuntimeError("Country master rows do not reconcile to source")
    for _, display, prefix in CONTESTS:
        expected_contestants = sum(
            int(row[f"{prefix}_appearance_count"]) > 0 for row in source_rows
        )
        expected_appearances = sum(
            int(row[f"{prefix}_appearance_count"]) for row in source_rows
        )
        if contest_totals[display] != {
            "contestants": expected_contestants,
            "appearances": expected_appearances,
        }:
            raise RuntimeError(
                f"{display} totals do not reconcile: {contest_totals[display]}"
            )

    shutil.copyfile(SOURCE_PATH, MASTER_COPY_PATH)
    if sha256(SOURCE_PATH) != sha256(MASTER_COPY_PATH):
        raise RuntimeError("Master.csv is not an exact copy of the combined source")

    write_changelog(
        countries=countries,
        file_components=file_components,
        by_country=by_country,
        country_counts=country_counts,
        contest_totals=contest_totals,
        progression_rows=progression_rows,
    )

    print(
        f"Wrote {EXPECTED_COUNTRY_COUNT} country CSVs to each of "
        f"{len(folder_names)} folders ({EXPECTED_COUNTRY_COUNT * len(folder_names)} total)"
    )
    print(f"Wrote {MASTER_COPY_PATH.relative_to(ROOT)} ({len(source_rows)} rows)")
    for _, display, _ in CONTESTS:
        totals = contest_totals[display]
        print(
            f"{display}: {totals['contestants']} contestant rows, "
            f"{totals['appearances']} appearances"
        )
    print(
        f"Wrote {COUNTRY_PROGRESSION_SUMMARY_PATH.relative_to(ROOT)} "
        f"({len(progression_rows)} countries)"
    )
    print(f"Wrote {CHANGELOG_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    run()
