"""Browser tool tests using a local HTML fixture and mocked Playwright pages.

No browser is launched and no network is used: the fixture is parsed to emulate
what the in-page JavaScript extractor returns, and all Playwright interactions
are driven through small fakes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import tools.browser_tool as bt
from agent.brain import ALL_TOOLS
from tools.browser_tool import (
    BROWSER_TOOLS,
    click_web_element,
    fill_web_field,
    list_actionable_links,
    list_landmarks_and_headings,
    open_url,
    read_page_summary,
    read_web_table,
)
from tools.os_tools import dispatch_tool

FIXTURE = Path(__file__).parent / "fixtures" / "sample_article.html"
SEMANTIC_FIXTURE = Path(__file__).parent / "fixtures" / "semantic_sections.html"


@pytest.fixture(autouse=True)
def _no_real_browser(monkeypatch):
    """Unit tests must never open a real browser window."""
    monkeypatch.setattr(bt.webbrowser, "open", lambda target: True)


def _strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _fixture_data() -> dict:
    """Emulate the JS extractor for the local HTML fixture."""
    html = FIXTURE.read_text(encoding="utf-8")
    title = re.search(r"<title>(.*?)</title>", html, re.S | re.I).group(1).strip()
    main = re.search(r"<main[^>]*>(.*?)</main>", html, re.S | re.I).group(1)

    headings = [
        {"level": int(m.group(1)), "text": _strip_tags(m.group(2))}
        for m in re.finditer(r"<h([1-6])[^>]*>(.*?)</h\1>", html, re.S | re.I)
    ]
    fields = []
    labels = dict(re.findall(r'<label for="([^"]+)">([^<]+)</label>', html))
    for tag in re.finditer(r"<input([^>]*)>", main, re.I):
        attrs = tag.group(1)
        ident = re.search(r'id="([^"]+)"', attrs)
        placeholder = re.search(r'placeholder="([^"]+)"', attrs)
        ftype = re.search(r'type="([^"]+)"', attrs)
        fields.append({
            "tag": "input",
            "type": ftype.group(1) if ftype else "",
            "label": (labels.get(ident.group(1), "") if ident else "") or (placeholder.group(1) if placeholder else ""),
            "required": "required" in attrs,
        })

    actions = []
    for m in re.finditer(r"<(button|a)\b[^>]*>(.*?)</\1>", main, re.S | re.I):
        text = _strip_tags(m.group(2))
        if text:
            actions.append({
                "role": "link" if m.group(1).lower() == "a" else "button",
                "text": text,
            })

    return {
        "title": title,
        "url": "https://example.com/blender-guide",
        "headings": headings,
        "fields": fields,
        "actions": actions,
        "text": _strip_tags(main),
    }


def _semantic_html() -> str:
    return SEMANTIC_FIXTURE.read_text(encoding="utf-8")


def _semantic_title() -> str:
    return re.search(r"<title>(.*?)</title>", _semantic_html(), re.S | re.I).group(1).strip()


def _semantic_outline_data() -> dict:
    """Emulate the outline extractor for the multi-section fixture."""
    html = _semantic_html()
    landmarks = []
    for m in re.finditer(r"<(main|nav|article|form|aside)\b([^>]*)>", html, re.I):
        tag = m.group(1).lower()
        closing = re.search(r"</" + tag + r">", html[m.end():], re.I)
        segment = html[m.end(): m.end() + closing.start()] if closing else html[m.end():]
        label = re.search(r'aria-label="([^"]+)"', m.group(2))
        heading = re.search(r"<h[1-3][^>]*>(.*?)</h[1-3]>", segment, re.S | re.I)
        landmarks.append({
            "tag": tag,
            "label": label.group(1) if label else "",
            "heading": _strip_tags(heading.group(1)) if heading else "",
            "text": _strip_tags(segment)[:160],
        })
    headings = [
        {"level": int(m.group(1)), "text": _strip_tags(m.group(2))}
        for m in re.finditer(r"<h([1-3])[^>]*>(.*?)</h\1>", html, re.S | re.I)
    ]
    return {"title": _semantic_title(), "landmarks": landmarks, "headings": headings}


def _semantic_table_data() -> dict:
    """Emulate the table extractor for two differently shaped tables."""
    html = _semantic_html()
    tables = []
    for tbl in re.finditer(r"<table>(.*?)</table>", html, re.S | re.I):
        body = tbl.group(1)
        head = re.search(r"<thead>(.*?)</thead>", body, re.S | re.I)
        header_source = head.group(1) if head else body
        first_tr = re.search(r"<tr>(.*?)</tr>", header_source, re.S | re.I)
        headers = (
            [_strip_tags(x) for x in re.findall(r"<th[^>]*>(.*?)</th>", first_tr.group(1), re.S | re.I)]
            if first_tr else []
        )
        tbody = re.search(r"<tbody>(.*?)</tbody>", body, re.S | re.I)
        row_source = tbody.group(1) if tbody else body
        rows = []
        for tr in re.finditer(r"<tr>(.*?)</tr>", row_source, re.S | re.I):
            cells = [_strip_tags(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr.group(1), re.S | re.I)]
            if cells:
                rows.append(cells)
        tables.append({"headers": headers, "rows": rows})
    return {"tables": tables}


def _semantic_links_data() -> dict:
    """Emulate the link extractor, skipping empty and decorative-only controls."""
    items = []
    for m in re.finditer(r"<(a|button)\b([^>]*)>(.*?)</\1>", _semantic_html(), re.S | re.I):
        tag = m.group(1).lower()
        aria = re.search(r'aria-label="([^"]+)"', m.group(2))
        text = _strip_tags(m.group(3))
        label = aria.group(1) if aria else text
        if not label or label in ("\U0001f517",):
            continue
        href = re.search(r'href="([^"]+)"', m.group(2))
        items.append({
            "role": "link" if tag == "a" else "button",
            "label": label,
            "href": href.group(1) if href else "",
        })
    return {"title": _semantic_title(), "items": items}


class FakeLocator:
    def __init__(self, page, name, found=True):
        self.page = page
        self.name = name
        self.found = found
        self.clicked = False
        self.filled = None

    def count(self):
        return 1 if self.found else 0

    @property
    def first(self):
        return self

    def click(self):
        self.clicked = True
        self.page.clicked.append(self.name)
        return None

    def fill(self, value):
        self.filled = value
        self.page.filled.append((self.name, value))
        return None


class FakePage:
    """Minimal Playwright page double."""

    def __init__(self, data=None):
        self.data = data if data is not None else _fixture_data()
        self.goto_calls = []
        self.clicked = []
        self.filled = []
        self.find_by = {}  # (method, name) -> bool found
        self._closed = False
        self.url = "https://example.com/start"
        self._title = "Example"

    # navigation
    def goto(self, url, **kwargs):
        self.goto_calls.append((url, kwargs))
        self.url = url
        return None

    def title(self):
        return self._title

    def is_closed(self):
        return self._closed

    def evaluate(self, script):
        if script is bt._OUTLINE_JS:
            return _semantic_outline_data()
        if script is bt._TABLE_JS:
            return _semantic_table_data()
        if script is bt._LINKS_JS:
            return _semantic_links_data()
        return self.data

    # locator factories
    def _make(self, method, name, value):
        found = self.find_by.get((method, value), False)
        return FakeLocator(self, f"{method}:{value}", found=found)

    def get_by_role(self, role, name=None, exact=False):
        return self._make("role", role, name or "")

    def get_by_label(self, name, exact=False):
        return self._make("label", "label", name)

    def get_by_placeholder(self, name, exact=False):
        return self._make("placeholder", "placeholder", name)

    def get_by_text(self, name, exact=False):
        return self._make("text", "text", name)

    def locator(self, selector):
        return self._make("locator", "selector", selector)


@pytest.fixture(autouse=True)
def _reset_browser_session():
    bt.reset()
    yield
    bt.reset()


# ---- registration / routing ----

def test_browser_tools_registered_in_brain():
    names = [t["function"]["name"] for t in BROWSER_TOOLS]
    assert set(names) == {
        "open_url", "read_page_summary", "click_web_element", "fill_web_field",
        "list_landmarks_and_headings", "read_web_table", "list_actionable_links",
    }
    brain_names = [t["function"]["name"] for t in ALL_TOOLS]
    for name in names:
        assert name in brain_names
    assert "describe_screen" in brain_names  # native GUI path preserved


def test_browser_tool_schemas_valid():
    for tool in BROWSER_TOOLS:
        fn = tool["function"]
        params = fn["parameters"]
        assert params["type"] == "object"
        assert isinstance(params["properties"], dict)
        assert isinstance(params["required"], list)


def test_dispatch_routes_browser_tools(monkeypatch):
    seen = []
    monkeypatch.setattr(bt, "open_url", lambda u: seen.append(("open", u)) or "opened")
    monkeypatch.setattr(bt, "read_page_summary", lambda: seen.append(("read",)) or "summary")
    monkeypatch.setattr(bt, "click_web_element", lambda l: seen.append(("click", l)) or "clicked")
    monkeypatch.setattr(bt, "fill_web_field", lambda l, t: seen.append(("fill", l, t)) or "filled")
    monkeypatch.setattr(bt, "list_landmarks_and_headings", lambda: seen.append(("outline",)) or "outline")
    monkeypatch.setattr(bt, "read_web_table", lambda i, r: seen.append(("table", i, r)) or "table")
    monkeypatch.setattr(bt, "list_actionable_links", lambda f: seen.append(("links", f)) or "links")

    assert dispatch_tool("open_url", {"url": "x"}, None) == "opened"
    assert dispatch_tool("read_page_summary", {}, None) == "summary"
    assert dispatch_tool("click_web_element", {"label_or_role": "Go"}, None) == "clicked"
    assert dispatch_tool("fill_web_field", {"field_label": "Name", "text": "Ada"}, None) == "filled"
    assert dispatch_tool("list_landmarks_and_headings", {}, None) == "outline"
    assert dispatch_tool("read_web_table", {"table_index": 1, "row_limit": 3}, None) == "table"
    assert dispatch_tool("list_actionable_links", {"filter_text": "download"}, None) == "links"
    assert seen == [
        ("open", "x"), ("read",), ("click", "Go"), ("fill", "Name", "Ada"),
        ("outline",), ("table", 1, 3), ("links", "download"),
    ]


def test_brain_prompt_prefers_browser_for_web():
    from agent.brain import SYSTEM_PROMPT

    lowered = SYSTEM_PROMPT.lower()
    assert "prefer the browser tools whenever the task is about" in lowered
    assert "native desktop apps" in lowered


# ---- URL / search handling ----

def test_open_url_direct_url():
    page = FakePage()
    result = open_url("https://example.com/guide", page=page)
    assert page.goto_calls[0][0] == "https://example.com/guide"
    assert "example.com/guide" in result


def test_open_url_search_defaults_to_duckduckgo():
    page = FakePage()
    open_url("python tutorials", page=page)
    url = page.goto_calls[0][0]
    assert url.startswith("https://duckduckgo.com/?q=")
    assert "python+tutorials" in url


def test_open_url_bare_domain_and_www():
    page = FakePage()
    open_url("example.com/news", page=page)
    assert page.goto_calls[0][0] == "https://example.com/news"
    open_url("www.example.com", page=page)
    assert page.goto_calls[-1][0] == "https://www.example.com"


def test_open_url_startpage_override(monkeypatch):
    monkeypatch.setattr(bt, "SEARCH_ENGINE", "startpage")
    page = FakePage()
    open_url("cats", page=page)
    assert page.goto_calls[0][0].startswith("https://www.startpage.com")


def test_open_url_uses_the_installed_default_browser(monkeypatch):
    opened = []
    monkeypatch.setattr(bt, "_load_playwright", lambda: None)
    monkeypatch.setattr(bt.webbrowser, "open", lambda target: opened.append(target))

    result = open_url("anything")

    assert opened and "duckduckgo" in opened[0]
    assert "default browser" in result
    assert "Playwright" not in result


# ---- page summaries ----

def test_read_page_summary_is_spoken_friendly():
    page = FakePage()
    summary = read_page_summary(page=page)
    assert "Page: Blender shortcuts guide." in summary
    assert "Heading 1: Blender shortcuts guide" in summary
    assert "Shift A to open the add menu" in summary
    assert "Email address" in summary and "required" in summary
    assert "button Subscribe" in summary
    assert "link Read the next guide" in summary
    # navigation clutter from <nav>/<footer> is stripped by the JS extractor
    assert "Copyright 2026" not in summary


def test_read_page_summary_empty_page():
    page = FakePage(data={"title": "", "url": "", "headings": [], "fields": [], "actions": [], "text": ""})
    assert "no readable text" in read_page_summary(page=page).lower()


def test_read_page_summary_survives_evaluate_error():
    class Broken(FakePage):
        def evaluate(self, script):
            raise RuntimeError("detached frame")

    assert "Could not read this page" in read_page_summary(page=Broken())


# ---- clicking / filling ----

def test_click_by_button_role():
    page = FakePage()
    page.find_by[("role", "Subscribe")] = True
    result = click_web_element("Subscribe", page=page)
    assert result == "Clicked Subscribe."
    assert page.clicked == ["role:Subscribe"]


def test_click_falls_back_to_link_then_text():
    page = FakePage()
    page.find_by[("role", "Read the next guide")] = True
    click_web_element("Read the next guide", page=page)
    assert page.clicked == ["role:Read the next guide"]

    page2 = FakePage()
    page2.find_by[("text", "Play tutorial")] = True
    click_web_element("Play tutorial", page=page2)
    assert page2.clicked == ["text:Play tutorial"]


def test_click_not_found_is_actionable():
    result = click_web_element("Nonexistent thing", page=FakePage())
    assert "couldn't find" in result.lower() and "Nonexistent thing" in result


def test_fill_by_label_then_placeholder():
    page = FakePage()
    page.find_by[("label", "Email address")] = True
    assert "Filled Email address." == fill_web_field("Email address", "ada@example.com", page=page)
    assert page.filled == [("label:Email address", "ada@example.com")]


def test_fill_by_placeholder_when_no_label():
    page = FakePage()
    page.find_by[("placeholder", "Search guides")] = True
    fill_web_field("Search guides", "blender", page=page)
    assert page.filled == [("placeholder:Search guides", "blender")]


def test_fill_not_found():
    result = fill_web_field("Missing", "x", page=FakePage())
    assert "couldn't find a field" in result.lower()


# ---- semantic outline / headings ----

def test_list_landmarks_and_headings_reads_multiple_sections():
    result = list_landmarks_and_headings(page=FakePage())
    assert "Page: Workspace plans and pricing." in result
    assert "Landmarks." in result
    assert "main" in result and "nav" in result
    assert "article" in result and "form" in result and "aside" in result
    assert "Headings." in result
    assert "Heading 1: Workspace plans and pricing" in result
    assert "Heading 2: Starter plan" in result
    assert "Heading 3: What is included" in result
    # footer is not a requested landmark
    assert "footer" not in result


def test_list_landmarks_and_headings_empty():
    class EmptyPage(FakePage):
        def evaluate(self, script):
            return {"title": "", "landmarks": [], "headings": []} if script is bt._OUTLINE_JS else super().evaluate(script)

    assert "no landmarks or headings" in list_landmarks_and_headings(page=EmptyPage()).lower()


def test_list_landmarks_and_headings_survives_evaluate_error():
    class Broken(FakePage):
        def evaluate(self, script):
            raise RuntimeError("detached frame")

    assert "Could not read this page structure" in list_landmarks_and_headings(page=Broken())


# ---- tables ----

def test_read_web_table_pairs_headers_to_cells():
    result = read_web_table(page=FakePage())
    assert "Table 1." in result
    assert "Columns: Plan, Price, Seats." in result
    assert "Row 1: Plan is Starter; Price is Free; Seats is 1." in result
    assert "Row 2: Plan is Pro; Price is 12 dollars; Seats is 10." in result
    assert "Row 3: Plan is Team; Price is 29 dollars; Seats is 50." in result


def test_read_web_table_respects_row_limit():
    result = read_web_table(table_index=0, row_limit=2, page=FakePage())
    assert "Row 1:" in result and "Row 2:" in result
    assert "Row 3:" not in result
    assert "Stopped after 2 of 3 rows." in result


def test_read_web_table_second_table_without_thead():
    result = read_web_table(table_index=1, page=FakePage())
    assert "Table 2." in result
    assert "Columns: Region, Latency." in result
    assert "Row 1: Region is Europe; Latency is 40 milliseconds." in result
    # the header-only <tr> was not spoken as a data row
    assert "Row 2: Region is Asia" in result
    assert "Row 3:" not in result


def test_read_web_table_out_of_range():
    result = read_web_table(table_index=7, page=FakePage())
    assert "I found 2 tables" in result
    assert "from 1 to 2" in result


def test_read_web_table_no_tables():
    class EmptyPage(FakePage):
        def evaluate(self, script):
            return {"tables": []} if script is bt._TABLE_JS else super().evaluate(script)

    assert "no data tables" in read_web_table(page=EmptyPage()).lower()


# ---- actionable links ----

def test_list_actionable_links_numbers_controls():
    result = list_actionable_links(page=FakePage())
    assert "I found" in result and "actionable links" in result
    assert "1. Home (link)" in result
    assert "Request a demo (button)" in result
    assert "Download the app (link)" in result
    # "Copy plan link" is kept because its aria-label is meaningful
    assert "Copy plan link (button)" in result
    assert "open link 3" in " ".join(
        t["function"]["description"] for t in BROWSER_TOOLS
    ).lower()


def test_list_actionable_links_skips_empty_and_decorative():
    data = _semantic_links_data()
    assert len(data["items"]) == 7  # 3 nav + demo + 2 main links + aria-labelled button
    assert all(it["label"] for it in data["items"])
    assert not any(it["label"] == "\U0001f517" for it in data["items"])


def test_list_actionable_links_filter():
    result = list_actionable_links(filter_text="download", page=FakePage())
    assert "1. Download the app (link)" in result
    assert "Home (link)" not in result


def test_list_actionable_links_no_matches():
    result = list_actionable_links(filter_text="not here", page=FakePage())
    assert "No links or buttons matching not here" in result


def test_list_actionable_links_empty_page():
    class EmptyPage(FakePage):
        def evaluate(self, script):
            return {"items": []} if script is bt._LINKS_JS else super().evaluate(script)

    assert "no links or buttons" in list_actionable_links(page=EmptyPage()).lower()


def test_brain_prompt_describes_semantic_navigation():
    from agent.brain import SYSTEM_PROMPT

    lowered = SYSTEM_PROMPT.lower()
    assert "list_landmarks_and_headings()" in lowered
    assert "read_web_table(table_index, row_limit)" in lowered
    assert "list_actionable_links(filter_text)" in lowered


# ---- session lifecycle ----

def test_browser_status_shape():
    status = bt.browser_status()
    assert set(status) == {
        "playwright_available", "cdp_available", "cdp_url",
        "session_active", "search_engine",
    }


def test_cdp_connection_preferred_when_available(monkeypatch):
    connected = {}

    class FakeLocatorPage:
        def is_closed(self): return False

    class FakeContext:
        def __init__(self): self.pages = [FakeLocatorPage()]

    class FakeBrowser:
        def __init__(self): self.contexts = [FakeContext()]
        def close(self): pass

    class FakeChromium:
        def connect_over_cdp(self, url):
            connected["url"] = url
            return FakeBrowser()

        def launch(self, **kwargs):
            pytest.fail("Should not launch a new browser when CDP is available")

    class FakeManager:
        chromium = FakeChromium()
        def stop(self): pass

    class FakePlaywright:
        def start(self):
            return FakeManager()

    monkeypatch.setattr(bt, "_cdp_available", lambda: True)
    monkeypatch.setattr(bt, "_playwright_factory", lambda: FakePlaywright())
    try:
        bt._start_session()
        assert connected["url"] == bt.CDP_URL
        assert bt._page is not None
    finally:
        bt.reset()
