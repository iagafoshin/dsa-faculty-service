"""HSE person-profile HTML → structured dict.

The file is organized as `parse_<section>(tree)` functions plus a handful of
utilities. Each `parse_*` is independent and tolerant of missing DOM: returns
an empty result rather than raising. Known DOM variants are handled inline
(tab-node first, then heading-based fallback). See
`docs/html_structure_analysis.md` for the variant playbook.
"""
from __future__ import annotations

import datetime
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from lxml import html

from app.scraper.normalizers import (
    normalize_award,
    normalize_conference_string,
    normalize_phone,
    normalize_position_title,
    normalize_work_experience,
)


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Header / identity
# ---------------------------------------------------------------------------

def parse_full_name(tree):
    main_el = get_main_root(tree)
    if main_el is not None:
        name_el = main_el.xpath(".//h1[contains(@class,'person-caption')]/text()")
        return clean_text(name_el[0]) if name_el else None
    return None


def parse_avatar(tree, base_url: str = "https://www.hse.ru"):
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


def parse_header(tree, base_url: str = "https://www.hse.ru") -> dict[str, Any]:
    """Convenience wrapper — identity block used by scrape_one_profile."""
    return {
        "full_name": parse_full_name(tree),
        "avatar": parse_avatar(tree, base_url=base_url),
        "languages": parse_languages(tree) or [],
    }


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

def parse_contacts(tree, base_url: str = "https://www.hse.ru"):
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
                # Join then re-split so comma-separated variants collapse cleanly.
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


# ---------------------------------------------------------------------------
# Research IDs, managers
# ---------------------------------------------------------------------------

def parse_research_ids(tree, base_url: str = "https://www.hse.ru"):
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


def parse_managers(tree, base_url: str = "https://www.hse.ru"):
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
                managers.append({"name": name, "url": url, "role": role})
    return managers


# ---------------------------------------------------------------------------
# Positions (employment) — splits comma-joined titles
# ---------------------------------------------------------------------------

def parse_positions(tree, base_url: str = "https://www.hse.ru") -> list[dict[str, Any]]:
    """Return one dict per individual title, with shared unit links.

    Single-title pages stay as before (one entry). Multi-title `<li>` like
    `"руководитель департамента, профессор:"` becomes two entries sharing the
    same `units` list.
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
            # LIs without an appointment title (e.g. class="i" bio-note lines)
            # are excluded here — they are surfaced via parse_employment_addition.
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


# Legacy alias kept so existing callers (profile.py, mapping.py) remain valid.
def parse_employment(tree, base_url: str = "https://www.hse.ru"):
    return parse_positions(tree, base_url=base_url)


def parse_employment_traits(tree):
    main_el = get_main_root(tree)
    traits = []
    if main_el is not None:
        traits_ul = main_el.xpath(".//ul[contains(@class,'employment-traits')]")
        if traits_ul:
            for li in traits_ul[0].xpath("./li"):
                txt = clean_text(li.text_content())
                if txt:
                    traits.append(txt)
    return traits


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


# ---------------------------------------------------------------------------
# Education
# ---------------------------------------------------------------------------

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


def parse_education(tree) -> dict[str, Any]:
    """Convenience wrapper for the education block."""
    return {
        "degrees": parse_degrees(tree) or [],
        "extra_education": parse_extra_education(tree) or [],
    }


def parse_professional_interests(tree, base_url: str = "https://www.hse.ru"):
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


# Alias for the brief's signature.
def parse_interests(tree, base_url: str = "https://www.hse.ru"):
    return parse_professional_interests(tree, base_url=base_url)


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


# ---------------------------------------------------------------------------
# Awards — uses normalize_award to parse optional year range
# ---------------------------------------------------------------------------

def parse_awards(tree) -> list[str]:
    """Return award entries as cleaned strings.

    Each `<li>` may carry one or many award mentions. We keep the item as a
    single string (the existing API contract) but pass it through
    ``normalize_award`` so callers can retrieve structured title/year range
    via ``normalize_award(item)``. The raw item text is preserved.
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
            if txt:
                awards.append(txt)
    return awards


def parse_awards_structured(tree) -> list[dict[str, Any]]:
    """Same as parse_awards but returns structured dicts via normalize_award.

    Not wired into scrape_one_profile yet — reserved for a future API upgrade.
    """
    return [normalize_award(s) for s in parse_awards(tree)]


# ---------------------------------------------------------------------------
# Work experience — split big blobs by year patterns
# ---------------------------------------------------------------------------

def _collect_experience_blob(tree) -> str:
    """Concatenate all experience text from the ``experience`` tab-node.

    Paragraph and with-indent block boundaries become single spaces. Per-p
    joining is critical because the HSE DOM frequently emits the year and
    the position text as *separate* sibling `<p>` tags — splitting the blob
    by year pattern only works on a single long string.
    """
    main_el = get_main_root(tree)
    if main_el is None:
        return ""
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
    return " ".join(chunks).strip()


def parse_work_experience(tree) -> list[str]:
    """Return per-entry strings for the experience section.

    The DOM may place year and position text in separate sibling `<p>` tags,
    so we concatenate the section text first and let
    ``normalize_work_experience`` split by year patterns. Each returned
    string is formatted as ``"years: position"`` when a year span was found,
    else the raw text.
    """
    blob = _collect_experience_blob(tree)
    if not blob:
        return []
    out: list[str] = []
    for piece in normalize_work_experience(blob):
        years = piece.get("years") or ""
        position = piece.get("position") or ""
        if years and position:
            out.append(f"{years}: {position}")
        elif position:
            out.append(position)
        elif years:
            out.append(years)
    return out


def parse_work_experience_structured(tree) -> list[dict[str, str]]:
    """Same as parse_work_experience but returns the `{years, position}` dicts."""
    blob = _collect_experience_blob(tree)
    if not blob:
        return []
    return normalize_work_experience(blob)


# ---------------------------------------------------------------------------
# Teaching — theses, courses
# ---------------------------------------------------------------------------

def parse_theses(tree, base_url: str = "https://www.hse.ru"):
    return []


def parse_courses(tree, base_url: str = "https://www.hse.ru"):
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


# ---------------------------------------------------------------------------
# Research — grants, editorial, conferences
# ---------------------------------------------------------------------------

def _iter_grant_items(block):
    """Yield cleaned strings for each `<li>` inside a grants block."""
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
    # Fallback: en-dash range without "г", e.g. "(2023–2026 гг.)"
    if years is None:
        m_range = re.search(r"(\d{4})\s*[–\-−—]\s*(\d{4})", txt)
        if m_range:
            try:
                years = {"start": int(m_range.group(1)), "end": int(m_range.group(2))}
            except ValueError:
                years = None
    return {"text": txt, "number": grant_number, "years": years}


def parse_grants(tree) -> list[dict[str, Any]]:
    """Return grants, trying tab-node first and falling back to heading-based DOM.

    Variant A: `<div tab-node="grants">` with `<ul>/<ol>` of `<li>`.
    Variant B: `<h2>Гранты</h2>` / `<h2>Исследовательские проекты и гранты</h2>`
               followed by `<div class="with-indent">` with `<p class="text">`
               paragraphs.
    """
    main_el = get_main_root(tree)
    if main_el is None:
        return []
    grants: list[dict[str, Any]] = []

    # Variant A — tab-node container
    for block in main_el.xpath(
        ".//div[contains(@class,'b-person-data') and @tab-node='grants']"
    ):
        for txt in _iter_grant_items(block):
            grants.append(_grant_from_text(txt))
    if grants:
        return grants

    # Variant B — heading-based fallback. We match any h2 whose normalized
    # text contains "ранты" (Гранты / гранты), which covers the two observed
    # phrasings on the site.
    for h in main_el.xpath(".//h2[contains(translate(text(),'Г','г'),'ранты')]"):
        nxt = h.xpath("./following-sibling::*[1]")
        if not nxt:
            continue
        container = nxt[0]
        paragraphs = container.xpath(".//p[contains(@class,'text')]") or [container]
        for p in paragraphs:
            txt = clean_text(p.text_content())
            if txt:
                grants.append(_grant_from_text(txt))
    return grants


def parse_editorial_staff(tree) -> list[dict[str, Any]]:
    main_el = get_main_root(tree)
    out: list[dict[str, Any]] = []
    if main_el is None:
        return out
    blocks = main_el.xpath(
        ".//div[contains(@class,'b-person-data') and @tab-node='editorial-staff']"
    )
    if not blocks:
        return out
    block = blocks[0]
    for div in block.xpath(".//div[contains(@class,'with-indent')]"):
        txt = clean_text(div.text_content())
        if not txt:
            continue
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
        out.append({"text": txt, "start_year": start_year, "journal": journal})
    return out


def parse_conferences(tree, base_url: str = "https://www.hse.ru") -> list[dict[str, Any]]:
    """Return per-conference dicts.

    The DOM year hangover populates `year`. The `<p>` body is additionally
    split via ``normalize_conference_string`` into ``title``/``location``/
    ``talk_title`` fields. The legacy ``description`` field is preserved so
    existing callers (e.g. ``mapping.py._conference_to_str``) keep working.
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
            links = []
            for a in li.xpath(".//a[@href]"):
                href = a.get("href")
                if href:
                    href = urljoin(base_url, href)
                link_text = clean_text(a.text_content()) or None
                links.append({"url": href, "text": link_text})
            if not description:
                continue
            structured = normalize_conference_string(description, year=year)
            out.append({
                "year": year,
                "description": description,
                "title": structured.get("title"),
                "location": structured.get("location"),
                "talk_title": structured.get("talk_title"),
                "links": links,
            })
    return out


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------

RU_MONTHS = {
    "янв.": 1, "фев.": 2, "мар.": 3, "апр.": 4, "май": 5, "июнь": 6,
    "июль": 7, "авг.": 8, "сент.": 9, "окт.": 10, "нояб.": 11, "дек.": 12,
}


def parse_news_date(day_str, month_str, year_str):
    day_str = clean_text(day_str)
    month_str = (clean_text(month_str) or "").lower()
    year_str = clean_text(year_str)
    if not day_str or not month_str or not year_str:
        return None
    try:
        day = int(day_str)
        year = int(year_str)
    except ValueError:
        return None
    month = RU_MONTHS.get(month_str)
    if month is None:
        return None
    try:
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return None


def parse_news(tree, base_url: str = "https://www.hse.ru"):
    main_el = get_main_root(tree)
    news = []
    if main_el is None:
        return news
    news_blocks = main_el.xpath(
        ".//div[contains(@class,'b-person-data') and @tab-node='press_links_news']"
    )
    for block in news_blocks:
        for post in block.xpath(".//div[contains(@class,'post')]"):
            day_el = post.xpath(".//div[contains(@class,'post-meta__day')]/text()")
            month_el = post.xpath(".//div[contains(@class,'post-meta__month')]/text()")
            year_el = post.xpath(".//div[contains(@class,'post-meta__year')]/text()")
            day = clean_text(day_el[0]) if day_el else None
            month = clean_text(month_el[0]) if month_el else None
            year = clean_text(year_el[0]) if year_el else None
            iso_date = parse_news_date(day, month, year) if (day and month and year) else None
            link_nodes = post.xpath(".//div[contains(@class,'post__content')]//h2//a")
            link_el = link_nodes[0] if link_nodes else None
            title = clean_text(link_el.text_content()) if link_el is not None else None
            url = None
            if link_el is not None:
                href = link_el.get("href")
                if href:
                    url = urljoin(base_url, href)
            snippet_nodes = post.xpath(".//div[contains(@class,'post__text')]//p")
            snippet_p = snippet_nodes[0] if snippet_nodes else None
            snippet = clean_text(snippet_p.text_content()) if snippet_p is not None else None
            if not (title or snippet or url):
                continue
            news.append({
                "title": title, "url": url, "date": iso_date,
                "day": day, "month": month, "year": year, "snippet": snippet,
            })
    return news
