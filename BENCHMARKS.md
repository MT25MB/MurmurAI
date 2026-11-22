# Murmur AI Benchmarks

Generated: 2026-11-21T23:40:04Z  
System: Windows-11-10.0.22631-SP0

Local, offline-friendly measurements. Lower is better. Cold includes model construction; warm reuses the loaded model. `skipped` means the optional dependency/model was not available on this machine.

## Hardware

| Metric | Value |
| --- | --- |
| Compute Backend | CPU |
| Tier | light |
| Total Ram Gb | 5.44 |
| Vram Gb | 0.0 |
| Cpu Cores | 12 |
| Os | Windows |

## Latency

| Benchmark | Cold (ms) | Warm (ms) | Status | Notes |
| --- | --- | --- | --- | --- |
| faster-whisper transcription | n/a | n/a | skipped | faster-whisper not installed |
| Ollama tool-call routing | n/a | n/a | skipped | Ollama unreachable on localhost |
| Set-of-Marks detection | 69 | 34 | ok | synthetic 1280x720 UI |
| qwen2.5-vl screen grounding | n/a | n/a | skipped | vision model unreachable on localhost |
| Kokoro-82M time-to-first-audio | n/a | n/a | skipped | kokoro not installed |

## Comparing platforms

Run `python scripts/benchmark.py` on a CPU-only machine, Apple Silicon Mac, and an NVIDIA GPU box, then compare the table above. Keep the same model versions and `MURMUR_*` environment variables for a fair comparison.
