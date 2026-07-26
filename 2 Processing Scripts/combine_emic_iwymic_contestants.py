#!/usr/bin/env python3
"""Combine the reviewed EMIC and IWYMIC unique-contestant tables."""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from emic_name_review import CROSS_STAGE_CANONICAL_RULES, clean_text, key_text, token_key
from project_paths import (
    APMO_MATCHED_PATH,
    COMBINED_CHANGELOG_PATH,
    COMBINED_MASTER_PATH,
    COMBINED_PROCESSED_DIR,
    EMIC_UNIQUE_PATH,
    IMO_MATCHED_PATH,
    IWYMIC_UNIQUE_PATH,
    PROJECT_ROOT,
)


ROOT = PROJECT_ROOT
EMIC_PATH = EMIC_UNIQUE_PATH
IWYMIC_PATH = IWYMIC_UNIQUE_PATH
OUT_DIR = COMBINED_PROCESSED_DIR
OUT_PATH = COMBINED_MASTER_PATH
CHANGELOG_PATH = COMBINED_CHANGELOG_PATH
HIGHER_APPEARANCE_PATHS = {
    "apmo": APMO_MATCHED_PATH,
    "imo": IMO_MATCHED_PATH,
}

HISTORY_FIELDS = (
    "appearance_count",
    "years",
    "medals_by_year",
    "rank_averages_by_year",
    "percentiles_by_year",
)

BASE_OUTPUT_FIELDS = [
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
]
OUTPUT_FIELDS = [
    *BASE_OUTPUT_FIELDS,
    *[f"apmo_{field}" for field in HISTORY_FIELDS],
    *[f"imo_{field}" for field in HISTORY_FIELDS],
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

REQUIRED_INPUT_FIELDS = {
    "id",
    "name_clean",
    "name_last_first",
    "name_key",
    "name_variants",
    "country_clean",
    "country_key",
    "appearance_count",
    "years",
    "medals_by_year",
    "rank_averages_by_year",
    "percentiles_by_year",
}

REVIEWED_REVERSE_STAGE_IDENTITIES = {
    ("malaysia", "ivan guan yu chan"),
}


@dataclass(frozen=True)
class StageRecord:
    stage: str
    row: dict[str, str]

    @property
    def uid(self) -> tuple[str, str]:
        return self.stage, self.row["id"]

    @property
    def years(self) -> set[int]:
        return {int(value) for value in self.row["years"].split(";") if value}

    @property
    def identity_keys(self) -> set[str]:
        return {
            key_text(value)
            for value in self.display_names
            if clean_text(value)
        }

    @property
    def token_keys(self) -> set[str]:
        return {
            token_key(value)
            for value in self.display_names
            if clean_text(value)
        }

    @property
    def display_names(self) -> list[str]:
        return [
            self.row["name_clean"],
            *[value for value in self.row["name_variants"].split(";") if value],
        ]


def stage_progression_allowed(left: StageRecord, right: StageRecord) -> bool:
    if left.years & right.years:
        return False
    if max(left.years) < min(right.years):
        return True
    shared_names = left.identity_keys & right.identity_keys
    return any(
        (left.row["country_key"], name_key) in REVIEWED_REVERSE_STAGE_IDENTITIES
        for name_key in shared_names
    )


def read_records(path: Path, stage: str) -> list[StageRecord]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_INPUT_FIELDS - set(reader.fieldnames or [])
        if missing:
            raise RuntimeError(f"{path} is missing required fields: {sorted(missing)}")
        return [StageRecord(stage, dict(row)) for row in reader]


def candidate_edges(
    emic: list[StageRecord],
    iwymic: list[StageRecord],
    *,
    key_attribute: str,
    used: set[tuple[str, str]],
    allow_year_overlap: bool = False,
) -> list[tuple[StageRecord, StageRecord]]:
    right_index: dict[tuple[str, str], list[StageRecord]] = defaultdict(list)
    for record in iwymic:
        if record.uid in used:
            continue
        for value in getattr(record, key_attribute):
            right_index[(record.row["country_key"], value)].append(record)

    edges: set[tuple[tuple[str, str], tuple[str, str]]] = set()
    by_uid = {record.uid: record for record in [*emic, *iwymic]}
    for left in emic:
        if left.uid in used:
            continue
        for value in getattr(left, key_attribute):
            for right in right_index.get((left.row["country_key"], value), []):
                if allow_year_overlap or stage_progression_allowed(left, right):
                    edges.add((left.uid, right.uid))
    return [(by_uid[left], by_uid[right]) for left, right in sorted(edges)]


def mutual_unique_pairs(
    edges: list[tuple[StageRecord, StageRecord]],
) -> list[tuple[StageRecord, StageRecord]]:
    left_degree = Counter(left.uid for left, _ in edges)
    right_degree = Counter(right.uid for _, right in edges)
    return [
        (left, right)
        for left, right in edges
        if left_degree[left.uid] == 1 and right_degree[right.uid] == 1
    ]


def canonical_score(record: StageRecord) -> tuple[int, int, int, int, int]:
    tokens = clean_text(record.row["name_clean"]).replace(",", " ").split()
    initials = sum(bool(re.fullmatch(r"[A-Za-z]\.?", token)) for token in tokens)
    non_ascii = sum(ord(character) > 127 for character in record.row["name_clean"])
    return (
        len(tokens) - initials,
        -initials,
        non_ascii,
        len(record.row["name_clean"]),
        1 if record.stage == "iwymic" else 0,
    )


def merged_row(
    emic: StageRecord | None,
    iwymic: StageRecord | None,
) -> dict[str, str | int]:
    records = [record for record in (emic, iwymic) if record]
    canonical = max(records, key=canonical_score)
    canonical_name = canonical.row["name_clean"]

    variants = {
        clean_text(value)
        for record in records
        for value in record.display_names
        if clean_text(value).casefold() != clean_text(canonical_name).casefold()
    }

    output: dict[str, str | int] = {
        "id": 0,
        "name_clean": canonical_name,
        "name_last_first": canonical.row["name_last_first"],
        "name_variants": ";".join(sorted(variants, key=lambda value: value.casefold())),
        "country_clean": canonical.row["country_clean"],
    }
    for prefix, record in (("emic", emic), ("iwymic", iwymic)):
        output[f"{prefix}_appearance_count"] = int(record.row["appearance_count"]) if record else 0
        for field in (
            "years",
            "medals_by_year",
            "rank_averages_by_year",
            "percentiles_by_year",
        ):
            output[f"{prefix}_{field}"] = record.row[field] if record else ""
    for prefix in ("apmo", "imo"):
        output[f"{prefix}_appearance_count"] = 0
        for field in HISTORY_FIELDS[1:]:
            output[f"{prefix}_{field}"] = ""
    return output


def history_years(value: object) -> list[int]:
    return [int(part) for part in str(value).split(";") if part]


def mapped_years(value: object) -> list[int]:
    return [
        int(part.split(":", 1)[0])
        for part in str(value).split(";")
        if part
    ]


def attach_higher_histories(
    rows: list[dict[str, str | int]],
) -> dict[str, dict[str, int]]:
    by_id = {int(row["id"]): row for row in rows}
    stats: dict[str, dict[str, int]] = {}
    for prefix, path in HIGHER_APPEARANCE_PATHS.items():
        if not path.exists():
            raise RuntimeError(
                f"{path.relative_to(ROOT)} is missing; run extract_apmo_imo_results.py "
                "after a --base-only combined build"
            )
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = HIGHER_REQUIRED_FIELDS - set(reader.fieldnames or [])
            if missing:
                raise RuntimeError(f"{path} is missing fields: {sorted(missing)}")
            source_rows = [dict(row) for row in reader]

        grouped: dict[int, list[dict[str, str]]] = defaultdict(list)
        seen: set[tuple[int, int]] = set()
        for source in source_rows:
            combined_id = int(source["combined_id"])
            year = int(source["year"])
            target = by_id.get(combined_id)
            if target is None:
                raise RuntimeError(f"{path}: unknown combined_id {combined_id}")
            if source["contest"] != prefix.upper():
                raise RuntimeError(
                    f"{path}: expected contest {prefix.upper()}, got {source['contest']}"
                )
            for field in ("name_clean", "name_last_first", "country_clean"):
                if source[field] != str(target[field]):
                    raise RuntimeError(
                        f"{path}: combined_id {combined_id} has stale {field}: "
                        f"{source[field]!r} != {target[field]!r}"
                    )
            key = (combined_id, year)
            if key in seen:
                raise RuntimeError(f"{path}: duplicate combined_id/year {key}")
            seen.add(key)

            rank_start = int(source["rank_start"])
            rank_end = int(source["rank_end"])
            rank_average = float(source["rank_average"])
            total_participants = int(source["total_participants"])
            percentile = float(source["percentile"])
            if rank_start > rank_end:
                raise RuntimeError(f"{path}: inverted rank span for {key}")
            if abs(rank_average - (rank_start + rank_end) / 2) > 1e-9:
                raise RuntimeError(f"{path}: incorrect average rank for {key}")
            if abs(percentile - (1 - rank_average / total_participants)) > 1e-9:
                raise RuntimeError(f"{path}: incorrect percentile for {key}")
            grouped[combined_id].append(source)

        for combined_id, appearances in grouped.items():
            appearances.sort(key=lambda row: int(row["year"]))
            target = by_id[combined_id]
            target[f"{prefix}_appearance_count"] = len(appearances)
            target[f"{prefix}_years"] = ";".join(row["year"] for row in appearances)
            target[f"{prefix}_medals_by_year"] = ";".join(
                f"{row['year']}:{row['medal']}" for row in appearances
            )
            target[f"{prefix}_rank_averages_by_year"] = ";".join(
                f"{row['year']}:{row['rank_average']}" for row in appearances
            )
            target[f"{prefix}_percentiles_by_year"] = ";".join(
                f"{row['year']}:{row['percentile']}" for row in appearances
            )
        stats[prefix] = {
            "appearances": len(source_rows),
            "contestants": len(grouped),
        }
    return stats


def validate_output(
    rows: list[dict[str, str | int]],
    emic: list[StageRecord],
    iwymic: list[StageRecord],
    pairs: list[tuple[StageRecord, StageRecord]],
    higher_stats: dict[str, dict[str, int]],
) -> None:
    expected_count = len(emic) + len(iwymic) - len(pairs)
    if len(rows) != expected_count:
        raise RuntimeError(f"Expected {expected_count} combined rows, got {len(rows)}")
    if sum(int(row["emic_appearance_count"]) for row in rows) != sum(
        int(record.row["appearance_count"]) for record in emic
    ):
        raise RuntimeError("EMIC appearance counts changed during combination")
    if sum(int(row["iwymic_appearance_count"]) for row in rows) != sum(
        int(record.row["appearance_count"]) for record in iwymic
    ):
        raise RuntimeError("IWYMIC appearance counts changed during combination")

    for prefix in ("emic", "iwymic", "apmo", "imo"):
        for row in rows:
            count = int(row[f"{prefix}_appearance_count"])
            years = history_years(row[f"{prefix}_years"])
            if count != len(years):
                raise RuntimeError(
                    f"Combined ID {row['id']}: {prefix} count {count} != years {years}"
                )
            if years != sorted(set(years)):
                raise RuntimeError(
                    f"Combined ID {row['id']}: {prefix} years are not unique and sorted"
                )
            for field in (
                "medals_by_year",
                "rank_averages_by_year",
                "percentiles_by_year",
            ):
                if mapped_years(row[f"{prefix}_{field}"]) != years:
                    raise RuntimeError(
                        f"Combined ID {row['id']}: {prefix}_{field} years do not align"
                    )

    for prefix, stats in higher_stats.items():
        attached = sum(int(row[f"{prefix}_appearance_count"]) for row in rows)
        if attached != stats["appearances"]:
            raise RuntimeError(
                f"{prefix.upper()} appearance counts changed: {attached} != "
                f"{stats['appearances']}"
            )

    for row in rows:
        if token_key(str(row["name_clean"])) != token_key(str(row["name_last_first"])):
            raise RuntimeError(
                f"Canonical display mismatch: {row['name_clean']} / {row['name_last_first']}"
            )


def write_changelog(
    *,
    emic: list[StageRecord],
    iwymic: list[StageRecord],
    rows: list[dict[str, str | int]],
    exact_pairs: list[tuple[StageRecord, StageRecord]],
    token_pairs: list[tuple[StageRecord, StageRecord]],
    overlap_edges: list[tuple[StageRecord, StageRecord]],
    chronology_edges: list[tuple[StageRecord, StageRecord]],
    ambiguous_edges: list[tuple[StageRecord, StageRecord]],
    higher_stats: dict[str, dict[str, int]],
    higher_attached: bool,
) -> None:
    paired_count = len(exact_pairs) + len(token_pairs)
    both_count = sum(
        bool(row["emic_appearance_count"] and row["iwymic_appearance_count"])
        for row in rows
    )
    lines = [
        "Combined EMIC / IWYMIC unique-contestant changelog",
        "",
        "Changelog:",
        "- 2026-07-18: Created the combined unique-contestant dataset from the reviewed Keystage II and Keystage III outputs.",
        "- 2026-07-18: Kept EMIC and IWYMIC appearance histories in separate prefixed columns for future contest expansion.",
        "- 2026-07-18: Required cross-stage matches to be mutual one-to-one candidates with no overlapping contest year.",
        "- 2026-07-18: Applied shared reviewed full-name/spelling identities before combining; source alternatives remain in name_variants.",
        "- 2026-07-18: Re-ran within-stage and cross-stage near-match review; merged only supported aliases and retained substantive or same-name ambiguities as separate records.",
        "- 2026-07-18: Wrote the combined CSV as plain UTF-8 without a byte-order mark so the first header imports exactly as id.",
        "- 2026-07-19: Added five APMO and five IMO history columns while keeping the EMIC/IWYMIC-derived identity roster fixed.",
        "- 2026-07-19: Attached only official higher-contest appearances matched to an existing combined ID; unmatched official contestants cannot create rows.",
        "- 2026-07-19: Computed higher-contest average ranks from global total-score tie spans and percentiles as 1 - rank_average / total_participants.",
        "- 2026-07-22: Completed a final country-by-country duplicate review across the combined roster and canonicalized 24 supported duplicate identities, including initials, omitted patronymics, and reviewed romanization variants.",
        "- 2026-07-22: Preserved same-year official-ID homonyms and unresolved common-name collisions as separate records rather than forcing an unsupported merge.",
        "- 2026-07-22: Corrected two exact-name over-merges by applying stage-age span guards: Ivan Safonov (EMIC 2013/2023) and Nhat Minh Nguyen (IWYMIC 2018/2022) are now separate identities.",
        "- 2026-07-22: Added a forward-stage chronology gate for automatic EMIC/IWYMIC matching and documented Ivan Guan Yu Chan as the sole reviewed reverse-stage exception, supported by the same full name in official APMO 2022 and IMO 2024-2025 records.",
        "- 2026-07-23: Extended attached APMO and IMO histories through 2026; the official APMO 2026 source is still marked preliminary.",
        "",
        "Inputs:",
        f"- {EMIC_PATH.relative_to(ROOT)}: {len(emic)} unique records, {sum(int(record.row['appearance_count']) for record in emic)} appearances",
        f"- {IWYMIC_PATH.relative_to(ROOT)}: {len(iwymic)} unique records, {sum(int(record.row['appearance_count']) for record in iwymic)} appearances",
        *(
            [
                f"- {HIGHER_APPEARANCE_PATHS['apmo'].relative_to(ROOT)}: {higher_stats['apmo']['appearances']} matched appearances",
                f"- {HIGHER_APPEARANCE_PATHS['imo'].relative_to(ROOT)}: {higher_stats['imo']['appearances']} matched appearances",
            ]
            if higher_attached
            else ["- Higher-contest histories intentionally omitted for this --base-only build."]
        ),
        "",
        "Output:",
        f"- {OUT_PATH.relative_to(ROOT)}: {len(rows)} combined records",
        f"- Records with both EMIC and IWYMIC histories: {both_count}",
        f"- Cross-stage records merged: {paired_count}",
        f"- Exact canonical/variant mutual matches: {len(exact_pairs)}",
        f"- Token-order mutual matches: {len(token_pairs)}",
        f"- Records with APMO histories: {sum(int(row['apmo_appearance_count']) > 0 for row in rows)}",
        f"- Records with IMO histories: {sum(int(row['imo_appearance_count']) > 0 for row in rows)}",
        f"- Attached APMO appearances: {sum(int(row['apmo_appearance_count']) for row in rows)}",
        f"- Attached IMO appearances: {sum(int(row['imo_appearance_count']) for row in rows)}",
        "",
        "Identity policy:",
        "- Country must match exactly after IMO country-name normalization.",
        "- A shared canonical name or observed name variant is the primary match key.",
        "- A token-order match is considered only after primary matching and only when unique in both directions.",
        "- Any same-year EMIC/IWYMIC overlap is rejected because one contestant cannot be assumed to occupy both keystages in the same contest.",
        "- Automatic cross-stage matches require the EMIC history to precede the IWYMIC history; Ivan Guan Yu Chan is the sole reviewed exception (IWYMIC 2021 / EMIC 2022), corroborated by official APMO and IMO records.",
        "- Ivan Guan Yu Chan reference: https://www.apmo-official.org/country_report/MYS/2022",
        "- Ivan Guan Yu Chan reference: https://www.imo-official.org/country_individual_r.aspx?code=MAS",
        "- Ambiguous one-to-many candidates remain separate rather than assigning an unsupported identity.",
        '- Run python "2 Processing Scripts/review_duplicate_name_candidates.py" to reproduce the final all-country duplicate-candidate review and its dispositions.',
        "- APMO/IMO matching never expands the roster: it resolves official names only against IDs already created from EMIC and IWYMIC.",
        "- Non-exact higher-contest aliases require an explicit reviewed rule; unresolved fuzzy candidates remain in 3 Processed Data/Higher Contests/APMO and IMO Match Review.csv.",
        "",
        "Shared reviewed canonical identities:",
        *[f"- {rule['country']}: {rule['note']}" for rule in CROSS_STAGE_CANONICAL_RULES],
        "",
        "Rejected same-year candidate pairs:",
    ]
    if overlap_edges:
        for left, right in overlap_edges:
            years = ", ".join(str(year) for year in sorted(left.years & right.years))
            lines.append(
                f"- {left.row['country_clean']}: {left.row['name_clean']} "
                f"(EMIC {left.row['years']}; IWYMIC {right.row['years']}); overlapping year(s): {years}."
            )
    else:
        lines.append("- None.")

    lines.extend(["", "Rejected reverse-stage candidate pairs:"])
    if chronology_edges:
        for left, right in chronology_edges:
            lines.append(
                f"- {left.row['country_clean']}: {left.row['name_clean']} "
                f"(EMIC {left.row['years']}; IWYMIC {right.row['years']}); "
                "the older-stage history precedes the younger-stage history."
            )
    else:
        lines.append("- None beyond the documented Ivan Guan Yu Chan exception.")

    lines.extend(["", "Ambiguous non-overlapping candidate pairs kept separate:"])
    if ambiguous_edges:
        seen: set[tuple[str, str, str]] = set()
        for left, right in ambiguous_edges:
            note_key = (
                left.row["country_clean"],
                left.row["name_clean"],
                right.row["name_clean"],
            )
            if note_key in seen:
                continue
            seen.add(note_key)
            lines.append(
                f"- {left.row['country_clean']}: {left.row['name_clean']} "
                f"(EMIC {left.row['years']}) / {right.row['name_clean']} "
                f"(IWYMIC {right.row['years']})."
            )
    else:
        lines.append("- None.")

    lines.extend(
        [
            "",
            "Column notes:",
            "- Empty contest-history fields mean the contestant has no reviewed appearance in that contest dataset.",
            "- Missing-contest appearance_count is 0; all other missing-contest fields are blank.",
            "- Semicolons separate multiple years, medals, ranks, percentiles, and name variants.",
            "- APMO coverage is 2016-2026; complete contestant-level official scores were not available for earlier public editions, and the official 2026 report remains preliminary.",
            "- IMO coverage is 2013-2026, the completed editions overlapping and following the EMIC/IWYMIC study period.",
            "- A higher-contest medal value of None records an appearance without an official award.",
        ]
    )
    CHANGELOG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(*, base_only: bool = False) -> None:
    emic = read_records(EMIC_PATH, "emic")
    iwymic = read_records(IWYMIC_PATH, "iwymic")
    used: set[tuple[str, str]] = set()

    exact_edges = candidate_edges(
        emic,
        iwymic,
        key_attribute="identity_keys",
        used=used,
    )
    exact_pairs = mutual_unique_pairs(exact_edges)
    for left, right in exact_pairs:
        used.update((left.uid, right.uid))

    token_edges = candidate_edges(
        emic,
        iwymic,
        key_attribute="token_keys",
        used=used,
    )
    token_pairs = mutual_unique_pairs(token_edges)
    for left, right in token_pairs:
        used.update((left.uid, right.uid))

    pairs = [*exact_pairs, *token_pairs]
    combined = [merged_row(left, right) for left, right in pairs]
    combined.extend(merged_row(record, None) for record in emic if record.uid not in used)
    combined.extend(merged_row(None, record) for record in iwymic if record.uid not in used)
    combined.sort(
        key=lambda row: (
            key_text(str(row["country_clean"])),
            key_text(str(row["name_last_first"])),
            key_text(str(row["name_clean"])),
            str(row["emic_years"]),
            str(row["iwymic_years"]),
        )
    )
    for output_id, row in enumerate(combined, start=1):
        row["id"] = output_id

    higher_stats = {
        prefix: {"appearances": 0, "contestants": 0}
        for prefix in HIGHER_APPEARANCE_PATHS
    }
    if not base_only:
        higher_stats = attach_higher_histories(combined)

    validate_output(combined, emic, iwymic, pairs, higher_stats)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(combined)

    all_identity_edges = candidate_edges(
        emic,
        iwymic,
        key_attribute="identity_keys",
        used=set(),
        allow_year_overlap=True,
    )
    overlap_edges = [pair for pair in all_identity_edges if pair[0].years & pair[1].years]
    chronology_edges = [
        pair
        for pair in all_identity_edges
        if not (pair[0].years & pair[1].years)
        and not stage_progression_allowed(*pair)
    ]
    paired_uids = {record.uid for pair in pairs for record in pair}
    all_non_overlap_edges = candidate_edges(
        emic,
        iwymic,
        key_attribute="identity_keys",
        used=paired_uids,
    )
    left_degree = Counter(left.uid for left, _ in all_non_overlap_edges)
    right_degree = Counter(right.uid for _, right in all_non_overlap_edges)
    ambiguous_edges = [
        (left, right)
        for left, right in all_non_overlap_edges
        if left_degree[left.uid] > 1 or right_degree[right.uid] > 1
    ]
    write_changelog(
        emic=emic,
        iwymic=iwymic,
        rows=combined,
        exact_pairs=exact_pairs,
        token_pairs=token_pairs,
        overlap_edges=overlap_edges,
        chronology_edges=chronology_edges,
        ambiguous_edges=ambiguous_edges,
        higher_stats=higher_stats,
        higher_attached=not base_only,
    )
    print(f"Wrote {OUT_PATH.relative_to(ROOT)} ({len(combined)} rows)")
    if not base_only:
        print(
            f"Attached {higher_stats['apmo']['appearances']} APMO and "
            f"{higher_stats['imo']['appearances']} IMO appearances"
        )
    print(f"Wrote {CHANGELOG_PATH.relative_to(ROOT)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-only",
        action="store_true",
        help="rebuild the fixed roster with blank APMO/IMO histories before rematching",
    )
    return parser.parse_args()


if __name__ == "__main__":
    run(base_only=parse_args().base_only)
