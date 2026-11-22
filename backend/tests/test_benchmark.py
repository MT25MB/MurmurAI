"""Benchmark report generation and offline-safe probes."""

from __future__ import annotations

import sys
import types

import pytest

import agent.brain as brain
import system.benchmark as bench
import tools.os_tools as os_tools


def test_result_row():
    row = bench.BenchmarkResult("Probe", 12.4, 8.1, "ok", "note").to_row()
    assert row == "| Probe | 12 | 8 | ok | note |"
    skipped = bench.BenchmarkResult("Probe", status="skipped", notes="missing").to_row()
    assert "| n/a | n/a | skipped | missing |" in skipped


def test_report_markdown_contains_all_sections():
    report = bench.BenchmarkReport(
        created_at="now",
        system="TestOS",
        hardware={"compute_backend": "CPU", "cpu_cores": 8},
        results=[bench.BenchmarkResult("Whisper", 100, 50, "ok", "synthetic")],
    )
    markdown = report.to_markdown()
    assert "# Murmur AI Benchmarks" in markdown
    assert "TestOS" in markdown
    assert "| Compute Backend | CPU |" in markdown
    assert "| Whisper | 100 | 50 | ok | synthetic |" in markdown
    assert "Comparing platforms" in markdown
    assert "Apple Silicon" in markdown and "NVIDIA" in markdown


def test_report_json():
    report = bench.BenchmarkReport(created_at="now", system="TestOS")
    data = __import__("json").loads(report.to_json())
    assert data["created_at"] == "now" and data["results"] == []


def test_run_all_uses_injected_probes_and_survives_errors():
    def good():
        return bench.BenchmarkResult("Good", 5, 4, "ok")

    def broken():
        raise RuntimeError("boom")

    report = bench.run_all(probes=[good, broken])
    assert [r.name for r in report.results] == ["Good", "broken"]
    assert report.results[0].status == "ok"
    assert report.results[1].status == "skipped"
    assert "probe error" in report.results[1].notes


def test_measure_som_with_mocked_annotator(monkeypatch):
    import agent.som_overlay as som

    monkeypatch.setattr(som, "annotate_screenshot", lambda png: object())
    result = bench.measure_som()
    assert result.status == "ok" and result.cold_ms is not None
    assert result.warm_ms is not None


def test_measure_whisper_with_fake_backend(monkeypatch):
    class FakeModel:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        def transcribe(self, audio, **kwargs):
            self.calls += 1
            return ([], {})

    module = types.ModuleType("faster_whisper")
    module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", module)

    result = bench.measure_whisper()
    assert result.status == "ok"
    assert result.cold_ms is not None and result.warm_ms is not None


def test_benchmark_tool_registered():
    names = [t["function"]["name"] for t in brain.ALL_TOOLS]
    assert "start_demo" in names  # demo is registered alongside benchmarks in the brain
    assert hasattr(bench, "run_all")


def test_dispatch_unrelated_benchmark_tool():
    assert "Unknown tool" in os_tools.dispatch_tool("run_benchmark", {}, None)
