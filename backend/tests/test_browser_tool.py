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
    open_url,
    read_page_summary,
)
from tools.os_tools import dispatch_tool

FIXTURE = Path(__file__).parent / "fixtures" / "sample_article.html"


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
        "open_url", "read_page_summary", "click_web_element", "fill_web_field"
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

    assert dispatch_tool("open_url", {"url": "x"}, None) == "opened"
    assert dispatch_tool("read_page_summary", {}, None) == "summary"
    assert dispatch_tool("click_web_element", {"label_or_role": "Go"}, None) == "clicked"
    assert dispatch_tool("fill_web_field", {"field_label": "Name", "text": "Ada"}, None) == "filled"
    assert seen == [
        ("open", "x"), ("read",), ("click", "Go"), ("fill", "Name", "Ada")
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


def test_open_url_missing_playwright_message(monkeypatch):
    monkeypatch.setattr(bt, "_load_playwright", lambda: None)
    result = open_url("anything")
    assert "Playwright is not installed" in result
    assert "playwright install chromium" in result


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
