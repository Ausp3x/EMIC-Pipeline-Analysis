#!/usr/bin/env python3
"""Validate reviewed names and all four contest-history blocks."""

from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

from emic_name_review import (
    CHINESE_SURNAMES,
    IMO_REFERENCE,
    KOREAN_SURNAMES,
    clean_text,
    key_text,
    reviewed_source_order,
    token_key,
)
from project_paths import (
    APMO_MATCHED_PATH,
    COMBINED_MASTER_PATH,
    COUNTRY_PROGRESSION_SUMMARY_PATH,
    DUPLICATE_REVIEW_PATH as REVIEW_PATH,
    EMIC_AWARDED_PATH,
    EMIC_UNIQUE_PATH,
    IMO_MATCHED_PATH,
    IWYMIC_AWARDED_PATH,
    IWYMIC_UNIQUE_PATH,
    PROJECT_ROOT,
)


ROOT = PROJECT_ROOT
STAGES = {
    "EMIC": {
        "full": EMIC_AWARDED_PATH,
        "unique": EMIC_UNIQUE_PATH,
        "expected_appearances": 2008,
    },
    "IWYMIC": {
        "full": IWYMIC_AWARDED_PATH,
        "unique": IWYMIC_UNIQUE_PATH,
        "expected_appearances": 1900,
    },
}
COMBINED_PATH = COMBINED_MASTER_PATH
DUPLICATE_REVIEW_PATH = REVIEW_PATH
HIGHER_SUPPORT_PATHS = {
    "apmo": APMO_MATCHED_PATH,
    "imo": IMO_MATCHED_PATH,
}

EAST_ASIAN_COUNTRIES = {
    "People's Republic of China",
    "Japan",
    "Republic of Korea",
    "Taiwan",
    "Hong Kong",
    "Macau",
}
CHINESE_NAME_COUNTRIES = {
    "People's Republic of China",
    "Taiwan",
    "Hong Kong",
    "Macau",
}
ALLOWED_MONONYMS = {("Indonesia", "radian")}
REVIEWED_REVERSE_STAGE_IDENTITIES = {
    ("Malaysia", "ivan guan yu chan"),
}
REVIEWED_SOURCE_SURNAME_CORRECTIONS = {
    ("People's Republic of China", "chegn tian le"): "Cheng",
    ("Mongolia", "nyamdavaa amar"): "Nyamdavaa",
    ("Mongolia", "amar nyamdavaa"): "Nyamdavaa",
    ("Bulgaria", "viet do cuong"): "Do",
    ("Bulgaria", "ivanov lyuboslav stefanov"): "Stefanov",
    ("Bulgaria", "ivanov lyuboslav"): "Stefanov",
    ("Tajikistan", "khairidinov doriush"): "Khayridinov",
    ("Republic of Korea", "jo seong joon"): "Cho",
    ("Macau", "leung chi hou"): "Leong",
}
PARTICLES = {
    "al", "bin", "binti", "da", "de", "del", "do", "dos", "du", "la", "las",
    "los", "van", "von",
}

COMBINED_FIELDS = [
    "id",
    "name_clean",
    "name_last_first",
    "name_variants",
    "country_clean",
    "emic_appearance_count",
    "emic_years",
    "emic_medals_by_year",
    "emic_rank_averages_by_year",
    "emic_percentiles_by_year",
    "iwymic_appearance_count",
    "iwymic_years",
    "iwymic_medals_by_year",
    "iwymic_rank_averages_by_year",
    "iwymic_percentiles_by_year",
    "apmo_appearance_count",
    "apmo_years",
    "apmo_medals_by_year",
    "apmo_rank_averages_by_year",
    "apmo_percentiles_by_year",
    "imo_appearance_count",
    "imo_years",
    "imo_medals_by_year",
    "imo_rank_averages_by_year",
    "imo_percentiles_by_year",
]

HIGHER_REQUIRED_FIELDS = {
    "combined_id",
    "name_clean",
    "name_last_first",
    "country_clean",
    "contest",
    "year",
    "medal",
    "rank_start",
    "rank_end",
    "rank_average",
    "percentile",
    "total_participants",
}
DUPLICATE_REVIEW_REQUIRED_FIELDS = {
    "country_clean",
    "left_id",
    "left_name",
    "right_id",
    "right_name",
    "evidence_strength",
    "review_disposition",
    "review_note",
}

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
HIGHER_MEDALS = {"Gold", "Silver", "Bronze"}
HIGHER_AWARDS = HIGHER_MEDALS | {"Honourable Mention"}
HIGHER_RESULTS = HIGHER_AWARDS | {"None"}


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def family_from_last_first(value: str) -> str:
    value = clean_text(value)
    return value.split(",", 1)[0].strip() if "," in value else value


def given_from_last_first(value: str) -> str:
    value = clean_text(value)
    return value.split(",", 1)[1].strip() if "," in value else ""


def field_values(value: str) -> list[str]:
    return [part for part in clean_text(value).split(";") if part]


def history_years(value: str) -> list[int]:
    return [int(part) for part in field_values(value)]


def mapped_years(value: str) -> list[int]:
    return [int(part.split(":", 1)[0]) for part in field_values(value)]


def mapped_awards(value: str) -> list[tuple[int, str]]:
    return [
        (int(part.split(":", 1)[0]), part.split(":", 1)[1])
        for part in field_values(value)
    ]


def percentage_text(numerator: int, denominator: int) -> str:
    return f"{100 * numerator / denominator:.10f}".rstrip("0").rstrip(".")


def case_anomalies(value: str) -> list[str]:
    anomalies: list[str] = []
    for token in clean_text(value).replace(",", " ").split():
        pieces = [piece for piece in re.split(r"[-']", token) if piece]
        for piece in pieces:
            letters = "".join(character for character in piece if character.isalpha())
            if not letters or len(letters) == 1 or key_text(letters) in PARTICLES:
                continue
            if re.fullmatch(r"(?:[A-Z]\.)+[A-Z]?", token) or re.fullmatch(
                r"[IVXLCDM]+", letters
            ):
                continue
            if letters.islower() or letters.isupper():
                anomalies.append(token)
    return anomalies


def expected_reviewed_family(row: dict[str, str]) -> str | None:
    country = row["country_clean"]
    source = clean_text(row["name_raw"])
    correction = REVIEWED_SOURCE_SURNAME_CORRECTIONS.get((country, key_text(source)))
    if correction:
        return correction
    reviewed = reviewed_source_order(source, country, int(row["year"]))
    if reviewed:
        return family_from_last_first(reviewed[1])
    if "," in source:
        left, right = [part.strip() for part in source.split(",", 1)]
        if country == "United States of America" and int(row["year"]) == 2013:
            return re.sub(r"\s*\([^)]*\)\s*$", "", right).strip()
        return left
    return None


def check_display_name(
    *,
    label: str,
    row: dict[str, str],
    errors: list[str],
    warnings: list[str],
) -> None:
    name = clean_text(row["name_clean"])
    last_first = clean_text(row["name_last_first"])
    country = row["country_clean"]
    identity = f"{label} {country}: {name}"
    if not name or not last_first:
        errors.append(f"{identity}: blank canonical name field")
        return
    if token_key(name) != token_key(last_first):
        errors.append(f"{identity}: name_clean/name_last_first components differ ({last_first})")
    if len(name.split()) > 1 and "," not in last_first:
        errors.append(f"{identity}: multi-part name_last_first has no surname comma")
    family = family_from_last_first(last_first)
    given = given_from_last_first(last_first)
    if given and not key_text(name).endswith(key_text(family)):
        errors.append(f"{identity}: name_clean does not end in reviewed surname {family!r}")
    if not given and (country, key_text(name)) not in ALLOWED_MONONYMS:
        errors.append(f"{identity}: unexpected mononym/no surname boundary")
    anomalies = sorted(set(case_anomalies(name) + case_anomalies(last_first)))
    if anomalies:
        warnings.append(f"{identity}: review casing token(s) {', '.join(anomalies)}")


def check_histories(
    *,
    label: str,
    row: dict[str, str],
    prefix: str,
    errors: list[str],
) -> None:
    base = f"{prefix}_" if prefix else ""
    count = int(row[f"{base}appearance_count"])
    years = history_years(row[f"{base}years"])
    identity = f"{label} {row['country_clean']}: {row['name_clean']}"
    if count != len(years):
        errors.append(f"{identity}: {base}appearance_count={count}, but years={years}")
    if years != sorted(years) or len(years) != len(set(years)):
        errors.append(f"{identity}: {base}years are not unique and sorted")
    for field in ("medals_by_year", "rank_averages_by_year", "percentiles_by_year"):
        mapped = mapped_years(row[f"{base}{field}"])
        if mapped != years:
            errors.append(f"{identity}: {base}{field} years {mapped} do not match {years}")


def audit_stage(
    stage: str,
    config: dict[str, Path | int],
    errors: list[str],
    warnings: list[str],
) -> dict[str, int | list[dict[str, str]]]:
    _, full_rows = read_csv(config["full"])  # type: ignore[arg-type]
    _, unique_rows = read_csv(config["unique"])  # type: ignore[arg-type]
    expected = int(config["expected_appearances"])
    if len(full_rows) != expected:
        errors.append(f"{stage}: expected {expected} appearances, found {len(full_rows)}")
    if sum(int(row["appearance_count"]) for row in unique_rows) != len(full_rows):
        errors.append(f"{stage}: unique appearance counts do not conserve full rows")
    if [int(row["id"]) for row in unique_rows] != list(range(1, len(unique_rows) + 1)):
        errors.append(f"{stage}: unique IDs are not sequential")

    imo_matches = 0
    imo_source_overrides = 0
    east_rows = 0
    east_rule_checks = 0
    reviewed_family_checks = 0
    for row in full_rows:
        check_display_name(label=f"{stage} row {row['id']}", row=row, errors=errors, warnings=warnings)
        if row["name_key"] != key_text(row["name_clean"]):
            errors.append(f"{stage} row {row['id']}: name_key is stale")
        if row["country_key"] != key_text(row["country_clean"]):
            errors.append(f"{stage} row {row['id']}: country_key is stale")

        country = row["country_clean"]
        actual_family = family_from_last_first(row["name_last_first"])
        expected_family = expected_reviewed_family(row)
        if expected_family:
            reviewed_family_checks += 1
            if key_text(expected_family) != key_text(actual_family):
                errors.append(
                    f"{stage} row {row['id']} {country}: expected reviewed/source surname "
                    f"{expected_family!r}, found {actual_family!r} ({row['name_raw']})"
                )
        if country in EAST_ASIAN_COUNTRIES:
            east_rows += 1
            if expected_family:
                east_rule_checks += 1
            if country == "Republic of Korea" and key_text(actual_family) not in KOREAN_SURNAMES:
                warnings.append(
                    f"{stage} row {row['id']} Republic of Korea: surname {actual_family!r} "
                    "is not in the reviewed Korean surname lexicon"
                )
            if (
                country in CHINESE_NAME_COUNTRIES
                and len(actual_family.split()) == 1
                and key_text(actual_family) not in CHINESE_SURNAMES
            ):
                warnings.append(
                    f"{stage} row {row['id']} {country}: surname {actual_family!r} "
                    "is not in the reviewed Chinese surname lexicon"
                )

        reference = IMO_REFERENCE.get((key_text(country), token_key(row["name_clean"])))
        if reference:
            imo_matches += 1
            reference_family = family_from_last_first(reference[1])
            if key_text(reference_family) != key_text(actual_family):
                expected_family = expected_reviewed_family(row)
                if expected_family and key_text(expected_family) == key_text(actual_family):
                    imo_source_overrides += 1
                else:
                    errors.append(
                        f"{stage} row {row['id']} {country}: IMO surname {reference_family!r} "
                        f"disagrees with {actual_family!r}"
                    )

    for row in unique_rows:
        check_display_name(label=f"{stage} unique {row['id']}", row=row, errors=errors, warnings=warnings)
        check_histories(label=f"{stage} unique {row['id']}", row=row, prefix="", errors=errors)
        if row["name_key"] != key_text(row["name_clean"]):
            errors.append(f"{stage} unique {row['id']}: name_key is stale")
        if row["country_key"] != key_text(row["country_clean"]):
            errors.append(f"{stage} unique {row['id']}: country_key is stale")
        canonical = key_text(row["name_clean"])
        if any(clean_text(value).casefold() == clean_text(row["name_clean"]).casefold() for value in field_values(row["name_variants"])):
            errors.append(f"{stage} unique {row['id']}: canonical name repeated in name_variants")
        for variant in field_values(row["name_variants"]):
            anomalies = sorted(set(case_anomalies(variant)))
            if anomalies:
                warnings.append(
                    f"{stage} unique {row['id']}: variant {variant!r} has casing token(s) "
                    f"{', '.join(anomalies)}"
                )

    return {
        "full": len(full_rows),
        "unique": len(unique_rows),
        "east_rows": east_rows,
        "east_rule_checks": east_rule_checks,
        "reviewed_family_checks": reviewed_family_checks,
        "imo_matches": imo_matches,
        "imo_source_overrides": imo_source_overrides,
        "unique_rows": unique_rows,
    }


def audit_higher_support(
    combined_rows: list[dict[str, str]],
    errors: list[str],
) -> dict[str, dict[str, int]]:
    by_id = {int(row["id"]): row for row in combined_rows}
    stats: dict[str, dict[str, int]] = {}
    for prefix, path in HIGHER_SUPPORT_PATHS.items():
        fields, source_rows = read_csv(path)
        missing = HIGHER_REQUIRED_FIELDS - set(fields)
        if missing:
            errors.append(f"{path}: missing support fields {sorted(missing)}")
            continue

        grouped: dict[int, list[dict[str, str]]] = {}
        seen: set[tuple[int, int]] = set()
        for source in source_rows:
            combined_id = int(source["combined_id"])
            year = int(source["year"])
            target = by_id.get(combined_id)
            if target is None:
                errors.append(f"{path}: unknown combined_id {combined_id}")
                continue
            if source["contest"] != prefix.upper():
                errors.append(
                    f"{path}: row {combined_id}/{year} contest is {source['contest']}"
                )
            for field in ("name_clean", "name_last_first", "country_clean"):
                if source[field] != target[field]:
                    errors.append(
                        f"{path}: row {combined_id}/{year} has stale {field} "
                        f"{source[field]!r}"
                    )
            key = (combined_id, year)
            if key in seen:
                errors.append(f"{path}: duplicate combined_id/year {key}")
            seen.add(key)
            grouped.setdefault(combined_id, []).append(source)

            rank_start = int(source["rank_start"])
            rank_end = int(source["rank_end"])
            rank_average = float(source["rank_average"])
            total_participants = int(source["total_participants"])
            percentile = float(source["percentile"])
            if rank_start > rank_end:
                errors.append(f"{path}: inverted rank span for {key}")
            if abs(rank_average - (rank_start + rank_end) / 2) > 1e-9:
                errors.append(f"{path}: incorrect average rank for {key}")
            if abs(percentile - (1 - rank_average / total_participants)) > 1e-9:
                errors.append(f"{path}: incorrect percentile for {key}")

        for combined_id, target in by_id.items():
            appearances = sorted(
                grouped.get(combined_id, []), key=lambda row: int(row["year"])
            )
            expected = {
                f"{prefix}_appearance_count": str(len(appearances)),
                f"{prefix}_years": ";".join(row["year"] for row in appearances),
                f"{prefix}_medals_by_year": ";".join(
                    f"{row['year']}:{row['medal']}" for row in appearances
                ),
                f"{prefix}_rank_averages_by_year": ";".join(
                    f"{row['year']}:{row['rank_average']}" for row in appearances
                ),
                f"{prefix}_percentiles_by_year": ";".join(
                    f"{row['year']}:{row['percentile']}" for row in appearances
                ),
            }
            for field, expected_value in expected.items():
                if target[field] != expected_value:
                    errors.append(
                        f"Combined row {combined_id}: {field} differs from {path.name}"
                    )
        stats[prefix] = {
            "appearances": len(source_rows),
            "contestants": len(grouped),
        }
    return stats


def audit_duplicate_review(
    combined_rows: list[dict[str, str]],
    errors: list[str],
) -> dict[str, int]:
    fields, review_rows = read_csv(DUPLICATE_REVIEW_PATH)
    missing = DUPLICATE_REVIEW_REQUIRED_FIELDS - set(fields)
    if missing:
        errors.append(
            f"{DUPLICATE_REVIEW_PATH}: missing review fields {sorted(missing)}"
        )
        return {"candidates": len(review_rows), "homonym_pairs": 0}

    by_id = {int(row["id"]): row for row in combined_rows}
    reported_pairs: set[tuple[int, int]] = set()
    homonym_pairs = 0
    for review in review_rows:
        left_id = int(review["left_id"])
        right_id = int(review["right_id"])
        pair = tuple(sorted((left_id, right_id)))
        if pair in reported_pairs:
            errors.append(f"Duplicate-review report repeats candidate pair {pair}")
        reported_pairs.add(pair)

        left = by_id.get(left_id)
        right = by_id.get(right_id)
        if left is None or right is None:
            errors.append(f"Duplicate-review report references unknown IDs {pair}")
            continue
        for side, source, expected_name in (
            ("left", left, review["left_name"]),
            ("right", right, review["right_name"]),
        ):
            if source["name_clean"] != expected_name:
                errors.append(
                    f"Duplicate-review {pair}: stale {side} name {expected_name!r}"
                )
            if source["country_clean"] != review["country_clean"]:
                errors.append(
                    f"Duplicate-review {pair}: stale {side} country "
                    f"{review['country_clean']!r}"
                )
        disposition = review["review_disposition"]
        if not disposition or disposition in {"unreviewed", "merge_required"}:
            errors.append(
                f"Duplicate-review {pair}: unresolved disposition {disposition!r}"
            )
        if not review["review_note"]:
            errors.append(f"Duplicate-review {pair}: blank review note")
        if key_text(left["name_clean"]) == key_text(right["name_clean"]):
            homonym_pairs += 1

    same_name_groups: dict[tuple[str, str], list[int]] = {}
    for row in combined_rows:
        same_name_groups.setdefault(
            (row["country_clean"], key_text(row["name_clean"])), []
        ).append(int(row["id"]))
    for ids in same_name_groups.values():
        if len(ids) < 2:
            continue
        for index, left_id in enumerate(ids):
            for right_id in ids[index + 1 :]:
                pair = tuple(sorted((left_id, right_id)))
                if pair not in reported_pairs:
                    errors.append(
                        f"Exact-name homonym pair {pair} is absent from duplicate review"
                    )

    return {"candidates": len(review_rows), "homonym_pairs": homonym_pairs}


def audit_country_progression(
    combined_rows: list[dict[str, str]],
    errors: list[str],
) -> dict[str, int]:
    if not COUNTRY_PROGRESSION_SUMMARY_PATH.exists():
        errors.append(
            "Country progression summary is missing; rerun "
            "build_contest_data_analysis.py"
        )
        return {
            "countries": 0,
            "denominator": 0,
            "apmo_awards": 0,
            "apmo_medals": 0,
            "imo_awards": 0,
            "imo_medals": 0,
        }

    fields, actual_rows = read_csv(COUNTRY_PROGRESSION_SUMMARY_PATH)
    if fields != PROGRESSION_FIELDS:
        errors.append(f"Country progression fields differ: {fields}")

    by_country: dict[str, list[dict[str, str]]] = {}
    for row in combined_rows:
        by_country.setdefault(row["country_clean"], []).append(row)

    expected_rows: list[dict[str, str]] = []
    for country in sorted(by_country):
        country_rows = by_country[country]
        counts = {
            "apmo_awards": 0,
            "apmo_medals": 0,
            "imo_awards": 0,
            "imo_medals": 0,
        }
        for row in country_rows:
            stage_years = history_years(row["emic_years"]) + history_years(
                row["iwymic_years"]
            )
            if not stage_years:
                errors.append(
                    f"Combined row {row['id']} has no stage year for progression"
                )
                continue
            first_stage_year = min(stage_years)
            for prefix in ("apmo", "imo"):
                history = mapped_awards(row[f"{prefix}_medals_by_year"])
                unknown = sorted(
                    {award for _, award in history if award not in HIGHER_RESULTS}
                )
                if unknown:
                    errors.append(
                        f"Combined row {row['id']} has unknown {prefix} "
                        f"progression result(s): {unknown}"
                    )
                later_awards = [
                    award for year, award in history if year > first_stage_year
                ]
                if any(award in HIGHER_AWARDS for award in later_awards):
                    counts[f"{prefix}_awards"] += 1
                if any(award in HIGHER_MEDALS for award in later_awards):
                    counts[f"{prefix}_medals"] += 1

        denominator = len(country_rows)
        expected_rows.append(
            {
                "country_clean": country,
                "emic_iwymic_unique_award_recipients": str(denominator),
                "later_apmo_award_recipients": str(counts["apmo_awards"]),
                "emic_iwymic_to_apmo_award_percent": percentage_text(
                    counts["apmo_awards"], denominator
                ),
                "later_apmo_medalists": str(counts["apmo_medals"]),
                "emic_iwymic_to_apmo_medal_percent": percentage_text(
                    counts["apmo_medals"], denominator
                ),
                "later_imo_award_recipients": str(counts["imo_awards"]),
                "emic_iwymic_to_imo_award_percent": percentage_text(
                    counts["imo_awards"], denominator
                ),
                "later_imo_medalists": str(counts["imo_medals"]),
                "emic_iwymic_to_imo_medal_percent": percentage_text(
                    counts["imo_medals"], denominator
                ),
            }
        )

    if actual_rows != expected_rows:
        actual_by_country = {
            row.get("country_clean", ""): row for row in actual_rows
        }
        expected_by_country = {
            row["country_clean"]: row for row in expected_rows
        }
        differing = [
            country
            for country in sorted(set(actual_by_country) | set(expected_by_country))
            if actual_by_country.get(country) != expected_by_country.get(country)
        ]
        errors.append(
            "Country progression rows differ from independently recomputed "
            f"histories for: {differing}"
        )

    return {
        "countries": len(expected_rows),
        "denominator": sum(
            int(row["emic_iwymic_unique_award_recipients"])
            for row in expected_rows
        ),
        "apmo_awards": sum(
            int(row["later_apmo_award_recipients"]) for row in expected_rows
        ),
        "apmo_medals": sum(
            int(row["later_apmo_medalists"]) for row in expected_rows
        ),
        "imo_awards": sum(
            int(row["later_imo_award_recipients"]) for row in expected_rows
        ),
        "imo_medals": sum(
            int(row["later_imo_medalists"]) for row in expected_rows
        ),
    }


def audit_combined(
    stage_stats: dict[str, dict[str, int | list[dict[str, str]]]],
    errors: list[str],
    warnings: list[str],
) -> dict[str, int]:
    fields, rows = read_csv(COMBINED_PATH)
    if fields != COMBINED_FIELDS:
        errors.append(f"Combined CSV fields differ: {fields}")
    if [int(row["id"]) for row in rows] != list(range(1, len(rows) + 1)):
        errors.append("Combined IDs are not sequential")

    both = 0
    for row in rows:
        check_display_name(label=f"Combined row {row['id']}", row=row, errors=errors, warnings=warnings)
        check_histories(label=f"Combined row {row['id']}", row=row, prefix="emic", errors=errors)
        check_histories(label=f"Combined row {row['id']}", row=row, prefix="iwymic", errors=errors)
        check_histories(label=f"Combined row {row['id']}", row=row, prefix="apmo", errors=errors)
        check_histories(label=f"Combined row {row['id']}", row=row, prefix="imo", errors=errors)
        emic_years = set(history_years(row["emic_years"]))
        iwymic_years = set(history_years(row["iwymic_years"]))
        if emic_years and iwymic_years:
            both += 1
            if emic_years & iwymic_years:
                errors.append(
                    f"Combined row {row['id']}: same-year EMIC/IWYMIC overlap "
                    f"{sorted(emic_years & iwymic_years)}"
                )
            if max(emic_years) >= min(iwymic_years) and (
                row["country_clean"], key_text(row["name_clean"])
            ) not in REVIEWED_REVERSE_STAGE_IDENTITIES:
                errors.append(
                    f"Combined row {row['id']}: unsupported reverse-stage chronology "
                    f"EMIC {sorted(emic_years)} / IWYMIC {sorted(iwymic_years)}"
                )
        if any(clean_text(value).casefold() == clean_text(row["name_clean"]).casefold() for value in field_values(row["name_variants"])):
            errors.append(f"Combined row {row['id']}: canonical name repeated in name_variants")
        for variant in field_values(row["name_variants"]):
            anomalies = sorted(set(case_anomalies(variant)))
            if anomalies:
                warnings.append(
                    f"Combined row {row['id']}: variant {variant!r} has casing token(s) "
                    f"{', '.join(anomalies)}"
                )

    emic_total = sum(int(row["emic_appearance_count"]) for row in rows)
    iwymic_total = sum(int(row["iwymic_appearance_count"]) for row in rows)
    if emic_total != int(stage_stats["EMIC"]["full"]):
        errors.append(f"Combined EMIC appearances changed: {emic_total}")
    if iwymic_total != int(stage_stats["IWYMIC"]["full"]):
        errors.append(f"Combined IWYMIC appearances changed: {iwymic_total}")
    expected_rows = (
        int(stage_stats["EMIC"]["unique"])
        + int(stage_stats["IWYMIC"]["unique"])
        - both
    )
    if len(rows) != expected_rows:
        errors.append(f"Combined row count {len(rows)} does not equal {expected_rows}")
    higher = audit_higher_support(rows, errors)
    duplicate_review = audit_duplicate_review(rows, errors)
    progression = audit_country_progression(rows, errors)
    return {
        "rows": len(rows),
        "both": both,
        "emic_total": emic_total,
        "iwymic_total": iwymic_total,
        "apmo_total": higher.get("apmo", {}).get("appearances", 0),
        "imo_total": higher.get("imo", {}).get("appearances", 0),
        "apmo_contestants": higher.get("apmo", {}).get("contestants", 0),
        "imo_contestants": higher.get("imo", {}).get("contestants", 0),
        "duplicate_candidates": duplicate_review["candidates"],
        "homonym_pairs": duplicate_review["homonym_pairs"],
        "progression_countries": progression["countries"],
        "progression_denominator": progression["denominator"],
        "progression_apmo_awards": progression["apmo_awards"],
        "progression_apmo_medals": progression["apmo_medals"],
        "progression_imo_awards": progression["imo_awards"],
        "progression_imo_medals": progression["imo_medals"],
    }


def main() -> int:
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    errors: list[str] = []
    warnings: list[str] = []
    stage_stats = {
        stage: audit_stage(stage, config, errors, warnings)
        for stage, config in STAGES.items()
    }
    combined = audit_combined(stage_stats, errors, warnings)

    for stage, stats in stage_stats.items():
        print(
            f"{stage}: {stats['full']} appearances, {stats['unique']} unique; "
            f"reviewed/source surname boundaries checked {stats['reviewed_family_checks']} rows "
            f"({stats['east_rule_checks']}/{stats['east_rows']} East Asian); "
            f"IMO exact-token references {stats['imo_matches']} "
            f"({stats['imo_source_overrides']} source-order overrides)"
        )
    print(
        f"Combined: {combined['rows']} rows, {combined['both']} cross-stage identities; "
        f"appearances {combined['emic_total']} EMIC + {combined['iwymic_total']} IWYMIC + "
        f"{combined['apmo_total']} APMO + {combined['imo_total']} IMO; "
        f"higher-contest identities {combined['apmo_contestants']} APMO / "
        f"{combined['imo_contestants']} IMO"
    )
    print(
        f"Duplicate review: {combined['duplicate_candidates']} candidate pairs, "
        f"including {combined['homonym_pairs']} exact-name homonym pairs; "
        "all require a completed disposition and note"
    )
    print(
        f"Progression summary: {combined['progression_countries']} countries / "
        f"{combined['progression_denominator']} EMIC-IWYMIC award recipients; "
        f"later APMO {combined['progression_apmo_awards']} awards / "
        f"{combined['progression_apmo_medals']} medals; later IMO "
        f"{combined['progression_imo_awards']} awards / "
        f"{combined['progression_imo_medals']} medals"
    )

    unique_warnings = list(dict.fromkeys(warnings))
    if unique_warnings:
        print(f"Warnings ({len(unique_warnings)}):")
        for warning in unique_warnings:
            print(f"- {warning}")
    if errors:
        print(f"Errors ({len(errors)}):")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        "All structural, surname-order, casing, rank, percentile, history, "
        "progression, and conservation checks passed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
