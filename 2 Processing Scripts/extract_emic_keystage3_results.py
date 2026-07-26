#!/usr/bin/env python3
"""Extract EMIC / Keystage III individual results from chiuchang.org.

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
    IWYMIC_AUDIT_PATH,
    IWYMIC_AWARDED_PATH,
    IWYMIC_CHANGELOG_PATH,
    IWYMIC_MEDAL_BUCKETS_PATH,
    IWYMIC_MEDAL_SUMMARY_PATH,
    IWYMIC_PROCESSED_DIR,
    IWYMIC_UNIQUE_PATH,
    RAW_EMIC_IWYMIC_DIR,
)


YEARS = [2013, 2014, 2015, 2016, 2017, 2018, 2019, 2021, 2022, 2023]
MAX_SAME_STAGE_YEAR_SPAN = 3

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

TOTAL_PARTICIPANTS_SOURCE = "estimated_from_two_thirds_awarded_rule"

MEDAL_ORDER = ["Gold", "Silver", "Bronze", "Merit"]
MEDAL_SORT_KEY = {medal: index for index, medal in enumerate(MEDAL_ORDER)}

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
    "BGR": "Bulgaria",
    "BUL": "Bulgaria",
    "MAS": "Malaysia",
    "MYS": "Malaysia",
    "PHI": "Philippines",
    "PHL": "Philippines",
    "ROU": "Romania",
    "RUS": "Russian Federation",
    "THA": "Thailand",
    "VIE": "Vietnam",
    "VNM": "Vietnam",
}

INTERNATIONAL_NAME_COUNTRIES = {
    "gergana yancheva goncheva": "Bulgaria",
    "martina dobromirova dimitrova": "Bulgaria",
    "ng wynshanelle gianeah chua": "Philippines",
    "skyler wongfatt": "Trinidad and Tobago",
    "vyara todorova ivanova": "Bulgaria",
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
    "Martina Dobromirova Dimitrova -> Bulgaria (official 2013 team label: Bulgaria-Nigeria A)",
    "Gergana Yancheva Goncheva -> Bulgaria (official 2013 team label: Bulgaria-Nigeria A)",
    "Vyara Todorova Ivanova -> Bulgaria (official 2013 team label: Bulgaria-Nigeria A)",
    "Veronica-Ioana Rotaru -> Romania (official ID prefix: ROU)",
    "Kanyanat Watthanasirikunlaphak -> Thailand (official ID prefix: THA)",
    "Katardzhieva Zhaklin Aleksandrova -> Bulgaria (official ID prefix: BUL)",
    "Dela Cruz, Cris Magdalene L. -> Philippines (official ID prefix: PHI)",
    "Zhaklin Aleksandrova Katardzhieva -> Bulgaria (official ID prefix: BUL)",
    "Sia, Trisha Danielle K. -> Philippines (official ID prefix: PHI)",
    "Isache Maria-Catalina -> Romania (official ID prefix: ROU)",
    "Ng, Wynshanelle Gianeah Chua -> Philippines (manual resolution; 2022 official row gives only International Girl Team)",
    "Skyler Wongfatt -> Trinidad and Tobago (manual resolution; 2022 official row gives only International Girl Team)",
]

GIVEN_COMMA_NAME_OVERRIDES = {
    "United States of America": {
        "Justin, Chan": ("Justin Chan", "Chan, Justin"),
        "Michelle, Song": ("Michelle Song", "Song, Michelle"),
        "Vinayak, Kumar": ("Vinayak Kumar", "Kumar, Vinayak"),
    }
}

NAME_CANONICALIZATION_RULES = [
    {
        "country": "Bulgaria",
        "aliases": ("Cuong Viet Do", "Viet Cuong Do", "Do Viet Cuong", "Viet Do Cuong", "Do Cuong Viet"),
        "canonical": "Cuong Viet Do",
        "last_first": "Do, Cuong Viet",
        "note": "Do Cuong Viet -> Cuong Viet Do (official RMM roster spelling/order)",
    },
    {
        "country": "Sri Lanka",
        "aliases": (
            "Herath Mudiyanselage Anjula Yasiru Herath",
            "Herath Herath Mudiyanselage Anjula Yasiru",
        ),
        "canonical": "Herath Mudiyanselage Anjula Yasiru Herath",
        "last_first": "Herath, Herath Mudiyanselage Anjula Yasiru",
        "note": "Herath Herath Mudiyanselage Anjula Yasiru -> Herath Mudiyanselage Anjula Yasiru Herath (same full-name components across adjacent source formats)",
    },
    {
        "country": "Australia",
        "aliases": ("Alexandra Truong.", "Alexandra Truong"),
        "canonical": "Alexandra Truong",
        "last_first": "Truong, Alexandra",
        "note": "Alexandra Truong. -> Alexandra Truong (removed source trailing punctuation)",
    },
    {
        "country": "Taiwan",
        "aliases": ("Bing- Hung Huang", "Bing-Hung Huang"),
        "canonical": "Bing-Hung Huang",
        "last_first": "Huang, Bing-Hung",
        "note": "Bing- Hung Huang -> Bing-Hung Huang (removed an internal source spacing error)",
    },
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
        "note": "Bunau Corina Anamaria / Bunau Corina- Anamaria -> Corina-Anamaria Bunău (surname and diacritics verified from Romanian national-olympiad records)",
    },
    {
        "country": "Philippines",
        "aliases": (
            "Alexandra Brianne Bendicion Gochian",
            "Alexandra Brianne B. Gochian",
        ),
        "canonical": "Alexandra Brianne Bendicion Gochian",
        "last_first": "Gochian, Alexandra Brianne Bendicion",
        "note": "Alexandra Brianne B. Gochian -> Alexandra Brianne Bendicion Gochian",
    },
    {
        "country": "Philippines",
        "aliases": (
            "Dominic Lawrence R. Bermudez",
            "Dominic Lawrence R Bermudez",
        ),
        "canonical": "Dominic Lawrence R. Bermudez",
        "last_first": "Bermudez, Dominic Lawrence R.",
        "note": "Dominic Lawrence R Bermudez -> Dominic Lawrence R. Bermudez",
    },
    {
        "country": "Philippines",
        "aliases": ("Matthew Eugene Chua",),
        "canonical": "Matthew Eugene Chua",
        "last_first": "Chua, Matthew Eugene",
        "note": "Chua , Matthew Eugene -> Matthew Eugene Chua",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Ivan-Aleksandar Veselinov Mavrov", "Mavrov Ivan-Aleksandar Veselinov"),
        "canonical": "Ivan-Aleksandar Veselinov Mavrov",
        "last_first": "Mavrov, Ivan-Aleksandar Veselinov",
        "note": "Mavrov Ivan-Aleksandar Veselinov -> Ivan-Aleksandar Veselinov Mavrov",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Zhaklin Aleksandrova Katardzhieva", "Katardzhieva Zhaklin Aleksandrova", "Zhaklin Katardzhieva"),
        "canonical": "Zhaklin Aleksandrova Katardzhieva",
        "last_first": "Katardzhieva, Zhaklin Aleksandrova",
        "note": "Katardzhieva Zhaklin Aleksandrova / Zhaklin Katardzhieva -> Zhaklin Aleksandrova Katardzhieva",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Dobromir Dobromirov Angelov", "Angelov Dobromir Dobromirov"),
        "canonical": "Dobromir Dobromirov Angelov",
        "last_first": "Angelov, Dobromir Dobromirov",
        "note": "Angelov Dobromir Dobromirov -> Dobromir Dobromirov Angelov",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Radostin Asenov Petrov", "Petrov Radostin Asenov"),
        "canonical": "Radostin Asenov Petrov",
        "last_first": "Petrov, Radostin Asenov",
        "note": "Petrov Radostin Asenov -> Radostin Asenov Petrov",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Galin Milenov Totev", "Totev Galin Milenov"),
        "canonical": "Galin Milenov Totev",
        "last_first": "Totev, Galin Milenov",
        "note": "Totev Galin Milenov -> Galin Milenov Totev",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Konstantin Radosvetov Garov", "Garov Konstantin Radosvetov"),
        "canonical": "Konstantin Radosvetov Garov",
        "last_first": "Garov, Konstantin Radosvetov",
        "note": "Garov Konstantin Radosvetov -> Konstantin Radosvetov Garov",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Tsvetan Ivanov Tinev", "Tinev Tsvetan Ivanov"),
        "canonical": "Tsvetan Ivanov Tinev",
        "last_first": "Tinev, Tsvetan Ivanov",
        "note": "Tinev Tsvetan Ivanov -> Tsvetan Ivanov Tinev",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Veselin Nikolaev Markovich", "Markovich Veselin Nikolaev"),
        "canonical": "Veselin Nikolaev Markovich",
        "last_first": "Markovich, Veselin Nikolaev",
        "note": "Markovich Veselin Nikolaev -> Veselin Nikolaev Markovich",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Nikola Martinov Staykov", "Staykov Nikola Martinov"),
        "canonical": "Nikola Martinov Staykov",
        "last_first": "Staykov, Nikola Martinov",
        "note": "Staykov Nikola Martinov -> Nikola Martinov Staykov",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Mihaela Filipova Gledacheva", "Gledacheva Mihaela Filipova", "Gledacheva Mihaela"),
        "canonical": "Mihaela Filipova Gledacheva",
        "last_first": "Gledacheva, Mihaela Filipova",
        "note": "Gledacheva Mihaela -> Mihaela Filipova Gledacheva",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Angel Ivanov Raychev", "Raychev Angel Ivanov", "Raychev Angel"),
        "canonical": "Angel Ivanov Raychev",
        "last_first": "Raychev, Angel Ivanov",
        "note": "Raychev Angel -> Angel Ivanov Raychev",
    },
    {
        "country": "Bulgaria",
        "aliases": (
            "Lyuboslav Ivanov Stefanov",
            "Lyuboslav Stefanov Ivanov",
            "Stefanov Lyuboslav Ivanov",
            "Ivanov Lyuboslav Stefanov",
            "Ivanov Lyuboslav",
        ),
        "canonical": "Lyuboslav Ivanov Stefanov",
        "last_first": "Stefanov, Lyuboslav Ivanov",
        "note": "Ivanov Lyuboslav -> Lyuboslav Ivanov Stefanov (full order independently confirmed in the IBO 2021 results)",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Ivayla Ivaylova Radkova", "Radkova Ivayla Ivaylova", "Radkova Ivayla"),
        "canonical": "Ivayla Ivaylova Radkova",
        "last_first": "Radkova, Ivayla Ivaylova",
        "note": "Radkova Ivayla -> Ivayla Ivaylova Radkova",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Borislav Valentinov Stoyanov", "Stoyanov Borislav Valentinov", "Stoyanov Borislav"),
        "canonical": "Borislav Valentinov Stoyanov",
        "last_first": "Stoyanov, Borislav Valentinov",
        "note": "Stoyanov Borislav -> Borislav Valentinov Stoyanov",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Atanas Stoyanov Hrisulev", "Atanas Hrisulev"),
        "canonical": "Atanas Stoyanov Hrisulev",
        "last_first": "Hrisulev, Atanas Stoyanov",
        "note": "Atanas Hrisulev -> Atanas Stoyanov Hrisulev",
    },
    {
        "country": "Cyprus",
        "aliases": ("Andreas Economou", "Economou Andreas"),
        "canonical": "Andreas Economou",
        "last_first": "Economou, Andreas",
        "note": "Economou Andreas -> Andreas Economou",
    },
    {
        "country": "Cyprus",
        "aliases": ("Kyriakos Tsiannis", "Tsiannis Kyriakos"),
        "canonical": "Kyriakos Tsiannis",
        "last_first": "Tsiannis, Kyriakos",
        "note": "Tsiannis Kyriakos -> Kyriakos Tsiannis",
    },
    {
        "country": "Cyprus",
        "aliases": ("Stelios Stylianou", "Stylianou Stelios"),
        "canonical": "Stelios Stylianou",
        "last_first": "Stylianou, Stelios",
        "note": "Stylianou Stelios -> Stelios Stylianou",
    },
    {
        "country": "Indonesia",
        "aliases": ("Farrel Dwireswara Salim", "Farrel Dwireswara S."),
        "canonical": "Farrel Dwireswara Salim",
        "last_first": "Salim, Farrel Dwireswara",
        "note": "Farrel Dwireswara S. -> Farrel Dwireswara Salim",
    },
    {
        "country": "Indonesia",
        "aliases": ("Alvin Putera Budiman", "Alvin Putera B."),
        "canonical": "Alvin Putera Budiman",
        "last_first": "Budiman, Alvin Putera",
        "note": "Alvin Putera B. -> Alvin Putera Budiman",
    },
    {
        "country": "Indonesia",
        "aliases": ("Muhammad Arif Wibisono", "M. Arif Wibisono"),
        "canonical": "Muhammad Arif Wibisono",
        "last_first": "Wibisono, Muhammad Arif",
        "note": "M. Arif Wibisono -> Muhammad Arif Wibisono",
    },
    {
        "country": "Indonesia",
        "aliases": ("Gabriela Erin Mariangel", "Gabriela Erin M"),
        "canonical": "Gabriela Erin Mariangel",
        "last_first": "Mariangel, Gabriela Erin",
        "note": "Gabriela Erin M -> Gabriela Erin Mariangel",
    },
    {
        "country": "Macau",
        "aliases": ("Wai Hon Ao", "Ao Wai Hon"),
        "canonical": "Wai Hon Ao",
        "last_first": "Ao, Wai Hon",
        "note": "Ao Wai Hon -> Wai Hon Ao",
    },
    {
        "country": "Macau",
        "aliases": ("Wong Cheng Hou", "Cheng Hou Wong"),
        "canonical": "Cheng Hou Wong",
        "last_first": "Wong, Cheng Hou",
        "note": "Wong Cheng Hou -> Cheng Hou Wong (Macau government records confirm Wong, Cheng Hou); Hou Cheng Wong remains separate",
    },
    {
        "country": "Macau",
        "aliases": ("Cho Hou Tang", "Tang Cho Hou"),
        "canonical": "Cho Hou Tang",
        "last_first": "Tang, Cho Hou",
        "note": "Tang Cho Hou -> Cho Hou Tang",
    },
    {
        "country": "Macau",
        "aliases": ("Chong Man Lao", "Lao Chong Man"),
        "canonical": "Chong Man Lao",
        "last_first": "Lao, Chong Man",
        "note": "Lao Chong Man -> Chong Man Lao",
    },
    {
        "country": "Macau",
        "aliases": ("Ho Ieng Ngai", "Ngai Ho Ieng"),
        "canonical": "Ho Ieng Ngai",
        "last_first": "Ngai, Ho Ieng",
        "note": "Ngai Ho Ieng -> Ho Ieng Ngai",
    },
    {
        "country": "Macau",
        "aliases": ("Pok Hong Lam", "Lam Pok Hong"),
        "canonical": "Pok Hong Lam",
        "last_first": "Lam, Pok Hong",
        "note": "Lam Pok Hong -> Pok Hong Lam",
    },
    {
        "country": "Macau",
        "aliases": ("Ka Hou Kuong", "Kuong Ka Hou"),
        "canonical": "Ka Hou Kuong",
        "last_first": "Kuong, Ka Hou",
        "note": "Kuong Ka Hou -> Ka Hou Kuong",
    },
    {
        "country": "Mongolia",
        "aliases": ("Turbat Battsengel", "Battsengel Turbat"),
        "canonical": "Turbat Battsengel",
        "last_first": "Battsengel, Turbat",
        "note": "Battsengel Turbat -> Turbat Battsengel",
    },
    {
        "country": "Mongolia",
        "aliases": ("Tsatsral Gankhulug", "Gankhulug Tsatsral"),
        "canonical": "Gankhulug Tsatsral",
        "last_first": "Tsatsral, Gankhulug",
        "note": "Tsatsral Gankhulug -> Gankhulug Tsatsral (surname Tsatsral established by the 2014-2016 source-order reversal)",
    },
    {
        "country": "Philippines",
        "aliases": ("Raymund Carlo A. Masbano", "Raymund Carlo A. Masba�o", "Raymund Carlo Masbano"),
        "canonical": "Raymund Carlo A. Masbano",
        "last_first": "Masbano, Raymund Carlo A.",
        "note": "Raymund Carlo A. Masba�o / Raymund Carlo Masbano -> Raymund Carlo A. Masbano",
    },
    {
        "country": "Philippines",
        "aliases": ("Andrea Jessica D. Jaba", "Andrea Jesscia D. Jaba"),
        "canonical": "Andrea Jessica D. Jaba",
        "last_first": "Jaba, Andrea Jessica D.",
        "note": "Andrea Jesscia D. Jaba -> Andrea Jessica D. Jaba",
    },
    {
        "country": "Philippines",
        "aliases": ("Andrhea G. San Gabriel", "Andrhea San Gabriel"),
        "canonical": "Andrhea G. San Gabriel",
        "last_first": "San Gabriel, Andrhea G.",
        "note": "Andrhea San Gabriel -> Andrhea G. San Gabriel",
    },
    {
        "country": "Philippines",
        "aliases": ("Steven John H. Wang", "Steven John Wang"),
        "canonical": "Steven John H. Wang",
        "last_first": "Wang, Steven John H.",
        "note": "Steven John Wang -> Steven John H. Wang",
    },
    {
        "country": "Philippines",
        "aliases": ("Adrian Guanson Chua Soriaga", "Adrian Guanson C. Soriaga"),
        "canonical": "Adrian Guanson Chua Soriaga",
        "last_first": "Soriaga, Adrian Guanson Chua",
        "note": "Adrian Guanson C. Soriaga -> Adrian Guanson Chua Soriaga",
    },
    {
        "country": "Philippines",
        "aliases": ("Bert Jacob Andal Tropicales", "Bert Jacob A. Tropicales"),
        "canonical": "Bert Jacob Andal Tropicales",
        "last_first": "Tropicales, Bert Jacob Andal",
        "note": "Bert Jacob A. Tropicales -> Bert Jacob Andal Tropicales",
    },
    {
        "country": "Philippines",
        "aliases": ("Mark Edward Miranda Gonzales", "Mark Edward M. Gonzales"),
        "canonical": "Mark Edward Miranda Gonzales",
        "last_first": "Gonzales, Mark Edward Miranda",
        "note": "Mark Edward M. Gonzales -> Mark Edward Miranda Gonzales",
    },
    {
        "country": "Philippines",
        "aliases": ("Vince Jan Faustino Torres", "Vince Jan F Torres"),
        "canonical": "Vince Jan Faustino Torres",
        "last_first": "Torres, Vince Jan Faustino",
        "note": "Vince Jan F Torres -> Vince Jan Faustino Torres",
    },
    {
        "country": "Romania",
        "aliases": ("George-Ioan Stoica", "George Loan Stoica", "Stoica George Loan", "Stoica George-Ioan"),
        "canonical": "George-Ioan Stoica",
        "last_first": "Stoica, George-Ioan",
        "note": "George Loan Stoica -> George-Ioan Stoica",
    },
    {
        "country": "Romania",
        "aliases": ("Alexia-Teodora Serghiuta", "Alexia Serghiuta", "Serghiuta Alexia", "Serghiuta Alexia-Teodora"),
        "canonical": "Alexia-Teodora Serghiuta",
        "last_first": "Serghiuta, Alexia-Teodora",
        "note": "Alexia Serghiuta -> Alexia-Teodora Serghiuta",
    },
    {
        "country": "Romania",
        "aliases": ("Maria-Otilia Casuneanu", "Casuneanu Maria-Otilia"),
        "canonical": "Maria-Otilia Casuneanu",
        "last_first": "Casuneanu, Maria-Otilia",
        "note": "Casuneanu Maria-Otilia -> Maria-Otilia Casuneanu",
    },
    {
        "country": "Romania",
        "aliases": ("Veronica-Ioana Rotaru", "Rotaru Veronica Ioana"),
        "canonical": "Veronica-Ioana Rotaru",
        "last_first": "Rotaru, Veronica-Ioana",
        "note": "Rotaru Veronica Ioana -> Veronica-Ioana Rotaru",
    },
    {
        "country": "Russian Federation",
        "aliases": ("Aleksandr Kirakosian", "Kirakosian Aleksandr"),
        "canonical": "Aleksandr Kirakosian",
        "last_first": "Kirakosian, Aleksandr",
        "note": "Kirakosian Aleksandr -> Aleksandr Kirakosian",
    },
    {
        "country": "Sri Lanka",
        "aliases": ("Sandaru Thathsara Balahewa", "Balahewa Sandaru Thathsara"),
        "canonical": "Sandaru Thathsara Balahewa",
        "last_first": "Balahewa, Sandaru Thathsara",
        "note": "Balahewa Sandaru Thathsara -> Sandaru Thathsara Balahewa",
    },
    {
        "country": "Sri Lanka",
        "aliases": (
            "Wijelath Mohotalage Don Sandil Sandipa Ranasinghe",
            "Ranasinghe Wijelath Mohotalage Don Sandil Sandipa",
        ),
        "canonical": "Wijelath Mohotalage Don Sandil Sandipa Ranasinghe",
        "last_first": "Ranasinghe, Wijelath Mohotalage Don Sandil Sandipa",
        "note": "Ranasinghe Wijelath Mohotalage Don Sandil Sandipa -> Wijelath Mohotalage Don Sandil Sandipa Ranasinghe",
    },
    {
        "country": "Sri Lanka",
        "aliases": ("Ruwimal Yasantha Pathiraja", "Pathiraja Ruwimal Yasantha"),
        "canonical": "Ruwimal Yasantha Pathiraja",
        "last_first": "Pathiraja, Ruwimal Yasantha",
        "note": "Pathiraja Ruwimal Yasantha -> Ruwimal Yasantha Pathiraja",
    },
    {
        "country": "Tajikistan",
        "aliases": ("Azamat Dushanov", "Dushanov Azamat"),
        "canonical": "Azamat Dushanov",
        "last_first": "Dushanov, Azamat",
        "note": "Dushanov Azamat -> Azamat Dushanov",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Borislav Kirilov Kirilov", "Kirilov Borislav Kirilov", "Kirilov Borislav"),
        "canonical": "Borislav Kirilov Kirilov",
        "last_first": "Kirilov, Borislav Kirilov",
        "note": "Kirilov Borislav -> Borislav Kirilov Kirilov",
    },
    {
        "country": "Canada",
        "aliases": ("Alexander Dazhen Cai", "Alexander Cai"),
        "canonical": "Alexander Dazhen Cai",
        "last_first": "Cai, Alexander Dazhen",
        "note": "Alexander Cai -> Alexander Dazhen Cai",
    },
    {
        "country": "Romania",
        "aliases": ("Bogdan-Stelian Duminică", "Duminică Bogdan-Stelian", "Duminica Bogdan"),
        "canonical": "Bogdan-Stelian Duminică",
        "last_first": "Duminică, Bogdan-Stelian",
        "note": "Duminica Bogdan -> Bogdan-Stelian Duminică",
    },
    {
        "country": "Sri Lanka",
        "aliases": (
            "Shenal Santhush Kotuwewatta",
            "Kotuwewatta Shenal Shanthush",
            "Kotuwewatta Shenal Santhush",
        ),
        "canonical": "Shenal Santhush Kotuwewatta",
        "last_first": "Kotuwewatta, Shenal Santhush",
        "note": "Kotuwewatta Shenal Santhush -> Shenal Santhush Kotuwewatta (official IMO surname field)",
    },
    {
        "country": "Thailand",
        "aliases": ("Kiattipoom Sicharoen", "Kiattipoom Sicharooen"),
        "canonical": "Kiattipoom Sicharoen",
        "last_first": "Sicharoen, Kiattipoom",
        "note": "Kiattipoom Sicharooen -> Kiattipoom Sicharoen (IMO spelling; same contestant ID in consecutive years)",
    },
    {
        "country": "Tajikistan",
        "aliases": ("Doriush Khayridinov", "Doriush Khairidinov"),
        "canonical": "Doriush Khayridinov",
        "last_first": "Khayridinov, Doriush",
        "note": "Doriush Khairidinov -> Doriush Khayridinov (IMO spelling; consecutive-year identity)",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Cuong Viet Do", "Guong Viet Do"),
        "canonical": "Cuong Viet Do",
        "last_first": "Do, Cuong Viet",
        "note": "Guong Viet Do -> Cuong Viet Do (official RMM spelling; consecutive-year identity)",
    },
    {
        "country": "Bulgaria",
        "aliases": ("Yoana Krasimirova Peeva", "Yoana Krosiwirova Peeva"),
        "canonical": "Yoana Krasimirova Peeva",
        "last_first": "Peeva, Yoana Krasimirova",
        "note": "Yoana Krosiwirova Peeva -> Yoana Krasimirova Peeva (consecutive-year source typo)",
    },
    {
        "country": "Cyprus",
        "aliases": ("Konstantinos Charalampous", "Constantinos Charalambous"),
        "canonical": "Konstantinos Charalampous",
        "last_first": "Charalampous, Konstantinos",
        "note": "Constantinos Charalambous -> Konstantinos Charalampous (IMO spelling; cross-year transliteration variant)",
    },
    {
        "country": "Islamic Republic of Iran",
        "aliases": ("Ilia Rezaei", "Ilia Rezaee"),
        "canonical": "Ilia Rezaei",
        "last_first": "Rezaei, Ilia",
        "note": "Ilia Rezaee -> Ilia Rezaei (cross-year romanization variant)",
    },
    {
        "country": "Mongolia",
        "aliases": ("Manlai Sonor", "Manlai Somor"),
        "canonical": "Manlai Sonor",
        "last_first": "Sonor, Manlai",
        "note": "Manlai Somor -> Manlai Sonor (IMO spelling; consecutive-year source typo)",
    },
    {
        "country": "Uzbekistan",
        "aliases": ("Anvarbek Rakhmatov", "Anvar Rakhmatov"),
        "canonical": "Anvarbek Rakhmatov",
        "last_first": "Rakhmatov, Anvarbek",
        "note": "Anvar Rakhmatov -> Anvarbek Rakhmatov (IMO full-name spelling; consecutive-year identity)",
    },
    {
        "country": "People's Republic of China",
        "aliases": ("Tianle Cheng", "Tianle Chegn"),
        "canonical": "Tianle Cheng",
        "last_first": "Cheng, Tianle",
        "note": "Tianle Chegn -> Tianle Cheng (corrected the source's apparent CHEGN transposition; no independent roster was found)",
    },
    {
        "country": "Vietnam",
        "aliases": ("Vĩ Thanh Quang Nguyễn", "Vi Thanh Quang Nguyen", "VI Thanh Quang Nguyen"),
        "canonical": "Vĩ Thanh Quang Nguyễn",
        "last_first": "Nguyễn, Vĩ Thanh Quang",
        "note": "Vi Thanh Quang Nguyen -> Vĩ Thanh Quang Nguyễn (Vietnamese competition records)",
    },
]

REVIEWED_NOT_MERGED_NAME_NOTES = [
    "Gatlabayan, Neo A. was converted to Neo A. Gatlabayan but not expanded because Keystage III does not contain the fuller spelling.",
]

FUZZY_REVIEW_NOTES = [
    "People's Republic of China: Ding Peiyu and Peiyu Ding were merged by the family-name-first rule; other close one-syllable Chinese given-name overlaps remain separate without stronger evidence.",
    "Republic of Korea: Cho Seongjoon and Jo Seongjoon are close romanizations with different official surname spelling, so they remain separate.",
    "Republic of Korea: Yoo Donghun and Yoo Seunghun share a surname and final given-name syllable but differ in the first given-name syllable, so they remain separate.",
    "Hong Kong/Macau: several rows differ only by Cantonese romanization spacing, but Hong Kong and Macau are not globally compacted because the source mixes Cantonese spacing and English given names.",
    "Bulgaria: Lazar Delyanov Todorov and Lazar Ivanov Todorov were left separate because the patronymic differs.",
    "Bulgaria: Gergana Marin Georgieva and Magdalena Marin Georgieva were left separate because the given name differs.",
    "Bulgaria: Denev Martin Dimitrov and Dimitrov Martin Dimitrov were left separate because the leading family-name component differs.",
    "Macau: Tam Hou and Tam Hou Wa were left separate because the extra syllable may identify a different name.",
    "Philippines: James Martin U. Young and James Matthew U. Young were left separate because Martin/Matthew is a substantive given-name difference.",
    "Taiwan and Vietnam: remaining fuzzy matches mostly share common surnames or common given-name syllables, so they were flagged but not merged without stronger evidence.",
]

NAME_PARTICLES = {"da", "de", "del", "di", "du", "la", "le", "van", "von"}
ROMAN_NUMERALS = {"II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"}

CHINESE_FAMILY_FIRST_COUNTRIES = {"People's Republic of China"}
KOREAN_FAMILY_FIRST_COUNTRIES = {"Republic of Korea"}
KOREAN_SURNAMES = {
    "Cha",
    "Cho",
    "Choi",
    "Goo",
    "Huh",
    "Hwang",
    "Jeon",
    "Jeong",
    "Jo",
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
    "Ok",
    "Park",
    "Ryu",
    "Seo",
    "Sin",
    "Son",
    "Yang",
    "Yoo",
    "Yoon",
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
OUT_DIR = IWYMIC_PROCESSED_DIR

LEGACY_OUTPUT_FILES = [
    "emic_keystage3_awarded_rows.csv",
    "emic_keystage3_awarded_full.csv",
    "emic_keystage3_unique_contestants.csv",
    "emic_keystage3_medal_summary.csv",
    "emic_keystage3_medal_buckets.csv",
    "emic_keystage3_audit.csv",
    "emic_keystage3_changelog.txt",
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
    return clean_text(
        re.sub(r"^(?:maser|master|miss\.?|mr\.?|ms\.?)\s*", "", value, flags=re.IGNORECASE)
    )


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
    value = re.sub(r"\s+,", ",", value)
    value = re.sub(r",\s*", ", ", value)
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
                if division != "Keystage III":
                    continue
            elif context_division == "Keystage III":
                division = "Keystage III"
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


def estimate_total_participants(awarded_count: int) -> int:
    return int(awarded_count * 3 / 2 + 0.5)


def bucket_order_key(row: ContestantRow) -> str:
    official_country = proper_case_if_all_caps(clean_text(row.country_raw))
    return key_text(official_country or row.country_clean)


def infer_bucket_sizes(medal_rows: list[ContestantRow]) -> list[int]:
    bucket_sizes: list[int] = []
    current_size = 0
    previous_key = ""

    for row in medal_rows:
        current_key = bucket_order_key(row)
        if current_size and current_key < previous_key:
            bucket_sizes.append(current_size)
            current_size = 0
        current_size += 1
        previous_key = current_key

    if current_size:
        bucket_sizes.append(current_size)
    return bucket_sizes


def compute_ranked_rows(rows: list[ContestantRow]) -> tuple[list[ContestantRow], list[MedalBucket]]:
    ranked_rows: list[ContestantRow] = []
    buckets: list[MedalBucket] = []

    rows_by_year: dict[int, list[ContestantRow]] = defaultdict(list)
    for row in rows:
        rows_by_year[row.year].append(row)

    for year in YEARS:
        year_rows = sorted(rows_by_year[year], key=lambda row: row.source_order)
        rank_cursor = 1
        total_participants = estimate_total_participants(len(year_rows))

        for medal in MEDAL_ORDER:
            medal_rows = [row for row in year_rows if row.medal == medal]
            configured_bucket_sizes = infer_bucket_sizes(medal_rows)

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
            total_participants = estimate_total_participants(total)
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
                    "bucket_validation": "auto-inferred from official order resets",
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
            awarded_count = counts[year]
            total_participants = estimate_total_participants(awarded_count)
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
        "EMIC / Keystage III changelog",
        "",
        "Changelog:",
        "- 2026-07-10: Created Keystage III extraction by mirroring the Keystage II output organization.",
        "- 2026-07-10: Added official-page extraction, HTML caching reuse, duplicate-row removal, medal summaries, unique-contestant output, inferred medal buckets, rank-average, percentile estimates, and total-participant audit output.",
        "- 2026-07-10: Normalized country names to IMO country-list names and resolved international-team contestants when official result-page IDs identify a country.",
        "- 2026-07-10: Added Keystage III-specific international-team notes and marked two 2022 generic-IGT country resolutions as manual because the official rows do not include country-coded IDs.",
        "- 2026-07-11: Added name_last_first, converted comma-order names to first-name-last-name in name_clean, stripped obvious title/country artifacts, and canonicalized reviewed Keystage III name aliases.",
        "- 2026-07-11: Proper-cased lower-case source name tokens and normalized Mainland Chinese and Korean family-name-first rows to first-name-last-name display order.",
        "- 2026-07-18: Re-audited name order across every contestant, added shared East Asian country/year rules, applied exact-token IMO given-name/surname references, and separated unresolved same-year homonyms.",
        "- 2026-07-18: Corrected compacted Korean source-order equivalence, fixed reviewed punctuation/spacing artifacts, restored Corina-Anamaria Bunău's surname/diacritics, and reran the full row-level name audit.",
        "- 2026-07-18: Added Malaysia/Singapore Chinese-name rules for family-first, English-given-first, and Chinese-name-comma-English-name source formats.",
        "- 2026-07-18: Added reviewed country/year surname-order rules for Bulgaria, Cyprus, Kazakhstan, Mongolia, Romania, Tajikistan, and suffix-supported Uzbek family-first rows.",
        "- 2026-07-18: Corrected Mexico/Peru/Bolivia name_last_first values to retain both Hispanic surnames when no explicit comma or IMO surname field is available.",
        "- 2026-07-18: Propagated unambiguous comma-explicit surname boundaries across matching appearances so full and unique outputs use the same compound surname.",
        "- 2026-07-18: Reconciled cross-year source-order reversals, including Gankhulug Tsatsral, and corrected Wong, Cheng Hou from Macau government records.",
        "- 2026-07-18: Corrected Cuong Viet Do and Lyuboslav Ivanov Stefanov from independent official rosters, and aligned one identical Sri Lankan full-name rotation.",
        "- 2026-07-18: Canonicalized high-confidence identities shared with Keystage II; shorter/conflicting source forms remain in name_variants.",
        "- 2026-07-18: Completed a reproducible full-output surname, casing, history, and conservation audit; made Japanese source order explicit and corrected two final source spelling/casing edge cases.",
        "- 2026-07-18: Merged eight high-confidence consecutive/cross-year spelling identities found by the final within-stage near-match review; substantive lookalikes remain separate.",
        "- 2026-07-19: Corrected Shenal Santhush Kotuwewatta to official given-name/surname order; family-first source spellings remain in name_variants.",
        "- 2026-07-22: Completed the final country-by-country duplicate pass; merged supported abbreviated, omitted-patronymic, and romanization identities through shared rules while retaining source spellings in name_variants.",
        "- 2026-07-22: Expanded four Sri Lankan initials-only names from official IMO, APMO, FIDE, and Sri Lanka Olympiad Mathematics Foundation records.",
        "- 2026-07-22: Added a three-year maximum same-stage identity span; split the unrelated Nhat Minh Nguyen records from 2018 and 2022 that exact-name grouping had previously combined.",
        "",
        "Country normalization source:",
        "- IMO country list: https://www.imo-official.org/countries/",
        "",
        "IMO country-name changes applied:",
        *[f"- {note}" for note in COUNTRY_CHANGE_NOTES],
        "",
        "International-team country resolutions:",
        "- Source: official result-page contestant IDs and international-team labels where available.",
        "- Manual note: 2022 IGT3A-P02 and IGT3A-P03 are the only Keystage III awarded rows whose official country and team fields both say only International Girl Team.",
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
        "- Japanese rows are already given-name-first in the official IWYMIC source and are retained in that order.",
        "- Vietnamese rows are normalized from family-name-first source order without compacting their given-name components.",
        "- Malaysian and Singaporean Chinese names are normalized by the observed surname position: family first, or second after an English given name; comma rows of the form Chinese name, English name use the first Chinese token as surname.",
        "- Country/year family-first rules are applied only where repeated identities or exact IMO surname fields establish the delegation's source convention; mixed years use reviewed named exceptions.",
        "- Mexican, Peruvian, and Bolivian non-comma names retain their final two surname components (plus an attached surname particle); explicit comma and exact IMO fields take precedence.",
        "- Delegation-specific surname rules take precedence when an IMO profile's separate name fields conflict with the contestant's cultural/source order; this affects one Vietnamese reference match.",
        "- For Mongolian names, name_last_first uses the source-established patronymic/family-like component as the sort key; this is not necessarily a Western hereditary surname.",
        "- Exact token-set matches to IMO contestants use the IMO site's separate given-name and surname fields; the original IWYMIC spelling remains in name_variants when it differs.",
        "- IMO name-order reference: https://www.imo-official.org/results/individual/country/{country-code}/",
        "- Corina-Anamaria Bunău surname/diacritic reference: https://www.edums.ro/onm2024/downloads/repartizare-onm-2024.pdf",
        "- Cuong Viet Do name-order reference: https://rmms.lbi.ro/rmm2019/index.php?id=participants_math",
        "- Lyuboslav Ivanov Stefanov full-name reference: https://www.ibo-info.org/en/contest/past-ibos.html?file=files%2Fdownloads%2Fresults-reports%2Fresults%2FIBO+2021+-+IBO+Challenge+II+-+results.pdf",
        "- Jakhongir Norboev spelling reference: https://www.imo-official.org/hall-of-fame/UZB/",
        "- Deyan Deyanov Hadzhi-Manich spelling reference: https://ioai-official.org/bulgaria-2024/2024-bulgaria-teams/",
        "- Nyamdavaa Amar name-order reference: https://imo-official.org/team_r.aspx?code=MNG&column=p6&language=en&order=desc&year=2020",
        "- Luthfi Bima Putra spacing reference: https://cdnc.heyzine.com/files/uploaded/v2/954cb37d1f67ad440006cd838836f7a0a2198129.pdf",
        "- Felicia Grace Angelyn Ferdianto full-name reference: https://humas.jatengprov.go.id/detail_berita_gubernur?id=2649",
        "- Wong, Cheng Hou surname/order reference: https://concurso-uni.safp.gov.mo/sites/concurso/files/430%28%E5%9C%9F%E6%9C%A8%E5%B7%A5%E7%A8%8B%29_%E8%87%A8%E6%99%82%E5%90%8D%E5%96%AE.pdf",
        "- Nguyễn Vĩ Thanh Quang spelling reference: https://vnexpress.net/viet-nam-gianh-hai-huy-chuong-vang-toan-hoc-tre-quoc-te-4485618.html",
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
            "- Keystage III total-participant counts were not provided separately.",
            "- The official result pages list awarded contestants but do not list every non-awarded contestant.",
            "- Therefore total_participants is estimated as round_half_up(1.5 * total_awarded), following the project assumption that approximately two-thirds of contestants are awarded.",
            "",
            "Bucket inference:",
            "- Medal buckets are inferred from official source order. Within each medal, a new bucket begins when the official displayed country ordering resets.",
            "- Unlike Keystage II, these bucket sizes have not been checked against an external confirmed bucket table.",
            "",
            "Cleaning notes:",
            "- Unicode is normalized with NFKC; non-breaking spaces and repeated whitespace are collapsed.",
            "- name_clean is the canonical first-name-last-name display value after reviewed name-order and spelling cleanup.",
            "- name_last_first is the companion last-name-first display value for sorting/review.",
            '- Run python "2 Processing Scripts/audit_emic_name_outputs.py" after regeneration to repeat the full name/history audit across both stages and the combined output.',
            "- name_variants is left empty only when the row-specific cleaned display spelling exactly matches name_clean.",
            "- Matching keys are lowercase, accent-insensitive, and punctuation-insensitive.",
            "- Countries are mostly preserved as shown by chiuchang.org; only obvious aliases like USA are expanded.",
            "- Only IDs whose division marker is 3 are kept, i.e. Keystage III / IWYMIC.",
            "- Exact repeated rows in the source HTML are removed before writing the processed CSVs.",
            "- Exact same-country names more than three years apart are kept as separate Keystage III identities unless a future explicit reviewed rule establishes otherwise.",
            "- Rank buckets are inferred from official result order and checked internally against official medal row counts.",
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
            raise RuntimeError(f"Parsed zero Keystage III rows for {year}: {result_url}")
        all_rows.extend(year_rows)
        print(f"{year}: {len(year_rows)} Keystage III awarded rows from {result_url}")

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

    write_rows(IWYMIC_AWARDED_PATH, all_rows)
    write_unique_contestants(IWYMIC_UNIQUE_PATH, all_rows)
    write_summary(IWYMIC_MEDAL_SUMMARY_PATH, all_rows, buckets)
    write_bucket_details(IWYMIC_MEDAL_BUCKETS_PATH, buckets)
    write_total_participants_audit(IWYMIC_AUDIT_PATH, all_rows)
    write_report(IWYMIC_CHANGELOG_PATH, result_urls, all_rows, buckets, duplicate_count)

    print()
    if duplicate_count:
        print(f"Removed {duplicate_count} exact duplicate source rows before writing processed CSVs.")
    print(f"Wrote {IWYMIC_AWARDED_PATH}")
    print(f"Wrote {IWYMIC_UNIQUE_PATH}")
    print(f"Wrote {IWYMIC_MEDAL_SUMMARY_PATH}")
    print(f"Wrote {IWYMIC_MEDAL_BUCKETS_PATH}")
    print(f"Wrote {IWYMIC_AUDIT_PATH}")
    print(f"Wrote {IWYMIC_CHANGELOG_PATH}")


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
