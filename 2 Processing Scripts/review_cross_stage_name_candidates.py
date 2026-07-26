#!/usr/bin/env python3
"""Score near-name matches for cross-stage identity review."""

from __future__ import annotations

import argparse
from difflib import SequenceMatcher

from combine_emic_iwymic_contestants import (
    EMIC_PATH,
    IWYMIC_PATH,
    candidate_edges,
    mutual_unique_pairs,
    read_records,
)
from emic_name_review import key_text


def split_name(record) -> tuple[str, str]:
    value = record.row["name_last_first"]
    if "," not in value:
        return key_text(value), ""
    family, given = value.split(",", 1)
    return key_text(family), key_text(given)


def ratio(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()


def scored_candidate(left, right):
    left_family, left_given = split_name(left)
    right_family, right_given = split_name(right)
    full_score = ratio(key_text(left.row["name_clean"]), key_text(right.row["name_clean"]))
    family_score = ratio(left_family, right_family)
    given_score = ratio(left_given, right_given)
    same_family = left_family == right_family
    if not (
        full_score >= 0.88
        or (same_family and given_score >= 0.72)
        or (family_score >= 0.88 and given_score >= 0.80)
    ):
        return None
    return max(full_score, (family_score + given_score) / 2), full_score, family_score, given_score, left, right


def print_candidates(label: str, candidates, *, verbose: bool) -> None:
    candidates.sort(
        key=lambda item: (
            -item[0],
            item[4].row["country_key"],
            item[4].row["name_key"],
            item[5].row["name_key"],
        )
    )
    print(f"{label}: {len(candidates)}")
    if not verbose:
        return
    for score, full, family, given, left, right in candidates:
        print(
            f"{score:.3f} full={full:.3f} family={family:.3f} given={given:.3f} | "
            f"{left.row['country_clean']} | {left.row['name_clean']} "
            f"({left.stage} {left.row['years']}) <> {right.row['name_clean']} "
            f"({right.stage} {right.row['years']})"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print candidate counts without the row-by-row review list.",
    )
    args = parser.parse_args()
    emic = read_records(EMIC_PATH, "emic")
    iwymic = read_records(IWYMIC_PATH, "iwymic")
    exact_edges = candidate_edges(
        emic, iwymic, key_attribute="identity_keys", used=set()
    )
    exact_pairs = mutual_unique_pairs(exact_edges)
    used = {record.uid for pair in exact_pairs for record in pair}
    token_edges = candidate_edges(
        emic, iwymic, key_attribute="token_keys", used=used
    )
    token_pairs = mutual_unique_pairs(token_edges)
    used.update(record.uid for pair in token_pairs for record in pair)

    candidates = []
    for left in emic:
        if left.uid in used:
            continue
        for right in iwymic:
            if right.uid in used or left.row["country_key"] != right.row["country_key"]:
                continue
            if left.years & right.years:
                continue
            candidate = scored_candidate(left, right)
            if candidate:
                candidates.append(candidate)
    print_candidates(
        "Cross-stage near-name candidates (see duplicate report for dispositions)",
        candidates,
        verbose=not args.summary,
    )

    for label, records in (("EMIC within-stage near-name candidates", emic), ("IWYMIC within-stage near-name candidates", iwymic)):
        within = []
        for index, left in enumerate(records):
            for right in records[index + 1 :]:
                if left.row["country_key"] != right.row["country_key"] or left.years & right.years:
                    continue
                candidate = scored_candidate(left, right)
                if candidate:
                    within.append(candidate)
        print_candidates(label, within, verbose=not args.summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
