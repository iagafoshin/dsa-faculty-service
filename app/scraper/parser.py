"""Ported verbatim from data/hse_persons.ipynb. All parse_* functions live here."""
from __future__ import annotations

import datetime
import re
from urllib.parse import urljoin, urlparse

from lxml import html


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
                contacts["phones"] = " | ".join(phones)

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


def parse_full_name(tree):
    main_el = get_main_root(tree)
    if main_el is not None:
        name_el = main_el.xpath(".//h1[contains(@class,'person-caption')]/text()")
        return clean_text(name_el[0]) if name_el else None
    return None


def parse_employment(tree, base_url: str = "https://www.hse.ru"):
    main_el = get_main_root(tree)
    employment = []
    if main_el is not None:
        ul_list = main_el.xpath(".//ul[contains(@class,'employment-add')]")
        if ul_list:
            ul = ul_list[0]
            for li in ul.xpath("./li"):
                title = clean_text("".join(
                    li.xpath(".//span[contains(@class,'person-appointment-title')]/text()")
                ))
                units = []
                for a in li.xpath(".//a[@class='link']"):
                    unit_name = clean_text(a.text_content())
                    href = a.get("href")
                    if href:
                        href = urljoin(base_url, href)
                    units.append({"name": unit_name, "url": href})
                employment.append({"title": title, "units": units})
    return employment


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


def parse_awards(tree):
    main_el = get_main_root(tree)
    awards = []
    if main_el is not None:
        award_blocks = main_el.xpath(
            ".//div[contains(@class,'b-person-data') and @tab-node='awards']"
        )
        for block in award_blocks:
            for li in block.xpath(".//ul[contains(@class,'g-list')]/li"):
                txt = clean_text(li.text_content())
                if txt:
                    awards.append(txt)
    return awards


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


def parse_grants(tree):
    main_el = get_main_root(tree)
    grants = []
    if main_el is None:
        return grants
    grant_blocks = main_el.xpath(
        ".//div[contains(@class,'b-person-data') and @tab-node='grants']"
    )
    for block in grant_blocks:
        for li in block.xpath(".//ol/li | .//ul/li"):
            txt = clean_text(li.text_content())
            if not txt:
                continue
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
            grants.append({"text": txt, "number": grant_number, "years": years})
    return grants


def parse_editorial_staff(tree):
    main_el = get_main_root(tree)
    editorial_staff = []
    if main_el is None:
        return editorial_staff
    blocks = main_el.xpath(
        ".//div[contains(@class,'b-person-data') and @tab-node='editorial-staff']"
    )
    if not blocks:
        return editorial_staff
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
        editorial_staff.append({"text": txt, "start_year": start_year, "journal": journal})
    return editorial_staff


def parse_conferences(tree, base_url: str = "https://www.hse.ru"):
    main_el = get_main_root(tree)
    conferences = []
    if main_el is None:
        return conferences
    blocks = main_el.xpath(
        ".//div[contains(@class,'b-person-data') and @tab-node='conferences']"
    )
    if not blocks:
        return conferences
    block = blocks[0]
    last_year = None
    for ul in block.xpath(".//ul[contains(@class,'g-list_closer')]"):
        for li in ul.xpath(".//li[contains(@class,'li2')]"):
            year_el = li.xpath(".//div[contains(@class,'person-list-hangover')]/text()")
            if year_el:
                year_raw = clean_text(year_el[0])
                year = None
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
            if description:
                conferences.append({"year": year, "description": description, "links": links})
    return conferences


def parse_work_experience(tree):
    main_el = get_main_root(tree)
    work_experience = []
    if main_el is None:
        return work_experience
    exp_blocks = main_el.xpath(
        ".//div[contains(@class,'b-person-data') and @tab-node='experience']"
    )
    for block in exp_blocks:
        for div in block.xpath(".//div[contains(@class,'with-indent')]"):
            txt = clean_text(div.text_content())
            if not txt:
                continue
            work_experience.append(txt)
    return work_experience


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
