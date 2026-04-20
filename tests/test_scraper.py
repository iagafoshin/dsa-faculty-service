from app.scraper.parser import get_person_id, make_tree


def test_staff_page_extracts_via_data_author():
    html = """
    <html><body>
      <div class="publications-widget" data-author="305052829"></div>
    </body></html>
    """
    tree = make_tree(html)
    assert get_person_id(tree) == 305052829


def test_legacy_page_extracts_via_data_person_id():
    html = """
    <html><body>
      <script data-person-id="25477"></script>
    </body></html>
    """
    tree = make_tree(html)
    assert get_person_id(tree) == 25477


def test_url_fallback_when_html_has_no_id_attributes():
    tree = make_tree("<html><body></body></html>")
    assert get_person_id(tree, url="https://www.hse.ru/org/persons/25477") == 25477
