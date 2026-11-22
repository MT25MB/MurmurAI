"""Declarative look-up tools: HTTPS GET only, allowlisted domains, off by default."""

from __future__ import annotations

import json

from tools.tool_recipes import execute_recipe, load_recipes, validate_recipe


RAW = {
    "id": "word_meaning",
    "description": "The first dictionary meaning of an English word.",
    "domains": ["api.dictionaryapi.dev"],
    "steps": [
        {
            "get": "https://api.dictionaryapi.dev/api/v2/entries/en/{text}",
            "keep": {"meaning": "[0].meanings[0].definitions[0].definition"},
        }
    ],
    "say": "{text}: {meaning}",
}


def test_valid_recipe_is_accepted():
    recipe = validate_recipe(RAW)
    assert recipe is not None
    assert recipe.id == "word_meaning"
    assert recipe.enabled is False, "new tools wait switched off until reviewed"


def test_http_and_off_domain_urls_are_rejected():
    bad_http = dict(RAW, steps=[{"get": "http://api.dictionaryapi.dev/x", "keep": {}}])
    assert validate_recipe(bad_http) is None

    bad_host = dict(RAW, steps=[{"get": "https://evil.example/x", "keep": {}}])
    assert validate_recipe(bad_host) is None


def test_auth_headers_are_rejected():
    with_auth = dict(RAW, steps=[{"get": "https://api.dictionaryapi.dev/x", "keep": {},
                                  "headers": {"Authorization": "Bearer secret"}}])
    assert validate_recipe(with_auth) is None


def test_only_reviewed_recipes_are_loaded(tmp_path):
    path = tmp_path / "tool_recipes.json"
    pending = dict(RAW)
    reviewed = dict(RAW, id="reviewed_tool", enabled=True)
    path.write_text(json.dumps({"recipes": [pending, reviewed]}), encoding="utf-8")

    recipes = load_recipes(path)
    assert set(recipes) == {"reviewed_tool"}


def test_execute_recipe_extracts_and_formats():
    recipe = validate_recipe(RAW)
    payload = [{"meanings": [{"definitions": [{"definition": "a large marine mammal"}]}]}]

    calls = []

    def fetcher(url, timeout):
        calls.append((url, timeout))
        return json.dumps(payload).encode("utf-8")

    result = execute_recipe(recipe, "whale", fetcher=fetcher)

    assert result == "whale: a large marine mammal"
    assert calls[0][0].endswith("/en/whale")
    assert calls[0][1] == 4.0


def test_recipe_tools_dispatch(monkeypatch, tmp_path):
    import tools.tool_recipes as recipe_module
    from tools.os_tools import dispatch_tool

    path = tmp_path / "recipes.json"
    path.write_text(json.dumps({"recipes": [dict(RAW, enabled=True)]}), encoding="utf-8")
    monkeypatch.setattr(recipe_module, "DEFAULT_PATH", path)
    monkeypatch.setattr(
        recipe_module,
        "execute_recipe",
        lambda recipe, text: f"{text}: a large marine mammal",
    )

    assert "word_meaning" in dispatch_tool("list_tool_recipes", {}, None)
    result = dispatch_tool("run_tool_recipe", {"recipe_id": "word_meaning", "text": "whale"}, None)
    assert result == "whale: a large marine mammal"


def test_execute_recipe_caps_output():
    recipe = validate_recipe(RAW)
    payload = [{"meanings": [{"definitions": [{"definition": "x" * 5000}]}]}]
    result = execute_recipe(
        recipe, "long", fetcher=lambda url, timeout: json.dumps(payload).encode("utf-8")
    )
    assert len(result) <= 2000
