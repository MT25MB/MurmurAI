"""Compact, grouped element manifests keep small local VLMs fast."""

from __future__ import annotations

from agent.som_manifest import ElementRecord, build_manifest, merge_elements


def _record(name, x, y, role="button", box=(0, 0, 100, 100), source="native"):
    return ElementRecord(name=name, role=role, center_x=x, center_y=y, box=box, source=source)


def test_merge_drops_contained_duplicates():
    items = [
        _record("Save", 50, 50, box=(10, 10, 90, 90)),
        _record("Save", 52, 52, box=(20, 20, 60, 60)),
    ]
    merged = merge_elements(items)
    assert len(merged) == 1
    assert merged[0].name == "Save"


def test_merge_groups_nearby_identical_labels():
    items = [
        _record("OK", 100, 100),
        _record("OK", 103, 101),
        _record("Cancel", 300, 300),
    ]
    merged = merge_elements(items)
    assert len(merged) == 2


def test_manifest_table_is_bounded_and_has_no_coordinates():
    items = [_record(f"Control {i}", i, i) for i in range(60)]
    manifest = build_manifest(items, limit=10, name_chars=20)
    lines = manifest.text.splitlines()
    assert len(lines) == 10
    assert "[1]" in manifest.text
    assert all("(" not in line for line in lines)
    assert "[10]" in manifest.text
    assert len(manifest.positions) == 10


def test_manifest_geometry_lives_in_side_map():
    items = [_record("Save", 500, 400, box=(450, 350, 550, 450))]
    manifest = build_manifest(items)
    first_id = next(iter(manifest.positions))
    assert manifest.positions[first_id] == (500, 400)
    assert "500" not in manifest.text


def test_manifest_handles_empty_input():
    manifest = build_manifest([])
    assert manifest.text == ""
    assert manifest.positions == {}
