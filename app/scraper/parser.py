"""HTML страницы преподавателя ВШЭ → структурированный dict.

Файл организован как набор функций `parse_<section>(tree)` плюс несколько утилит.
Каждая `parse_*` независима и устойчива к отсутствующему DOM — вместо ошибки
возвращает пустой результат. Известные варианты вёрстки обрабатываются inline
(сначала tab-node, потом fallback по заголовкам).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from lxml import html

from app.scraper.client import BASE_URL


# === Нормализаторы строк/URL (работают с уже извлечённым текстом, не с HTML) ===

_PERSON_ID_URL_RE = re.compile(r"/(?:staff|org/persons)/(\d+)")


def extract_person_id_from_url(url: str | None) -> int | None:
    if not url:
        return None
    m = _PERSON_ID_URL_RE.search(url)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def clean_whitespace(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()


def normalize_position_title(raw: str | None) -> list[str]:
    """Разбивает `'A, B, C:'` → `['A', 'B', 'C']`."""
    text = clean_whitespace(raw).rstrip(":").rstrip(",").strip()
    if not text:
        return []
    parts = [clean_whitespace(p).rstrip(":") for p in text.split(",")]
    return [p for p in parts if p]


_YEAR_ATOM = r"(?:\d{1,2}\.)?(?:19|20)\d{2}(?:\s*г\.?)?"
_OPEN_END = r"(?:по\s+н\.?в\.?|по\s+настоящее\s+время|н\.?в\.?)"
_SEP = r"\s*[–\-−—]\s*"
_ENTRY_PREFIX_RE = re.compile(
    rf"(?<![\d.])(?P<span>{_YEAR_ATOM}(?:{_SEP}(?:{_YEAR_ATOM}|{_OPEN_END}))?)(?=\s|$|[,;:.])",
    re.IGNORECASE,
)


def normalize_work_experience(raw: Any) -> list[dict[str, str]]:
    """Разбивает блок «опыт работы» на записи `[{years, position}, ...]`."""
    if raw is None:
        return []
    if isinstance(raw, list):
        out: list[dict[str, str]] = []
        for item in raw:
            out.extend(normalize_work_experience(item))
        return out

    text = clean_whitespace(str(raw))
    if not text:
        return []

    spans = list(_ENTRY_PREFIX_RE.finditer(text))
    if not spans:
        return [{"years": "", "position": text}]

    entries: list[dict[str, str]] = []
    preface = text[: spans[0].start()].strip(" ,.;—–-\t\n")
    for i, m in enumerate(spans):
        years = clean_whitespace(m.group("span"))
        start = m.end()
        end = spans[i + 1].start() if i + 1 < len(spans) else len(text)
        body = text[start:end].strip(" ,.;—–-\t\n")
        if i == 0 and preface:
            body = f"{preface} {body}".strip()
        if body:
            entries.append({"years": years, "position": body})
    return entries


_CONF_FULL_RE = re.compile(
    r"^\s*(?P<year>\d{4})\s*[:.]\s*(?P<title>.+?)\s*\((?P<loc>[^()]+)\)\s*\.\s*Доклад\s*:\s*(?P<talk>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_CONF_NO_LOC_RE = re.compile(
    r"^\s*(?P<year>\d{4})\s*[:.]\s*(?P<title>.+?)\s*\.\s*Доклад\s*:\s*(?P<talk>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_CONF_NO_TALK_RE = re.compile(
    r"^\s*(?P<year>\d{4})\s*[:.]\s*(?P<title>.+?)\s*\((?P<loc>[^()]+)\)\s*\.?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_CONF_TITLE_ONLY_RE = re.compile(
    r"^\s*(?P<year>\d{4})\s*[:.]\s*(?P<title>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_CONF_BODY_FULL_RE = re.compile(
    r"^\s*(?P<title>.+?)\s*\((?P<loc>[^()]+)\)\s*\.\s*Доклад\s*:\s*(?P<talk>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_CONF_BODY_NO_LOC_RE = re.compile(
    r"^\s*(?P<title>.+?)\s*\.\s*Доклад\s*:\s*(?P<talk>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_CONF_BODY_NO_TALK_RE = re.compile(
    r"^\s*(?P<title>.+?)\s*\((?P<loc>[^()]+)\)\s*\.?\s*$",
    re.IGNORECASE | re.DOTALL,
)


def normalize_conference_string(raw: str | None, year: int | None = None) -> dict[str, Any]:
    """Парсит описание конференции в {year, title, location, talk_title}."""
    result: dict[str, Any] = {"year": year, "title": None, "location": None, "talk_title": None}

    text = clean_whitespace(raw)
    if not text:
        return result

    if year is not None:
        patterns = [
            (_CONF_BODY_FULL_RE, ("title", "loc", "talk")),
            (_CONF_BODY_NO_LOC_RE, ("title", "talk")),
            (_CONF_BODY_NO_TALK_RE, ("title", "loc")),
        ]
        for pat, keys in patterns:
            m = pat.match(text)
            if m:
                result["title"] = clean_whitespace(m.group("title")) or None
                if "loc" in keys:
                    result["location"] = clean_whitespace(m.group("loc")) or None
                if "talk" in keys:
                    result["talk_title"] = clean_whitespace(m.group("talk")) or None
                return result
        result["title"] = text
        return result

    patterns_y = [
        (_CONF_FULL_RE, ("year", "title", "loc", "talk")),
        (_CONF_NO_LOC_RE, ("year", "title", "talk")),
        (_CONF_NO_TALK_RE, ("year", "title", "loc")),
        (_CONF_TITLE_ONLY_RE, ("year", "title")),
    ]
    for pat, keys in patterns_y:
        m = pat.match(text)
        if m:
            try:
                result["year"] = int(m.group("year"))
            except (ValueError, IndexError):
                pass
            if "title" in keys:
                result["title"] = clean_whitespace(m.group("title")) or None
            if "loc" in keys:
                result["location"] = clean_whitespace(m.group("loc")) or None
            if "talk" in keys:
                result["talk_title"] = clean_whitespace(m.group("talk")) or None
            return result

    result["title"] = text
    return result


def normalize_phone(raw: str | None) -> list[str]:
    """Разбивает строку телефонов (через запятую/палку) в список."""
    text = clean_whitespace(raw)
    if not text:
        return []
    parts = re.split(r"\s*[,|;/]\s*", text)
    return [p for p in (clean_whitespace(x) for x in parts) if p]


_AWARD_YEAR_RANGE_RE = re.compile(
    r"\s*\(\s*(?:[^()\d]*?)(?P<from>\d{4})(?:\s*[–\-−—]\s*(?P<to>\d{4}))?\s*(?:г\.|гг\.)?\s*\)\s*$"
)


def normalize_award(raw: str | None) -> dict[str, Any]:
    """Достаёт опциональный `(YYYY)` / `(YYYY–YYYY)` из названия награды."""
    text = clean_whitespace(raw)
    if not text:
        return {"title": "", "year_from": None, "year_to": None}

    m = _AWARD_YEAR_RANGE_RE.search(text)
    if not m:
        return {"title": text, "year_from": None, "year_to": None}

    year_from = int(m.group("from"))
    year_to_raw = m.group("to")
    year_to = int(year_to_raw) if year_to_raw else None
    title = text[: m.start()].rstrip(" ,.;:-–—")
    return {
        "title": title or text,
        "year_from": year_from,
        "year_to": year_to,
    }


# === Низкоуровневые хелперы ===

def clean_text(s):
    if not s:
        return None
    return re.sub(r"\s+", " ", s).strip()


def make_tree(html_text: str):
    return html.fromstring(html_text)


def get_sidebar_root(tree):
    if tree is None:
        return None
    side_nodes = tree.xpath("//div[@class='l-extra js-mobile_menu_content is-desktop']/div")
    return side_nodes[0] if side_nodes else None


def get_main_root(tree):
    if tree is None:
        return None
    main_nodes = tree.xpath("//div[contains(@class, 'main__inner')]")
    return main_nodes[0] if main_nodes else None


def get_person_id(tree, url: str | None = None) -> int | None:
    if tree is not None:
        for v in tree.xpath("//*[@data-author]/@data-author"):
            s = str(v).strip()
            if s.isdigit():
                return int(s)

        vals = tree.xpath("//script[@data-person-id]/@data-person-id")
        for v in vals:
            s = str(v).strip()
            if s.isdigit():
                return int(s)
            try:
                return int(s)
            except ValueError:
                continue

    if url:
        try:
            path = urlparse(url).path.rstrip("/")
            if path:
                last = path.split("/")[-1]
                if last.isdigit():
                    return int(last)
        except Exception:
            pass

    return None


# === Шапка профиля / идентичность ===

def parse_full_name(tree):
    main_el = get_main_root(tree)
    if main_el is not None:
        name_el = main_el.xpath(".//h1[contains(@class,'person-caption')]/text()")
        return clean_text(name_el[0]) if name_el else None
    return None


def parse_avatar(tree, base_url: str = BASE_URL):
    avatar = None
    side_el = get_sidebar_root(tree)
    if side_el is not None:
        avatar_div = side_el.xpath(".//div[contains(@class,'person-avatar')]")
        if avatar_div:
            style = avatar_div[0].get("style", "") or ""
            m = re.search(r"url\(([^)]+)\)", style)
            if m:
                raw_avatar = m.group(1).strip().strip("'\"")
                avatar = urljoin(base_url, raw_avatar)
    return avatar


def parse_languages(tree):
    languages = []
    side_el = get_sidebar_root(tree)
    if side_el is not None:
        langs = side_el.xpath(
            ".//dl[contains(@class,'main-list-language-knowledge-level')]//dd/text()"
        )
        languages = [clean_text(x) for x in langs if clean_text(x)]
    return languages


# === Контакты ===

def parse_contacts(tree, base_url: str = BASE_URL):
    contacts = {"phones": None, "address": None, "hours": None, "timetable_url": None}

    side_el = get_sidebar_root(tree)
    if side_el is None:
        return contacts

    contacts_dl = side_el.xpath(
        ".//dl[contains(@class,'main-list')][dt[contains(text(),'Контакты')]]"
    )
    if contacts_dl:
        dl = contacts_dl[0]
        dds = dl.xpath("./dd")

        if dds:
            phone_dd = dds[0]
            texts = [clean_text(t) for t in phone_dd.xpath(".//text()") if clean_text(t)]
            phones = [t for t in texts if not t.startswith("Телефон")]
            if phones:
                # Склеиваем и снова разбиваем — варианты через запятую схлопнутся аккуратно.
                joined = ", ".join(phones)
                parts = normalize_phone(joined)
                contacts["phones"] = " | ".join(parts) if parts else None

        addr_dd = dl.xpath(".//dd[contains(@class,'address-with-hours')]")
        if addr_dd:
            addr_text = clean_text(" ".join(addr_dd[0].xpath(".//text()")))
            if "Время присутствия:" in addr_text:
                left, right = addr_text.split("Время присутствия:", 1)
                address = clean_text(left.replace("Адрес:", ""))
                hours = clean_text(right)
            elif "Время консультаций:" in addr_text:
                left, right = addr_text.split("Время консультаций:", 1)
                address = clean_text(left.replace("Адрес:", ""))
                hours = clean_text(right)
            else:
                address = addr_text.replace("Адрес:", "").strip()
                hours = None
            contacts["address"] = address or None
            contacts["hours"] = hours or None

    timetable_dl = side_el.xpath(".//dl[contains(@class,'person-extra-indent-timetable')]")
    if timetable_dl:
        link = timetable_dl[0].xpath(".//a[@class='link']/@href")
        if link:
            contacts["timetable_url"] = urljoin(base_url, link[0])

    return contacts


# === Research ID и руководители ===

def parse_research_ids(tree, base_url: str = BASE_URL):
    research_ids = {}
    side_el = get_sidebar_root(tree)
    if side_el is None:
        return research_ids

    ids_dl = side_el.xpath(
        ".//dl[contains(@class,'person-extra-indent') "
        "     and not(contains(@class,'person-extra-indent-timetable')) "
        "     and not(contains(@class,'colleagues'))]"
    )
    if ids_dl:
        for dd in ids_dl[0].xpath("./dd"):
            label = clean_text("".join(dd.xpath(".//span[@class='b']/text()")))
            if not label:
                link = dd.xpath(".//a")
                if link:
                    name = clean_text(link[0].text_content())
                    url = link[0].get("href")
                    url = urljoin(base_url, url) if url else None
                    research_ids[name] = {"label": name, "url": url}
                continue

            link = dd.xpath(".//a")
            if link:
                value_text = clean_text(link[0].text_content())
                url = link[0].get("href")
                url = urljoin(base_url, url) if url else None
            else:
                full = clean_text(dd.text_content())
                value_text = full.replace(label, "").replace(":", "").strip()
                url = None

            research_ids[label] = {"value": value_text, "url": url}

    return research_ids


def parse_managers(tree, base_url: str = BASE_URL):
    managers = []
    side_el = get_sidebar_root(tree)
    if side_el is not None:
        coll_dl = side_el.xpath(".//dl[contains(@class,'colleagues')]")
        if coll_dl:
            for dd in coll_dl[0].xpath("./dd"):
                name = clean_text("".join(dd.xpath(".//a/text()")))
                url = dd.xpath(".//a/@href")
                url = urljoin(base_url, url[0]) if url else None
                role = clean_text("".join(dd.xpath(".//span[contains(@class,'grey')]/text()")))
                managers.append({
                    "person_id": extract_person_id_from_url(url),
                    "name": name,
                    "url": url,
                    "role": role,
                })
    return managers


# === Должности (employment) — разбивает несколько должностей через запятую ===

def parse_positions(tree, base_url: str = BASE_URL) -> list[dict[str, Any]]:
    """Один dict на каждую должность, общие ссылки на подразделения.

    Если у профиля одна должность — один элемент. Если в `<li>` несколько
    через запятую («руководитель департамента, профессор:») — каждая должность
    становится отдельной записью с общим `units`.
    """
    main_el = get_main_root(tree)
    if main_el is None:
        return []
    positions: list[dict[str, Any]] = []
    ul_list = main_el.xpath(".//ul[contains(@class,'employment-add')]")
    if not ul_list:
        return positions
    ul = ul_list[0]
    for li in ul.xpath("./li"):
        raw_title = clean_text("".join(
            li.xpath(".//span[contains(@class,'person-appointment-title')]/text()")
        ))
        if not raw_title:
            # LI без названия должности (например, строки class="i" с биографией)
            # сюда не попадают — их вытаскивает parse_employment_addition.
            continue
        units: list[dict[str, Any]] = []
        for a in li.xpath(".//a[@class='link']"):
            unit_name = clean_text(a.text_content())
            href = a.get("href")
            if href:
                href = urljoin(base_url, href)
            units.append({"name": unit_name, "url": href})
        titles = normalize_position_title(raw_title) or [raw_title.rstrip(":").strip()]
        for t in titles:
            positions.append({"title": t, "units": list(units)})
    return positions


def parse_employment_addition(tree):
    main_el = get_main_root(tree)
    addition = []
    if main_el is not None:
        add_ul = main_el.xpath(".//ul[contains(@class,'person-employment-addition')]")
        if add_ul:
            for li in add_ul[0].xpath("./li"):
                txt = clean_text(li.text_content())
                if txt:
                    addition.append(txt)
    return addition


# === Образование ===

def parse_degrees(tree):
    main_el = get_main_root(tree)
    degrees = []
    if main_el is not None:
        degree_blocks = main_el.xpath(
            ".//div[contains(@class,'b-person-data') and @tab-node='sci-degrees1']"
        )
        for block in degree_blocks:
            entries = block.xpath(
                ".//div[contains(@class,'g-list_closer')]//div[contains(@class,'with-indent')]"
            )
            for entry in entries:
                year_el = entry.xpath(".//div[contains(@class,'person-list-hangover')]/text()")
                year_raw = clean_text(year_el[0]) if year_el else None
                year = None
                if year_raw:
                    try:
                        year = int(year_raw)
                    except Exception:
                        year = None
                full_text = clean_text(entry.text_content())
                if year_raw and full_text.startswith(year_raw):
                    text = clean_text(full_text[len(year_raw):])
                else:
                    text = full_text
                if text:
                    degrees.append({"year": year, "text": text})
    return degrees


def parse_professional_interests(tree, base_url: str = BASE_URL):
    main_el = get_main_root(tree)
    interests = []
    if main_el is not None:
        interest_blocks = main_el.xpath(
            ".//div[contains(@class,'b-person-data') and @tab-node='sci-intrests']"
        )
        for block in interest_blocks:
            for a in block.xpath(".//a[contains(@class,'tag')]"):
                label = clean_text(a.text_content())
                href = a.get("href")
                if href:
                    href = urljoin(base_url, href)
                if label:
                    interests.append({"label": label, "url": href})
    return interests


def parse_extra_education(tree):
    main_el = get_main_root(tree)
    extra_ed = []
    if main_el is not None:
        extra_blocks = main_el.xpath(
            ".//div[contains(@class,'b-person-data') and @tab-node='additional_education']"
        )
        for block in extra_blocks:
            year_paragraphs = block.xpath(".//p[strong]")
            for p in year_paragraphs:
                year_raw = clean_text("".join(p.xpath(".//strong/text()")))
                year = None
                if year_raw:
                    try:
                        year = int(year_raw)
                    except Exception:
                        year = None
                ul = p.xpath("./following-sibling::ul[1]")
                if not ul:
                    continue
                ul = ul[0]
                for li in ul.xpath(".//li"):
                    text = clean_text(li.text_content())
                    if not text:
                        continue
                    extra_ed.append({"year": year, "text": text})
    return extra_ed


# === Награды — используют normalize_award для парсинга диапазона лет ===

def parse_awards(tree) -> list[str]:
    """Возвращает награды как очищенные строки.

    Один `<li>` может содержать одну или несколько наград. Храним всё как
    единую строку (так требует контракт API), но при необходимости вызывающий
    код может разобрать каждую запись через `normalize_award(item)`.
    """
    main_el = get_main_root(tree)
    awards: list[str] = []
    if main_el is None:
        return awards
    award_blocks = main_el.xpath(
        ".//div[contains(@class,'b-person-data') and @tab-node='awards']"
    )
    for block in award_blocks:
        for li in block.xpath(".//ul[contains(@class,'g-list')]/li"):
            txt = clean_text(li.text_content())
            if not txt:
                continue
            # ВШЭ иногда оставляет ведущие маркеры списка ("- ", "• ") в тексте <li>
            txt = re.sub(r"^[\s\-•·*–—]+", "", txt).strip()
            if txt:
                awards.append(txt)
    return awards


# === Опыт работы — разбивает большой текстовый блок по шаблону годов ===

def _collect_experience_paragraphs(tree) -> list[str]:
    """Возвращает текст блока «опыт работы» как список абзацев (не склеивая).

    Раньше был один большой блоб + разбивка по шаблону года, но регекс цеплял
    «2017 г.» внутри предложений → корявые «записи». Теперь каждый абзац
    обрабатывается независимо — обычно один абзац = одна запись опыта.
    """
    main_el = get_main_root(tree)
    if main_el is None:
        return []
    chunks: list[str] = []
    for block in main_el.xpath(
        ".//div[contains(@class,'b-person-data') and @tab-node='experience']"
    ):
        paragraphs = block.xpath(
            ".//div[contains(@class,'with-indent')]//p[contains(@class,'text')]"
        )
        if paragraphs:
            for p in paragraphs:
                txt = clean_text(p.text_content())
                if txt:
                    chunks.append(txt)
        else:
            for div in block.xpath(".//div[contains(@class,'with-indent')]"):
                txt = clean_text(div.text_content())
                if txt:
                    chunks.append(txt)
    return chunks


def parse_work_experience(tree) -> list[str]:
    """Возвращает по одной строке на каждую запись опыта работы.

    Обрабатывает абзацы независимо: для каждого `<p>` запускает
    `normalize_work_experience`, который разбивает текст по шаблону года.
    Каждая запись — `"годы: должность"`, если год найден, иначе сырой текст.
    """
    out: list[str] = []
    for paragraph in _collect_experience_paragraphs(tree):
        for piece in normalize_work_experience(paragraph):
            years = piece.get("years") or ""
            position = piece.get("position") or ""
            if years and position:
                out.append(f"{years}: {position}")
            elif position:
                out.append(position)
            elif years:
                out.append(years)
    return out


# === Преподавание — курсы ===

def parse_courses(tree, base_url: str = BASE_URL):
    main_el = get_main_root(tree)
    courses = []
    if main_el is None:
        return courses
    course_blocks = main_el.xpath(".//div[contains(@class,'edu-courses')]")
    for block in course_blocks:
        academic_year = None
        h2 = block.xpath(".//h2/text()")
        if h2:
            m_year = re.search(r"(\d{4}/\d{4})", clean_text(h2[0]) or "")
            if m_year:
                academic_year = m_year.group(1)
        for li in block.xpath(".//ul[contains(@class,'g-list')]/li"):
            if li.xpath(".//span[contains(@class,'edu-courses-archive-toogle')]"):
                continue
            a = li.xpath(".//a[@class='link' and contains(@href, '/edu/courses/')]")
            if not a:
                continue
            link_el = a[0]
            title = clean_text(link_el.text_content())
            href = link_el.get("href")
            url = urljoin(base_url, href) if href else None
            lang_el = li.xpath(".//span[contains(@class,'language-label')]/text()")
            language = clean_text(lang_el[0]) if lang_el else None
            li_text = clean_text(li.text_content())
            meta = None
            m_meta = re.search(r"\(([^()]*)\)", li_text or "")
            if m_meta:
                meta = clean_text(m_meta.group(1))
            courses.append({
                "title": title,
                "url": url,
                "academic_year": academic_year,
                "language": language,
                "meta": meta,
            })
    return courses


# === Научная работа — гранты, редколлегии, конференции ===

def _iter_grant_items(block):
    for li in block.xpath(".//ol/li | .//ul/li"):
        txt = clean_text(li.text_content())
        if txt:
            yield txt


def _grant_from_text(txt: str) -> dict[str, Any]:
    grant_number = None
    m_num = re.search(r"Номер:\s*([^,]+)", txt)
    if m_num:
        grant_number = clean_text(m_num.group(1))
    years = None
    year_matches = re.findall(r"(\d{4})\s*г", txt)
    if year_matches:
        try:
            if len(year_matches) == 1:
                y = int(year_matches[0])
                years = {"start": y, "end": y}
            else:
                years = {"start": int(year_matches[0]), "end": int(year_matches[-1])}
        except Exception:
            years = None
    # Запасной вариант: диапазон через тире без "г", например "(2023–2026 гг.)"
    if years is None:
        m_range = re.search(r"(\d{4})\s*[–\-−—]\s*(\d{4})", txt)
        if m_range:
            try:
                years = {"start": int(m_range.group(1)), "end": int(m_range.group(2))}
            except ValueError:
                years = None
    return {"text": txt, "number": grant_number, "years": years}


_GRANT_HEADING_KEYWORDS = ("гранты", "проекты", "исследован")


def parse_grants(tree) -> list[dict[str, Any]]:
    """Возвращает гранты/проекты. Сначала пробует tab-node, потом fallback по заголовку.

    Вариант A: `<div tab-node="grants">` с `<ul>/<ol>` из `<li>`.
    Вариант B: `<h2>` с одним из ключевых слов («Гранты», «Проекты»,
               «Исследовательские проекты», «Исследования в проектах») —
               затем `<div class="with-indent">` с `<p class="text">`.
    """
    main_el = get_main_root(tree)
    if main_el is None:
        return []
    grants: list[dict[str, Any]] = []

    # Вариант A — контейнер tab-node
    for block in main_el.xpath(
        ".//div[contains(@class,'b-person-data') and @tab-node='grants']"
    ):
        for txt in _iter_grant_items(block):
            grants.append(_grant_from_text(txt))
    if grants:
        return grants

    # Вариант B — fallback по заголовку. Несколько шаблонов h2 на сайте ВШЭ:
    # «Гранты», «Проекты», «Исследовательские проекты», «Исследования в проектах».
    for h in main_el.xpath(".//h2"):
        h_text = (h.text_content() or "").strip().lower()
        if not any(kw in h_text for kw in _GRANT_HEADING_KEYWORDS):
            continue
        nxt = h.xpath("./following-sibling::*[1]")
        if not nxt:
            continue
        container = nxt[0]
        paragraphs = container.xpath(".//p[contains(@class,'text')]") or [container]
        for p in paragraphs:
            txt = clean_text(p.text_content())
            if txt:
                grants.append(_grant_from_text(txt))
        if grants:
            break
    return grants


def _editorial_entry_from_text(txt: str) -> dict[str, Any]:
    start_year = None
    m_year = re.search(r"(\d{4})\s*г", txt)
    if m_year:
        try:
            start_year = int(m_year.group(1))
        except Exception:
            start_year = None
    journal = None
    m_journal = re.search(r"«([^»]+)»", txt)
    if m_journal:
        journal = clean_text(m_journal.group(1))
    return {"text": txt, "start_year": start_year, "journal": journal}


def parse_editorial_staff(tree) -> list[dict[str, Any]]:
    main_el = get_main_root(tree)
    out: list[dict[str, Any]] = []
    if main_el is None:
        return out

    # Вариант A — контейнер tab-node
    blocks = main_el.xpath(
        ".//div[contains(@class,'b-person-data') and @tab-node='editorial-staff']"
    )
    if blocks:
        for div in blocks[0].xpath(".//div[contains(@class,'with-indent')]"):
            txt = clean_text(div.text_content())
            if txt:
                out.append(_editorial_entry_from_text(txt))
        if out:
            return out

    # Вариант B — fallback по h2 («Участие в редколлегиях научных журналов»)
    for h in main_el.xpath(".//h2"):
        if "редколлег" not in (h.text_content() or "").lower():
            continue
        nxt = h.xpath("./following-sibling::*[1]")
        if not nxt:
            continue
        container = nxt[0]
        paragraphs = container.xpath(".//p[contains(@class,'text')]") or [container]
        for p in paragraphs:
            txt = clean_text(p.text_content())
            if txt:
                out.append(_editorial_entry_from_text(txt))
        if out:
            break
    return out


def _conference_entry(description: str, year: int | None, links: list) -> dict[str, Any]:
    structured = normalize_conference_string(description, year=year)
    return {
        "year": year,
        "description": description,
        "title": structured.get("title"),
        "location": structured.get("location"),
        "talk_title": structured.get("talk_title"),
        "links": links,
    }


def _parse_conferences_inline(block) -> list[dict[str, Any]]:
    """Альтернативная разметка: все конференции внутри одного <li>,
    разделены парами <p class="text"> — «Заголовок, YYYY г.» + «Доклад: ...».
    """
    out: list[dict[str, Any]] = []
    for li in block.xpath(".//li[contains(@class,'li2')]"):
        title_text: str | None = None
        title_year: int | None = None
        for p in li.xpath('.//p[contains(@class,"text")]'):
            if p.xpath('.//span[contains(@class,"file")]'):
                continue
            txt = clean_text(p.text_content())
            if not txt:
                continue
            if txt.startswith("Доклад:"):
                if title_text is not None:
                    talk = clean_text(txt[len("Доклад:"):].lstrip(": ")) or None
                    entry = _conference_entry(title_text, title_year, [])
                    if talk:
                        entry["talk_title"] = talk
                    out.append(entry)
                    title_text = None
                    title_year = None
                continue
            if title_text is not None:
                out.append(_conference_entry(title_text, title_year, []))
            m = re.search(r"(?:[,\s])(\d{4})\s*г\.?", txt)
            title_year = int(m.group(1)) if m else None
            title_text = txt
        if title_text is not None:
            out.append(_conference_entry(title_text, title_year, []))
    return out


def parse_conferences(tree, base_url: str = BASE_URL) -> list[dict[str, Any]]:
    """Возвращает по одному dict на конференцию.

    Поддерживает два DOM-варианта:
    A — один <li> на конференцию, год берётся из `person-list-hangover`.
    B — все конференции в одном <li>, разделены парами <p class="text">
        («Заголовок, YYYY г.» + «Доклад: ...»). Срабатывает как fallback.
    """
    main_el = get_main_root(tree)
    out: list[dict[str, Any]] = []
    if main_el is None:
        return out
    blocks = main_el.xpath(
        ".//div[contains(@class,'b-person-data') and @tab-node='conferences']"
    )
    if not blocks:
        return out
    block = blocks[0]

    last_year: int | None = None
    for ul in block.xpath(".//ul[contains(@class,'g-list_closer')]"):
        for li in ul.xpath(".//li[contains(@class,'li2')]"):
            year_el = li.xpath(".//div[contains(@class,'person-list-hangover')]/text()")
            if year_el:
                year_raw = clean_text(year_el[0])
                year: int | None = None
                if year_raw:
                    try:
                        year = int(year_raw)
                    except Exception:
                        year = None
                last_year = year
            else:
                year = last_year

            p = li.xpath(".//p")[0] if li.xpath(".//p") else li
            description = clean_text(p.text_content())
            if not description:
                continue
            links = []
            for a in li.xpath(".//a[@href]"):
                href = a.get("href")
                if href:
                    href = urljoin(base_url, href)
                link_text = clean_text(a.text_content()) or None
                links.append({"url": href, "text": link_text})
            out.append(_conference_entry(description, year, links))

    if not out:
        out = _parse_conferences_inline(block)
    return out


# === Патенты — извлекаются из <table class="patent_table"> ===

_PATENT_TITLE_MAP = {
    "Номер РИД": "number",
    "Вид РИД": "kind",
    "Наименование РИД": "title",
    "Сведения о регистрации": "registration",
    "Авторы": "authors",
    "Год": "year",
    "№ п/п": "index",
}


def _patent_cell_value(td, base_url: str = BASE_URL) -> dict[str, Any] | str | None:
    links = td.xpath(".//a[@href]")
    text = clean_text(td.text_content())
    if not text:
        return None
    if links:
        href = links[0].get("href")
        if href:
            href = urljoin(base_url, href)
        return {"text": text, "url": href}
    return text


def parse_patents(tree, base_url: str = BASE_URL) -> list[dict[str, Any]]:
    """Извлекает записи из таблицы `<table class="patent_table">` (патенты).

    Каждая строка → один dict. Ключи — английские имена, выведенные из атрибута
    `data-title` каждого `<td>`. Ячейка со ссылкой превращается в
    `{"text": ..., "url": ...}`, остальные — обычные строки.
    Поле `year` верхнего уровня берётся из ячейки регистрации, если там есть
    4-значный год; иначе `None`.
    """
    main_el = get_main_root(tree)
    out: list[dict[str, Any]] = []
    if main_el is None:
        return out

    tables = main_el.xpath(
        ".//div[contains(@class,'b-person-data') and @tab-node='patents']"
        "//table[contains(@class,'patent_table')]"
    )
    for table in tables:
        for tr in table.xpath(".//tr[contains(@class,'patent_table__item')]"):
            row: dict[str, Any] = {}
            for td in tr.xpath("./td[@data-title]"):
                label = clean_text(td.get("data-title"))
                if not label:
                    continue
                key = _PATENT_TITLE_MAP.get(label, label.lower())
                row[key] = _patent_cell_value(td, base_url=base_url)

            # Если data-title отсутствует — строка похожа на заголовок, пропускаем.
            if not row:
                continue
            authors_raw = row.get("authors")
            if isinstance(authors_raw, str):
                names = [clean_text(n) for n in re.split(r"[,;]", authors_raw)]
                row["authors"] = [n for n in names if n]
            elif isinstance(authors_raw, dict):
                names = [clean_text(n) for n in re.split(r"[,;]", authors_raw.get("text", ""))]
                row["authors"] = [n for n in names if n]
            else:
                row["authors"] = []

            reg = row.get("registration")
            year: int | None = None
            reg_text: str | None = None
            if isinstance(reg, dict):
                reg_text = reg.get("text")
            elif isinstance(reg, str):
                reg_text = reg
            if reg_text:
                m = re.search(r"\b(19|20)\d{2}\b", reg_text)
                if m:
                    try:
                        year = int(m.group(0))
                    except ValueError:
                        year = None
            row["year"] = year

            out.append(row)
    return out


