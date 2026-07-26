#!/usr/bin/env python3
"""Shared reviewed name-order rules for the EMIC/IWYMIC extractors.

The contest pages mix delegation-specific name formats.  This module keeps the
country/year rules in one place and optionally applies exact-token matches from
the IMO site's explicit given-name and surname fields.
"""

from __future__ import annotations

import csv
import html
import re
import unicodedata
from dataclasses import dataclass

from project_paths import IMO_NAME_REFERENCE_PATH


REFERENCE_PATH = IMO_NAME_REFERENCE_PATH


@dataclass(frozen=True)
class ReviewedName:
    first_last: str
    last_first: str
    variant_first_last: str


def clean_text(value: str) -> str:
    value = html.unescape(value)
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("\u00a0", " ").replace("\u200b", "")
    return re.sub(r"\s+", " ", value).strip()


def key_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", clean_text(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch)).casefold()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def token_key(value: str) -> str:
    return " ".join(sorted(key_text(value).split()))


def character_key(value: str) -> str:
    return key_text(value).replace(" ", "")


def character_bag_key(value: str) -> str:
    """Compare the same normalized characters despite token spacing/order."""
    return "".join(sorted(character_key(value)))


def align_last_first(name_first_last: str, authoritative_last_first: str) -> str | None:
    """Transfer an explicit surname boundary onto the canonical display spelling."""
    if "," not in authoritative_last_first:
        return None
    family_source = authoritative_last_first.split(",", 1)[0].strip().split()
    name_parts = clean_text(name_first_last).split()
    family_keys = [key_text(part) for part in family_source]
    name_keys = [key_text(part) for part in name_parts]
    for start in range(len(name_parts) - len(family_source) + 1):
        end = start + len(family_source)
        if name_keys[start:end] != family_keys:
            continue
        family = " ".join(name_parts[start:end])
        given = " ".join(name_parts[:start] + name_parts[end:])
        if given:
            return clean_text(f"{family}, {given}")
    return None


def _load_imo_reference() -> dict[tuple[str, str], tuple[str, str]]:
    if not REFERENCE_PATH.exists():
        return {}

    candidates: dict[tuple[str, str], set[tuple[str, str]]] = {}
    with REFERENCE_PATH.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            lookup_key = (key_text(row["country_clean"]), row["name_token_key"])
            candidates.setdefault(lookup_key, set()).add(
                (clean_text(row["name_clean"]), clean_text(row["name_last_first"]))
            )

    return {
        lookup_key: next(iter(values))
        for lookup_key, values in candidates.items()
        if len(values) == 1
    }


IMO_REFERENCE = _load_imo_reference()


CHINESE_SURNAMES = {
    "ang", "ao", "au", "bai", "bao", "bian", "boo", "cai", "cao", "chaang",
    "chan", "chang", "chao", "cheng", "chiang", "chien", "chuang", "chueh",
    "chau", "cheang", "chen", "cheng", "cheong", "cheung", "chi", "chin", "chiu",
    "cho", "choi", "chong", "chou", "chow", "chu", "chung", "deng", "ding", "du",
    "chew", "chia", "chieng", "choy", "chuah", "fan", "fang", "feng", "fok", "fong",
    "dai", "dong", "fu", "gan", "gao", "goh", "gu", "guan", "guo", "han", "he",
    "ho", "hong", "hou", "hsiao", "hsieh", "hsin", "hsu", "hu", "hua", "huang",
    "hui", "hung", "iam", "ieong", "iong", "ip", "ji", "jian", "jiang", "jin", "kan",
    "jan", "jia", "jing", "kang", "kao", "kho", "khor", "ko", "koh", "kong", "kou", "kow", "ku", "kua",
    "kuang", "kung", "kuo", "kuong", "kwan", "kwok", "lai", "lang",
    "lam", "lan", "lao", "lau", "law", "lee", "lei", "leong", "leung", "li", "liang",
    "liao", "liew", "lim", "lin", "ling", "lio", "liu", "lo", "loo", "low", "long",
    "lu", "luan", "luo", "lyu", "ma", "mak", "man", "mao", "meng", "mii", "mok", "nan", "ng", "ngai", "ning", "niu",
    "ong", "ou", "pan", "pang", "peng", "poon",
    "pu", "qi", "qin", "qiu", "qu", "rao", "ren", "see", "shi", "shih", "shing", "sin", "si", "sit", "siu", "so", "sou",
    "seah", "shee", "siow", "song", "soo", "sun", "sung", "tai", "tam", "tan", "tang",
    "teng", "teo", "tey", "that", "tho", "tian", "tien", "ting", "toh", "tong", "tsai", "tsang",
    "tseng", "tse", "tsoi", "tzeng", "un", "voo", "wan", "wang", "wei", "weng", "woh",
    "wong", "woo", "wu",
    "xia", "xiang", "xiao", "xie", "xu", "xuan", "xue", "yan", "yang", "yao", "yau", "ye", "yeh", "yen", "yeung", "yi", "yip",
    "yap", "yeoh", "yiu", "you", "yu", "yuan", "yuen", "zhan", "zhang", "zhao", "zhen",
    "zheng", "zhong", "zhou", "zhu", "zhuo", "zou", "zuo",
}

KOREAN_SURNAMES = {
    "ahn", "an", "bae", "baek", "bak", "bang", "bok", "byun", "cha", "chang", "cho",
    "choi", "chun", "eom", "gang", "go", "gong", "goo", "gu", "gwak", "han", "heo",
    "hong", "huh", "hwang", "im", "jang", "jeon", "jeong", "jin", "jo", "joo", "ju",
    "jung", "kang", "kim", "ko", "koo", "kwak", "kwon", "lee", "lim", "ma", "min",
    "moon", "mun", "na", "nam", "no", "noh", "oh", "ok", "park", "ryu", "seo", "seok",
    "shim", "shin", "sim", "sin", "son", "song", "um", "yang", "yeo", "yoo", "yoon",
    "yu", "yun",
}

KOREAN_GIVEN_FIRST_EXCEPTIONS = {
    "ian choi",
    "jun woo yang",
    "yijoon park",
}

TAIWAN_GIVEN_COMMA_EXCEPTIONS = {
    "en yu lin",
}

MACAU_GIVEN_FIRST_YEARS = {2021, 2022}
JAPAN_GIVEN_FIRST_YEARS = {2013, 2014, 2015}
SOUTHEAST_ASIAN_CHINESE_COUNTRIES = {"Malaysia", "Singapore"}

FAMILY_FIRST_YEARS = {
    "Bulgaria": {2015, 2016},
    "Cyprus": {2015, 2019},
    "Kazakhstan": {2013, 2015, 2016, 2023},
    "Mongolia": {2015, 2016, 2017},
    "Romania": {2013, 2014, 2015, 2016, 2017, 2018, 2019, 2021, 2022, 2023},
    "Tajikistan": {2016, 2017, 2018, 2019, 2021, 2022},
}

GIVEN_FIRST_SOURCE_EXCEPTIONS = {
    ("Bulgaria", "margulan erlanovich ismoldayev"),
    ("Cyprus", "christofis michail"),
    ("Romania", "alexandru ilie"),
    ("Romania", "ana alexia gradinaru"),
    ("Romania", "andreea ristescu"),
    ("Romania", "bogdan stelian duminica"),
    ("Romania", "cristian dimitrie caba"),
    ("Romania", "ioana cristina prioteasa"),
    ("Romania", "malina elena constantinescu"),
    ("Romania", "maria otilia casuneanu"),
    ("Romania", "matei bogdan plescan"),
    ("Romania", "nicolae timofte"),
    ("Romania", "razvan lisa"),
    ("Romania", "veronica ioana rotaru"),
    ("Tajikistan", "azamat dushanov"),
    ("Tajikistan", "bakhtovari khotami"),
    ("Tajikistan", "fariz dekhoti"),
}

CENTRAL_ASIAN_SURNAME_SUFFIX = re.compile(
    r"(?:bekov|boyev|boev|qulov|kulov|zoda|zade|iyev|ieva|yev|yeva|ov|ova|ev|eva)$"
)
BULGARIAN_FAMILY_SUFFIX = re.compile(r"(?:ov|ev|ova|eva|ski|ska)$")
SPANISH_TWO_SURNAME_COUNTRIES = {"Bolivia", "Mexico", "Peru"}
SPANISH_SURNAME_PARTICLES = {"da", "de", "del", "do", "dos", "la", "las", "los"}

CROSS_STAGE_CANONICAL_RULES = [
    {
        "country": "Philippines",
        "aliases": ("Trisha Danielle Ko Sia", "Trisha Danielle K. Sia"),
        "canonical": "Trisha Danielle Ko Sia",
        "last_first": "Sia, Trisha Danielle Ko",
        "note": "Trisha Danielle K. Sia -> Trisha Danielle Ko Sia",
    },
    {
        "country": "Philippines",
        "aliases": ("Fredrick Lance R. Lim", "Fedrick Lance R. Lim"),
        "canonical": "Fredrick Lance R. Lim",
        "last_first": "Lim, Fredrick Lance R.",
        "note": "Fedrick Lance R. Lim -> Fredrick Lance R. Lim (source spelling conflict; earlier full source retained)",
    },
    {
        "country": "Philippines",
        "aliases": ("Sean Kendrick Ng Yeo", "Sean Kendrick N. Yeo"),
        "canonical": "Sean Kendrick Ng Yeo",
        "last_first": "Yeo, Sean Kendrick Ng",
        "note": "Sean Kendrick N. Yeo -> Sean Kendrick Ng Yeo",
    },
    {
        "country": "Philippines",
        "aliases": ("Immanuel Josiah Ang Balete", "Immanuel Josiah A. Balete"),
        "canonical": "Immanuel Josiah Ang Balete",
        "last_first": "Balete, Immanuel Josiah Ang",
        "note": "Immanuel Josiah A. Balete -> Immanuel Josiah Ang Balete",
    },
    {
        "country": "Philippines",
        "aliases": ("Bryce Ainsley Ang Sanchez", "Bryce Ainsley A. Sanchez"),
        "canonical": "Bryce Ainsley Ang Sanchez",
        "last_first": "Sanchez, Bryce Ainsley Ang",
        "note": "Bryce Ainsley A. Sanchez -> Bryce Ainsley Ang Sanchez",
    },
    {
        "country": "Philippines",
        "aliases": ("Stephen James Lim Ty", "Stephen James L. Ty"),
        "canonical": "Stephen James Lim Ty",
        "last_first": "Ty, Stephen James Lim",
        "note": "Stephen James L. Ty -> Stephen James Lim Ty",
    },
    {
        "country": "Philippines",
        "aliases": ("Jaymi Mae Lim Ching", "Jaymi Mae L. Ching"),
        "canonical": "Jaymi Mae Lim Ching",
        "last_first": "Ching, Jaymi Mae Lim",
        "note": "Jaymi Mae L. Ching -> Jaymi Mae Lim Ching",
    },
    {
        "country": "Philippines",
        "aliases": ("Jared Cobe Woo Ng", "Jared Cobe W. Ng"),
        "canonical": "Jared Cobe Woo Ng",
        "last_first": "Ng, Jared Cobe Woo",
        "note": "Jared Cobe W. Ng -> Jared Cobe Woo Ng",
    },
    {
        "country": "Philippines",
        "aliases": ("Kate Dominique Kung Siaco", "Kate Dominique K. Siaco"),
        "canonical": "Kate Dominique Kung Siaco",
        "last_first": "Siaco, Kate Dominique Kung",
        "note": "Kate Dominique K. Siaco -> Kate Dominique Kung Siaco",
    },
    {
        "country": "Philippines",
        "aliases": ("Ryan Mark L. Shao", "Ryan Mark Shao"),
        "canonical": "Ryan Mark L. Shao",
        "last_first": "Shao, Ryan Mark L.",
        "note": "Ryan Mark Shao -> Ryan Mark L. Shao",
    },
    {
        "country": "Philippines",
        "aliases": ("Kei Hang Derek Hao Chan", "Kei Hang Derek Chan"),
        "canonical": "Kei Hang Derek Hao Chan",
        "last_first": "Chan, Kei Hang Derek Hao",
        "note": "Kei Hang Derek Chan -> Kei Hang Derek Hao Chan",
    },
    {
        "country": "Philippines",
        "aliases": ("Ambrose James Garcia Torreon", "Ambrose James G. Torreon"),
        "canonical": "Ambrose James Garcia Torreon",
        "last_first": "Torreon, Ambrose James Garcia",
        "note": "Ambrose James G. Torreon -> Ambrose James Garcia Torreon",
    },
    {
        "country": "Philippines",
        "aliases": ("Alyana Zoie Siytiu Chua", "Alyana Zoie S. Chua"),
        "canonical": "Alyana Zoie Siytiu Chua",
        "last_first": "Chua, Alyana Zoie Siytiu",
        "note": "Alyana Zoie S. Chua -> Alyana Zoie Siytiu Chua",
    },
    {
        "country": "Philippines",
        "aliases": ("Ethan Jared Reyes Chan", "Ethan Jared Chan"),
        "canonical": "Ethan Jared Reyes Chan",
        "last_first": "Chan, Ethan Jared Reyes",
        "note": "Ethan Jared Chan -> Ethan Jared Reyes Chan",
    },
    {
        "country": "Philippines",
        "aliases": ("Neo Angelo G. Gatlabayan", "Neo A. Gatlabayan"),
        "canonical": "Neo Angelo G. Gatlabayan",
        "last_first": "Gatlabayan, Neo Angelo G.",
        "note": "Neo A. Gatlabayan -> Neo Angelo G. Gatlabayan",
    },
    {
        "country": "Indonesia",
        "aliases": ("Luthfi Bima Putra", "Luthfi Bimaputra"),
        "canonical": "Luthfi Bima Putra",
        "last_first": "Putra, Luthfi Bima",
        "note": "Luthfi Bimaputra -> Luthfi Bima Putra (Indonesian school records)",
    },
    {
        "country": "Indonesia",
        "aliases": ("Felicia Grace Angelyn Ferdianto", "Felicia Grace Angelyn F"),
        "canonical": "Felicia Grace Angelyn Ferdianto",
        "last_first": "Ferdianto, Felicia Grace Angelyn",
        "note": "Felicia Grace Angelyn F -> Felicia Grace Angelyn Ferdianto (Indonesian government/school records)",
    },
    {
        "country": "Uzbekistan",
        "aliases": ("Jakhongir Norboev", "Jahongir Norboev"),
        "canonical": "Jakhongir Norboev",
        "last_first": "Norboev, Jakhongir",
        "note": "Jahongir Norboev -> Jakhongir Norboev (IMO spelling)",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Deyan Deyanov Hadzhi-Manich", "Deyan Deyanov Hadzhi Manich", "Deyan Deyanov Hadji-Manich"),
        "canonical": "Deyan Deyanov Hadzhi-Manich",
        "last_first": "Hadzhi-Manich, Deyan Deyanov",
        "note": "Deyan Deyanov Hadji-Manich / Hadzhi Manich -> Deyan Deyanov Hadzhi-Manich (official IOAI spelling)",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Georgi Atanasov", "Geohgi Atanasov"),
        "canonical": "Georgi Atanasov",
        "last_first": "Atanasov, Georgi",
        "note": "Geohgi Atanasov -> Georgi Atanasov",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Evgeni Staev Kayryakov", "Evgeni Staev Kairakov"),
        "canonical": "Evgeni Staev Kayryakov",
        "last_first": "Kayryakov, Evgeni Staev",
        "note": "Evgeni Staev Kairakov -> Evgeni Staev Kayryakov (official RMM spelling)",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Ivan-Aleksandar Veselinov Mavrov", "Ivan-Aleksandar Mavrov"),
        "canonical": "Ivan-Aleksandar Veselinov Mavrov",
        "last_first": "Mavrov, Ivan-Aleksandar Veselinov",
        "note": "Ivan-Aleksandar Mavrov -> Ivan-Aleksandar Veselinov Mavrov",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Aleksandar Georgiev Georgiev", "Aleksandar Georgiev"),
        "canonical": "Aleksandar Georgiev Georgiev",
        "last_first": "Georgiev, Aleksandar Georgiev",
        "note": "Aleksandar Georgiev -> Aleksandar Georgiev Georgiev",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Kaloyan Todorov Fachikov", "Kaloyan Fachikov"),
        "canonical": "Kaloyan Todorov Fachikov",
        "last_first": "Fachikov, Kaloyan Todorov",
        "note": "Kaloyan Fachikov -> Kaloyan Todorov Fachikov",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Vanesa Angelova Kalinkova", "Vanesa Kalinkova"),
        "canonical": "Vanesa Angelova Kalinkova",
        "last_first": "Kalinkova, Vanesa Angelova",
        "note": "Vanesa Kalinkova -> Vanesa Angelova Kalinkova",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Marin Hristov Hristov", "Marin Hristov"),
        "canonical": "Marin Hristov Hristov",
        "last_first": "Hristov, Marin Hristov",
        "note": "Marin Hristov -> Marin Hristov Hristov",
    },
    {
        "country": "Thailand",
        "aliases": ("Kittipong Ruamsub", "Kittipong Ruemsub"),
        "canonical": "Kittipong Ruamsub",
        "last_first": "Ruamsub, Kittipong",
        "note": "Kittipong Ruemsub -> Kittipong Ruamsub (later source spelling)",
    },
    {
        "country": "Thailand",
        "aliases": ("Nattaphat Phattanapiradech", "Nattaphat Pathanapiradech"),
        "canonical": "Nattaphat Phattanapiradech",
        "last_first": "Phattanapiradech, Nattaphat",
        "note": "Nattaphat Pathanapiradech -> Nattaphat Phattanapiradech",
    },
    {
        "country": "Thailand",
        "aliases": ("Thanakorn Auttawetchakul", "Thanakorn Auttawatchakui"),
        "canonical": "Thanakorn Auttawetchakul",
        "last_first": "Auttawetchakul, Thanakorn",
        "note": "Thanakorn Auttawatchakui -> Thanakorn Auttawetchakul",
    },
    {
        "country": "Romania",
        "aliases": ("Răzvan Andrei Morariu", "Razvan Andrei Morariu", "Razvan Morariu"),
        "canonical": "Răzvan Andrei Morariu",
        "last_first": "Morariu, Răzvan Andrei",
        "note": "Razvan Morariu -> Răzvan Andrei Morariu",
    },
    {
        "country": "Romania",
        "aliases": (
            "Bogdan-Stelian Duminică",
            "Bogdan-Stelian Duminica",
            "Bogdan Duminica",
            "Duminica Bogdan",
        ),
        "canonical": "Bogdan-Stelian Duminică",
        "last_first": "Duminică, Bogdan-Stelian",
        "note": "Bogdan Duminica -> Bogdan-Stelian Duminică (same ROU2A01 contestant ID in consecutive years)",
    },
    {
        "country": "Mongolia",
        "aliases": ("Amar Nyamdavaa", "Nyamdavaa Amar"),
        "canonical": "Amar Nyamdavaa",
        "last_first": "Nyamdavaa, Amar",
        "note": "Nyamdavaa Amar / Amar Nyamdavaa -> Amar Nyamdavaa (cross-stage source-order reversal; official IMO display order confirms Nyamdavaa Amar)",
    },
    {
        "country": "Tajikistan",
        "aliases": ("Doriush Khayridinov", "Doriush Khairidinov"),
        "canonical": "Doriush Khayridinov",
        "last_first": "Khayridinov, Doriush",
        "note": "Doriush Khairidinov -> Doriush Khayridinov (IMO spelling; shared cross-stage identity)",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Dobromir Angelov", "Dobromir Dobromirov Angelov"),
        "canonical": "Dobromir Dobromirov Angelov",
        "last_first": "Angelov, Dobromir Dobromirov",
        "note": "Dobromir Angelov -> Dobromir Dobromirov Angelov (full patronymic source; EMIC 2019 to IWYMIC 2021-2023 progression)",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Kiril Bangachev", "Kiril Atanasov Bangachev"),
        "canonical": "Kiril Atanasov Bangachev",
        "last_first": "Bangachev, Kiril Atanasov",
        "note": "Kiril Bangachev -> Kiril Atanasov Bangachev (full patronymic source; later IMO short form confirms the identity)",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Boris Barbov", "Boris Aleksandrov Barbov"),
        "canonical": "Boris Aleksandrov Barbov",
        "last_first": "Barbov, Boris Aleksandrov",
        "note": "Boris Barbov -> Boris Aleksandrov Barbov (full patronymic source; consecutive age-stage progression)",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Martin Dimitrov", "Martin Dimitrov Dimitrov"),
        "canonical": "Martin Dimitrov Dimitrov",
        "last_first": "Dimitrov, Martin Dimitrov",
        "note": "Martin Dimitrov -> Martin Dimitrov Dimitrov (full patronymic source; consecutive IWYMIC appearances)",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Ivan Georgiev", "Ivan Ventsislavov Georgiev"),
        "canonical": "Ivan Ventsislavov Georgiev",
        "last_first": "Georgiev, Ivan Ventsislavov",
        "note": "Ivan Georgiev -> Ivan Ventsislavov Georgiev (full patronymic source; EMIC-to-IWYMIC progression; Ivan Todorov Georgiev remains distinct)",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Boris Gerginov", "Boris Velkov Gerginov"),
        "canonical": "Boris Velkov Gerginov",
        "last_first": "Gerginov, Boris Velkov",
        "note": "Boris Gerginov -> Boris Velkov Gerginov (full patronymic source; EMIC-to-IWYMIC progression)",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Asel Ismoldaeva", "Asel Irlanovna Ismoldaeva"),
        "canonical": "Asel Irlanovna Ismoldaeva",
        "last_first": "Ismoldaeva, Asel Irlanovna",
        "note": "Asel Ismoldaeva -> Asel Irlanovna Ismoldaeva (full patronymic source; non-overlapping IWYMIC appearances)",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Zlatina Mileva", "Zlatina Todorova Mileva"),
        "canonical": "Zlatina Todorova Mileva",
        "last_first": "Mileva, Zlatina Todorova",
        "note": "Zlatina Mileva -> Zlatina Todorova Mileva (full patronymic source; independently listed in Mathematics Without Borders results)",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Irina Sofronova", "Irina Julianova Sofronova"),
        "canonical": "Irina Julianova Sofronova",
        "last_first": "Sofronova, Irina Julianova",
        "note": "Irina Sofronova -> Irina Julianova Sofronova (full patronymic source; EMIC-to-IWYMIC progression)",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Kaloyan Tsanev", "Kaloyan Vladislavov Tsanev"),
        "canonical": "Kaloyan Vladislavov Tsanev",
        "last_first": "Tsanev, Kaloyan Vladislavov",
        "note": "Kaloyan Tsanev -> Kaloyan Vladislavov Tsanev (full patronymic source; independently listed in Bulgarian mathematics results)",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Neli Tsokanova", "Neli Tsvetanova Tsokanova"),
        "canonical": "Neli Tsvetanova Tsokanova",
        "last_first": "Tsokanova, Neli Tsvetanova",
        "note": "Neli Tsokanova -> Neli Tsvetanova Tsokanova (full patronymic source; EMIC-to-IWYMIC progression)",
    },
    {
        "country": "Canada",
        "aliases": ("Andrew Carlson", "Andrew Chunwing Carlson"),
        "canonical": "Andrew Chunwing Carlson",
        "last_first": "Carlson, Andrew Chunwing",
        "note": "Andrew Carlson -> Andrew Chunwing Carlson (full middle-name source; EMIC 2014 to IWYMIC 2016-2018 progression)",
    },
    {
        "country": "Indonesia",
        "aliases": ("M. Abdurrahman B.", "Muhammad Abdurrahman Basyah"),
        "canonical": "Muhammad Abdurrahman Basyah",
        "last_first": "Basyah, Muhammad Abdurrahman",
        "note": "M. Abdurrahman B. -> Muhammad Abdurrahman Basyah (initials expand exactly; consecutive EMIC/IWYMIC source progression)",
    },
    {
        "country": "Macau",
        "aliases": ("Iek Hin Ng", "Iek Hin Bosco Ng"),
        "canonical": "Iek Hin Bosco Ng",
        "last_first": "Ng, Iek Hin Bosco",
        "note": "Iek Hin Ng -> Iek Hin Bosco Ng (full English middle-name source; EMIC-to-IWYMIC progression)",
    },
    {
        "country": "Macau",
        "aliases": ("Chi Hou Leong", "Chi Hou Leung"),
        "canonical": "Chi Hou Leong",
        "last_first": "Leong, Chi Hou",
        "note": "Chi Hou Leung -> Chi Hou Leong (Leung/Leong surname romanization; exact given name in non-overlapping IWYMIC appearances)",
    },
    {
        "country": "Republic of Korea",
        "aliases": ("Seongjoon Jo", "Seongjoon Cho"),
        "canonical": "Seongjoon Cho",
        "last_first": "Cho, Seongjoon",
        "note": "Seongjoon Jo -> Seongjoon Cho (Jo/Cho surname romanization; exact given name in consecutive IWYMIC appearances)",
    },
    {
        "country": "Sri Lanka",
        "aliases": (
            "H.M.M.A. Bandara",
            "Mihiru Anushka Bandara",
            "Hitihami Mudiyanselage Mihiru Anushka Bandara",
        ),
        "canonical": "Hitihami Mudiyanselage Mihiru Anushka Bandara",
        "last_first": "Bandara, Hitihami Mudiyanselage Mihiru Anushka",
        "note": "H.M.M.A. Bandara -> Hitihami Mudiyanselage Mihiru Anushka Bandara (official IMO full name; APMO short form)",
    },
    {
        "country": "Sri Lanka",
        "aliases": (
            "R.M.M. Manuja Jayasekara",
            "Ramanayake Mudiyanselage Minindu Manuja Jayasekara",
        ),
        "canonical": "Ramanayake Mudiyanselage Minindu Manuja Jayasekara",
        "last_first": "Jayasekara, Ramanayake Mudiyanselage Minindu Manuja",
        "note": "R.M.M. Manuja Jayasekara -> Ramanayake Mudiyanselage Minindu Manuja Jayasekara (Sri Lanka Olympiad Mathematics Foundation full name)",
    },
    {
        "country": "Sri Lanka",
        "aliases": ("R.T.U. Jayasena", "Tharaka Udayanga Jayasena"),
        "canonical": "Tharaka Udayanga Jayasena",
        "last_first": "Jayasena, Tharaka Udayanga",
        "note": "R.T.U. Jayasena -> Tharaka Udayanga Jayasena (official APMO and FIDE full name)",
    },
    {
        "country": "Sri Lanka",
        "aliases": (
            "W.S. Nethmina Perera",
            "Welikadage Sithusha Nethmina Perera",
        ),
        "canonical": "Welikadage Sithusha Nethmina Perera",
        "last_first": "Perera, Welikadage Sithusha Nethmina",
        "note": "W.S. Nethmina Perera -> Welikadage Sithusha Nethmina Perera (Sri Lanka Olympiad Mathematics Foundation full name)",
    },
    {
        "country": "Sri Lanka",
        "aliases": ("S.A. Kotuwewatta", "Sithija Abhishek Kotuwewatta"),
        "canonical": "Sithija Abhishek Kotuwewatta",
        "last_first": "Kotuwewatta, Sithija Abhishek",
        "note": "S.A. Kotuwewatta -> Sithija Abhishek Kotuwewatta (initials, chronology, and official APMO/IMO records)",
    },
    {
        "country": "Sri Lanka",
        "aliases": ("S.B. Marapana", "Sanupa Bimsath Marapana"),
        "canonical": "Sanupa Bimsath Marapana",
        "last_first": "Marapana, Sanupa Bimsath",
        "note": "S.B. Marapana -> Sanupa Bimsath Marapana (initials, chronology, and official APMO record)",
    },
    {
        "country": "Sri Lanka",
        "aliases": (
            "P.L.D. Pathirana",
            "Luchitha Disal Pathirana",
            "Pathirannehelage Luchitha Disal Pathirana",
        ),
        "canonical": "Pathirannehelage Luchitha Disal Pathirana",
        "last_first": "Pathirana, Pathirannehelage Luchitha Disal",
        "note": "P.L.D. Pathirana / Luchitha Disal Pathirana -> Pathirannehelage Luchitha Disal Pathirana (initials, chronology, and official APMO/IMO records)",
    },
    {
        "country": "Sri Lanka",
        "aliases": ("G.M.B. Perera", "Gonaduwage Maneth Banula Perera"),
        "canonical": "Gonaduwage Maneth Banula Perera",
        "last_first": "Perera, Gonaduwage Maneth Banula",
        "note": "G.M.B. Perera -> Gonaduwage Maneth Banula Perera (initials, chronology, and official APMO/IMO records)",
    },
    {
        "country": "Sri Lanka",
        "aliases": (
            "T.V.N. Vithanachchi",
            "Thellabura Vithanachchige Nelushi Vithanachchi",
        ),
        "canonical": "Thellabura Vithanachchige Nelushi Vithanachchi",
        "last_first": "Vithanachchi, Thellabura Vithanachchige Nelushi",
        "note": "T.V.N. Vithanachchi -> Thellabura Vithanachchige Nelushi Vithanachchi (initials, chronology, and official APMO/IMO records)",
    },
    {
        "country": "Sri Lanka",
        "aliases": (
            "C.T.B. Wanasinghe",
            "Chandhopama Thidas Bandara Wanasinghe",
        ),
        "canonical": "Chandhopama Thidas Bandara Wanasinghe",
        "last_first": "Wanasinghe, Chandhopama Thidas Bandara",
        "note": "C.T.B. Wanasinghe -> Chandhopama Thidas Bandara Wanasinghe (initials, chronology, and official APMO/IMO records)",
    },
    {
        "country": "Tajikistan",
        "aliases": ("Abdurauf Abdurasulov", "Abdurauf Zinatulloevich Abdurasulov"),
        "canonical": "Abdurauf Zinatulloevich Abdurasulov",
        "last_first": "Abdurasulov, Abdurauf Zinatulloevich",
        "note": "Abdurauf Abdurasulov -> Abdurauf Zinatulloevich Abdurasulov (full patronymic source; EMIC-to-IWYMIC progression)",
    },
]


def _build_cross_stage_aliases() -> dict[tuple[str, str], tuple[str, str]]:
    aliases: dict[tuple[str, str], tuple[str, str]] = {}
    for rule in CROSS_STAGE_CANONICAL_RULES:
        value = (clean_text(rule["canonical"]), clean_text(rule["last_first"]))
        for alias in (*rule["aliases"], rule["canonical"]):
            aliases[(key_text(rule["country"]), key_text(alias))] = value
    return aliases


CROSS_STAGE_ALIAS_RULES = _build_cross_stage_aliases()


def compact_given_name(parts: list[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return parts[0] + "".join(part[:1].lower() + part[1:] for part in parts[1:])


def family_first(value: str, *, compact_given: bool = False) -> tuple[str, str]:
    parts = clean_text(value).split()
    family = parts[0]
    given_parts = parts[1:]
    given = compact_given_name(given_parts) if compact_given else " ".join(given_parts)
    return clean_text(f"{given} {family}"), clean_text(f"{family}, {given}")


def given_first(value: str, *, compact_given: bool = False) -> tuple[str, str]:
    parts = clean_text(value).split()
    family = parts[-1]
    given_parts = parts[:-1]
    given = compact_given_name(given_parts) if compact_given else " ".join(given_parts)
    return clean_text(f"{given} {family}"), clean_text(f"{family}, {given}")


def southeast_asian_chinese_order(value: str) -> tuple[str, str] | None:
    """Normalize the Chinese-name formats used by Malaysia and Singapore."""
    if "," in value:
        left, right = [part.strip() for part in value.split(",", 1)]
        left_parts = left.split()
        if not left_parts or key_text(left_parts[0]) not in CHINESE_SURNAMES:
            return None
        family = left_parts[0]
        given = " ".join([right, *left_parts[1:]])
        return clean_text(f"{given} {family}"), clean_text(f"{family}, {given}")

    parts = value.split()
    if len(parts) < 2:
        return None
    if key_text(parts[0]) in CHINESE_SURNAMES:
        return family_first(value)
    if len(parts) >= 3 and key_text(parts[1]) in CHINESE_SURNAMES:
        family = parts[1]
        given = " ".join([parts[0], *parts[2:]])
        return clean_text(f"{given} {family}"), clean_text(f"{family}, {given}")
    return None


def reviewed_source_order(
    source_name: str,
    country: str,
    year: int,
) -> tuple[str, str] | None:
    value = clean_text(source_name)
    if len(value.split()) < 2:
        return None

    if country == "People's Republic of China" and "," not in value:
        return family_first(value, compact_given=True)

    if country == "Republic of Korea" and "," not in value:
        parts = value.split()
        first = key_text(parts[0])
        last = key_text(parts[-1])
        if key_text(value) in KOREAN_GIVEN_FIRST_EXCEPTIONS:
            return given_first(value, compact_given=True)
        if first in KOREAN_SURNAMES and last not in KOREAN_SURNAMES:
            return family_first(value, compact_given=True)
        if last in KOREAN_SURNAMES and first not in KOREAN_SURNAMES:
            return given_first(value, compact_given=True)
        if first in KOREAN_SURNAMES:
            return family_first(value, compact_given=True)

    if country == "Taiwan" and "," in value:
        left, right = [part.strip() for part in value.split(",", 1)]
        if key_text(f"{left} {right}") in TAIWAN_GIVEN_COMMA_EXCEPTIONS:
            return clean_text(f"{left} {right}"), clean_text(f"{right}, {left}")

    if country == "Hong Kong" and "," not in value:
        parts = value.split()
        first = key_text(parts[0])
        last = key_text(parts[-1])
        if first not in CHINESE_SURNAMES and last in CHINESE_SURNAMES:
            return given_first(value)
        return family_first(value)

    if country == "Macau" and "," not in value:
        if year in MACAU_GIVEN_FIRST_YEARS:
            return given_first(value)
        return family_first(value)

    if country == "Japan" and year in JAPAN_GIVEN_FIRST_YEARS and "," not in value:
        return given_first(value)

    if country in SOUTHEAST_ASIAN_CHINESE_COUNTRIES:
        return southeast_asian_chinese_order(value)

    if (
        year in FAMILY_FIRST_YEARS.get(country, set())
        and (country, key_text(value)) not in GIVEN_FIRST_SOURCE_EXCEPTIONS
        and "," not in value
    ):
        return family_first(value)

    if country == "Bulgaria" and "," not in value:
        if BULGARIAN_FAMILY_SUFFIX.search(key_text(value.split()[0])):
            return family_first(value)

    if country == "Uzbekistan" and "," not in value:
        parts = value.split()
        first_is_family = bool(CENTRAL_ASIAN_SURNAME_SUFFIX.search(key_text(parts[0])))
        last_is_family = bool(CENTRAL_ASIAN_SURNAME_SUFFIX.search(key_text(parts[-1])))
        if first_is_family and not last_is_family:
            return family_first(value)
        if key_text(value) == "li david":
            return family_first(value)

    if country == "Vietnam" and "," not in value:
        return family_first(value)

    return None


def vietnamese_reference_order(
    source_name: str,
    reference_first_last: str,
) -> tuple[str, str] | None:
    source_parts = clean_text(source_name).replace(",", " ").split()
    reference_parts = clean_text(reference_first_last).split()
    if len(source_parts) < 2 or len(reference_parts) < 2:
        return None

    family_key = key_text(source_parts[0])
    family_index = next(
        (index for index, part in enumerate(reference_parts) if key_text(part) == family_key),
        None,
    )
    if family_index is None:
        return None
    family = reference_parts[family_index]
    given = " ".join(reference_parts[:family_index] + reference_parts[family_index + 1 :])
    return clean_text(f"{given} {family}"), clean_text(f"{family}, {given}")


def review_name(
    *,
    source_name: str,
    country: str,
    year: int,
    base_first_last: str,
    base_last_first: str,
    base_variant_first_last: str,
) -> ReviewedName:
    first_last = clean_text(base_first_last)
    last_first = clean_text(base_last_first)
    variant = clean_text(base_variant_first_last)
    manually_canonicalized = first_last != variant

    source_order = reviewed_source_order(source_name, country, year)
    if source_order:
        ordered_first_last, ordered_last_first = source_order
        if (
            token_key(first_last) == token_key(ordered_first_last)
            or character_key(first_last) == character_key(ordered_first_last)
            or character_bag_key(first_last) == character_bag_key(ordered_first_last)
        ):
            if not manually_canonicalized:
                first_last = ordered_first_last
                last_first = ordered_last_first
        variant = ordered_first_last

    reference = IMO_REFERENCE.get((key_text(country), token_key(first_last)))
    if reference and source_order and country != "Vietnam":
        source_family = key_text(source_order[1].split(",", 1)[0])
        reference_family = key_text(reference[1].split(",", 1)[0])
        if source_family != reference_family:
            reference = None
    if reference:
        reference_first_last, reference_last_first = reference
        if country == "Vietnam":
            vietnamese_order = vietnamese_reference_order(source_name, reference_first_last)
            if vietnamese_order:
                reference_first_last, reference_last_first = vietnamese_order
        first_last = reference_first_last
        last_first = reference_last_first
    elif (
        country in SPANISH_TWO_SURNAME_COUNTRIES
        and "," not in clean_text(source_name)
        and len(first_last.split()) >= 3
    ):
        parts = first_last.split()
        surname_start = len(parts) - 2
        if surname_start > 1 and key_text(parts[surname_start - 1]) in SPANISH_SURNAME_PARTICLES:
            surname_start -= 1
        given = " ".join(parts[:surname_start])
        family = " ".join(parts[surname_start:])
        last_first = clean_text(f"{family}, {given}")

    cross_stage = CROSS_STAGE_ALIAS_RULES.get((key_text(country), key_text(first_last)))
    if cross_stage:
        canonical_first_last, canonical_last_first = cross_stage
        if first_last != canonical_first_last:
            variant = first_last
        first_last = canonical_first_last
        last_first = canonical_last_first

    return ReviewedName(
        first_last=clean_text(first_last),
        last_first=clean_text(last_first),
        variant_first_last=clean_text(variant),
    )
