#!/usr/bin/env python3
"""Extract APMO/IMO results and match them to the fixed EMIC/IWYMIC roster."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from emic_name_review import clean_text, key_text
from project_paths import (
    APMO_MATCHED_PATH,
    COMBINED_MASTER_PATH,
    HIGHER_AUDIT_PATH,
    HIGHER_CHANGELOG_PATH,
    HIGHER_MATCH_REVIEW_PATH,
    HIGHER_PROCESSED_DIR,
    IMO_MATCHED_PATH,
    IMO_NAME_REFERENCE_PATH,
    PROJECT_ROOT,
    RAW_APMO_DIR,
    RAW_IMO_DIR,
)


ROOT = PROJECT_ROOT
BASE_PATH = COMBINED_MASTER_PATH
IMO_REFERENCE_PATH = IMO_NAME_REFERENCE_PATH
OUT_DIR = HIGHER_PROCESSED_DIR

APMO_OUT_PATH = APMO_MATCHED_PATH
IMO_OUT_PATH = IMO_MATCHED_PATH
AUDIT_PATH = HIGHER_AUDIT_PATH
CANDIDATE_PATH = HIGHER_MATCH_REVIEW_PATH
CHANGELOG_PATH = HIGHER_CHANGELOG_PATH

APMO_YEARS = tuple(range(2016, 2027))
IMO_YEARS = tuple(range(2013, 2027))

APMO_RESULTS_URL = (
    "https://raw.githubusercontent.com/leomtz/apmowebsite/master/"
    "data/reports/score_awards_{year}.csv"
)
APMO_YEAR_REPORT_URL = "https://www.apmo-official.org/year_report/{year}"
IMO_RESULTS_URL = "https://www.imo-official.org/results/individual/year/{year}/"

# The APMO source uses ISO-style codes while IMO retains several historical codes.
APMO_TO_IMO_CODE = {"ARE": "UAE", "MYS": "MAS", "PHL": "PHI"}
IMO_COUNTRY_CODE_OVERRIDES = {
    "GER": "Germany",
    "NGA": "Nigeria",
}
COUNTRY_ALIASES = {
    "China": "People's Republic of China",
    "Iran": "Islamic Republic of Iran",
    "Korea": "Republic of Korea",
    "Russia": "Russian Federation",
    "South Korea": "Republic of Korea",
    "United States": "United States of America",
    "USA": "United States of America",
}

NAME_TRANSLITERATION = str.maketrans(
    {
        "Đ": "D",
        "đ": "d",
        "Ð": "D",
        "ð": "d",
        "Ł": "L",
        "ł": "l",
        "Ø": "O",
        "ø": "o",
        "Þ": "Th",
        "þ": "th",
        "Æ": "Ae",
        "æ": "ae",
        "Œ": "Oe",
        "œ": "oe",
        "ß": "ss",
    }
)

AWARD_ALIASES = {
    "": "None",
    "-": "None",
    "nan": "None",
    "none": "None",
    "gold": "Gold",
    "gold medal": "Gold",
    "silver": "Silver",
    "silver medal": "Silver",
    "bronze": "Bronze",
    "bronze medal": "Bronze",
    "hon men": "Honourable Mention",
    "honorable mention": "Honourable Mention",
    "honourable mention": "Honourable Mention",
    "hm": "Honourable Mention",
}

def reviewed_match(
    contest: str,
    country: str,
    official_name: str,
    target_name: str,
    *,
    target_country: str | None = None,
    note: str | None = None,
) -> dict[str, str]:
    return {
        "contest": contest,
        "official_country": country,
        "official_name": official_name,
        "target_country": target_country or country,
        "target_name": target_name,
        "note": note or f"{official_name} -> {target_name}",
    }


# These non-exact identities were individually reviewed. "BOTH" applies the
# same official spelling to APMO and IMO without tying the rule to generated IDs.
REVIEWED_MATCHES: tuple[dict[str, str], ...] = (
    reviewed_match("BOTH", "Philippines", "Alvann Walter Paredes Dy", "Alvann Walter W. Paredes Dy"),
    reviewed_match("BOTH", "Philippines", "Mark Justin Villafuerte", "Mark Justin M. Villafuerte"),
    reviewed_match("BOTH", "Philippines", "Immanuel Josiah Balete", "Immanuel Josiah Ang Balete"),
    reviewed_match("BOTH", "Philippines", "Bryce Ainsley Sanchez", "Bryce Ainsley Ang Sanchez"),
    reviewed_match("BOTH", "Philippines", "Ervin Joshua Bautista", "Ervin Joshua V. Bautista"),
    reviewed_match("BOTH", "Philippines", "Albert John Patupat", "Albert John L. Patupat"),
    reviewed_match("BOTH", "Philippines", "Farrell Eldrian Wu", "Farrell Eldrian S. Wu"),
    reviewed_match("BOTH", "Philippines", "Filbert Ephraim Wu", "Filbert Ephraim S. Wu"),
    reviewed_match("BOTH", "Philippines", "Mohammad Nur Casib", "Mohammad Nur G. Casib"),
    reviewed_match("BOTH", "Philippines", "Shaquille Wyan Que", "Shaquille Wyan T. Que"),
    reviewed_match("BOTH", "Thailand", "Krittitee Naulkhao", "Krittitee Naulhao"),
    reviewed_match("BOTH", "Philippines", "Luke Sebastian Sy", "Luke Sebastian C. Sy"),
    reviewed_match("BOTH", "Philippines", "Rickson Caleb Tan", "Rickson Caleb Y. Tan"),
    reviewed_match("BOTH", "Philippines", "Sarji Elijah Bona", "Sarji Elijah S. Bona"),
    reviewed_match("BOTH", "Philippines", "Clyde Wesley Ang", "Clyde Wesley S. Ang"),
    reviewed_match("BOTH", "Philippines", "Vince Jan Torres", "Vince Jan Faustino Torres"),
    reviewed_match("BOTH", "Thailand", "Nitiwit Sirimalaisuwan", "Nitiwit Sirimaraisuwan"),
    reviewed_match("BOTH", "Uzbekistan", "Asadbek Bobokulov", "Asadbek Boboqulov"),
    reviewed_match("BOTH", "Tajikistan", "Sino Khayridinov", "Sino Khairidinov"),
    reviewed_match("BOTH", "Philippines", "Nathan Gabriel Neria", "Nathan Gabriel Ang Neria"),
    reviewed_match("BOTH", "Philippines", "Sean Anderson Ty", "Sean Anderson Lim Ty"),
    reviewed_match("BOTH", "Uzbekistan", "Ozodbek Akhtamov", "Ozod Akhtamov"),
    reviewed_match("APMO", "Mexico", "Luis Edardo Martinez Aguirre", "Luis Eduardo Martinez Aguirre"),
    reviewed_match("APMO", "Thailand", "Kornpholkrit Weraarchakul", "Kornpholkrit Weeraarchakul"),
    reviewed_match("APMO", "Bolivia", "Luis Andre Villlan Gabriel", "Luis Andre Villan Gabriel"),
    reviewed_match("APMO", "Islamic Republic of Iran", "Alireza Rezaei Moghaddam", "Alireza Rezaeimoghadam"),
    reviewed_match("APMO", "Philippines", "Patric Xamwell Legaspi", "Patric Xamwell C. Legaspi"),
    reviewed_match("APMO", "Tajikistan", "Naimdzhon Khonddzhonov", "Naimdzhon Khondzhonov"),
    reviewed_match("APMO", "Philippines", "Neo Angelo Gatlabayan", "Neo Angelo G. Gatlabayan"),
    reviewed_match("APMO", "Kazakhstan", "Asylbek Olzhabayev", "Assylbek Olzhabayev"),
    reviewed_match("APMO", "Kazakhstan", "Raimbek Akshulakov", "Raiymbek Akshulakov"),
    reviewed_match("APMO", "Kazakhstan", "Kuanysh Zholdasov", "Kuanysh Zholdassov"),
    reviewed_match("APMO", "Philippines", "Kristen Steffi Teh", "Kristen Steffi S. Teh"),
    reviewed_match("APMO", "Tajikistan", "Bakhtovar Khotami", "Bakhtovari Khotami"),
    reviewed_match("APMO", "Tajikistan", "Mehron Bobokhonov", "Mekhron Bobokhonov"),
    reviewed_match("APMO", "Tajikistan", "Mekron Bobokhonov", "Mekhron Bobokhonov"),
    reviewed_match("APMO", "Uzbekistan", "Abdulaziz Radjabov", "Abdulaziz Rajabov"),
    reviewed_match("APMO", "Islamic Republic of Iran", "Ahmad Ramezanpour", "Ahmad Ramzan Pour"),
    reviewed_match("APMO", "Islamic Republic of Iran", "Hosein Zakerinia", "Hossein Zakerinia"),
    reviewed_match("APMO", "Mexico", "Jonatan Alejandro Gonzalez Cazarez", "Jonatan Alejandro Gonzalez Cazares"),
    reviewed_match("APMO", "Philippines", "Cassidy Kyler Tan", "Cassidy Kyler L. Tan"),
    reviewed_match("APMO", "Philippines", "Jose Lorenzo Abad", "Jose Lorenzo P. Abad"),
    reviewed_match("APMO", "Philippines", "Julian Raymund Yu", "Julian Raymund C. Yu"),
    reviewed_match("APMO", "Philippines", "Sedrick Scott Keh", "Sedrick Scott S. Keh"),
    reviewed_match("APMO", "Philippines", "Enzo Rafael Chan", "Enzo Rafael S. Chan"),
    reviewed_match("APMO", "Philippines", "Stephen James Ty", "Stephen James Lim Ty"),
    reviewed_match("APMO", "Tajikistan", "Vazirdzon Pirov", "Vazirdzhon Pirov"),
    reviewed_match("APMO", "Indonesia", "Bennet Clement", "Bennett Clement"),
    reviewed_match("BOTH", "Tajikistan", "Muhammadidris Saimuhudinzoda", "Muhammadidris Saymuhudinzoda"),
    reviewed_match("APMO", "Thailand", "Chatchanun Suriyaamaranont", "Chatchanun Suriyaammaranon"),
    reviewed_match("APMO", "Malaysia", "Tan Ming Heng", "Min Heng Tan"),
    reviewed_match("APMO", "Tajikistan", "Muhammadikbol Mahmadov", "Muhammadiqbol Mahmadov"),
    reviewed_match("APMO", "Islamic Republic of Iran", "Farhoud Rostamkhani", "Farhood Rostamkhani"),
    reviewed_match("APMO", "Kazakhstan", "Tamerlan Burambayev", "Tamerlan Burumbayev"),
    reviewed_match("APMO", "Uzbekistan", "Anvarbek Sadullayev", "Anvarbek Sadulloyev"),
    reviewed_match("BOTH", "Kazakhstan", "Beiganov Batyrkhan", "Batyrkhan Baiganov"),
    reviewed_match("APMO", "Malaysia", "Brandon Choo Tze How", "Brandon Choo Sze How"),
    reviewed_match("APMO", "Indonesia", "Nathaniel Lukas Christanto", "Nathanael Lukas Christianto"),
    reviewed_match("APMO", "Sri Lanka", "Nadesamurthy Sivamynthan", "Nadesamoorthy Sivamynthan"),
    reviewed_match("APMO", "Uzbekistan", "Yusufjon Ortikov", "Yusufjon Ortiqov"),
    reviewed_match("APMO", "Tajikistan", "Abubakr Usmonov", "Abubakr Usmanov"),
    reviewed_match("APMO", "Tajikistan", "Muhamahammadrasul Shernazarov", "Muhammadrasul Shernazarov"),
    reviewed_match("APMO", "Uzbekistan", "Begzod Khoshimjonov", "Begzod Xoshimjonov"),
    reviewed_match("APMO", "Islamic Republic of Iran", "Aryan Zamani", "Arian Zamani"),
    reviewed_match("APMO", "Philippines", "Stefan Marcus Ong", "Stefan Marcus Ang Ong"),
    reviewed_match("APMO", "Tajikistan", "Olimjon Tukhtarov", "Olimdzhon Tukhtarov"),
    reviewed_match("APMO", "Uzbekistan", "Anvarbek Raxmatov", "Anvarbek Rakhmatov"),
    reviewed_match("APMO", "Thailand", "Paramutb Samuthrsindb", "Paramuth Samuthrsindh"),
    reviewed_match("APMO", "Tajikistan", "Mashrafjon Inomov", "Mashraf Inomov"),
    reviewed_match("APMO", "Tajikistan", "Parviz Aliev", "Parvizjon Aliev"),
    reviewed_match("APMO", "Islamic Republic of Iran", "Faraz Ghahremani Koure", "Faraz Ghahremany Kooreh"),
    reviewed_match("APMO", "Hong Kong", "Alfin Cheak Hin Tse", "Alvin Cheuk Hin Tse"),
    reviewed_match("APMO", "Tajikistan", "Jakhongir Urakov", "Dzhakhongir Urakov"),
    reviewed_match("APMO", "Tajikistan", "Raufjon Dadabaev", "Raufdzhon Dadabaev"),
    reviewed_match("APMO", "Peru", "Kevin Andres Pomasoncco Sulca", "Kevin Pomasoncco Sulca"),
    reviewed_match("APMO", "Kazakhstan", "Altynbek Erasyl", "Yerassyl Altinbek"),
    reviewed_match("APMO", "Tajikistan", "Bejan Asoev", "Bezhan Asoev"),
    reviewed_match("APMO", "Bulgaria", "Alexandar Stefanov", "Alexander Rossen Stefanov"),
    reviewed_match("APMO", "Philippines", "Jaden Nathan Hernandez", "Jaden Nathan Tanking Hernandez"),
    reviewed_match("APMO", "Philippines", "Jared Cobe Ng", "Jared Cobe Woo Ng"),
    reviewed_match("APMO", "Philippines", "Robert Henrik Uy", "Robert Henrik Diaz Uy"),
    reviewed_match("BOTH", "Philippines", "Shaun Lawrence Poh Leung", "Shaun Lawrence Tiong Poh Leung"),
    reviewed_match("BOTH", "Philippines", "Zion Skye Earl Carmelo Uy", "Zion Skye Earl Carmelo C. Uy"),
    reviewed_match("APMO", "Sri Lanka", "Praveen Athauda-Arachchi", "Praveen Charuka Athauda Arachchi"),
    reviewed_match("APMO", "Tajikistan", "Olimdzhon Tuhtarov", "Olimdzhon Tukhtarov"),
    reviewed_match("IMO", "Bulgaria", "Kiril Zulyamski", "Kiril Ivanov Zulyamski"),
    reviewed_match("IMO", "Peru", "Kevin Pomasoncco", "Kevin Pomasoncco Sulca"),
    reviewed_match("IMO", "South Africa", "Noah Karl Rassou", "Noah Rassou"),
    reviewed_match("IMO", "South Africa", "Noah Moshe Greenblatt", "Noah Greenblatt"),
    reviewed_match(
        "APMO",
        "Tajikistan",
        "Muhammad Boboev",
        "Muhammadjon Boboev",
        note="Muhammad Boboev -> Muhammadjon Boboev (same 2016-2017 IMO contestant)",
    ),
    reviewed_match(
        "APMO",
        "Sri Lanka",
        "Shenal Kotuwewatta",
        "Shenal Santhush Kotuwewatta",
        note="Shenal Kotuwewatta -> Shenal Santhush Kotuwewatta (official IMO full name)",
    ),
    reviewed_match(
        "APMO",
        "Sri Lanka",
        "Mihiru Anushka Bandara",
        "Hitihami Mudiyanselage Mihiru Anushka Bandara",
        note="Mihiru Anushka Bandara -> Hitihami Mudiyanselage Mihiru Anushka Bandara (official IMO full name)",
    ),
    reviewed_match(
        "APMO",
        "Sri Lanka",
        "Maneth Perera",
        "Gonaduwage Maneth Banula Perera",
        note="Maneth Perera -> Gonaduwage Maneth Banula Perera (official IMO full name)",
    ),
    reviewed_match(
        "APMO",
        "Sri Lanka",
        "Maneth Banula Perera",
        "Gonaduwage Maneth Banula Perera",
        note="Maneth Banula Perera -> Gonaduwage Maneth Banula Perera (official IMO full name)",
    ),
    reviewed_match(
        "APMO",
        "Sri Lanka",
        "Nelushi Vithanachchi",
        "Thellabura Vithanachchige Nelushi Vithanachchi",
        note="Nelushi Vithanachchi -> Thellabura Vithanachchige Nelushi Vithanachchi (official IMO full name)",
    ),
    reviewed_match(
        "APMO",
        "Sri Lanka",
        "Thidas Bandara Wanasinghe",
        "Chandhopama Thidas Bandara Wanasinghe",
        note="Thidas Bandara Wanasinghe -> Chandhopama Thidas Bandara Wanasinghe (official IMO full name)",
    ),
    reviewed_match(
        "APMO",
        "Sri Lanka",
        "Luchitha Disal Pathirana",
        "Pathirannehelage Luchitha Disal Pathirana",
        note="Luchitha Disal Pathirana -> Pathirannehelage Luchitha Disal Pathirana (official IMO full name)",
    ),
    reviewed_match("IMO", "Sri Lanka", "Thenura Dilruk Wickramaratna", "Thenura Dilruk Wickramarathna"),
    reviewed_match("IMO", "Uzbekistan", "Anvarbek Sadulloev", "Anvarbek Sadulloyev"),
    reviewed_match("IMO", "Tajikistan", "Mekhrubon Yusupov", "Mehrubon Yusupov"),
    reviewed_match("IMO", "Indonesia", "Farras Mohammad Hibban Faddila", "Farras Mohammad Hibban Fadilla"),
    reviewed_match("IMO", "Islamic Republic of Iran", "Parnia Dabbagh", "Parnia Dabagh"),
    reviewed_match("IMO", "Sri Lanka", "Mohamed Afham Mohamed Aflal", "Mohammed Aflal Mohammed Afham"),
    reviewed_match("IMO", "Kazakhstan", "Yerassyl Altynbek", "Yerassyl Altinbek"),
    reviewed_match("IMO", "Bulgaria", "Evgeni Kayryakov", "Evgeni Staev Kayryakov"),
)

APPEARANCE_FIELDS = [
    "combined_id",
    "name_clean",
    "name_last_first",
    "country_clean",
    "contest",
    "year",
    "official_name",
    "official_name_last_first",
    "official_country",
    "official_country_code",
    "official_person_id",
    "score",
    "medal",
    "rank_start",
    "rank_end",
    "rank_average",
    "percentile",
    "total_participants",
    "match_method",
    "source_url",
]

AUDIT_FIELDS = [
    "contest",
    "year",
    "source_url",
    "expected_participants",
    "parsed_participants",
    "matched_appearances",
    "matched_unique_combined_ids",
    "official_rank_checks",
    "official_rank_mismatches",
    "official_award_checks",
    "official_award_mismatches",
    "problem_score_total_mismatches",
    "status",
]

CANDIDATE_FIELDS = [
    "contest",
    "official_name",
    "official_name_last_first",
    "official_country",
    "official_years",
    "candidate_scope",
    "candidate_combined_id",
    "candidate_name_clean",
    "candidate_name_last_first",
    "candidate_country_clean",
    "similarity",
    "candidate_emic_years",
    "candidate_iwymic_years",
]


def format_number(value: float) -> str:
    return f"{value:.10f}".rstrip("0").rstrip(".")


def normalize_country(value: str) -> str:
    value = clean_text(value)
    return COUNTRY_ALIASES.get(value, value)


def name_key(value: str) -> str:
    return key_text(clean_text(value).translate(NAME_TRANSLITERATION))


def name_token_key(value: str) -> str:
    return " ".join(sorted(name_key(value).split()))


def name_compact_key(value: str) -> str:
    return name_key(value).replace(" ", "")


def normalize_award(value: object) -> str:
    normalized = key_text("" if value is None else str(value))
    if normalized not in AWARD_ALIASES:
        raise RuntimeError(f"Unknown award label: {value!r}")
    return AWARD_ALIASES[normalized]


def parse_score(value: str) -> int:
    value = clean_text(value)
    if not value or value == "-":
        raise RuntimeError("A complete score field is blank")
    return int(float(value))


def fetch(url: str, cache_path: Path, refresh: bool) -> str:
    if cache_path.exists() and not refresh:
        return cache_path.read_text(encoding="utf-8")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; EMICContestantAnalysis/1.0; "
                "+https://chiuchang.org/)"
            )
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            body = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"Could not fetch {url}: {exc}") from exc
    text = body.decode(charset, errors="replace")
    cache_path.write_text(text, encoding="utf-8", newline="")
    return text


def read_csv_text(text: str) -> list[dict[str, str]]:
    return [dict(row) for row in csv.DictReader(text.splitlines())]


def read_base_rows() -> list[dict[str, str]]:
    with BASE_PATH.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "id",
            "name_clean",
            "name_last_first",
            "name_variants",
            "country_clean",
            "emic_years",
            "iwymic_years",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise RuntimeError(f"{BASE_PATH} is missing fields: {sorted(missing)}")
        rows = [dict(row) for row in reader]
    if [int(row["id"]) for row in rows] != list(range(1, len(rows) + 1)):
        raise RuntimeError("Combined roster IDs must be sequential before matching")
    return rows


def load_country_codes() -> dict[str, str]:
    mapping: dict[str, str] = dict(IMO_COUNTRY_CODE_OVERRIDES)
    with IMO_REFERENCE_PATH.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = clean_text(row["country_code"])
            country = normalize_country(row["country_clean"])
            previous = mapping.setdefault(code, country)
            if previous != country:
                raise RuntimeError(f"IMO code {code} maps to both {previous} and {country}")
    return mapping


@dataclass(frozen=True)
class BaseIdentity:
    row: dict[str, str]
    display_names: tuple[str, ...] = field(init=False)
    ordered_keys: frozenset[str] = field(init=False)
    token_keys: frozenset[str] = field(init=False)
    compact_keys: frozenset[str] = field(init=False)

    def __post_init__(self) -> None:
        names = [self.row["name_clean"], self.row["name_last_first"]]
        names.extend(value for value in self.row["name_variants"].split(";") if value)
        names = list(dict.fromkeys(clean_text(value) for value in names if clean_text(value)))
        object.__setattr__(self, "display_names", tuple(names))
        object.__setattr__(
            self,
            "ordered_keys",
            frozenset(name_key(value) for value in names),
        )
        object.__setattr__(
            self,
            "token_keys",
            frozenset(name_token_key(value) for value in names),
        )
        object.__setattr__(
            self,
            "compact_keys",
            frozenset(name_compact_key(value) for value in names),
        )

    @property
    def id(self) -> int:
        return int(self.row["id"])

    @property
    def country_key(self) -> str:
        return key_text(self.row["country_clean"])


@dataclass
class Appearance:
    contest: str
    year: int
    official_given_names: str
    official_surname: str
    official_country: str
    official_country_code: str
    official_person_id: str
    problem_scores: tuple[int, ...]
    score: int
    medal: str
    source_url: str
    official_rank: int | None = None
    rank_start: int = 0
    rank_end: int = 0
    rank_average: float = 0.0
    percentile: float = 0.0
    total_participants: int = 0
    matched_id: int | None = None
    match_method: str = ""

    @property
    def official_name(self) -> str:
        return clean_text(f"{self.official_given_names} {self.official_surname}")

    @property
    def official_name_last_first(self) -> str:
        if not self.official_surname:
            return self.official_given_names
        return clean_text(f"{self.official_surname}, {self.official_given_names}")

    @property
    def name_forms(self) -> tuple[str, ...]:
        forms = [self.official_name, clean_text(f"{self.official_surname} {self.official_given_names}")]
        for value in tuple(forms):
            without_parenthetical = clean_text(re.sub(r"\s*\([^)]*\)", "", value))
            if without_parenthetical:
                forms.append(without_parenthetical)
            parenthetical = re.search(r"\(([^)]*)\)", value)
            if parenthetical:
                before = clean_text(value[: parenthetical.start()])
                after = clean_text(value[parenthetical.end() :])
                forms.append(clean_text(f"{parenthetical.group(1)} {after or before}"))
        return tuple(dict.fromkeys(value for value in forms if value))

    @property
    def ordered_keys(self) -> frozenset[str]:
        return frozenset(name_key(value) for value in self.name_forms)

    @property
    def token_keys(self) -> frozenset[str]:
        return frozenset(name_token_key(value) for value in self.name_forms)

    @property
    def compact_keys(self) -> frozenset[str]:
        return frozenset(name_compact_key(value) for value in self.name_forms)


class ResultJsonParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.capture = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "script":
            return
        attributes = dict(attrs)
        if "data-results-individual-year-contestants" in attributes:
            self.capture = True

    def handle_data(self, data: str) -> None:
        if self.capture:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self.capture:
            self.capture = False


class PageTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = clean_text(data)
        if value:
            self.parts.append(value)


def parse_apmo_year_report(year: int, html: str) -> dict[str, int]:
    parser = PageTextParser()
    parser.feed(html)
    text = clean_text(" ".join(parser.parts))

    participant_match = re.search(r"(\d+)\s+participating students", text, re.IGNORECASE)
    if not participant_match:
        raise RuntimeError(f"APMO {year}: participant count not found on official year report")

    cutoffs: dict[str, int] = {}
    for medal in ("gold", "silver", "bronze"):
        match = re.search(
            rf"{medal}\s+cut-?off[^0-9]{{0,40}}(\d+)",
            text,
            re.IGNORECASE,
        )
        if not match:
            raise RuntimeError(f"APMO {year}: {medal} cutoff not found on official year report")
        cutoffs[medal] = int(match.group(1))
    return {
        "participants": int(participant_match.group(1)),
        "preliminary": int("preliminary" in text.casefold()),
        **cutoffs,
    }


def expected_apmo_medal(
    total: int, country_rank: int, cutoffs: dict[str, int]
) -> str | None:
    if total >= cutoffs["gold"] and country_rank == 1:
        return "Gold"
    if total >= cutoffs["silver"] and country_rank <= 3:
        return "Silver"
    if total >= cutoffs["bronze"] and country_rank <= 7:
        return "Bronze"
    return None


def parse_apmo_results(
    *,
    year: int,
    text: str,
    metadata: dict[str, int],
    country_codes: dict[str, str],
) -> tuple[list[Appearance], int, int]:
    rows = read_csv_text(text)
    required = {"code", "country", "rank", "last", "first", "p1", "p2", "p3", "p4", "p5", "total", "award"}
    if rows and not required <= set(rows[0]):
        raise RuntimeError(f"APMO {year} source fields are incomplete")
    appearances: list[Appearance] = []
    award_mismatches = 0
    total_mismatches = 0
    for row in rows:
        source_code = clean_text(row["code"])
        imo_code = APMO_TO_IMO_CODE.get(source_code, source_code)
        source_country = normalize_country(row["country"])
        country = country_codes.get(imo_code, source_country)
        scores = tuple(parse_score(row[f"p{problem}"]) for problem in range(1, 6))
        total = parse_score(row["total"])
        if total != sum(scores):
            total_mismatches += 1
        medal = normalize_award(row["award"])
        expected_medal = expected_apmo_medal(total, int(row["rank"]), metadata)
        if (medal if medal in {"Gold", "Silver", "Bronze"} else None) != expected_medal:
            award_mismatches += 1
        appearances.append(
            Appearance(
                contest="APMO",
                year=year,
                official_given_names=clean_text(row["first"]),
                official_surname=clean_text(row["last"]),
                official_country=country,
                official_country_code=source_code,
                official_person_id=f"{source_code}:{year}:{clean_text(row['rank'])}",
                problem_scores=scores,
                score=total,
                medal=medal,
                source_url=f"https://www.apmo-official.org/country_report/{source_code}/{year}",
            )
        )
    if len(appearances) != metadata["participants"]:
        raise RuntimeError(
            f"APMO {year}: expected {metadata['participants']} participants, parsed {len(appearances)}"
        )
    return appearances, award_mismatches, total_mismatches


def parse_imo_results(
    *, year: int, text: str, country_codes: dict[str, str]
) -> tuple[list[Appearance], int]:
    parser = ResultJsonParser()
    parser.feed(text)
    if not parser.parts:
        raise RuntimeError(f"IMO {year}: structured contestant JSON was not found")
    data = json.loads("".join(parser.parts))
    appearances: list[Appearance] = []
    total_mismatches = 0
    for item in data:
        scores = tuple(int(value) for value in item.get("scores", []) if value is not None)
        total = item.get("total")
        if total is None or not scores:
            raise RuntimeError(f"IMO {year}: incomplete score for participation {item.get('participationId')}")
        if int(total) != sum(scores):
            total_mismatches += 1
        code = clean_text(item.get("countryCode") or "")
        country = country_codes.get(code, code)
        medal = normalize_award(item.get("award"))
        person_id = item.get("contestantId") or item.get("participationId")
        appearances.append(
            Appearance(
                contest="IMO",
                year=year,
                official_given_names=clean_text(item.get("name") or ""),
                official_surname=clean_text(item.get("surname") or ""),
                official_country=country,
                official_country_code=code,
                official_person_id=str(person_id),
                problem_scores=scores,
                score=int(total),
                medal=medal,
                official_rank=int(item["rank"]) if item.get("rank") is not None else None,
                source_url=IMO_RESULTS_URL.format(year=year),
            )
        )
    return appearances, total_mismatches


def assign_ranks(appearances: list[Appearance]) -> None:
    by_year: dict[tuple[str, int], list[Appearance]] = defaultdict(list)
    for appearance in appearances:
        by_year[(appearance.contest, appearance.year)].append(appearance)
    for group in by_year.values():
        total_participants = len(group)
        by_score: dict[int, list[Appearance]] = defaultdict(list)
        for appearance in group:
            by_score[appearance.score].append(appearance)
        position = 1
        for score in sorted(by_score, reverse=True):
            tied = by_score[score]
            rank_start = position
            rank_end = position + len(tied) - 1
            rank_average = (rank_start + rank_end) / 2
            percentile = 1 - rank_average / total_participants
            for appearance in tied:
                appearance.rank_start = rank_start
                appearance.rank_end = rank_end
                appearance.rank_average = rank_average
                appearance.percentile = percentile
                appearance.total_participants = total_participants
            position = rank_end + 1
        if position != total_participants + 1:
            raise RuntimeError("Rank assignment did not consume every participant")


class IdentityIndex:
    def __init__(self, identities: list[BaseIdentity]) -> None:
        self.identities = identities
        self.by_id = {identity.id: identity for identity in identities}
        self.by_country: dict[str, list[BaseIdentity]] = defaultdict(list)
        self.indexes: dict[str, dict[tuple[str, str], set[int]]] = {
            "ordered": defaultdict(set),
            "token": defaultdict(set),
            "compact": defaultdict(set),
        }
        self.global_indexes: dict[str, dict[str, set[int]]] = {
            "ordered": defaultdict(set),
            "token": defaultdict(set),
            "compact": defaultdict(set),
        }
        for identity in identities:
            self.by_country[identity.country_key].append(identity)
            for method, values in (
                ("ordered", identity.ordered_keys),
                ("token", identity.token_keys),
                ("compact", identity.compact_keys),
            ):
                for value in values:
                    self.indexes[method][(identity.country_key, value)].add(identity.id)
                    self.global_indexes[method][value].add(identity.id)

    def resolve(self, appearance: Appearance) -> tuple[int | None, str]:
        country = key_text(appearance.official_country)
        methods = (
            ("same_country_exact", "ordered", appearance.ordered_keys),
            ("same_country_token", "token", appearance.token_keys),
            ("same_country_compact", "compact", appearance.compact_keys),
        )
        for label, method, values in methods:
            candidates = {
                candidate
                for value in values
                for candidate in self.indexes[method].get((country, value), set())
            }
            if len(candidates) == 1:
                return next(iter(candidates)), label
            if len(candidates) > 1:
                return None, f"ambiguous_{label}"

        # A unique exact ordered name can identify a contestant who later changed delegation.
        global_candidates = {
            candidate
            for value in appearance.ordered_keys
            for candidate in self.global_indexes["ordered"].get(value, set())
        }
        if len(global_candidates) == 1:
            return next(iter(global_candidates)), "global_exact_country_change"
        if len(global_candidates) > 1:
            return None, "ambiguous_global_exact"
        return None, ""


def resolve_reviewed_matches(index: IdentityIndex) -> dict[tuple[str, str, str], tuple[int, str]]:
    resolved: dict[tuple[str, str, str], tuple[int, str]] = {}
    for rule in REVIEWED_MATCHES:
        targets = [
            identity
            for identity in index.identities
            if identity.country_key == key_text(rule["target_country"])
            and name_key(identity.row["name_clean"]) == name_key(rule["target_name"])
        ]
        if len(targets) != 1:
            raise RuntimeError(f"Reviewed higher-contest target is not unique: {rule}")
        contests = ("APMO", "IMO") if rule["contest"].upper() == "BOTH" else (rule["contest"].upper(),)
        for contest in contests:
            lookup = (
                contest,
                key_text(rule["official_country"]),
                name_token_key(rule["official_name"]),
            )
            if lookup in resolved:
                raise RuntimeError(f"Duplicate reviewed higher-contest lookup: {lookup}")
            resolved[lookup] = (targets[0].id, rule["note"])
    return resolved


def match_appearances(
    appearances: list[Appearance], index: IdentityIndex
) -> None:
    reviewed = resolve_reviewed_matches(index)
    for appearance in appearances:
        lookup = (
            appearance.contest,
            key_text(appearance.official_country),
            name_token_key(appearance.official_name),
        )
        if lookup in reviewed:
            appearance.matched_id = reviewed[lookup][0]
            appearance.match_method = "reviewed_alias"
            continue
        matched_id, method = index.resolve(appearance)
        appearance.matched_id = matched_id
        appearance.match_method = method

    # IMO contestant IDs are stable across editions. One exact match therefore
    # establishes that person's other official appearances without fuzzy names.
    imo_people: dict[str, list[Appearance]] = defaultdict(list)
    for appearance in appearances:
        if appearance.contest == "IMO":
            imo_people[appearance.official_person_id].append(appearance)
    for person_id, group in imo_people.items():
        matched = {appearance.matched_id for appearance in group if appearance.matched_id}
        if len(matched) > 1:
            raise RuntimeError(f"IMO person {person_id} matched multiple combined IDs: {matched}")
        if len(matched) == 1:
            matched_id = next(iter(matched))
            for appearance in group:
                if appearance.matched_id is None:
                    appearance.matched_id = matched_id
                    appearance.match_method = "imo_person_id_propagation"

    seen: dict[tuple[str, int, int], Appearance] = {}
    for appearance in appearances:
        if appearance.matched_id is None:
            continue
        key = (appearance.contest, appearance.year, appearance.matched_id)
        if key in seen:
            other = seen[key]
            raise RuntimeError(
                f"{appearance.contest} {appearance.year}: combined ID {appearance.matched_id} "
                f"matched both {other.official_name!r} and {appearance.official_name!r}"
            )
        seen[key] = appearance


def similarity(left: BaseIdentity, right: Appearance) -> float:
    best = 0.0
    for left_name in left.display_names:
        left_key = name_compact_key(left_name)
        if not left_key:
            continue
        for right_name in right.name_forms:
            right_key = name_compact_key(right_name)
            if not right_key:
                continue
            best = max(best, SequenceMatcher(None, left_key, right_key).ratio())
    return best


def build_candidates(
    appearances: list[Appearance], index: IdentityIndex
) -> list[dict[str, str | int]]:
    grouped: dict[tuple[str, str, str], list[Appearance]] = defaultdict(list)
    for appearance in appearances:
        if appearance.matched_id is None:
            grouped[
                (
                    appearance.contest,
                    key_text(appearance.official_country),
                    name_token_key(appearance.official_name),
                )
            ].append(appearance)

    rows: list[dict[str, str | int]] = []
    for (_, country_key, _), group in grouped.items():
        representative = group[0]
        same_country = index.by_country.get(country_key, [])
        scored = sorted(
            ((similarity(identity, representative), identity) for identity in same_country),
            key=lambda item: (-item[0], item[1].id),
        )
        selected = [("same_country", score, identity) for score, identity in scored[:3] if score >= 0.78]
        for scope, score, identity in selected:
            rows.append(
                {
                    "contest": representative.contest,
                    "official_name": representative.official_name,
                    "official_name_last_first": representative.official_name_last_first,
                    "official_country": representative.official_country,
                    "official_years": ";".join(str(year) for year in sorted({item.year for item in group})),
                    "candidate_scope": scope,
                    "candidate_combined_id": identity.id,
                    "candidate_name_clean": identity.row["name_clean"],
                    "candidate_name_last_first": identity.row["name_last_first"],
                    "candidate_country_clean": identity.row["country_clean"],
                    "similarity": format_number(score),
                    "candidate_emic_years": identity.row["emic_years"],
                    "candidate_iwymic_years": identity.row["iwymic_years"],
                }
            )
    rows.sort(
        key=lambda row: (
            str(row["contest"]),
            -float(row["similarity"]),
            str(row["official_country"]),
            str(row["official_name"]),
            int(row["candidate_combined_id"]),
        )
    )
    return rows


def matched_output_rows(
    appearances: list[Appearance], index: IdentityIndex, contest: str
) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    for appearance in appearances:
        if appearance.contest != contest or appearance.matched_id is None:
            continue
        identity = index.by_id[appearance.matched_id]
        rows.append(
            {
                "combined_id": identity.id,
                "name_clean": identity.row["name_clean"],
                "name_last_first": identity.row["name_last_first"],
                "country_clean": identity.row["country_clean"],
                "contest": contest,
                "year": appearance.year,
                "official_name": appearance.official_name,
                "official_name_last_first": appearance.official_name_last_first,
                "official_country": appearance.official_country,
                "official_country_code": appearance.official_country_code,
                "official_person_id": appearance.official_person_id,
                "score": appearance.score,
                "medal": appearance.medal,
                "rank_start": appearance.rank_start,
                "rank_end": appearance.rank_end,
                "rank_average": format_number(appearance.rank_average),
                "percentile": format_number(appearance.percentile),
                "total_participants": appearance.total_participants,
                "match_method": appearance.match_method,
                "source_url": appearance.source_url,
            }
        )
    rows.sort(key=lambda row: (int(row["combined_id"]), int(row["year"])))
    return rows


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_audit_rows(
    appearances: list[Appearance],
    apmo_metadata: dict[int, dict[str, int]],
    apmo_award_mismatches: dict[int, int],
    source_total_mismatches: dict[tuple[str, int], int],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for contest, years in (("APMO", APMO_YEARS), ("IMO", IMO_YEARS)):
        for year in years:
            group = [
                appearance
                for appearance in appearances
                if appearance.contest == contest and appearance.year == year
            ]
            rank_checks = sum(appearance.official_rank is not None for appearance in group)
            rank_mismatches = sum(
                appearance.official_rank is not None
                and appearance.official_rank != appearance.rank_start
                for appearance in group
            )
            award_checks = len(group) if contest == "APMO" else 0
            award_mismatches = apmo_award_mismatches.get(year, 0) if contest == "APMO" else 0
            total_mismatches = source_total_mismatches.get((contest, year), 0)
            expected = apmo_metadata[year]["participants"] if contest == "APMO" else len(group)
            preliminary = (
                contest == "APMO"
                and bool(apmo_metadata[year].get("preliminary", 0))
            )
            source_url = (
                f"https://www.apmo-official.org/year_report/{year}"
                if contest == "APMO"
                else IMO_RESULTS_URL.format(year=year)
            )
            rows.append(
                {
                    "contest": contest,
                    "year": year,
                    "source_url": source_url,
                    "expected_participants": expected,
                    "parsed_participants": len(group),
                    "matched_appearances": sum(appearance.matched_id is not None for appearance in group),
                    "matched_unique_combined_ids": len(
                        {appearance.matched_id for appearance in group if appearance.matched_id}
                    ),
                    "official_rank_checks": rank_checks,
                    "official_rank_mismatches": rank_mismatches,
                    "official_award_checks": award_checks,
                    "official_award_mismatches": award_mismatches,
                    "problem_score_total_mismatches": total_mismatches,
                    "status": (
                        "fail"
                        if len(group) != expected or award_mismatches
                        else "pass_preliminary_source_with_anomaly"
                        if preliminary and (total_mismatches or rank_mismatches)
                        else "pass_preliminary_source"
                        if preliminary
                        else "pass_with_source_anomaly"
                        if total_mismatches or rank_mismatches
                        else "pass"
                    ),
                }
            )
    return rows


def write_changelog(
    *,
    base_count: int,
    appearances: list[Appearance],
    audit_rows: list[dict[str, object]],
    candidate_rows: list[dict[str, object]],
) -> None:
    matched = [appearance for appearance in appearances if appearance.matched_id]
    methods = Counter(appearance.match_method for appearance in matched)
    lines = [
        "APMO / IMO higher-contest changelog",
        "",
        "Changelog:",
        "- 2026-07-19: Added official APMO and IMO result extraction for the fixed EMIC/IWYMIC identity universe.",
        "- 2026-07-19: Added global score-tie rank averages and percentiles using 1 - rank_average / total_participants.",
        "- 2026-07-19: Added matched-appearance CSVs, a year-level source audit, and a conservative near-match review file.",
        "- 2026-07-19: Kept all official-only contestants outside the combined roster; no APMO/IMO name can create a new combined ID.",
        "- 2026-07-19: Used the APMO 2024 year report's corrected 355-participant total; the timeline summary remains stale at 345 while the year report and both complete score files agree on 355.",
        "- 2026-07-19: Corrected the IMO 2014 12-point tie to positions 367-374; the official page labels that group rank 366 even though the adjacent 13-point and 11-point groups establish starts of 361 and 375.",
        "- 2026-07-19: Expanded the official IMO delegation codes GER and NGA to Germany and Nigeria in supporting rows; a blank delegation remains blank for the 2022 independent appearance.",
        "- 2026-07-22: Rebuilt higher-contest matches after the final EMIC/IWYMIC identity deduplication and added reviewed APMO short-name aliases for six Sri Lankan official full names.",
        "- 2026-07-23: Added official 2026 score-level data for APMO and IMO. The APMO source remains explicitly preliminary and is marked as such in the audit.",
        "- 2026-07-23: Reviewed twelve 2026 omitted-middle-name and romanization alias rules, resolving sixteen APMO/IMO appearances while retaining ambiguous common-name candidates for review.",
        "- 2026-07-23: Retained APMO 2026 contestant Đăng Nguyên Phạm's official total of 25 for ranking; the source problem columns sum to 18 and the discrepancy is recorded as a source anomaly.",
        "",
        "Coverage:",
        "- APMO: 2016-2026 inclusive. The 2016-2025 reports are final; the complete 2026 score-level report is included with its official preliminary status retained.",
        "- APMO 2013-2015 are excluded because the archive does not provide complete contestant-level score tables for those years; incomplete data cannot support the requested global tie ranks and percentiles.",
        "- IMO: 2013-2026 inclusive, using the official individual-results pages.",
        "",
        "Identity policy:",
        f"- Fixed base roster: {base_count} EMIC/IWYMIC identities.",
        "- Primary matching requires the same normalized country and an exact canonical/variant name, token set, or character-order-preserving compact name.",
        "- A globally unique exact ordered name may match across a later delegation change; this is explicitly labeled in match_method.",
        "- IMO contestant IDs propagate an already established exact match across that same person's other IMO editions.",
        "- Same-country fuzzy similarity never merges automatically; candidates remain in APMO and IMO Match Review.csv until reviewed.",
        "",
        "Ranking and award validation:",
        "- Ties are grouped by total score across the complete field for that contest-year.",
        "- rank_average = (rank_start + rank_end) / 2.",
        "- percentile = 1 - rank_average / total_participants.",
        "- The official total field is authoritative for ranking; any disagreement with the displayed problem-score sum is retained as a source anomaly in the audit.",
        "- APMO Gold/Silver/Bronze labels are checked against the official yearly cutoffs and within-country rank limits; official Honourable Mention labels are preserved because their criteria may vary by year.",
        "- APMO source status is read from each official year report; a preliminary report receives a distinct passing audit status.",
        "- IMO recomputed rank_start values are checked against every official rank value.",
        "",
        "Output counts:",
    ]
    for contest in ("APMO", "IMO"):
        contest_all = [appearance for appearance in appearances if appearance.contest == contest]
        contest_matched = [appearance for appearance in contest_all if appearance.matched_id]
        lines.append(
            f"- {contest}: {len(contest_all)} official appearances parsed; "
            f"{len(contest_matched)} appearances matched to "
            f"{len({appearance.matched_id for appearance in contest_matched})} combined identities."
        )
    lines.append(f"- Near-match candidate rows retained for review: {len(candidate_rows)}.")
    lines.append("")
    lines.append("Match methods:")
    for method, count in sorted(methods.items()):
        lines.append(f"- {method}: {count}")
    if not methods:
        lines.append("- None.")
    lines.extend(["", "Reviewed non-exact aliases:"])
    if REVIEWED_MATCHES:
        for rule in REVIEWED_MATCHES:
            lines.append(
                f"- {rule['contest']} {rule['official_country']}: {rule['official_name']} -> "
                f"{rule['target_name']} ({rule['target_country']}); {rule['note']}"
            )
    else:
        lines.append("- None in this build.")
    lines.extend(["", "Year-level validation:"])
    for row in audit_rows:
        lines.append(
            f"- {row['contest']} {row['year']}: {row['parsed_participants']} participants, "
            f"{row['matched_appearances']} matched; rank mismatches "
            f"{row['official_rank_mismatches']}, award mismatches "
            f"{row['official_award_mismatches']}, problem-total mismatches "
            f"{row['problem_score_total_mismatches']} ({row['status']})."
        )
    CHANGELOG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="re-download cached official data")
    return parser.parse_args()


def run(refresh: bool = False) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    base_rows = read_base_rows()
    identities = [BaseIdentity(row) for row in base_rows]
    index = IdentityIndex(identities)
    country_codes = load_country_codes()

    apmo_metadata: dict[int, dict[str, int]] = {}
    appearances: list[Appearance] = []
    apmo_award_mismatches: dict[int, int] = {}
    source_total_mismatches: dict[tuple[str, int], int] = {}
    for year in APMO_YEARS:
        report_html = fetch(
            APMO_YEAR_REPORT_URL.format(year=year),
            RAW_APMO_DIR / f"apmo_{year}_year_report.html",
            refresh,
        )
        apmo_metadata[year] = parse_apmo_year_report(year, report_html)
        text = fetch(
            APMO_RESULTS_URL.format(year=year),
            RAW_APMO_DIR / f"apmo_{year}.csv",
            refresh,
        )
        parsed, award_mismatches, total_mismatches = parse_apmo_results(
            year=year,
            text=text,
            metadata=apmo_metadata[year],
            country_codes=country_codes,
        )
        appearances.extend(parsed)
        apmo_award_mismatches[year] = award_mismatches
        source_total_mismatches[("APMO", year)] = total_mismatches
        print(f"APMO {year}: parsed {len(parsed)} participants")

    for year in IMO_YEARS:
        text = fetch(
            IMO_RESULTS_URL.format(year=year),
            RAW_IMO_DIR / f"imo_{year}.html",
            refresh,
        )
        parsed, total_mismatches = parse_imo_results(
            year=year, text=text, country_codes=country_codes
        )
        appearances.extend(parsed)
        source_total_mismatches[("IMO", year)] = total_mismatches
        print(f"IMO {year}: parsed {len(parsed)} participants")

    assign_ranks(appearances)
    match_appearances(appearances, index)
    candidate_rows = build_candidates(appearances, index)
    apmo_rows = matched_output_rows(appearances, index, "APMO")
    imo_rows = matched_output_rows(appearances, index, "IMO")
    audit_rows = build_audit_rows(
        appearances,
        apmo_metadata,
        apmo_award_mismatches,
        source_total_mismatches,
    )
    if any(row["status"] == "fail" for row in audit_rows):
        failures = [f"{row['contest']} {row['year']}" for row in audit_rows if row["status"] == "fail"]
        raise RuntimeError(f"Higher-contest source validation failed: {', '.join(failures)}")

    write_csv(APMO_OUT_PATH, APPEARANCE_FIELDS, apmo_rows)
    write_csv(IMO_OUT_PATH, APPEARANCE_FIELDS, imo_rows)
    write_csv(AUDIT_PATH, AUDIT_FIELDS, audit_rows)
    write_csv(CANDIDATE_PATH, CANDIDATE_FIELDS, candidate_rows)
    write_changelog(
        base_count=len(base_rows),
        appearances=appearances,
        audit_rows=audit_rows,
        candidate_rows=candidate_rows,
    )
    print(
        f"Matched {len(apmo_rows)} APMO and {len(imo_rows)} IMO appearances "
        f"to the fixed {len(base_rows)}-row roster"
    )
    print(f"Wrote {CANDIDATE_PATH.relative_to(ROOT)} ({len(candidate_rows)} review rows)")


if __name__ == "__main__":
    run(parse_args().refresh)
