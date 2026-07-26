#!/usr/bin/env python3
"""Extract EMIC / Keystage II individual results from chiuchang.org.

The script intentionally uses only the Python standard library. It downloads
the official IMC result pages, caches the raw HTML, parses the result tables,
and writes both per-appearance and de-duplicated contestant CSVs.
"""

from __future__ import annotations

import argparse
import csv
import html
from html.parser import HTMLParser
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from emic_name_review import CROSS_STAGE_CANONICAL_RULES, align_last_first, review_name
from project_paths import (
    EMIC_AUDIT_PATH,
    EMIC_AWARDED_PATH,
    EMIC_CHANGELOG_PATH,
    EMIC_MEDAL_BUCKETS_PATH,
    EMIC_MEDAL_SUMMARY_PATH,
    EMIC_PROCESSED_DIR,
    EMIC_UNIQUE_PATH,
    RAW_EMIC_IWYMIC_DIR,
)


YEARS = [2013, 2014, 2015, 2016, 2017, 2018, 2019, 2021, 2022, 2023]
MAX_SAME_STAGE_YEAR_SPAN = 2

CATEGORY_URLS = {
    2013: "https://chiuchang.org/imc/en/category/bimc-2013-en/",
    2014: "https://chiuchang.org/imc/en/category/kimc-2014-en/",
    2015: "https://chiuchang.org/imc/en/category/cimc-2015-en/",
    2016: "https://chiuchang.org/imc/en/category/timc-2016-en/",
    2017: "https://chiuchang.org/imc/en/category/inimc-2017-en/",
    2018: "https://chiuchang.org/imc/en/category/bimc-2018/",
    2019: "https://chiuchang.org/imc/en/category/saimc-2019/",
    2021: "https://chiuchang.org/imc/en/category/iimc-2021/",
    2022: "https://chiuchang.org/imc/en/category/iimc-2022/",
    2023: "https://chiuchang.org/imc/en/category/bimc2023-en/",
}

TOTAL_PARTICIPANTS = {
    2013: 294,
    2014: 323,
    2015: 308,
    2016: 262,
    2017: 299,
    2018: 314,
    2019: 255,
    2021: 312,
    2022: 288,
    2023: 308,
}

TOTAL_PARTICIPANTS_SOURCE = "friend_researched_total"

MEDAL_ORDER = ["Gold", "Silver", "Bronze", "Merit"]
MEDAL_SORT_KEY = {medal: index for index, medal in enumerate(MEDAL_ORDER)}

FRIEND_MEDAL_BUCKETS = {
    2013: {
        "Gold": [1, 5, 3, 8],
        "Silver": [7, 17, 26],
        "Bronze": [20, 27],
        "Merit": [24, 34, 25],
    },
    2014: {
        "Gold": [2, 5, 6, 14],
        "Silver": [23, 20],
        "Bronze": [19, 30],
        "Merit": [31, 28, 14],
    },
    2015: {
        "Gold": [4, 2, 7, 13],
        "Silver": [14, 35],
        "Bronze": [35],
        "Merit": [31, 40, 33],
    },
    2016: {
        "Gold": [2, 5, 6],
        "Silver": [14, 20],
        "Bronze": [17, 19, 27],
        "Merit": [24, 20, 23, 19],
    },
    2017: {
        "Gold": [1, 3, 2, 6, 6],
        "Silver": [7, 16, 24],
        "Bronze": [21, 31],
        "Merit": [29, 31],
    },
    2018: {
        "Gold": [5, 8, 16],
        "Silver": [16],
        "Bronze": [37, 28],
        "Merit": [42, 50],
    },
    2019: {
        "Gold": [7, 14],
        "Silver": [17, 18],
        "Bronze": [20, 21],
        "Merit": [23, 21, 24],
    },
    2021: {
        "Gold": [1, 4, 9, 7],
        "Silver": [11, 11, 19],
        "Bronze": [19, 22, 18],
        "Merit": [30, 23, 37],
    },
    2022: {
        "Gold": [3, 5, 6],
        "Silver": [14, 12, 21],
        "Bronze": [27, 28],
        "Merit": [29, 41, 30],
    },
    2023: {
        "Gold": [4, 7, 10],
        "Silver": [22, 23],
        "Bronze": [23, 39],
        "Merit": [15, 27, 31, 37],
    },
}

COUNTRY_ALIASES = {
    "CHINA": "People's Republic of China",
    "China": "People's Republic of China",
    "Hong Kong, China": "Hong Kong",
    "Iran": "Islamic Republic of Iran",
    "Korea": "Republic of Korea",
    "Macau, China": "Macau",
    "Netherland": "Netherlands",
    "Russia": "Russian Federation",
    "South Korea": "Republic of Korea",
    "Turkey": "Türkiye",
    "USA": "United States of America",
    "U.S.A.": "United States of America",
    "United States": "United States of America",
    "UAE": "United Arab Emirates",
}

INTERNATIONAL_ID_PREFIX_COUNTRIES = {
    "BUL": "Bulgaria",
    "MAS": "Malaysia",
    "PHI": "Philippines",
    "RUS": "Russian Federation",
    "THA": "Thailand",
    "VIE": "Vietnam",
}

INTERNATIONAL_NAME_COUNTRIES = {
    "goo ga rin": "Republic of Korea",
    "joo hae jin": "Republic of Korea",
    "kim jeong woo": "Republic of Korea",
    "kim ji tae": "Republic of Korea",
    "kristian emilov minchev": "Bulgaria",
    "meng wei qi": "People's Republic of China",
    "viktor petrov baltin": "Bulgaria",
}

COUNTRY_CHANGE_NOTES = [
    "China -> People's Republic of China",
    "Hong Kong, China -> Hong Kong",
    "Iran -> Islamic Republic of Iran",
    "Korea -> Republic of Korea",
    "Macau, China -> Macau",
    "Russia -> Russian Federation",
    "USA/U.S.A./United States -> United States of America",
]

INTERNATIONAL_CHANGE_NOTES = [
    "Kim Ji Tae -> Republic of Korea",
    "Goo Ga Rin -> Republic of Korea",
    "Viktor Petrov Baltin -> Bulgaria",
    "Joo Hae Jin -> Republic of Korea",
    "Kristian Emilov Minchev -> Bulgaria",
    "Kim Jeong Woo -> Republic of Korea",
    "Meng Wei Qi -> People's Republic of China",
    "Cao Thuy An -> Vietnam",
    "Matawee Leelalertwong -> Thailand",
    "Pak, Mi Jung -> Philippines",
    "Mihaylova Kamelia Svetoslsvsva -> Bulgaria",
    "Aidan Ong Ming Feng -> Malaysia",
    "Sharafetdinova Galiia -> Russian Federation",
    "Nguyen Dang Huyen My -> Vietnam",
    "Madrazo, Angelene Erika T. -> Philippines",
    "Josiah Kho Rui Ming -> Malaysia",
]

GIVEN_COMMA_NAME_OVERRIDES = {
    "United States of America": {
        "Kenny, Wang": ("Kenny Wang", "Wang, Kenny"),
        "Kevin, Chen": ("Kevin Chen", "Chen, Kevin"),
        "Yibing, Pei (Dianna)": ("Yibing (Dianna) Pei", "Pei, Yibing (Dianna)"),
        "Michelle, Fang": ("Michelle Fang", "Fang, Michelle"),
        "Jonathan, Huang": ("Jonathan Huang", "Huang, Jonathan"),
    }
}

NAME_CANONICALIZATION_RULES = [
    {
        "country": "Romania",
        "aliases": (
            "Bunau Corina Anamaria",
            "Bunau Corina- Anamaria",
            "Corina Anamaria Bunau",
            "Corina-Anamaria Bunau",
        ),
        "canonical": "Corina-Anamaria Bunău",
        "last_first": "Bunău, Corina-Anamaria",
        "note": "Bunau Corina Anamaria -> Corina-Anamaria Bunău (surname and diacritics verified from Romanian national-olympiad records)",
    },
    {
        "country": "Bolivia",
        "aliases": ("Franco Miguel Rinaldi Copa", "Franco Rinaldi"),
        "canonical": "Franco Miguel Rinaldi Copa",
        "last_first": "Rinaldi Copa, Franco Miguel",
        "note": "Franco Rinaldi -> Franco Miguel Rinaldi Copa",
    },
    {
        "country": "Indonesia",
        "aliases": ("Aditya Ilham Khairullah Seger", "Aditya Ilham K.S"),
        "canonical": "Aditya Ilham Khairullah Seger",
        "last_first": "Seger, Aditya Ilham Khairullah",
        "note": "Aditya Ilham K.S -> Aditya Ilham Khairullah Seger",
    },
    {
        "country": "Indonesia",
        "aliases": ("Muhammad Surya Siddiq", "M. Surya Siddiq"),
        "canonical": "Muhammad Surya Siddiq",
        "last_first": "Siddiq, Muhammad Surya",
        "note": "M. Surya Siddiq -> Muhammad Surya Siddiq",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Bozhidar Aleksandrov Sakarev", "Sakarev Bozhidar Aleksandrov"),
        "canonical": "Bozhidar Aleksandrov Sakarev",
        "last_first": "Sakarev, Bozhidar Aleksandrov",
        "note": "Sakarev Bozhidar Aleksandrov -> Bozhidar Aleksandrov Sakarev",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Boris Dimitrov Angelov", "Angelov Boris Dimitrov"),
        "canonical": "Boris Dimitrov Angelov",
        "last_first": "Angelov, Boris Dimitrov",
        "note": "Angelov Boris Dimitrov -> Boris Dimitrov Angelov",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Iliyas Bashir Noman", "Noman Iliyas Bashir"),
        "canonical": "Iliyas Bashir Noman",
        "last_first": "Noman, Iliyas Bashir",
        "note": "Noman Iliyas Bashir -> Iliyas Bashir Noman",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Cuong Viet Do", "Viet Cuong Do", "Do Viet Cuong", "Viet Do Cuong", "Do Cuong Viet"),
        "canonical": "Cuong Viet Do",
        "last_first": "Do, Cuong Viet",
        "note": "Do Viet Cuong / Viet Do Cuong -> Cuong Viet Do (official RMM roster spelling/order)",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Darina Spartak Marinova", "Marinova Darina Spartak"),
        "canonical": "Darina Spartak Marinova",
        "last_first": "Marinova, Darina Spartak",
        "note": "Marinova Darina Spartak -> Darina Spartak Marinova",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Venislav Emanoelov Ivanov", "Ivanov Venislav Emanoelov"),
        "canonical": "Venislav Emanoelov Ivanov",
        "last_first": "Ivanov, Venislav Emanoelov",
        "note": "Ivanov Venislav Emanoelov -> Venislav Emanoelov Ivanov",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Emiliyan Ventsislavov Stefanov", "Stefanov Emiliyan Ventsislavov"),
        "canonical": "Emiliyan Ventsislavov Stefanov",
        "last_first": "Stefanov, Emiliyan Ventsislavov",
        "note": "Stefanov Emiliyan Ventsislavov -> Emiliyan Ventsislavov Stefanov",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Stanislava Georgieva Petrova", "Petrova Stanislava Georgieva"),
        "canonical": "Stanislava Georgieva Petrova",
        "last_first": "Petrova, Stanislava Georgieva",
        "note": "Petrova Stanislava Georgieva -> Stanislava Georgieva Petrova",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Yoana Plamenova Mladenova", "Mladenova Yoana Plamenova"),
        "canonical": "Yoana Plamenova Mladenova",
        "last_first": "Mladenova, Yoana Plamenova",
        "note": "Mladenova Yoana Plamenova -> Yoana Plamenova Mladenova",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Alyara Alkanova Mahmudova", "Alyara Mahmudova"),
        "canonical": "Alyara Alkanova Mahmudova",
        "last_first": "Mahmudova, Alyara Alkanova",
        "note": "Alyara Mahmudova -> Alyara Alkanova Mahmudova",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Angel Antonov Hristov", "Angel Hristov"),
        "canonical": "Angel Antonov Hristov",
        "last_first": "Hristov, Angel Antonov",
        "note": "Angel Hristov -> Angel Antonov Hristov",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Dimitar Dimitrov Hristov", "Hristov Dimitar", "Hristov Dimitar Dimitrov"),
        "canonical": "Dimitar Dimitrov Hristov",
        "last_first": "Hristov, Dimitar Dimitrov",
        "note": "Hristov Dimitar / Hristov Dimitar Dimitrov -> Dimitar Dimitrov Hristov",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Milen Milenov Shumanov", "Shumanov Milen", "Shumanov Milen Milenov"),
        "canonical": "Milen Milenov Shumanov",
        "last_first": "Shumanov, Milen Milenov",
        "note": "Shumanov Milen / Shumanov Milen Milenov -> Milen Milenov Shumanov",
    },
    {
        "country": "Kazakhstan",
        "aliases": ("Adil Alimzhan", "Alimzhan Adil"),
        "canonical": "Alimzhan Adil",
        "last_first": "Adil, Alimzhan",
        "note": "Adil Alimzhan -> Alimzhan Adil (surname Adil established by the 2014-2016 source-order reversal)",
    },
    {
        "country": "Kazakhstan",
        "aliases": ("Alan Beremkulov", "Beremkulov Alan"),
        "canonical": "Alan Beremkulov",
        "last_first": "Beremkulov, Alan",
        "note": "Beremkulov Alan -> Alan Beremkulov",
    },
    {
        "country": "Kazakhstan",
        "aliases": ("Alexey Tsekhovoy", "Tsekhovoy Alexey"),
        "canonical": "Alexey Tsekhovoy",
        "last_first": "Tsekhovoy, Alexey",
        "note": "Tsekhovoy Alexey -> Alexey Tsekhovoy",
    },
    {
        "country": "Kazakhstan",
        "aliases": ("Aruzhan Amanbayeva", "Amanbayeva Aruzhan"),
        "canonical": "Aruzhan Amanbayeva",
        "last_first": "Amanbayeva, Aruzhan",
        "note": "Amanbayeva Aruzhan -> Aruzhan Amanbayeva",
    },
    {
        "country": "Kazakhstan",
        "aliases": ("Danil Baimuldin", "Baimuldin Danil"),
        "canonical": "Danil Baimuldin",
        "last_first": "Baimuldin, Danil",
        "note": "Baimuldin Danil -> Danil Baimuldin",
    },
    {
        "country": "Kazakhstan",
        "aliases": ("Miras Kabdygali", "Kabdygali Miras"),
        "canonical": "Miras Kabdygali",
        "last_first": "Kabdygali, Miras",
        "note": "Kabdygali Miras -> Miras Kabdygali",
    },
    {
        "country": "Macau",
        "aliases": ("Cheok Lam Cheang", "Cheang Cheok Lam"),
        "canonical": "Cheok Lam Cheang",
        "last_first": "Cheang, Cheok Lam",
        "note": "Cheang Cheok Lam / Cheok Lam CHEANG -> Cheok Lam Cheang",
    },
    {
        "country": "Macau",
        "aliases": ("Chi Lok Choi", "Choi Chi Lok"),
        "canonical": "Chi Lok Choi",
        "last_first": "Choi, Chi Lok",
        "note": "Choi Chi Lok -> Chi Lok Choi",
    },
    {
        "country": "Macau",
        "aliases": ("Pak Io Fong", "Fong Pak Io"),
        "canonical": "Pak Io Fong",
        "last_first": "Fong, Pak Io",
        "note": "Fong Pak Io -> Pak Io Fong",
    },
    {
        "country": "Hong Kong",
        "aliases": ("Kwan Yu Chan", "Kwan Chan", "Chan Kwan"),
        "canonical": "Kwan Yu Chan",
        "last_first": "Chan, Kwan Yu",
        "note": "Kwan Chan -> Kwan Yu Chan (full official IMO given name)",
    },
    {
        "country": "Mongolia",
        "aliases": ("Amar Nyamdavaa", "Nyamdavaa Amar"),
        "canonical": "Amar Nyamdavaa",
        "last_first": "Nyamdavaa, Amar",
        "note": "Nyamdavaa Amar -> Amar Nyamdavaa",
    },
    {
        "country": "Mongolia",
        "aliases": ("Temuulen Baasannorov", "Baasannorov Temuulen"),
        "canonical": "Temuulen Baasannorov",
        "last_first": "Baasannorov, Temuulen",
        "note": "Baasannorov Temuulen -> Temuulen Baasannorov",
    },
    {
        "country": "Mongolia",
        "aliases": ("Misheel Otgonbayar", "Otgonbayar Misheel"),
        "canonical": "Misheel Otgonbayar",
        "last_first": "Otgonbayar, Misheel",
        "note": "Otgonbayar Misheel -> Misheel Otgonbayar",
    },
    {
        "country": "Nepal",
        "aliases": ("Anweshan Adhikari", "Adhikari Anweshan"),
        "canonical": "Anweshan Adhikari",
        "last_first": "Adhikari, Anweshan",
        "note": "Adhikari Anweshan -> Anweshan Adhikari",
    },
    {
        "country": "Philippines",
        "aliases": ("Lance Gabriel Torion Madrazo", "Lance Gabriel T. Madrazo"),
        "canonical": "Lance Gabriel Torion Madrazo",
        "last_first": "Madrazo, Lance Gabriel Torion",
        "note": "Lance Gabriel T. Madrazo -> Lance Gabriel Torion Madrazo",
    },
    {
        "country": "Philippines",
        "aliases": ("Paul Vincent Leandrei Laylo Navarro", "Paul Vincent Leandrei L. Navarro"),
        "canonical": "Paul Vincent Leandrei Laylo Navarro",
        "last_first": "Navarro, Paul Vincent Leandrei Laylo",
        "note": "Paul Vincent Leandrei L. Navarro -> Paul Vincent Leandrei Laylo Navarro",
    },
    {
        "country": "Philippines",
        "aliases": ("Shaun Lawrence Tiong Poh Leung", "Shaun Lawrence T. Poh Leung"),
        "canonical": "Shaun Lawrence Tiong Poh Leung",
        "last_first": "Poh Leung, Shaun Lawrence Tiong",
        "note": "Shaun Lawrence T. Poh Leung -> Shaun Lawrence Tiong Poh Leung",
    },
    {
        "country": "Philippines",
        "aliases": ("Robert Frederik Diaz Uy", "Robert Frederik D. Uy"),
        "canonical": "Robert Frederik Diaz Uy",
        "last_first": "Uy, Robert Frederik Diaz",
        "note": "Robert Frederik D. Uy -> Robert Frederik Diaz Uy",
    },
    {
        "country": "Philippines",
        "aliases": ("Wesley Gavin G. Palomar", "Wesley Gavin Palomar"),
        "canonical": "Wesley Gavin G. Palomar",
        "last_first": "Palomar, Wesley Gavin G.",
        "note": "Wesley Gavin Palomar -> Wesley Gavin G. Palomar",
    },
    {
        "country": "Philippines",
        "aliases": ("Shawn Darren S. Chua", "Shawn Darren Chua"),
        "canonical": "Shawn Darren S. Chua",
        "last_first": "Chua, Shawn Darren S.",
        "note": "Shawn Darren Chua -> Shawn Darren S. Chua",
    },
    {
        "country": "Philippines",
        "aliases": ("Frederick Ivan Tiong Tan", "Frederick Ivan T. Tan"),
        "canonical": "Frederick Ivan Tiong Tan",
        "last_first": "Tan, Frederick Ivan Tiong",
        "note": "Frederick Ivan T. Tan -> Frederick Ivan Tiong Tan",
    },
    {
        "country": "Philippines",
        "aliases": ("Caitlin Enrile Lopingco", "Caitlin E. Lopingco"),
        "canonical": "Caitlin Enrile Lopingco",
        "last_first": "Lopingco, Caitlin Enrile",
        "note": "Caitlin E. Lopingco -> Caitlin Enrile Lopingco",
    },
    {
        "country": "Romania",
        "aliases": (
            "Ilinca Ruxandra Radu",
            "Ilinca Rucsandra Radu",
            "Radu Ilinca Ruxandra",
            "Radu Ilinca Rucsandra",
        ),
        "canonical": "Ilinca Ruxandra Radu",
        "last_first": "Radu, Ilinca Ruxandra",
        "note": "Radu Ilinca Rucsandra / Radu Ilinca Ruxandra -> Ilinca Ruxandra Radu",
    },
    {
        "country": "Russian Federation",
        "aliases": ("Arseniy Yenatskiy", "Arseny Yenatsky"),
        "canonical": "Arseniy Yenatskiy",
        "last_first": "Yenatskiy, Arseniy",
        "note": "Arseny Yenatsky -> Arseniy Yenatskiy",
    },
    {
        "country": "Russian Federation",
        "aliases": ("Ivan Safonov", "Safonov Ivan"),
        "canonical": "Ivan Safonov",
        "last_first": "Safonov, Ivan",
        "note": "Safonov Ivan -> Ivan Safonov",
    },
    {
        "country": "Sri Lanka",
        "aliases": ("Seinul Asamdeen Arbith Ahamed", "S.A. Arbith Ahamed"),
        "canonical": "Seinul Asamdeen Arbith Ahamed",
        "last_first": "Ahamed, Seinul Asamdeen Arbith",
        "note": "S.A. Arbith Ahamed -> Seinul Asamdeen Arbith Ahamed",
    },
    {
        "country": "Thailand",
        "aliases": ("Punnisa Wongvanitchakorn", "Punnisa Wongwanitchagorn"),
        "canonical": "Punnisa Wongvanitchakorn",
        "last_first": "Wongvanitchakorn, Punnisa",
        "note": "Punnisa Wongwanitchagorn -> Punnisa Wongvanitchakorn",
    },
    {
        "country": "Thailand",
        "aliases": ("Phonlaphat Watthanaudom", "Phollaphat Watthanaudom"),
        "canonical": "Phonlaphat Watthanaudom",
        "last_first": "Watthanaudom, Phonlaphat",
        "note": "Phollaphat Watthanaudom -> Phonlaphat Watthanaudom",
    },
    {
        "country": "Mexico",
        "aliases": ("Zariffe Yamel Céspedes Pelayo", "Zariffe Yamel C?spedes Pelayo"),
        "canonical": "Zariffe Yamel Céspedes Pelayo",
        "last_first": "Céspedes Pelayo, Zariffe Yamel",
        "note": "Zariffe Yamel C?spedes Pelayo -> Zariffe Yamel Céspedes Pelayo",
    },
    {
        "country": "Mexico",
        "aliases": ("Artie Aarón Ramírez Villa", "Artie Aar?n Ram?rez Villa"),
        "canonical": "Artie Aarón Ramírez Villa",
        "last_first": "Ramírez Villa, Artie Aarón",
        "note": "Artie Aar?n Ram?rez Villa -> Artie Aarón Ramírez Villa",
    },
    {
        "country": "Mexico",
        "aliases": ("Takumi Higashida Martínez", "Takumi Higashida Mart?nez"),
        "canonical": "Takumi Higashida Martínez",
        "last_first": "Higashida Martínez, Takumi",
        "note": "Takumi Higashida Mart?nez -> Takumi Higashida Martínez",
    },
    {
        "country": "Mexico",
        "aliases": ("Antonio Gutiérrez Meléndez", "Antonio Guti?rrez Melendez"),
        "canonical": "Antonio Gutiérrez Meléndez",
        "last_first": "Gutiérrez Meléndez, Antonio",
        "note": "Antonio Guti?rrez Melendez -> Antonio Gutiérrez Meléndez",
    },
    {
        "country": "Mexico",
        "aliases": ("Olaf Daniel Magos Hernández", "Olaf Daniel Magos Hern?ndez"),
        "canonical": "Olaf Daniel Magos Hernández",
        "last_first": "Magos Hernández, Olaf Daniel",
        "note": "Olaf Daniel Magos Hern?ndez -> Olaf Daniel Magos Hernández",
    },
    {
        "country": "Tajikistan",
        "aliases": ("Olimdzhon Tukhtarov", "Olimzhon Tukhtarov"),
        "canonical": "Olimdzhon Tukhtarov",
        "last_first": "Tukhtarov, Olimdzhon",
        "note": "Olimzhon Tukhtarov -> Olimdzhon Tukhtarov (IMO spelling; consecutive-year identity)",
    },
    {
        "country": "Republic of Korea",
        "aliases": ("Myoungjin Seo", "Myongjin Seo"),
        "canonical": "Myoungjin Seo",
        "last_first": "Seo, Myoungjin",
        "note": "Myongjin Seo -> Myoungjin Seo (consecutive-year romanization variant)",
    },
    {
        "country": "Republic of Korea",
        "aliases": ("Doyeup Lee", "Doyoup Lee"),
        "canonical": "Doyeup Lee",
        "last_first": "Lee, Doyeup",
        "note": "Doyoup Lee -> Doyeup Lee (consecutive-year romanization variant)",
    },
    {
        "country": "Philippines",
        "aliases": ("Lance Heinrich Sy Lim", "Lance Heinrich S. Lim", "Lance Henrich Sy Lim"),
        "canonical": "Lance Heinrich Sy Lim",
        "last_first": "Lim, Lance Heinrich Sy",
        "note": "Lance Henrich Sy Lim / Lance Heinrich S. Lim -> Lance Heinrich Sy Lim (consecutive-year full-name reconciliation)",
    },
]

REVIEWED_NOT_MERGED_NAME_NOTES = [
    "Robert Gerard D. Uy and Robert Henrik Diaz Uy were kept separate from Robert Frederik Diaz Uy because the given/middle names differ.",
    "Herath Mudiyanselage Anjana Kavindu Herath and Herath Mudiyanselage Anjula Yasiru Herath were kept separate because the given names differ.",
]

FUZZY_REVIEW_NOTES = [
    "Hong Kong: Yip Chun Hei and Yiu Chun Hei are close spellings across adjacent years, but the surname differs, so they remain separate.",
    "Hong Kong: Wong Pak Qiu and Wong Pak Yu share surname and one given-name syllable, but the final syllable differs, so they remain separate.",
    "Republic of Korea: Kim Jeongwoo, Kim Jongwoo, and Kim Jungwoo look similar, but the appearances span separated cohorts, so they remain separate.",
]

NAME_PARTICLES = {"da", "de", "del", "di", "du", "la", "le", "van", "von"}
ROMAN_NUMERALS = {"II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"}

CHINESE_FAMILY_FIRST_COUNTRIES = {"People's Republic of China"}
KOREAN_FAMILY_FIRST_COUNTRIES = {"Republic of Korea"}
KOREAN_SURNAMES = {
    "Choi",
    "Goo",
    "Hwang",
    "Jeong",
    "Joo",
    "Jung",
    "Kang",
    "Kim",
    "Ko",
    "Kwak",
    "Kwon",
    "Lee",
    "Lim",
    "No",
    "Park",
    "Ryu",
    "Seo",
    "Yang",
    "Yun",
}

MEDAL_ALIASES = {
    "GOLD": "Gold",
    "GOLD MEDAL": "Gold",
    "SILVER": "Silver",
    "SILVER MEDAL": "Silver",
    "BRONZE": "Bronze",
    "BRONZE MEDAL": "Bronze",
    "MERIT": "Merit",
    "MERIT MEDAL": "Merit",
}

RAW_DIR = RAW_EMIC_IWYMIC_DIR
OUT_DIR = EMIC_PROCESSED_DIR

LEGACY_OUTPUT_FILES = [
    "emic_keystage2_awarded_rows.csv",
    "emic_unique_contestants.csv",
    "emic_medal_summary.csv",
    "emic_medal_buckets.csv",
    "emic_total_participants_audit.csv",
    "emic_extraction_report.txt",
]


@dataclass(frozen=True)
class Link:
    href: str
    text: str


@dataclass(frozen=True)
class Table:
    context: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class ContestantRow:
    year: int
    source_order: int
    division: str
    source_url: str
    contestant_id: str
    country_raw: str
    country_clean: str
    country_key: str
    team_name: str
    name_raw: str
    name_clean: str
    name_last_first: str
    name_key: str
    name_variant_clean: str
    medal: str
    medal_bucket_index: int = 0
    medal_bucket_size: int = 0
    rank_start: int = 0
    rank_end: int = 0
    rank_average: float = 0.0
    percentile: float = 0.0
    total_participants: int = 0
    total_participants_source: str = ""


@dataclass(frozen=True)
class MedalBucket:
    year: int
    medal: str
    medal_bucket_index: int
    medal_bucket_size: int
    rank_start: int
    rank_end: int
    rank_average: float
    percentile: float
    first_country: str
    last_country: str
    country_sequence: tuple[str, ...]


@dataclass(frozen=True)
class CleanName:
    first_last: str
    last_first: str
    variant_first_last: str


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[Link] = []
        self._href_stack: list[str | None] = []
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = next((value for key, value in attrs if key.lower() == "href"), None)
        self._href_stack.append(href)
        self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href_stack:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href_stack:
            return
        href = self._href_stack.pop()
        text = clean_text(" ".join(self._text_parts))
        if href and text:
            self.links.append(Link(href=html.unescape(href), text=text))
        self._text_parts = []


class ResultTableParser(HTMLParser):
    BLOCK_TAGS = {"h1", "h2", "h3", "h4", "p"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[Table] = []
        self._block_tag: str | None = None
        self._block_parts: list[str] = []
        self._recent_blocks: list[str] = []
        self._in_table = False
        self._table_rows: list[tuple[str, ...]] = []
        self._in_row = False
        self._row_cells: list[str] = []
        self._in_cell = False
        self._cell_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.BLOCK_TAGS and not self._in_table:
            self._block_tag = tag
            self._block_parts = []
        elif tag == "table":
            self._in_table = True
            self._table_rows = []
        elif tag == "tr" and self._in_table:
            self._in_row = True
            self._row_cells = []
        elif tag in {"td", "th"} and self._in_row:
            self._in_cell = True
            self._cell_parts = []
        elif tag == "br" and self._in_cell:
            self._cell_parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(data)
        elif self._block_tag:
            self._block_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._in_cell:
            self._row_cells.append(clean_text(" ".join(self._cell_parts)))
            self._in_cell = False
            self._cell_parts = []
        elif tag == "tr" and self._in_row:
            if any(cell for cell in self._row_cells):
                self._table_rows.append(tuple(self._row_cells))
            self._in_row = False
            self._row_cells = []
        elif tag == "table" and self._in_table:
            self.tables.append(
                Table(
                    context=tuple(self._recent_blocks[-8:]),
                    rows=tuple(self._table_rows),
                )
            )
            self._in_table = False
            self._table_rows = []
        elif tag == self._block_tag:
            block_text = clean_text(" ".join(self._block_parts))
            if block_text:
                self._recent_blocks.append(block_text)
            self._block_tag = None
            self._block_parts = []


def clean_text(value: str) -> str:
    value = html.unescape(value)
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("\u00a0", " ").replace("\u200b", "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def proper_case_if_all_caps(value: str) -> str:
    value = clean_text(value)
    letters = [ch for ch in value if ch.isalpha()]
    if letters and all(ch.isupper() for ch in letters):
        return value.title()
    return value


def key_text(value: str) -> str:
    value = clean_text(value)
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def proper_case_name_tokens(value: str) -> str:
    value = clean_text(value)

    def convert(match: re.Match[str]) -> str:
        token = match.group(0)
        if match.start() > 0 and value[match.start() - 1] in {"?", "�"}:
            return token
        if token.isupper() and token in ROMAN_NUMERALS:
            return token.upper()
        if token.casefold() in NAME_PARTICLES and token.islower():
            return token.casefold()
        if len(token) == 1:
            return token.upper()
        if token.isupper() or token.islower() or token[0].islower():
            return token[:1].upper() + token[1:].lower()
        return token

    value = re.sub(r"[^\W\d_]+", convert, value)
    value = re.sub(r"\bIi\b", "II", value)
    value = re.sub(r"\bIii\b", "III", value)
    value = re.sub(r"\bIv\b", "IV", value)
    return clean_text(value)


def strip_name_title(value: str) -> str:
    return clean_text(re.sub(r"^(?:maser|master|miss\.?)\s*", "", value, flags=re.IGNORECASE))


def strip_country_suffix(value: str, country: str) -> str:
    match = re.search(r"\s+\(([^)]+)\)$", value)
    if not match:
        return value
    suffix = match.group(1)
    if key_text(clean_country(suffix)) == key_text(country):
        return clean_text(value[: match.start()])
    return value


def first_last_to_last_first(value: str) -> str:
    value = clean_text(value)
    if "," in value:
        return value
    parts = value.split()
    if len(parts) <= 1:
        return value
    return f"{parts[-1]}, {' '.join(parts[:-1])}"


def compact_given_name(parts: list[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return parts[0] + "".join(part[:1].lower() + part[1:] for part in parts[1:])


def family_first_to_first_last(value: str, country: str) -> tuple[str, str] | None:
    if "," in value:
        return None
    parts = value.split()
    if len(parts) < 2:
        return None

    family = parts[0]
    if country in CHINESE_FAMILY_FIRST_COUNTRIES:
        given = compact_given_name(parts[1:])
    elif country in KOREAN_FAMILY_FIRST_COUNTRIES and family in KOREAN_SURNAMES:
        given = " ".join(parts[1:])
    else:
        return None

    return clean_text(f"{given} {family}"), clean_text(f"{family}, {given}")


def normalize_korean_given_spacing(first_last: str, last_first: str, country: str) -> tuple[str, str]:
    if country not in KOREAN_FAMILY_FIRST_COUNTRIES or "," not in last_first:
        return first_last, last_first
    family, given = [part.strip() for part in last_first.split(",", 1)]
    if family not in KOREAN_SURNAMES:
        return first_last, last_first
    compacted_given = compact_given_name(given.split())
    return clean_text(f"{compacted_given} {family}"), clean_text(f"{family}, {compacted_given}")


def split_surname_comma_name(value: str) -> tuple[str, str] | None:
    if "," not in value:
        return None
    family, given = [part.strip() for part in value.split(",", 1)]
    if not family or not given:
        return None
    return clean_text(f"{given} {family}"), clean_text(f"{family}, {given}")


def build_given_comma_overrides() -> dict[tuple[str, str], tuple[str, str]]:
    rules: dict[tuple[str, str], tuple[str, str]] = {}
    for country, aliases in GIVEN_COMMA_NAME_OVERRIDES.items():
        country_key = key_text(country)
        for alias, cleaned in aliases.items():
            rules[(country_key, key_text(alias))] = cleaned
    return rules


def build_name_alias_rules() -> dict[tuple[str, str], tuple[str, str]]:
    rules: dict[tuple[str, str], tuple[str, str]] = {}
    for rule in NAME_CANONICALIZATION_RULES:
        country_key = key_text(rule["country"])
        canonical = clean_text(rule["canonical"])
        last_first = clean_text(rule["last_first"])
        for alias in rule["aliases"]:
            rules[(country_key, key_text(alias))] = (canonical, last_first)
        rules[(country_key, key_text(canonical))] = (canonical, last_first)
    return rules


GIVEN_COMMA_OVERRIDE_RULES = build_given_comma_overrides()
NAME_ALIAS_RULES = build_name_alias_rules()


def clean_name(raw_name: str, country: str, year: int) -> CleanName:
    name = proper_case_name_tokens(raw_name)
    name = strip_name_title(name)
    name = strip_country_suffix(name, country)

    country_key = key_text(country)
    override = GIVEN_COMMA_OVERRIDE_RULES.get((country_key, key_text(name)))
    if override:
        first_last, last_first = override
    else:
        comma_split = split_surname_comma_name(name)
        if comma_split:
            first_last, last_first = comma_split
        else:
            family_first_split = family_first_to_first_last(name, country)
            if family_first_split:
                first_last, last_first = family_first_split
            else:
                first_last = name
                last_first = first_last_to_last_first(first_last)

    first_last = proper_case_name_tokens(first_last)
    last_first = proper_case_name_tokens(last_first)
    variant_first_last = first_last
    first_last, last_first = normalize_korean_given_spacing(first_last, last_first, country)
    alias = NAME_ALIAS_RULES.get((country_key, key_text(first_last)))
    if alias:
        canonical_first_last, canonical_last_first = alias
    else:
        canonical_first_last, canonical_last_first = first_last, last_first
    canonical_first_last = proper_case_name_tokens(canonical_first_last)
    canonical_last_first = proper_case_name_tokens(canonical_last_first)

    reviewed = review_name(
        source_name=name,
        country=country,
        year=year,
        base_first_last=canonical_first_last,
        base_last_first=canonical_last_first,
        base_variant_first_last=variant_first_last,
    )

    reviewed_first_last = reviewed.first_last
    reviewed_last_first = reviewed.last_first
    reviewed_variant = reviewed.variant_first_last
    post_review_alias = NAME_ALIAS_RULES.get((country_key, key_text(reviewed_first_last)))
    if post_review_alias:
        reviewed_first_last, reviewed_last_first = post_review_alias
        if not reviewed_variant or clean_text(reviewed_variant).casefold() == clean_text(
            reviewed_first_last
        ).casefold():
            reviewed_variant = reviewed.first_last

    return CleanName(
        first_last=reviewed_first_last,
        last_first=reviewed_last_first,
        variant_first_last=reviewed_variant,
    )


def clean_country(value: str) -> str:
    value = clean_text(value)
    if value in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[value]
    value = proper_case_if_all_caps(value)
    return COUNTRY_ALIASES.get(value, value)


def country_from_team(team_name: str) -> str:
    team_name = clean_text(team_name)
    # Team labels are usually "Country A", "Country B", etc.
    inferred = re.sub(r"\s+[A-Z]$", "", team_name).strip()
    return clean_country(inferred or team_name)


def country_from_international_row(contestant_id: str, name: str) -> str | None:
    code_match = re.match(r"^([A-Z]{3})", contestant_id.upper())
    if code_match:
        country = INTERNATIONAL_ID_PREFIX_COUNTRIES.get(code_match.group(1))
        if country:
            return country
    return INTERNATIONAL_NAME_COUNTRIES.get(key_text(name))


def clean_contestant_country(country: str, team_name: str, contestant_id: str, name: str) -> str:
    country = clean_country(country)
    if country.casefold().startswith("international"):
        resolved = country_from_international_row(contestant_id, name)
        if resolved:
            return resolved
    return country


def clean_medal(value: str) -> str | None:
    value = clean_text(value)
    value = re.sub(r"\s+", " ", value).upper()
    return MEDAL_ALIASES.get(value)


def format_number(value: float) -> str:
    return f"{value:.10f}".rstrip("0").rstrip(".")


def format_bucket_list(values: Iterable[int]) -> str:
    return "[" + ", ".join(str(value) for value in values) + "]"


def division_from_id(contestant_id: str) -> str | None:
    match = re.match(r"^[A-Z]{3}([23])", contestant_id.upper())
    if not match:
        return None
    return "Keystage II" if match.group(1) == "2" else "Keystage III"


def division_from_context(context: Iterable[str]) -> str | None:
    for block in reversed(tuple(context)):
        key = key_text(block)
        if key in {"iwymic", "keystage iii", "key stage iii"}:
            return "Keystage III"
        if key in {"emic", "keystage ii", "key stage ii"}:
            return "Keystage II"
    return None


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
        with urlopen(request, timeout=30) as response:
            body = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"Could not fetch {url}: {exc}") from exc

    text = body.decode(charset, errors="replace")
    cache_path.write_text(text, encoding="utf-8", newline="")
    return text


def find_result_url(year: int, category_html: str) -> str:
    parser = LinkParser()
    parser.feed(category_html)

    candidates = [
        link
        for link in parser.links
        if str(year) in link.text and "result" in link.text.casefold()
    ]
    if not candidates:
        candidates = [link for link in parser.links if "result" in link.text.casefold()]

    post_candidates = [
        link for link in candidates if re.search(r"/imc/en/\d{4}/\d{2}/\d{2}/", link.href)
    ]
    if post_candidates:
        return post_candidates[0].href
    if candidates:
        return candidates[0].href
    raise RuntimeError(f"Could not find a result-post link for {year}")


def normalize_header(cell: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", cell.casefold())


def parse_result_rows(year: int, source_url: str, result_html: str) -> list[ContestantRow]:
    parser = ResultTableParser()
    parser.feed(result_html)

    rows: list[ContestantRow] = []
    source_order = 0
    for table in parser.tables:
        if not table.rows:
            continue
        header = [normalize_header(cell) for cell in table.rows[0]]
        header_set = set(header)
        has_modern_header = {"id", "country", "name", "medal"}.issubset(header_set)
        has_legacy_header = {"country", "name", "prize"}.issubset(header_set)
        has_team_only_header = {"id", "teamname", "name", "prize"}.issubset(header_set)
        has_blank_medal_header = {"id", "country", "name"}.issubset(header_set) and "" in header_set
        if (
            not has_modern_header
            and not has_legacy_header
            and not has_team_only_header
            and not has_blank_medal_header
        ):
            continue

        country_idx = header.index("country") if "country" in header else None
        name_idx = header.index("name")
        id_idx = header.index("id") if "id" in header else None
        if "medal" in header:
            medal_idx = header.index("medal")
        elif "prize" in header:
            medal_idx = header.index("prize")
        else:
            medal_idx = len(header) - 1
        team_idx = header.index("teamname") if "teamname" in header else None
        context_division = division_from_context(table.context)

        for cells in table.rows[1:]:
            needed_indexes = [name_idx, medal_idx]
            if country_idx is not None:
                needed_indexes.append(country_idx)
            if team_idx is not None:
                needed_indexes.append(team_idx)
            if max(needed_indexes) >= len(cells):
                continue

            contestant_id = clean_text(cells[id_idx]) if id_idx is not None and id_idx < len(cells) else ""
            if contestant_id:
                division = division_from_id(contestant_id)
                if division is None:
                    division = context_division
                if division != "Keystage II":
                    continue
            elif context_division == "Keystage II":
                division = "Keystage II"
            else:
                continue

            medal = clean_medal(cells[medal_idx])
            if medal is None:
                continue

            name_raw = clean_text(cells[name_idx])
            name_for_country = proper_case_name_tokens(name_raw)
            team_name = clean_text(cells[team_idx]) if team_idx is not None and team_idx < len(cells) else ""
            if country_idx is not None:
                country_raw = clean_text(cells[country_idx])
                country_clean = clean_contestant_country(country_raw, team_name, contestant_id, name_for_country)
            else:
                country_raw = country_from_team(team_name)
                country_clean = clean_contestant_country(country_raw, team_name, contestant_id, name_for_country)
            name_info = clean_name(name_raw, country_clean, year)

            rows.append(
                ContestantRow(
                    year=year,
                    source_order=source_order,
                    division=division,
                    source_url=source_url,
                    contestant_id=contestant_id,
                    country_raw=country_raw,
                    country_clean=country_clean,
                    country_key=key_text(country_clean),
                    team_name=team_name,
                    name_raw=name_raw,
                    name_clean=name_info.first_last,
                    name_last_first=name_info.last_first,
                    name_key=key_text(name_info.first_last),
                    name_variant_clean=name_info.variant_first_last,
                    medal=medal,
                )
            )
            source_order += 1

    return rows


def write_rows(path: Path, rows: Iterable[ContestantRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "id",
        "year",
        "contestant_id",
        "country_raw",
        "country_clean",
        "country_key",
        "name_raw",
        "name_clean",
        "name_last_first",
        "name_key",
        "medal",
        "medal_bucket_size",
        "rank_start",
        "rank_end",
        "rank_average",
        "percentile",
        "total_participants",
        "source_url",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            output = {field: getattr(row, field) for field in fieldnames if field != "id"}
            output["id"] = row.source_order + 1
            output["rank_average"] = format_number(row.rank_average)
            output["percentile"] = format_number(row.percentile)
            writer.writerow(output)


def build_unique_groups(rows: list[ContestantRow]) -> list[list[ContestantRow]]:
    grouped: dict[tuple[str, str], list[ContestantRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.name_key, row.country_key)].append(row)

    unique_groups: list[list[ContestantRow]] = []
    for group in grouped.values():
        year_counts = Counter(row.year for row in group)
        group_years = sorted(year_counts)
        exceeds_age_span = group_years[-1] - group_years[0] > MAX_SAME_STAGE_YEAR_SPAN
        if any(count > 1 for count in year_counts.values()) or exceeds_age_span:
            # Distinct contestant IDs in the same division/year are homonyms,
            # and a long same-stage span cannot be assigned safely from name alone.
            unique_groups.extend([[row] for row in group])
        else:
            unique_groups.append(group)
    return unique_groups


def write_unique_contestants(path: Path, rows: list[ContestantRow]) -> None:
    unique_groups = build_unique_groups(rows)

    fieldnames = [
        "id",
        "name_clean",
        "name_last_first",
        "name_key",
        "country_clean",
        "country_key",
        "appearance_count",
        "years",
        "medals_by_year",
        "rank_averages_by_year",
        "percentiles_by_year",
        "contestant_ids",
        "name_variants",
        "country_variants",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for unique_id, group in enumerate(
            sorted(
                unique_groups,
                key=lambda item: (
                    item[0].country_clean,
                    item[0].name_clean,
                    min(row.year for row in item),
                    item[0].contestant_id,
                ),
            ),
            start=1,
        ):
            group = sorted(group, key=lambda row: (row.year, row.contestant_id))
            canonical = group[0]
            name_variants = {
                value
                for row in group
                for value in (row.name_clean, row.name_variant_clean)
                if clean_text(value).casefold() != clean_text(canonical.name_clean).casefold()
            }
            writer.writerow(
                {
                    "id": unique_id,
                    "name_clean": canonical.name_clean,
                    "name_last_first": canonical.name_last_first,
                    "name_key": canonical.name_key,
                    "country_clean": canonical.country_clean,
                    "country_key": canonical.country_key,
                    "appearance_count": len(group),
                    "years": ";".join(str(row.year) for row in group),
                    "medals_by_year": ";".join(f"{row.year}:{row.medal}" for row in group),
                    "rank_averages_by_year": ";".join(
                        f"{row.year}:{format_number(row.rank_average)}" for row in group
                    ),
                    "percentiles_by_year": ";".join(
                        f"{row.year}:{format_number(row.percentile)}" for row in group
                    ),
                    "contestant_ids": ";".join(row.contestant_id for row in group),
                    "name_variants": ";".join(sorted(name_variants)),
                    "country_variants": ";".join(sorted({row.country_clean for row in group})),
                }
            )


def compute_ranked_rows(rows: list[ContestantRow]) -> tuple[list[ContestantRow], list[MedalBucket]]:
    ranked_rows: list[ContestantRow] = []
    buckets: list[MedalBucket] = []

    rows_by_year: dict[int, list[ContestantRow]] = defaultdict(list)
    for row in rows:
        rows_by_year[row.year].append(row)

    for year in YEARS:
        year_rows = sorted(rows_by_year[year], key=lambda row: row.source_order)
        rank_cursor = 1
        total_participants = TOTAL_PARTICIPANTS[year]

        for medal in MEDAL_ORDER:
            medal_rows = [row for row in year_rows if row.medal == medal]
            configured_bucket_sizes = FRIEND_MEDAL_BUCKETS[year][medal]
            if sum(configured_bucket_sizes) != len(medal_rows):
                raise RuntimeError(
                    f"{year} {medal} bucket sizes sum to {sum(configured_bucket_sizes)}, "
                    f"but parsed {len(medal_rows)} official rows"
                )

            row_offset = 0
            for medal_bucket_index, medal_bucket_size in enumerate(configured_bucket_sizes, start=1):
                bucket_rows = medal_rows[row_offset : row_offset + medal_bucket_size]
                row_offset += medal_bucket_size
                rank_start = rank_cursor
                rank_end = rank_cursor + len(bucket_rows) - 1
                rank_average = (rank_start + rank_end) / 2
                percentile = 1 - rank_average / total_participants
                country_sequence = tuple(row.country_clean for row in bucket_rows)

                buckets.append(
                    MedalBucket(
                        year=year,
                        medal=medal,
                        medal_bucket_index=medal_bucket_index,
                        medal_bucket_size=len(bucket_rows),
                        rank_start=rank_start,
                        rank_end=rank_end,
                        rank_average=rank_average,
                        percentile=percentile,
                        first_country=country_sequence[0],
                        last_country=country_sequence[-1],
                        country_sequence=country_sequence,
                    )
                )

                for row in bucket_rows:
                    ranked_rows.append(
                        replace(
                            row,
                            medal_bucket_index=medal_bucket_index,
                            medal_bucket_size=len(bucket_rows),
                            rank_start=rank_start,
                            rank_end=rank_end,
                            rank_average=rank_average,
                            percentile=percentile,
                            total_participants=total_participants,
                            total_participants_source=TOTAL_PARTICIPANTS_SOURCE,
                        )
                    )

                rank_cursor = rank_end + 1

    return ranked_rows, buckets


def write_summary(path: Path, rows: list[ContestantRow], buckets: list[MedalBucket]) -> None:
    fieldnames = [
        "year",
        "gold",
        "gold_buckets",
        "silver",
        "silver_buckets",
        "bronze",
        "bronze_buckets",
        "merit",
        "merit_buckets",
        "awarded_total",
        "total_participants",
        "awarded_fraction_of_total_participants",
        "bucket_validation",
    ]
    counts: dict[int, Counter[str]] = defaultdict(Counter)
    for row in rows:
        counts[row.year][row.medal] += 1

    buckets_by_year_medal: dict[tuple[int, str], list[int]] = defaultdict(list)
    for bucket in buckets:
        buckets_by_year_medal[(bucket.year, bucket.medal)].append(bucket.medal_bucket_size)

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for year in YEARS:
            counter = counts[year]
            total = sum(counter.values())
            total_participants = TOTAL_PARTICIPANTS[year]
            validation_parts = []
            for medal in MEDAL_ORDER:
                computed = buckets_by_year_medal[(year, medal)]
                expected = FRIEND_MEDAL_BUCKETS[year][medal]
                validation_parts.append(
                    f"{medal}:ok" if computed == expected else f"{medal}:computed {computed} expected {expected}"
                )
            writer.writerow(
                {
                    "year": year,
                    "gold": counter["Gold"],
                    "gold_buckets": format_bucket_list(buckets_by_year_medal[(year, "Gold")]),
                    "silver": counter["Silver"],
                    "silver_buckets": format_bucket_list(buckets_by_year_medal[(year, "Silver")]),
                    "bronze": counter["Bronze"],
                    "bronze_buckets": format_bucket_list(buckets_by_year_medal[(year, "Bronze")]),
                    "merit": counter["Merit"],
                    "merit_buckets": format_bucket_list(buckets_by_year_medal[(year, "Merit")]),
                    "awarded_total": total,
                    "total_participants": total_participants,
                    "awarded_fraction_of_total_participants": f"{total / total_participants:.4f}",
                    "bucket_validation": "; ".join(validation_parts),
                }
            )


def write_bucket_details(path: Path, buckets: list[MedalBucket]) -> None:
    fieldnames = [
        "year",
        "medal",
        "medal_bucket_size",
        "rank_start",
        "rank_end",
        "rank_average",
        "percentile",
        "first_country",
        "last_country",
        "country_sequence",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for bucket in buckets:
            writer.writerow(
                {
                    "year": bucket.year,
                    "medal": bucket.medal,
                    "medal_bucket_size": bucket.medal_bucket_size,
                    "rank_start": bucket.rank_start,
                    "rank_end": bucket.rank_end,
                    "rank_average": format_number(bucket.rank_average),
                    "percentile": format_number(bucket.percentile),
                    "first_country": bucket.first_country,
                    "last_country": bucket.last_country,
                    "country_sequence": ";".join(bucket.country_sequence),
                }
            )


def write_total_participants_audit(path: Path, rows: list[ContestantRow]) -> None:
    fieldnames = [
        "year",
        "total_participants",
        "total_awarded",
        "awarded_fraction",
    ]
    counts = Counter(row.year for row in rows)

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for year in YEARS:
            total_participants = TOTAL_PARTICIPANTS[year]
            awarded_count = counts[year]
            writer.writerow(
                {
                    "year": year,
                    "total_participants": total_participants,
                    "total_awarded": awarded_count,
                    "awarded_fraction": f"{awarded_count / total_participants:.4f}",
                }
            )


def write_report(
    path: Path,
    result_urls: dict[int, str],
    rows: list[ContestantRow],
    buckets: list[MedalBucket],
    duplicate_count: int,
) -> None:
    lines = [
        "EMIC / Keystage II changelog",
        "",
        "Changelog:",
        "- 2026-07-09: Added official-page extraction, HTML caching, duplicate-row removal, medal summaries, and unique-contestant output.",
        "- 2026-07-09: Added confirmed medal buckets, rank-average, percentile estimates, and total-participant audit output.",
        "- 2026-07-10: Renamed processed outputs for Keystage II, trimmed audit/debug columns, title-cased all-uppercase display names/countries, and moved denominator notes into this changelog.",
        "- 2026-07-10: Renamed audit and medal-bucket outputs, normalized country names to IMO country-list names, and resolved international-team contestants to countries.",
        "- 2026-07-11: Added name_last_first, converted comma-order names to first-name-last-name in name_clean, stripped obvious title/country artifacts, and canonicalized reviewed name aliases.",
        "- 2026-07-11: Proper-cased lower-case source name tokens and normalized Mainland Chinese and Korean family-name-first rows to first-name-last-name display order.",
        "- 2026-07-18: Re-audited name order across every contestant, added shared East Asian country/year rules, applied exact-token IMO given-name/surname references, and separated unresolved same-year homonyms.",
        "- 2026-07-18: Corrected compacted Korean source-order equivalence, restored reviewed Mexican/Romanian diacritics, and reran the full row-level name audit.",
        "- 2026-07-18: Added Malaysia/Singapore Chinese-name rules for family-first, English-given-first, and Chinese-name-comma-English-name source formats.",
        "- 2026-07-18: Added reviewed country/year surname-order rules for Bulgaria, Cyprus, Kazakhstan, Mongolia, Romania, Tajikistan, and suffix-supported Uzbek family-first rows.",
        "- 2026-07-18: Corrected Mexico/Peru/Bolivia name_last_first values to retain both Hispanic surnames when no explicit comma or IMO surname field is available.",
        "- 2026-07-18: Propagated unambiguous comma-explicit surname boundaries across matching appearances so full and unique outputs use the same compound surname.",
        "- 2026-07-18: Reconciled cross-year source-order reversals, including Alimzhan Adil, and added Bulgarian surname-first detection for mixed 2017-2019 lists.",
        "- 2026-07-18: Corrected Cuong Viet Do from the official RMM roster and extended Bulgarian surname-first detection to later lists.",
        "- 2026-07-18: Canonicalized high-confidence identities shared with Keystage III; shorter/conflicting source forms remain in name_variants.",
        "- 2026-07-18: Completed a reproducible full-output surname, casing, history, and conservation audit; Japanese source order is now an explicit shared rule.",
        "- 2026-07-18: Merged four high-confidence consecutive-year spelling/romanization identities found by the final within-stage near-match review.",
        "- 2026-07-19: Expanded Kwan Chan to the official IMO full name Kwan Yu Chan; the shorter EMIC source form remains in name_variants.",
        "- 2026-07-22: Completed the final country-by-country duplicate pass; merged supported abbreviated, omitted-patronymic, and romanization identities through shared rules while retaining source spellings in name_variants.",
        "- 2026-07-22: Expanded four Sri Lankan initials-only names from official IMO, APMO, FIDE, and Sri Lanka Olympiad Mathematics Foundation records.",
        "- 2026-07-22: Added a two-year maximum same-stage identity span; split the unrelated Ivan Safonov records from 2013 and 2023 that exact-name grouping had previously combined.",
        "- 2026-07-23: Refreshed the IMO surname reference through 2026 and corrected Minal Thattamparambil Ranjith's surname boundary to 'Thattamparambil Ranjith, Minal'.",
        "",
        "Country normalization source:",
        "- IMO country list: https://www.imo-official.org/countries/",
        "",
        "IMO country-name changes applied:",
        *[f"- {note}" for note in COUNTRY_CHANGE_NOTES],
        "",
        "International-team country resolutions:",
        "- Source: official result-page contestant IDs and international-team labels; 2013 rows without IDs were resolved from the listed mixed-team label plus contestant name.",
        *[f"- {note}" for note in INTERNATIONAL_CHANGE_NOTES],
        "",
        "Name cleaning and canonicalization changes:",
        "- Comma-order names are converted to first-name-last-name in name_clean; the sortable last-name-first form is written to name_last_first.",
        "- Thai title prefixes Master, Miss/Miss., and the observed typo Maser are removed from name_clean.",
        "- Trailing country labels in parentheses are removed only when they match the resolved contestant country.",
        "- 2013 United States comma rows that were written as given-name, surname are handled as special cases.",
        "- People's Republic of China rows without commas are treated as family-name-first; their given-name syllables are compacted, e.g. Zhou Si Qi -> Siqi Zhou.",
        "- Republic of Korea rows with a recognized Korean surname are normalized to first-name-last-name; non-hyphenated given-name syllables are compacted, e.g. Kang Seung Ho -> Seungho Kang.",
        "- Taiwan comma rows use the text before the comma as surname, except the reviewed source reversal En-Yu, Lin.",
        "- Hong Kong uncommaed rows are treated as family-name-first unless a recognized Chinese surname occurs only at the end; Cantonese and English given-name components retain their source spacing/order.",
        "- Macau uses the delegation's observed source convention by year: 2021-2022 are given-name-first, while uncommaed 2014, 2016, 2018, 2019, and 2023 rows are family-name-first.",
        "- Japanese rows are already given-name-first in the official EMIC source and are retained in that order.",
        "- Vietnamese rows are normalized from family-name-first source order without compacting their given-name components.",
        "- Malaysian and Singaporean Chinese names are normalized by the observed surname position: family first, or second after an English given name; comma rows of the form Chinese name, English name use the first Chinese token as surname.",
        "- Country/year family-first rules are applied only where repeated identities or exact IMO surname fields establish the delegation's source convention; mixed years use reviewed named exceptions.",
        "- Mexican, Peruvian, and Bolivian non-comma names retain their final two surname components (plus an attached surname particle); explicit comma and exact IMO fields take precedence.",
        "- Delegation-specific surname rules take precedence when an IMO profile's separate name fields conflict with the contestant's cultural/source order; this affects one Vietnamese reference match.",
        "- For Mongolian names, name_last_first uses the source-established patronymic/family-like component as the sort key; this is not necessarily a Western hereditary surname.",
        "- Radian (Indonesia, 2013) is listed by the official source as a mononym, so name_last_first also remains Radian rather than inventing a surname.",
        "- Exact token-set matches to IMO contestants use the IMO site's separate given-name and surname fields; the original EMIC spelling remains in name_variants when it differs.",
        "- IMO name-order reference: https://www.imo-official.org/results/individual/country/{country-code}/",
        "- Mexican 2021 spelling/diacritic reference: https://www.ommenlinea.org/wp-content/uploads/2021/12/Tzaloa-4-2021.pdf",
        "- Corina-Anamaria Bunău surname/diacritic reference: https://www.edums.ro/onm2024/downloads/repartizare-onm-2024.pdf",
        "- Cuong Viet Do name-order reference: https://rmms.lbi.ro/rmm2019/index.php?id=participants_math",
        "- Jakhongir Norboev spelling reference: https://www.imo-official.org/hall-of-fame/UZB/",
        "- Deyan Deyanov Hadzhi-Manich spelling reference: https://ioai-official.org/bulgaria-2024/2024-bulgaria-teams/",
        "- Nyamdavaa Amar name-order reference: https://imo-official.org/team_r.aspx?code=MNG&column=p6&language=en&order=desc&year=2020",
        "- Luthfi Bima Putra spacing reference: https://cdnc.heyzine.com/files/uploaded/v2/954cb37d1f67ad440006cd838836f7a0a2198129.pdf",
        "- Felicia Grace Angelyn Ferdianto full-name reference: https://humas.jatengprov.go.id/detail_berita_gubernur?id=2649",
        *[f"- {rule['note']}" for rule in NAME_CANONICALIZATION_RULES],
        *[f"- {rule['note']}" for rule in CROSS_STAGE_CANONICAL_RULES],
        "",
        "Reviewed similar names kept separate:",
        *[f"- {note}" for note in REVIEWED_NOT_MERGED_NAME_NOTES],
        "",
        "Peculiar fuzzy matches flagged for later review:",
        *[f"- {note}" for note in FUZZY_REVIEW_NOTES],
        "",
        "Source result posts:",
    ]
    for year in YEARS:
        lines.append(f"- {year}: {result_urls[year]}")

    lines.extend(["", "Awarded rows extracted by year:"])
    counts = Counter(row.year for row in rows)
    for year in YEARS:
        lines.append(f"- {year}: {counts[year]}")

    bucket_mismatches = []
    buckets_by_year_medal: dict[tuple[int, str], list[int]] = defaultdict(list)
    for bucket in buckets:
        buckets_by_year_medal[(bucket.year, bucket.medal)].append(bucket.medal_bucket_size)
    for year in YEARS:
        for medal in MEDAL_ORDER:
            computed = buckets_by_year_medal[(year, medal)]
            expected = FRIEND_MEDAL_BUCKETS[year][medal]
            if computed != expected:
                bucket_mismatches.append(f"{year} {medal}: computed {computed}, expected {expected}")

    unique_count = len(build_unique_groups(rows))
    collision_groups: dict[tuple[int, str, str], list[ContestantRow]] = defaultdict(list)
    for row in rows:
        collision_groups[(row.year, row.country_clean, row.name_clean)].append(row)
    homonym_notes = [
        f"- {year} {country}: {name} appears under distinct contestant IDs "
        + ", ".join(sorted(row.contestant_id for row in group))
        + "; these appearances are kept as separate identities."
        for (year, country, name), group in sorted(collision_groups.items())
        if len(group) > 1
    ]
    lines.extend(
        [
            "",
            f"Total awarded appearances: {len(rows)}",
            f"Conservative unique contestant records: {unique_count}",
            f"Exact duplicate source rows removed: {duplicate_count}",
            "",
            "Same-name collision handling:",
            *(homonym_notes or ["- No same-year same-name collisions were found."]),
            "",
            "Total participant denominator:",
            f"- Source used: {TOTAL_PARTICIPANTS_SOURCE}",
            "- The official result pages list awarded contestants but do not list every non-awarded contestant.",
            "- No total-participant corrections were derivable from these result pages alone.",
            "- This note was removed from emic_total_participants_audit.csv and preserved here instead.",
            "",
            "Bucket validation:",
            (
                "- All computed bucket sizes match the friend screenshot."
                if not bucket_mismatches
                else "- Mismatches: " + " | ".join(bucket_mismatches)
            ),
            "",
            "Cleaning notes:",
            "- Unicode is normalized with NFKC; non-breaking spaces and repeated whitespace are collapsed.",
            "- name_clean is the canonical first-name-last-name display value after reviewed name-order and spelling cleanup.",
            "- name_last_first is the companion last-name-first display value for sorting/review.",
            '- Run python "2 Processing Scripts/audit_emic_name_outputs.py" after regeneration to repeat the full name/history audit across both stages and the combined output.',
            "- name_variants is left empty only when the row-specific cleaned display spelling exactly matches name_clean.",
            "- Matching keys are lowercase, accent-insensitive, and punctuation-insensitive.",
            "- Countries are mostly preserved as shown by chiuchang.org; only obvious aliases like USA are expanded.",
            "- Only IDs whose division marker is 2 are kept, i.e. Keystage II / EMIC.",
            "- Exact repeated rows in the source HTML are removed before writing the processed CSVs.",
            "- Exact same-country names more than two years apart are kept as separate Keystage II identities unless a future explicit reviewed rule establishes otherwise.",
            "- Rank buckets are applied from the confirmed bucket-size table and checked against official medal row counts.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def row_identity(row: ContestantRow) -> tuple[object, ...]:
    return (
        row.year,
        row.contestant_id,
        row.country_key,
        row.team_name,
        row.name_key,
        row.medal,
    )


def deduplicate_rows(rows: list[ContestantRow]) -> tuple[list[ContestantRow], int]:
    seen: set[tuple[object, ...]] = set()
    deduped: list[ContestantRow] = []
    duplicate_count = 0
    for row in rows:
        identity = row_identity(row)
        if identity in seen:
            duplicate_count += 1
            continue
        seen.add(identity)
        deduped.append(row)
    return deduped, duplicate_count


def harmonize_explicit_surnames(rows: list[ContestantRow]) -> list[ContestantRow]:
    explicit: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        if "," in row.name_raw and "," in row.name_last_first:
            explicit[(row.country_key, row.name_key)].add(row.name_last_first)

    authoritative = {
        key: next(iter(values))
        for key, values in explicit.items()
        if len(values) == 1
    }
    harmonized: list[ContestantRow] = []
    for row in rows:
        preferred = authoritative.get((row.country_key, row.name_key))
        aligned = align_last_first(row.name_clean, preferred) if preferred else None
        harmonized.append(replace(row, name_last_first=aligned) if aligned else row)
    return harmonized


def run(refresh: bool) -> None:
    all_rows: list[ContestantRow] = []
    result_urls: dict[int, str] = {}

    for year in YEARS:
        category_url = CATEGORY_URLS[year]
        category_html = fetch(category_url, RAW_DIR / f"{year}_category.html", refresh)
        result_url = find_result_url(year, category_html)
        result_urls[year] = result_url
        result_html = fetch(result_url, RAW_DIR / f"{year}_results.html", refresh)
        year_rows = parse_result_rows(year, result_url, result_html)
        if not year_rows:
            raise RuntimeError(f"Parsed zero Keystage II rows for {year}: {result_url}")
        all_rows.extend(year_rows)
        print(f"{year}: {len(year_rows)} Keystage II awarded rows from {result_url}")

    all_rows, duplicate_count = deduplicate_rows(all_rows)
    all_rows = harmonize_explicit_surnames(all_rows)
    all_rows, buckets = compute_ranked_rows(all_rows)
    all_rows.sort(key=lambda row: (row.year, row.source_order))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for legacy_file in LEGACY_OUTPUT_FILES:
        legacy_path = OUT_DIR / legacy_file
        if legacy_path.exists():
            try:
                legacy_path.unlink()
            except PermissionError:
                print(f"Warning: could not remove locked legacy output {legacy_path}")

    write_rows(EMIC_AWARDED_PATH, all_rows)
    write_unique_contestants(EMIC_UNIQUE_PATH, all_rows)
    write_summary(EMIC_MEDAL_SUMMARY_PATH, all_rows, buckets)
    write_bucket_details(EMIC_MEDAL_BUCKETS_PATH, buckets)
    write_total_participants_audit(EMIC_AUDIT_PATH, all_rows)
    write_report(EMIC_CHANGELOG_PATH, result_urls, all_rows, buckets, duplicate_count)

    print()
    if duplicate_count:
        print(f"Removed {duplicate_count} exact duplicate source rows before writing processed CSVs.")
    print(f"Wrote {EMIC_AWARDED_PATH}")
    print(f"Wrote {EMIC_UNIQUE_PATH}")
    print(f"Wrote {EMIC_MEDAL_SUMMARY_PATH}")
    print(f"Wrote {EMIC_MEDAL_BUCKETS_PATH}")
    print(f"Wrote {EMIC_AUDIT_PATH}")
    print(f"Wrote {EMIC_CHANGELOG_PATH}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-download official pages instead of using cached HTML.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        run(refresh=args.refresh)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
