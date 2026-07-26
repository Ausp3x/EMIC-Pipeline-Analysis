#!/usr/bin/env python3
"""Cache IMO given-name/surname fields for countries in the EMIC datasets."""

from __future__ import annotations

import csv
import html
from html.parser import HTMLParser
import re
import sys
import unicodedata
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from project_paths import IMO_NAME_REFERENCE_PATH


OUT_PATH = IMO_NAME_REFERENCE_PATH

COUNTRY_CODES = {
    "Australia": "AUS",
    "Bangladesh": "BGD",
    "Bolivia": "BOL",
    "Botswana": "BWA",
    "Bulgaria": "BGR",
    "Canada": "CAN",
    "Cyprus": "CYP",
    "Ghana": "GHA",
    "Hong Kong": "HKG",
    "India": "IND",
    "Indonesia": "IDN",
    "Islamic Republic of Iran": "IRN",
    "Japan": "JPN",
    "Kazakhstan": "KAZ",
    "Kyrgyzstan": "KGZ",
    "Lebanon": "LEB",
    "Macau": "MAC",
    "Malaysia": "MAS",
    "Mexico": "MEX",
    "Mongolia": "MNG",
    "Nepal": "NPL",
    "Netherlands": "NLD",
    "People's Republic of China": "CHN",
    "Peru": "PER",
    "Philippines": "PHI",
    "Republic of Korea": "KOR",
    "Romania": "ROU",
    "Russian Federation": "RUS",
    "Singapore": "SGP",
    "South Africa": "SAF",
    "Sri Lanka": "LKA",
    "Taiwan": "TWN",
    "Tajikistan": "TJK",
    "Thailand": "THA",
    "Trinidad and Tobago": "TTO",
    "Tunisia": "TUN",
    "Uganda": "UGA",
    "Ukraine": "UKR",
    "United Arab Emirates": "UAE",
    "United States of America": "USA",
    "Uzbekistan": "UZB",
    "Vietnam": "VNM",
}


def clean_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", html.unescape(value))
    return re.sub(r"\s+", " ", value).strip()


def key_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", clean_text(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch)).casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value)).strip()


def token_key(value: str) -> str:
    return " ".join(sorted(key_text(value).split()))


class PersonNameParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.names: set[tuple[str, str]] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "span":
            return
        attr = dict(attrs)
        if "data-person-name" not in attr:
            return
        given = clean_text(attr.get("data-name") or "")
        surname = clean_text(attr.get("data-surname") or "")
        if given or surname:
            self.names.add((given, surname))


def fetch_names(country: str, code: str) -> list[dict[str, str]]:
    source_url = f"https://www.imo-official.org/results/individual/country/{code}/"
    request = Request(source_url, headers={"User-Agent": "EMIC-name-audit/1.0"})
    with urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8", errors="replace")

    parser = PersonNameParser()
    parser.feed(body)
    rows = []
    for given, surname in sorted(parser.names, key=lambda value: (value[1], value[0])):
        name_clean = clean_text(f"{given} {surname}")
        name_last_first = clean_text(f"{surname}, {given}") if given and surname else name_clean
        rows.append(
            {
                "country_clean": country,
                "country_code": code,
                "given_names": given,
                "surname": surname,
                "name_clean": name_clean,
                "name_last_first": name_last_first,
                "name_token_key": token_key(name_clean),
                "source_url": source_url,
            }
        )
    return rows


def main() -> int:
    rows: list[dict[str, str]] = []
    for country, code in COUNTRY_CODES.items():
        try:
            country_rows = fetch_names(country, code)
        except (HTTPError, URLError, TimeoutError) as exc:
            print(f"{country}: no IMO individual-results reference ({exc})")
            continue
        rows.extend(country_rows)
        print(f"{country}: {len(country_rows)} unique IMO names")

    rows.sort(key=lambda row: (row["country_clean"], row["surname"], row["given_names"]))
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
