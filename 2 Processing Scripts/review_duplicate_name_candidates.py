#!/usr/bin/env python3
"""Find possible duplicate identities remaining in the combined roster."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from emic_name_review import clean_text, key_text
from project_paths import COMBINED_MASTER_PATH, DUPLICATE_REVIEW_PATH, PROJECT_ROOT


ROOT = PROJECT_ROOT
COMBINED_PATH = COMBINED_MASTER_PATH
OUTPUT_PATH = DUPLICATE_REVIEW_PATH

OUTPUT_FIELDS = [
    "country_clean",
    "left_id",
    "left_name",
    "left_name_last_first",
    "left_emic_years",
    "left_iwymic_years",
    "right_id",
    "right_name",
    "right_name_last_first",
    "right_emic_years",
    "right_iwymic_years",
    "reason",
    "evidence_strength",
    "family_similarity",
    "given_similarity",
    "full_similarity",
    "token_overlap",
    "same_contest_year_overlap",
    "review_disposition",
    "review_note",
]


def reviewed_pair_key(country: str, left: str, right: str) -> tuple[str, tuple[str, str]]:
    return country, tuple(sorted((key_text(left), key_text(right))))


SPECIAL_REVIEW_NOTES = {
    reviewed_pair_key("Bulgaria", "Martina Dimitrova", "Martina Dobromirova Dimitrova"): (
        "reviewed_distinct",
        "The fuller name is an IWYMIC 2013 contestant, while the shorter name appears in the younger EMIC division in 2014; that reverse stage chronology does not support one identity.",
    ),
    reviewed_pair_key("Hong Kong", "Chun Hei Yip", "Chun Hei Yiu"): (
        "reviewed_distinct",
        "Independent Hong Kong school records place Yip and Yiu at different schools; the one-letter surname similarity is coincidental.",
    ),
    reviewed_pair_key("Macau", "Hou Tam", "Hou Wa Tam"): (
        "reviewed_distinct",
        "Both are IWYMIC contestants, nine years apart (2014 and 2023); the age span rules out one same-stage identity.",
    ),
    reviewed_pair_key(
        "Philippines", "Robert Frederik Diaz Uy", "Robert Henrik Diaz Uy"
    ): (
        "reviewed_distinct",
        "The middle given names differ and the EMIC appearances are seven years apart (2015-2016 versus 2022).",
    ),
    reviewed_pair_key("Republic of Korea", "Junyeong Park", "Junyoung Park"): (
        "reviewed_distinct_same_year",
        "The official 2014 results list separate Keystage II and III contestant IDs; similar romanizations alone cannot override the same-year conflict.",
    ),
    reviewed_pair_key("Taiwan", "Nai-Wei Lu", "Wei Lu"): (
        "reviewed_distinct",
        "Wei Lu appears in IWYMIC 2018 before Nai-Wei Lu appears in the younger EMIC division in 2021, so the stage chronology is reversed.",
    ),
    reviewed_pair_key("Vietnam", "Le Nhat Minh Bui", "Nhat Minh Bui"): (
        "reviewed_distinct",
        "Le Nhat Minh Bui appears in IWYMIC 2018 before Nhat Minh Bui appears in EMIC 2022-2023; the reverse stage chronology does not support one identity.",
    ),
    reviewed_pair_key("Vietnam", "Hoang Nam Do", "Hoang Nam Hieu Do"): (
        "reviewed_distinct",
        "Hoang Nam Hieu Do appears in IWYMIC 2014 before Hoang Nam Do appears in EMIC 2019; the reverse stage chronology and omitted name do not support a merge.",
    ),
    reviewed_pair_key("Vietnam", "Tung Hoang", "Xuan Tung Hoang"): (
        "reviewed_distinct",
        "Tung Hoang appears in IWYMIC 2014 before Xuan Tung Hoang appears in EMIC 2017; the reverse stage chronology does not support a merge.",
    ),
    reviewed_pair_key("Russian Federation", "Ivan Safonov", "Ivan Safonov"): (
        "retained_age_separated_homonym",
        "The exact name recurs in EMIC 2013 and 2023 under separate source entries; a ten-year same-stage span rules out one identity.",
    ),
}


@dataclass(frozen=True)
class Identity:
    row: dict[str, str]
    family: str
    given_tokens: tuple[str, ...]

    @property
    def id(self) -> int:
        return int(self.row["id"])

    @property
    def full_tokens(self) -> tuple[str, ...]:
        return tuple(key_text(self.row["name_clean"]).split())


def split_name(value: str) -> tuple[str, tuple[str, ...]]:
    value = clean_text(value)
    if "," not in value:
        parts = key_text(value).split()
        return (parts[-1] if parts else ""), tuple(parts[:-1])
    family, given = value.split(",", 1)
    return key_text(family), tuple(key_text(given).split())


def token_matches(short: str, long: str) -> bool:
    return short == long or (len(short) == 1 and long.startswith(short))


def ordered_subsequence(short: tuple[str, ...], long: tuple[str, ...]) -> bool:
    if not short or len(short) > len(long):
        return False
    cursor = 0
    for token in short:
        while cursor < len(long) and not token_matches(token, long[cursor]):
            cursor += 1
        if cursor == len(long):
            return False
        cursor += 1
    return True


def initials(tokens: tuple[str, ...]) -> str:
    return "".join(token[0] for token in tokens if token)


def token_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / min(len(left_set), len(right_set))


def has_initial(tokens: tuple[str, ...]) -> bool:
    return any(len(token) == 1 for token in tokens)


def abbreviation_compatible(
    short: tuple[str, ...],
    long: tuple[str, ...],
) -> bool:
    """Return true when a shorter token sequence expands cleanly into a longer one."""
    return (
        len(short) >= 2
        and len(short) <= len(long)
        and ordered_subsequence(short, long)
        and (has_initial(short) or len(short) < len(long))
    )


def years(value: str) -> set[int]:
    return {int(part) for part in value.split(";") if part}


def candidate_reason(
    left: Identity,
    right: Identity,
) -> tuple[str, str, float, float, float, float] | None:
    family_similarity = SequenceMatcher(None, left.family, right.family).ratio()
    left_given = " ".join(left.given_tokens)
    right_given = " ".join(right.given_tokens)
    given_similarity = SequenceMatcher(None, left_given, right_given).ratio()
    full_similarity = SequenceMatcher(
        None,
        " ".join(left.full_tokens),
        " ".join(right.full_tokens),
    ).ratio()
    overlap = token_overlap(left.full_tokens, right.full_tokens)
    same_family = left.family == right.family

    if key_text(left.row["name_clean"]) == key_text(right.row["name_clean"]):
        return (
            "exact_same_display_name",
            "high",
            family_similarity,
            given_similarity,
            full_similarity,
            overlap,
        )

    for short, long in ((left.given_tokens, right.given_tokens), (right.given_tokens, left.given_tokens)):
        if same_family and ordered_subsequence(short, long):
            if has_initial(short):
                return (
                    "initials_expand_to_full_name",
                    "high",
                    family_similarity,
                    given_similarity,
                    full_similarity,
                    overlap,
                )
            if len(short) < len(long) and len(short) >= 1:
                return (
                    "given_name_is_ordered_subset",
                    "high",
                    family_similarity,
                    given_similarity,
                    full_similarity,
                    overlap,
                )

    if same_family and initials(left.given_tokens) == initials(right.given_tokens):
        if initials(left.given_tokens) and (
            has_initial(left.given_tokens)
            or has_initial(right.given_tokens)
        ):
            return (
                "same_given_initials",
                "medium",
                family_similarity,
                given_similarity,
                full_similarity,
                overlap,
            )

    for short, long in ((left.full_tokens, right.full_tokens), (right.full_tokens, left.full_tokens)):
        if abbreviation_compatible(short, long):
            return (
                "whole_name_abbreviation_or_omission",
                "medium",
                family_similarity,
                given_similarity,
                full_similarity,
                overlap,
            )

    if family_similarity >= 0.80 and given_similarity >= 0.94:
        return (
            "surname_spelling_variant",
            "high" if family_similarity >= 0.88 else "medium",
            family_similarity,
            given_similarity,
            full_similarity,
            overlap,
        )
    if same_family and given_similarity >= 0.72:
        return (
            "similar_given_names_same_surname",
            "medium" if given_similarity >= 0.84 else "low",
            family_similarity,
            given_similarity,
            full_similarity,
            overlap,
        )
    if full_similarity >= 0.88 or (overlap >= 0.80 and full_similarity >= 0.78):
        return (
            "high_whole_name_similarity",
            "medium" if full_similarity >= 0.92 else "low",
            family_similarity,
            given_similarity,
            full_similarity,
            overlap,
        )
    return None


def reviewed_disposition(
    country: str,
    left: Identity,
    right: Identity,
    reason: str,
    contest_year_overlap: bool,
) -> tuple[str, str]:
    special = SPECIAL_REVIEW_NOTES.get(
        reviewed_pair_key(country, left.row["name_clean"], right.row["name_clean"])
    )
    if special:
        return special

    same_display = key_text(left.row["name_clean"]) == key_text(right.row["name_clean"])
    if same_display and contest_year_overlap:
        return (
            "retained_same_year_homonym",
            "The official results contain separate contestant rows in the same contest year, so the shared display name is a homonym rather than a merge key.",
        )
    if same_display:
        return (
            "retained_ambiguous_homonym",
            "The exact display name recurs, but no unique source identifier or reviewed alias establishes which appearances belong to one person; records remain separate conservatively.",
        )
    if contest_year_overlap:
        return (
            "reviewed_distinct_same_year",
            "The official results place both names in the same contest year as separate entries; the substantive spelling/given-name difference is retained.",
        )

    reason_notes = {
        "initials_expand_to_full_name": "The initials pattern was reviewed, but chronology or the expanded name components do not support one identity.",
        "given_name_is_ordered_subset": "The shorter name is structurally compatible, but contest chronology or age-stage evidence does not support one identity.",
        "same_given_initials": "The initials coincide, but the expanded given names are substantively different.",
        "whole_name_abbreviation_or_omission": "The abbreviation pattern was reviewed, but the remaining name and chronology evidence does not support one identity.",
        "surname_spelling_variant": "The spelling similarity was reviewed, but the source names or contest chronology support separate identities.",
        "similar_given_names_same_surname": "The shared surname and similar given names were reviewed; substantive given-name differences remain.",
        "high_whole_name_similarity": "The pair was reviewed as a whole-name near match; differing name components and contest history do not support a merge.",
    }
    return "reviewed_distinct", reason_notes[reason]


def run() -> None:
    with COMBINED_PATH.open(encoding="utf-8-sig", newline="") as handle:
        source_rows = [dict(row) for row in csv.DictReader(handle)]

    by_country: dict[str, list[Identity]] = {}
    for row in source_rows:
        family, given_tokens = split_name(row["name_last_first"])
        by_country.setdefault(row["country_clean"], []).append(
            Identity(row=row, family=family, given_tokens=given_tokens)
        )

    candidates: list[dict[str, str | int]] = []
    for country, identities in by_country.items():
        for index, left in enumerate(identities):
            for right in identities[index + 1 :]:
                result = candidate_reason(left, right)
                if result is None:
                    continue
                (
                    reason,
                    evidence_strength,
                    family_similarity,
                    given_similarity,
                    full_similarity,
                    name_token_overlap,
                ) = result
                contest_year_overlap = bool(
                    years(left.row["emic_years"]) & years(right.row["emic_years"])
                    or years(left.row["iwymic_years"]) & years(right.row["iwymic_years"])
                )
                disposition, review_note = reviewed_disposition(
                    country,
                    left,
                    right,
                    reason,
                    contest_year_overlap,
                )
                candidates.append(
                    {
                        "country_clean": country,
                        "left_id": left.id,
                        "left_name": left.row["name_clean"],
                        "left_name_last_first": left.row["name_last_first"],
                        "left_emic_years": left.row["emic_years"],
                        "left_iwymic_years": left.row["iwymic_years"],
                        "right_id": right.id,
                        "right_name": right.row["name_clean"],
                        "right_name_last_first": right.row["name_last_first"],
                        "right_emic_years": right.row["emic_years"],
                        "right_iwymic_years": right.row["iwymic_years"],
                        "reason": reason,
                        "evidence_strength": evidence_strength,
                        "family_similarity": f"{family_similarity:.6f}",
                        "given_similarity": f"{given_similarity:.6f}",
                        "full_similarity": f"{full_similarity:.6f}",
                        "token_overlap": f"{name_token_overlap:.6f}",
                        "same_contest_year_overlap": "yes" if contest_year_overlap else "no",
                        "review_disposition": disposition,
                        "review_note": review_note,
                    }
                )

    candidates.sort(
        key=lambda row: (
            str(row["country_clean"]),
            {"high": 0, "medium": 1, "low": 2}[str(row["evidence_strength"])],
            -float(str(row["full_similarity"])),
            int(row["left_id"]),
            int(row["right_id"]),
        )
    )
    with OUTPUT_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(candidates)
    print(f"Wrote {OUTPUT_PATH.relative_to(ROOT)} ({len(candidates)} candidates)")
    disposition_counts: dict[str, int] = {}
    for row in candidates:
        disposition = str(row["review_disposition"])
        disposition_counts[disposition] = disposition_counts.get(disposition, 0) + 1
    print(
        "Review dispositions: "
        + ", ".join(
            f"{name}={count}" for name, count in sorted(disposition_counts.items())
        )
    )


if __name__ == "__main__":
    run()
