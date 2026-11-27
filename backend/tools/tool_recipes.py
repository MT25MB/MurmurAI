"""Declarative look-up tools: HTTPS GET only, fixed domains, no code or keys.

Capri's .capri-tool recipes are small JSON look-ups that cannot run code. Murmur
uses its own format in ~/.murmur-ai/tool_recipes.json; new recipes are saved
switched off until the user reviews them.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import urllib.request
from urllib.parse import quote, urlparse

logger = logging.getLogger("murmur_ai.tools.tool_recipes")

DEFAULT_PATH = Path.home() / ".murmur-ai" / "tool_recipes.json"

RECIPE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_tool_recipes",
            "description": "List reviewed local look-up tools the user has enabled.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tool_recipe",
            "description": "Run an enabled local look-up tool with one text input.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipe_id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["recipe_id", "text"],
                "additionalProperties": False,
            },
        },
    },
]


def handle_recipe_tool(name: str, arguments: dict[str, Any]) -> str | None:
    names = {tool["function"]["name"] for tool in RECIPE_TOOLS}
    if name not in names:
        return None
    recipes = load_recipes()
    if name == "list_tool_recipes":
        if not recipes:
            return "No look-up tools are enabled yet."
        return "Enabled look-up tools: " + ", ".join(sorted(recipes))
    recipe = recipes.get(str(arguments.get("recipe_id", "")))
    if recipe is None:
        return "That look-up tool is not enabled."
    return execute_recipe(recipe, str(arguments.get("text", "")))


_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_HOST_RE = re.compile(r"^[a-z0-9.-]+$")
_PATH_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")
MAX_RESPONSE = 64 * 1024
MAX_SAY = 2000


@dataclass(frozen=True)
class Recipe:
    id: str
    description: str
    domains: tuple[str, ...]
    steps: tuple[dict[str, Any], ...]
    say: str
    enabled: bool = False


def validate_recipe(raw: dict[str, Any]) -> Recipe | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("id", ""))
    if not _ID_RE.match(name):
        return None
    domains = raw.get("domains") or []
    if not isinstance(domains, list) or not 1 <= len(domains) <= 5:
        return None
    hosts = tuple(str(d).lower() for d in domains)
    if any(not _HOST_RE.match(host) for host in hosts):
        return None
    steps = raw.get("steps") or []
    if not isinstance(steps, list) or not 1 <= len(steps) <= 3:
        return None
    for step in steps:
        if not isinstance(step, dict):
            return None
        url = str(step.get("get", ""))
        parsed = urlparse(url)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in hosts:
            return None
        if "headers" in step or "auth" in step:
            return None
        if not isinstance(step.get("keep"), dict):
            return None
    return Recipe(
        id=name,
        description=str(raw.get("description", ""))[:200],
        domains=hosts,
        steps=tuple(steps),
        say=str(raw.get("say", ""))[:MAX_SAY],
        enabled=bool(raw.get("enabled", False)),
    )


class _ValidatingRedirect(urllib.request.HTTPRedirectHandler):
    """Re-check the recipe allowlist on every redirect hop.

    A trusted allowed domain must not be able to redirect a lookup into
    loopback or link-local metadata services.
    """

    def __init__(self, domains: tuple[str, ...]) -> None:
        self.domains = domains

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(str(newurl))
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in self.domains:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def load_recipes(path: Path | None = None) -> dict[str, Recipe]:
    path = Path(path) if path else DEFAULT_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read tool recipes %s: %s", path, exc)
        return {}
    raw = data.get("recipes", []) if isinstance(data, dict) else []
    recipes: dict[str, Recipe] = {}
    for entry in raw if isinstance(raw, list) else []:
        recipe = validate_recipe(entry)
        if recipe is not None and recipe.enabled:
            recipes[recipe.name if hasattr(recipe, "name") else recipe.id] = recipe
    return recipes


def _extract(data: Any, path: str) -> Any:
    current = data
    for match in _PATH_TOKEN.finditer(path):
        key, index = match.group(1), match.group(2)
        try:
            current = current[int(index)] if index is not None else current[key]
        except (KeyError, IndexError, TypeError):
            return None
    return current


def execute_recipe(
    recipe: Recipe,
    text: str,
    fetcher=None,
) -> str:
    """Run the recipe's GET steps and return a short spoken result."""
    values: dict[str, Any] = {"text": text}
    for step in recipe.steps:
        url = str(step["get"]).replace("{text}", quote(text or ""))
        for name, value in values.items():
            url = url.replace("{" + name + "}", quote(str(value)))
        if fetcher is None:
            opener = urllib.request.build_opener(
                _ValidatingRedirect(tuple(recipe.domains))
            )
            raw = opener.open(url, timeout=4.0).read(MAX_RESPONSE)
        else:
            raw = fetcher(url, 4.0)
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            return f"{recipe.id} could not read that answer."
        for name, path in step["keep"].items():
            values[str(name)] = _extract(payload, str(path))
    try:
        return recipe.say.format(**values)[:MAX_SAY]
    except (KeyError, ValueError):
        return f"{recipe.id} could not format that answer."
