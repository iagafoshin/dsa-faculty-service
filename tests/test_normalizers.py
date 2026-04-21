import pytest

from app.scraper.normalizers import (
    extract_person_id_from_url,
    normalize_award,
    normalize_conference_string,
    normalize_phone,
    normalize_position_title,
    normalize_work_experience,
)


# ---------------------------------------------------------------------------
# extract_person_id_from_url
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.hse.ru/staff/414353659/", 414353659),
        ("https://www.hse.ru/staff/414353659", 414353659),
        ("https://www.hse.ru/org/persons/859153138", 859153138),
        ("https://www.hse.ru/org/persons/859153138/", 859153138),
        ("https://www.hse.ru/staff/414353659/?ref=abc", 414353659),
        ("https://www.hse.ru/org/persons/859153138?utm=x", 859153138),
        ("https://www.hse.ru/en/staff/123/", 123),
        ("https://www.hse.ru/en/org/persons/456/", 456),
    ],
)
def test_extract_person_id_from_url_valid(url, expected):
    assert extract_person_id_from_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "https://example.com/",
        "https://www.hse.ru/staff/spekarski/",
        "https://www.hse.ru/some/other/path/123",
        "not a url",
    ],
)
def test_extract_person_id_from_url_invalid(url):
    assert extract_person_id_from_url(url) is None


# ---------------------------------------------------------------------------
# normalize_position_title
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            "Старший преподаватель, Младший научный сотрудник, Аспирант:",
            ["Старший преподаватель", "Младший научный сотрудник", "Аспирант"],
        ),
        ("Профессор:", ["Профессор"]),
        ("Профессор: ", ["Профессор"]),
        (
            "руководитель департамента, профессор: ",
            ["руководитель департамента", "профессор"],
        ),
        ("  ,, Заведующий кафедрой,, ", ["Заведующий кафедрой"]),
        ("Старший преподаватель", ["Старший преподаватель"]),
        ("", []),
        (None, []),
    ],
)
def test_normalize_position_title(raw, expected):
    assert normalize_position_title(raw) == expected


# ---------------------------------------------------------------------------
# normalize_work_experience
# ---------------------------------------------------------------------------

def test_work_experience_multi_entry_blob():
    raw = (
        "2021 г. – по н.в. Высшая школа экономики, факультет X, доцент. "
        "2018 – 2020 лаборант, НИИ Y. "
        "2015 – 2017 стажёр-исследователь, Z"
    )
    got = normalize_work_experience(raw)
    assert len(got) == 3
    assert got[0]["years"] == "2021 г. – по н.в."
    assert "Высшая школа экономики" in got[0]["position"]
    assert got[1]["years"] == "2018 – 2020"
    assert "лаборант" in got[1]["position"]
    assert got[2]["years"] == "2015 – 2017"
    assert got[2]["position"].startswith("стажёр-исследователь")


def test_work_experience_single_entry_with_year():
    raw = "2015 – 2020 профессор, МГУ"
    got = normalize_work_experience(raw)
    assert got == [{"years": "2015 – 2020", "position": "профессор, МГУ"}]


def test_work_experience_no_year_markers():
    raw = "Работает в ВШЭ."
    got = normalize_work_experience(raw)
    assert got == [{"years": "", "position": "Работает в ВШЭ."}]


def test_work_experience_empty():
    assert normalize_work_experience("") == []
    assert normalize_work_experience(None) == []


def test_work_experience_list_input():
    raw = [
        "2021 – 2022 А. 2019 – 2020 Б.",
        "2015 – 2017 В.",
    ]
    got = normalize_work_experience(raw)
    assert len(got) == 3
    assert [e["years"] for e in got] == ["2021 – 2022", "2019 – 2020", "2015 – 2017"]


def test_work_experience_mixed_formats():
    raw = "1997 г. специалист. 1999 магистр Института социологии. 2000 - аспирант"
    got = normalize_work_experience(raw)
    assert len(got) >= 2
    assert got[0]["years"].startswith("1997")
    assert "специалист" in got[0]["position"]


def test_work_experience_open_ended_range():
    raw = "2020 – н.в. Ведущий научный сотрудник"
    got = normalize_work_experience(raw)
    assert got[0]["years"] == "2020 – н.в."


# ---------------------------------------------------------------------------
# normalize_conference_string
# ---------------------------------------------------------------------------

def test_conference_full_with_year_prefix():
    raw = (
        "2024: Форум имени А.А. Высоковского «Доказательная урбанистика» (Москва). "
        "Доклад: Как выходить из тарифного кризиса"
    )
    got = normalize_conference_string(raw)
    assert got["year"] == 2024
    assert "Форум имени" in got["title"]
    assert got["location"] == "Москва"
    assert got["talk_title"] == "Как выходить из тарифного кризиса"


def test_conference_body_only_with_external_year():
    raw = "12th European Conference (Milan). Доклад: Confrontation of two orientations"
    got = normalize_conference_string(raw, year=2023)
    assert got["year"] == 2023
    assert got["location"] == "Milan"
    assert got["talk_title"] == "Confrontation of two orientations"


def test_conference_no_location():
    raw = "2022: Конференция по ИИ. Доклад: Новый метод"
    got = normalize_conference_string(raw)
    assert got["year"] == 2022
    assert got["title"] == "Конференция по ИИ"
    assert got["location"] is None
    assert got["talk_title"] == "Новый метод"


def test_conference_no_talk():
    raw = "2021: Летняя школа (Санкт-Петербург)"
    got = normalize_conference_string(raw)
    assert got["year"] == 2021
    assert got["location"] == "Санкт-Петербург"
    assert got["talk_title"] is None


def test_conference_only_year_and_title():
    raw = "2020: Приглашённый доклад на воркшопе"
    got = normalize_conference_string(raw)
    assert got["year"] == 2020
    assert got["title"] == "Приглашённый доклад на воркшопе"
    assert got["location"] is None
    assert got["talk_title"] is None


def test_conference_garbage_input_returns_title_only():
    raw = "какая-то свободная строчка без годов"
    got = normalize_conference_string(raw)
    assert got["year"] is None
    assert got["title"] == raw


def test_conference_empty():
    got = normalize_conference_string("")
    assert got == {"year": None, "title": None, "location": None, "talk_title": None}


# ---------------------------------------------------------------------------
# normalize_phone
# ---------------------------------------------------------------------------

def test_phone_comma_separated_with_extension():
    raw = "main: +7 (495) 772-95-90 *22120, mobile: +7 (999) 123-45-67"
    got = normalize_phone(raw)
    assert got == [
        "main: +7 (495) 772-95-90 *22120",
        "mobile: +7 (999) 123-45-67",
    ]


def test_phone_single():
    assert normalize_phone("+7 (495) 772-95-90") == ["+7 (495) 772-95-90"]


def test_phone_pipe_separator():
    raw = "+7 (495) 111-22-33 | +7 (495) 444-55-66"
    got = normalize_phone(raw)
    assert len(got) == 2
    assert got[0].endswith("111-22-33")


def test_phone_empty():
    assert normalize_phone("") == []
    assert normalize_phone(None) == []


def test_phone_extra_whitespace():
    raw = "  +7 (495) 111-22-33  ,  +7 (495) 444-55-66  "
    assert normalize_phone(raw) == [
        "+7 (495) 111-22-33",
        "+7 (495) 444-55-66",
    ]


# ---------------------------------------------------------------------------
# normalize_award
# ---------------------------------------------------------------------------

def test_award_year_range():
    raw = "Надбавка за публикацию в журнале из Списка B (2025–2026)"
    got = normalize_award(raw)
    assert got["title"] == "Надбавка за публикацию в журнале из Списка B"
    assert got["year_from"] == 2025
    assert got["year_to"] == 2026


def test_award_single_year():
    raw = "Медаль «За заслуги» (2024 г.)"
    got = normalize_award(raw)
    assert got["title"] == "Медаль «За заслуги»"
    assert got["year_from"] == 2024
    assert got["year_to"] is None


def test_award_no_year():
    raw = "Благодарность ректора"
    got = normalize_award(raw)
    assert got == {"title": "Благодарность ректора", "year_from": None, "year_to": None}


def test_award_range_with_gg_suffix():
    raw = "Лучший преподаватель (2022–2023 гг.)"
    got = normalize_award(raw)
    assert got["year_from"] == 2022
    assert got["year_to"] == 2023


def test_award_empty():
    got = normalize_award("")
    assert got == {"title": "", "year_from": None, "year_to": None}


def test_award_whitespace_only():
    got = normalize_award("   ")
    assert got == {"title": "", "year_from": None, "year_to": None}
