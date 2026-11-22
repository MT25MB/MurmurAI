"""Cancellation releases waiting workers and always runs cleanup.

Capri's input-cancel suite proves a cancelled helper is stopped and held input
is released. Murmur's equivalent boundary is the shared abort controller: a
worker blocked waiting for approval must be released by abort, cleanup must run
in ``finally``, and unrelated failures must never be mistaken for cancellation.
"""

from __future__ import annotations

import threading

from agent.abort import AbortController


def test_abort_releases_waiting_worker():
    controller = AbortController()
    started = threading.Event()
    outcomes: list[bool] = []

    def worker() -> None:
        started.set()
        outcomes.append(controller.wait(5))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    assert started.wait(1)

    controller.abort("user said stop")
    thread.join(timeout=1)

    assert outcomes == [True]
    assert not thread.is_alive()
    controller.reset()


def test_wait_times_out_without_abort():
    controller = AbortController()
    assert controller.wait(0.02) is False


def test_cleanup_runs_when_wait_is_cancelled():
    controller = AbortController()
    released: list[str] = []

    def worker() -> None:
        try:
            controller.wait(5)
        finally:
            released.append("held input released")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    controller.abort("cancel during drag")
    thread.join(timeout=1)

    assert released == ["held input released"]
    controller.reset()


def test_unrelated_failure_does_not_abort():
    controller = AbortController()
    failures: list[str] = []

    def worker() -> None:
        try:
            raise OSError("transport interruption")
        except OSError as error:
            failures.append(str(error))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=1)

    assert failures == ["transport interruption"]
    assert not controller.is_aborted()


def test_abort_is_idempotent_and_listener_fires_once():
    controller = AbortController()
    reasons: list[str] = []
    controller.add_listener(reasons.append)

    controller.abort("first")
    controller.abort("second")

    assert reasons == ["first"]
    assert controller.reason == "first"
    controller.reset()
