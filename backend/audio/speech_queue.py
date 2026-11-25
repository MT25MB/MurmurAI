"""Priority-ordered speech delivery with clean preemption and barge-in.

Narration is queued; urgent prompts (confirmations, errors) preempt it once and
then queue behind each other. A single worker drains the queue so audio output
never overlaps, and a barge-in clears only interruptible pending items while
preserving critical uninterruptible announcements.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Optional

logger = logging.getLogger("murmur_ai.audio.speech_queue")


class SpeechPriority(IntEnum):
    BACKGROUND_STATUS = 0
    NORMAL_QUEUE = 1
    INTERRUPT = 2


# Highest first, for deterministic scheduler scans.
SPEECH_PRIORITIES = (SpeechPriority.INTERRUPT, SpeechPriority.NORMAL_QUEUE, SpeechPriority.BACKGROUND_STATUS)


@dataclass(frozen=True)
class SpeechRequest:
    text: str
    priority: SpeechPriority = SpeechPriority.NORMAL_QUEUE
    interruptible: bool = True
    context_id: str = ""


@dataclass
class _Queue:
    items: deque[SpeechRequest] = field(default_factory=deque)


class SpeechQueue:
    """Single-consumer priority queue for spoken output."""

    def __init__(self, sink: Callable[[SpeechRequest], None]) -> None:
        self._sink = sink
        self._queues: dict[SpeechPriority, _Queue] = {
            priority: _Queue() for priority in SPEECH_PRIORITIES
        }
        self._current: SpeechPriority | None = None
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._idle = threading.Event()
        self._idle.set()
        self._stopping = False
        self._worker: Optional[threading.Thread] = None

    def _ensure_worker(self) -> None:
        if self._worker is None:
            self._worker = threading.Thread(
                target=self._run, daemon=True, name="murmur-ai-speech-queue"
            )
            self._worker.start()

    @property
    def is_idle(self) -> bool:
        return self._idle.is_set()

    def enqueue(self, request: SpeechRequest) -> bool:
        """Add a request. Returns True when it should preempt current speech."""
        self._ensure_worker()
        with self._lock:
            queue = self._queues[request.priority]
            first = not queue.items and self._current != request.priority
            queue.items.append(request)
            self._idle.clear()
            self._wake.notify()
        should_interrupt = request.priority == SpeechPriority.INTERRUPT and first
        if should_interrupt:
            logger.debug("Urgent speech preempting current narration")
        return should_interrupt

    def clear_interruptible(self) -> int:
        """Drop queued interruptible items; keep uninterruptible ones."""
        dropped = 0
        with self._lock:
            for queue in self._queues.values():
                kept = deque()
                for item in queue.items:
                    if item.interruptible:
                        dropped += 1
                    else:
                        kept.append(item)
                queue.items = kept
            if not any(q.items for q in self._queues.values()) and self._current is None:
                self._idle.set()
        return dropped

    def clear_all(self) -> int:
        """Drop every queued item, including urgent confirmations."""
        dropped = 0
        with self._lock:
            for queue in self._queues.values():
                dropped += len(queue.items)
                queue.items.clear()
            self._idle.set()
        return dropped

    def _next(self) -> Optional[SpeechRequest]:
        for priority in SPEECH_PRIORITIES:
            queue = self._queues[priority]
            if queue.items:
                self._current = priority
                return queue.items.popleft()
        self._current = None
        return None

    def _run(self) -> None:
        while True:
            with self._lock:
                while not self._stopping and not any(
                    q.items for q in self._queues.values()
                ):
                    self._idle.set()
                    self._wake.wait()
                if self._stopping:
                    return
                request = self._next()
            if request is None:
                continue
            try:
                self._sink(request)
            except Exception:  # pragma: no cover - sink defensive
                logger.exception("Speech delivery failed")
            finally:
                with self._lock:
                    self._current = None
                    if not any(q.items for q in self._queues.values()):
                        self._idle.set()

    def wait_until_idle(self, timeout: float = 5.0) -> bool:
        return self._idle.wait(timeout)

    def shutdown(self) -> None:
        with self._lock:
            self._stopping = True
            self._wake.notify_all()
        if self._worker is not None:
            self._worker.join(timeout=2)
