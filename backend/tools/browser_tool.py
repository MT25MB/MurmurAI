"""Accessibility-first browser automation for Murmur AI.

Uses Playwright with automatic Chromium fallback, or attaches to the user's
running browser over Chrome DevTools Protocol (http://localhost:9222) when
available. Designed for spoken narration: page summaries strip navigation
clutter and return structured, concise text meant to be read aloud.

No API keys and no cloud services: web search defaults to DuckDuckGo (or
Startpage via MURMUR_SEARCH_ENGINE=startpage).

All heavy imports are lazy. If Playwright is not installed the tools return a
clear, actionable message instead of crashing the brain.
"""

from __future__ import annotations

import json
import logging
import os
import re
import webbrowser
from typing import Any, Optional
from urllib.parse import quote_plus, urlparse

logger = logging.getLogger("murmur_ai.tools.browser_tool")

CDP_URL = os.getenv("MURMUR_BROWSER_CDP_URL", "http://localhost:9222").rstrip("/")
HEADLESS = os.getenv("MURMUR_BROWSER_HEADLESS", "0") == "1"
SEARCH_ENGINE = os.getenv("MURMUR_SEARCH_ENGINE", "duckduckgo").lower()

MAX_SUMMARY_CHARS = int(os.getenv("MURMUR_PAGE_SUMMARY_CHARS", "2000"))
MAX_ELEMENTS = int(os.getenv("MURMUR_PAGE_ELEMENTS", "30"))

DDG_SEARCH = "https://duckduckgo.com/?q={query}"
STARTPAGE_SEARCH = "https://www.startpage.com/sp/search?query={query}"

# Module-level session state, lazily created. Tests can reset with reset().
_playwright_factory = None
_browser = None
_context = None
_page = None
_manager = None


BROWSER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_url",
            "description": (
                "Open a website or search the web in the local browser. Pass a "
                "full URL (http/https) to visit it, or plain words to run a "
                "private web search (DuckDuckGo/Startpage, no API key)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "A full http(s) URL, or a search phrase.",
                    }
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_page_summary",
            "description": (
                "Read the active browser page as concise, spoken-friendly text: "
                "headings, main article text, form fields, and interactive "
                "buttons/links. Navigation bars and clutter are removed. Use "
                "this for reading articles, search results, or web content."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click_web_element",
            "description": (
                "Click a button, link, or control on the active web page by its "
                "visible text or ARIA label, with no pixel coordinates."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "label_or_role": {
                        "type": "string",
                        "description": "Visible text or ARIA label of the element to activate.",
                    }
                },
                "required": ["label_or_role"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fill_web_field",
            "description": (
                "Type text into an input, textarea, or search field on the "
                "active web page, located by its label or placeholder."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "field_label": {
                        "type": "string",
                        "description": "Label, aria-label, or placeholder of the field.",
                    },
                    "text": {
                        "type": "string",
                        "description": "The text to type into the field.",
                    },
                },
                "required": ["field_label", "text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_landmarks_and_headings",
            "description": (
                "Read the semantic structure of the active web page: HTML "
                "landmarks (main, navigation, article, form, aside) and the "
                "H1-H3 heading hierarchy. Use for 'jump to main content', "
                "'skip navigation', 'read the headings on this page', or "
                "'what sections are on this page'."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_web_table",
            "description": (
                "Read an HTML data table row by row with each column header "
                "paired to its cell, instead of dumping raw text. Use when the "
                "user asks to read a table, a schedule, prices, or comparison "
                "data on the page. table_index is zero based (first table is 0)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_index": {
                        "type": "integer",
                        "description": "Zero-based table to read. Defaults to the first table.",
                    },
                    "row_limit": {
                        "type": "integer",
                        "description": "Maximum rows to speak. Defaults to 10.",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_actionable_links",
            "description": (
                "List numbered, meaningful links and buttons on the active "
                "page, skipping empty or decorative icon controls. Use for "
                "'what links are here', 'list the buttons', 'open link 3' or "
                "'find a link about X'. Then click it with click_web_element "
                "using the numbered label."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filter_text": {
                        "type": "string",
                        "description": (
                            "Optional word to narrow the list (for example 'download'). "
                            "Leave empty to list every actionable control."
                        ),
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def _load_playwright():
    """Return the sync_playwright factory, or None when not installed."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore

        return sync_playwright
    except Exception:  # pragma: no cover - optional dependency
        return None


def _cdp_available() -> bool:
    """True when a browser exposes a DevTools endpoint on localhost:9222."""
    try:
        import urllib.request

        with urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _start_session() -> None:
    """Create a browser session: attach over CDP when possible, else launch."""
    global _playwright_factory, _manager, _browser, _context, _page

    factory = _playwright_factory if _playwright_factory is not None else _load_playwright()
    if factory is None:
        raise RuntimeError(
            "Playwright is not installed. Run: pip install playwright && playwright install chromium"
        )

    _playwright_factory = factory
    _manager = factory().start()
    try:
        if _cdp_available():
            _browser = _manager.chromium.connect_over_cdp(CDP_URL)
            _context = _browser.contexts[0] if _browser.contexts else _browser.new_context()
        else:
            # Prefer a browser the user already has installed over Playwright's
            # bundled Chromium, which is often missing and needs a big download.
            for engine, channel in (
                (_manager.chromium, "chrome"),
                (_manager.chromium, "msedge"),
                (_manager.firefox, "firefox"),
            ):
                try:
                    _browser = engine.launch(headless=HEADLESS, channel=channel)
                    break
                except Exception:  # pragma: no cover - depends on installed browsers
                    continue
            if _browser is None:
                _browser = _manager.chromium.launch(headless=HEADLESS)
            _context = _browser.new_context()
        _page = _context.pages[0] if _context.pages else _context.new_page()
        logger.info("Browser session ready (CDP: %s)", _cdp_available())
    except Exception:
        _stop_session()
        raise


def _stop_session() -> None:
    global _browser, _context, _page, _manager
    try:
        if _browser is not None:
            _browser.close()
    except Exception:  # pragma: no cover - best effort
        pass
    try:
        if _manager is not None:
            _manager.stop()
    except Exception:  # pragma: no cover - best effort
        pass
    _browser = _context = _page = _manager = None


def reset() -> None:
    """Close the session and clear cached factories (used in tests/settings)."""
    global _playwright_factory
    _stop_session()
    _playwright_factory = None


def _existing_page() -> Any | None:
    """Return an already-open Playwright page without launching a browser."""
    if _page is not None and not _page.is_closed():
        return _page
    return None


def _active_page(page: Any | None = None) -> Any:
    if page is not None:
        return page
    if _page is None or _page.is_closed():
        _start_session()
    return _page


def browser_status() -> dict[str, Any]:
    """Report browser availability for diagnostics/settings."""
    return {
        "playwright_available": _load_playwright() is not None,
        "cdp_available": _cdp_available(),
        "cdp_url": CDP_URL,
        "session_active": _page is not None,
        "search_engine": SEARCH_ENGINE,
    }


# ---------------------------------------------------------------------------
# Public tools
# ---------------------------------------------------------------------------

def _search_url(query: str) -> str:
    template = STARTPAGE_SEARCH if SEARCH_ENGINE == "startpage" else DDG_SEARCH
    return template.format(query=quote_plus(query))


def _normalize_target(target: str) -> str:
    value = (target or "").strip()
    parsed = urlparse(value)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return value
    if value.startswith("www."):
        return "https://" + value
    # Bare domain such as "example.com/path".
    if re.match(r"^[\w.-]+\.[a-z]{2,}(/|$)", value, re.IGNORECASE):
        return "https://" + value
    return _search_url(value)


def open_url(url: str, page: Any | None = None) -> str:
    """Open a URL or run a private web search for a phrase."""
    target = _normalize_target(url)
    if not target or target == _search_url(""):
        return "Please provide a URL or something to search for."
    # Always use the user's own default browser first. No Playwright download
    # is needed just to open a page; reading/clicking can attach later.
    try:
        webbrowser.open(target)
    except Exception:  # pragma: no cover - platform dependent
        logger.debug("webbrowser.open failed", exc_info=True)

    try:
        pg = _existing_page() if page is None else page
        if pg is not None:
            pg.goto(target, wait_until="domcontentloaded", timeout=30000)
            title = ""
            try:
                title = pg.title() or ""
            except Exception:
                pass
            return f"Opened {title or target}. {pg.url}"
    except Exception as exc:
        logger.debug("Browser page navigation failed", exc_info=True)
    return f"Opened {target} in your default browser."


# JS runs in the page: collect only accessible, meaningful content.
_EXTRACT_JS = """() => {
  const clean = (el) => (el && (el.innerText || el.textContent) || '').replace(/\\s+/g, ' ').trim();
  const skip = el => !el || !!(el.closest && el.closest('nav,header,footer,aside,script,style,[aria-hidden="true"]'));
  const visible = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const labelOf = (el) => {
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();
    if (el.id) {
      const lbl = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (lbl) return clean(lbl);
    }
    if (el.closest && el.closest('label')) return clean(el.closest('label'));
    return el.getAttribute('placeholder') || el.getAttribute('name') || el.getAttribute('type') || '';
  };
  const main = document.querySelector('main,article,[role="main"]') || document.body;
  const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6'))
    .filter(visible).slice(0, 20)
    .map(h => ({level: Number(h.tagName[1]), text: clean(h)})).filter(h => h.text);
  const fields = Array.from(document.querySelectorAll('input,textarea,select'))
    .filter(visible).slice(0, 30).map(el => ({
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type') || '',
      label: labelOf(el),
      required: el.required || el.getAttribute('aria-required') === 'true'
    }));
  const actions = Array.from(document.querySelectorAll('button,a,[role="button"],[role="link"]'))
    .filter(visible).filter(el => !skip(el)).slice(0, 40)
    .map(el => ({role: el.tagName.toLowerCase() === 'a' ? 'link' : 'button',
                 text: clean(el) || el.getAttribute('aria-label') || ''}))
    .filter(a => a.text);
  return {title: document.title || '', url: location.href,
          headings, fields, actions, text: clean(main)};
}"""


def _summarize_data(data: dict[str, Any]) -> str:
    """Turn extracted page data into terse, narration-friendly lines."""
    lines: list[str] = []
    title = (data.get("title") or "").strip()
    if title:
        lines.append(f"Page: {title}.")
    url = (data.get("url") or "").strip()
    if url:
        lines.append(f"Address: {url}.")

    headings = data.get("headings") or []
    if headings:
        parts = [f"Heading {h.get('level', 1)}: {h.get('text', '')}" for h in headings[:10]]
        lines.append("Headings. " + "; ".join(parts) + ".")

    text = re.sub(r"\s+", " ", data.get("text") or "").strip()
    if text:
        lines.append("Article. " + text[:MAX_SUMMARY_CHARS] + ("." if not text.endswith(".") else ""))

    fields = data.get("fields") or []
    if fields:
        parts = []
        for f in fields[:MAX_ELEMENTS]:
            label = f.get("label") or "unlabeled field"
            req = " required" if f.get("required") else ""
            parts.append(f"{label} ({f.get('type') or f.get('tag') or 'input'}{req})")
        lines.append("Form fields. " + "; ".join(parts) + ".")

    actions = data.get("actions") or []
    if actions:
        parts = [f"{a.get('role', 'control')} {a.get('text', '')}" for a in actions[:MAX_ELEMENTS]]
        lines.append("Interactive items. " + "; ".join(parts) + ".")

    return "\n".join(lines) if lines else "This page has no readable text."


def read_page_summary(page: Any | None = None) -> str:
    """Return a concise, screen-reader-friendly summary of the active page."""
    try:
        pg = _active_page(page)
        data = pg.evaluate(_EXTRACT_JS)
        if not isinstance(data, dict):
            return "Could not read this page."
        return _summarize_data(data)
    except Exception as exc:
        logger.exception("Page summary failed")
        return f"Could not read this page: {exc}"


# ---------------------------------------------------------------------------
# Semantic structure, table and actionable-link extraction
# ---------------------------------------------------------------------------

# Each script runs inside the page and returns plain JSON-safe data. Keeping
# extraction in JavaScript (and narration in Python) makes the tools testable
# without a real browser: tests feed the same data shape through a fake page.
_OUTLINE_JS = """() => {
  const clean = (el) => (el && (el.innerText || el.textContent) || '').replace(/\\s+/g, ' ').trim();
  const visible = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const sel = 'main,nav,article,form,aside,[role="main"],[role="navigation"],[role="article"],[role="form"],[role="complementary"]';
  const landmarks = Array.from(document.querySelectorAll(sel))
    .filter(visible).slice(0, 20).map(el => {
      const role = el.getAttribute('role');
      const tag = role ? role.toLowerCase() : el.tagName.toLowerCase();
      const heading = el.querySelector('h1,h2,h3');
      return {
        tag,
        label: (el.getAttribute('aria-label') || '').trim(),
        heading: heading ? clean(heading) : '',
        text: clean(el).slice(0, 160)
      };
    }).filter(l => l.label || l.heading || l.text);
  const headings = Array.from(document.querySelectorAll('h1,h2,h3'))
    .filter(visible).slice(0, 30)
    .map(h => ({level: Number(h.tagName[1]), text: clean(h)}))
    .filter(h => h.text);
  return {title: document.title || '', landmarks, headings};
}"""

_TABLE_JS = """() => {
  const clean = (el) => (el && (el.innerText || el.textContent) || '').replace(/\\s+/g, ' ').trim();
  const tables = Array.from(document.querySelectorAll('table')).map(table => {
    const headRow = table.querySelector('thead tr') || table.querySelector('tr');
    const headers = headRow
      ? Array.from(headRow.querySelectorAll('th')).map(clean)
      : [];
    const bodyRows = Array.from(table.querySelectorAll('tbody tr'));
    const source = bodyRows.length ? bodyRows : Array.from(table.querySelectorAll('tr'));
    const rows = source.map(tr => Array.from(tr.querySelectorAll('td')).map(clean))
      .filter(cells => cells.length);
    return {headers, rows};
  });
  return {tables};
}"""

_LINKS_JS = """() => {
  const clean = (el) => (el && (el.innerText || el.textContent) || '').replace(/\\s+/g, ' ').trim();
  const visible = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const decorative = /^[\\s\\u2022\\u00b7\\u25aa\\u2013\\u2014\\u2026\\u2192\\u2190\\u25ba\\u25c4\\u2605\\u2606\\u2665\\u2713\\u2717\\u00d7]*$/;
  const items = Array.from(document.querySelectorAll('a[href],button,[role="link"],[role="button"]'))
    .filter(visible)
    .map(el => {
      const tag = (el.tagName || '').toLowerCase();
      const role = tag === 'a' || el.getAttribute('role') === 'link' ? 'link' : 'button';
      const text = clean(el);
      const label = (el.getAttribute('aria-label') || '').trim() || text ||
                    (el.getAttribute('title') || '').trim();
      return {role, label, href: el.getAttribute('href') || ''};
    })
    .filter(it => it.label && !decorative.test(it.label))
    .slice(0, 60);
  return {title: document.title || '', items};
}"""


def _format_outline(data: dict[str, Any]) -> str:
    """Narrate landmarks and headings as a structured page outline."""
    lines: list[str] = []
    title = (data.get("title") or "").strip()
    if title:
        lines.append(f"Page: {title}.")

    landmarks = data.get("landmarks") or []
    if landmarks:
        parts = []
        for lm in landmarks[:10]:
            tag = lm.get("tag") or "section"
            label = (lm.get("label") or "").strip()
            heading = (lm.get("heading") or "").strip()
            detail = label or heading
            parts.append(f"{tag}" + (f" ({detail})" if detail else ""))
        lines.append("Landmarks. " + "; ".join(parts) + ".")

    headings = data.get("headings") or []
    if headings:
        parts = [f"Heading {h.get('level', 1)}: {h.get('text', '')}" for h in headings[:12]]
        lines.append("Headings. " + "; ".join(parts) + ".")

    return "\n".join(lines) if lines else "This page has no landmarks or headings."


def _format_table(data: dict[str, Any], table_index: int, row_limit: int) -> str:
    """Narrate a table one row at a time, pairing each header with its cell."""
    tables = data.get("tables") or []
    if not tables:
        return "This page has no data tables."
    try:
        index = int(table_index)
    except (TypeError, ValueError):
        index = 0
    if index < 0 or index >= len(tables):
        return (
            f"I found {len(tables)} table{'s' if len(tables) != 1 else ''} on this page. "
            f"Please choose a table from 1 to {len(tables)}."
        )
    table = tables[index]
    headers = [str(h).strip() for h in (table.get("headers") or [])]
    rows = table.get("rows") or []
    try:
        limit = max(1, min(int(row_limit), 50))
    except (TypeError, ValueError):
        limit = 10

    lines = [f"Table {index + 1}."]
    if headers:
        lines.append("Columns: " + ", ".join(headers) + ".")
    if not rows:
        lines.append("This table has no data rows.")
        return " ".join(lines)

    for row_num, cells in enumerate(rows[:limit], start=1):
        pairs = []
        for col_num, cell in enumerate(cells):
            name = headers[col_num] if col_num < len(headers) else f"Column {col_num + 1}"
            pairs.append(f"{name} is {cell}")
        lines.append(f"Row {row_num}: " + "; ".join(pairs) + ".")
    if len(rows) > limit:
        lines.append(f"Stopped after {limit} of {len(rows)} rows.")
    return " ".join(lines)


def _format_links(data: dict[str, Any], filter_text: str | None) -> str:
    """Number actionable controls so 'open link 3' resolves to a clean label."""
    items = data.get("items") or []
    needle = (filter_text or "").strip().lower()
    if needle:
        items = [it for it in items if needle in (it.get("label") or "").lower()]
    if not items:
        if needle:
            return f"No links or buttons matching {filter_text.strip()}."
        return "There are no links or buttons on this page."
    parts = [
        f"{num}. {it.get('label', '')} ({it.get('role') or 'control'})"
        for num, it in enumerate(items[:MAX_ELEMENTS], start=1)
    ]
    return f"I found {len(items)} actionable links. " + "; ".join(parts) + "."


def list_landmarks_and_headings(page: Any | None = None) -> str:
    """Return a spoken outline of landmarks and H1-H3 headings."""
    try:
        pg = _active_page(page)
        data = pg.evaluate(_OUTLINE_JS)
        if not isinstance(data, dict):
            return "Could not read this page structure."
        return _format_outline(data)
    except Exception as exc:
        logger.exception("Outline extraction failed")
        return f"Could not read this page structure: {exc}"


def read_web_table(
    table_index: int = 0, row_limit: int = 10, page: Any | None = None
) -> str:
    """Read an HTML table with headers paired to each cell, row by row."""
    try:
        pg = _active_page(page)
        data = pg.evaluate(_TABLE_JS)
        if not isinstance(data, dict):
            return "Could not read tables on this page."
        return _format_table(data, table_index, row_limit)
    except Exception as exc:
        logger.exception("Table extraction failed")
        return f"Could not read tables on this page: {exc}"


def list_actionable_links(filter_text: str | None = None, page: Any | None = None) -> str:
    """List numbered, meaningful links and buttons, optionally filtered."""
    try:
        pg = _active_page(page)
        data = pg.evaluate(_LINKS_JS)
        if not isinstance(data, dict):
            return "Could not read links on this page."
        return _format_links(data, filter_text)
    except Exception as exc:
        logger.exception("Link extraction failed")
        return f"Could not read links on this page: {exc}"


def _first_match(page: Any, strategies: list) -> Any | None:
    for make in strategies:
        try:
            locator = make()
            if locator is not None and locator.count() > 0:
                return locator.first
        except Exception:
            continue
    return None


def click_web_element(label_or_role: str, page: Any | None = None) -> str:
    """Activate a button/link by visible text or ARIA label (no coordinates)."""
    label = (label_or_role or "").strip()
    if not label:
        return "Please tell me which element to click."
    try:
        pg = _active_page(page)
        element = _first_match(
            pg,
            [
                lambda: pg.get_by_role("button", name=label, exact=False),
                lambda: pg.get_by_role("link", name=label, exact=False),
                lambda: pg.get_by_label(label, exact=False),
                lambda: pg.get_by_placeholder(label, exact=False),
                lambda: pg.get_by_text(label, exact=False),
            ],
        )
        if element is None:
            return f"I couldn't find a control called {label} on this page."
        element.click()
        return f"Clicked {label}."
    except Exception as exc:
        logger.exception("Click failed for %s", label)
        return f"Could not click {label}: {exc}"


def fill_web_field(field_label: str, text: str, page: Any | None = None) -> str:
    """Type into a form field located by label, aria-label, or placeholder."""
    label = (field_label or "").strip()
    if not label:
        return "Please tell me which field to fill."
    try:
        pg = _active_page(page)
        quoted = json.dumps(label)
        field = _first_match(
            pg,
            [
                lambda: pg.get_by_label(label, exact=False),
                lambda: pg.get_by_placeholder(label, exact=False),
                lambda: pg.get_by_role("textbox", name=label, exact=False),
                lambda: pg.locator(f"[aria-label={quoted}]"),
            ],
        )
        if field is None:
            return f"I couldn't find a field called {label} on this page."
        field.fill(text or "")
        return f"Filled {label}."
    except Exception as exc:
        logger.exception("Fill failed for %s", label)
        return f"Could not fill {label}: {exc}"
