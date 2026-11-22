"""Sentence-boundary chunking and priority-ordered speech delivery."""

from __future__ import annotations

import threading
import time

from audio.speech_queue import SpeechPriority, SpeechQueue, SpeechRequest
from audio.streaming import Sentence, SentenceChunker


def test_chunker_emits_complete_sentences_only():
    chunker = SentenceChunker()
    assert list(chunker.feed("Hello there")) == []
    first = chunker.feed(". How are you?")
    first.extend(chunker.flush())  # trailing mark needs end-of-stream confirmation
    assert [s.text for s in first] == ["Hello there.", "How are you?"]


def test_chunker_keeps_abbreviations_together():
    chunker = SentenceChunker()
    assert list(chunker.feed("Dr. Smith will see you")) == []
    out = chunker.feed(" soon. Okay.")
    out.extend(chunker.flush())
    assert [s.text for s in out] == ["Dr. Smith will see you soon.", "Okay."]


def test_chunker_handles_exclamation_and_question_marks():
    chunker = SentenceChunker()
    out = chunker.feed("Yes! Really? Done.")
    out.extend(chunker.flush())
    assert [s.text for s in out] == ["Yes!", "Really?", "Done."]


def test_chunker_flush_releases_partial_sentence():
    chunker = SentenceChunker()
    assert list(chunker.feed("A partial thought")) == []
    tail = chunker.flush()
    assert [s.text for s in tail] == ["A partial thought"]


def test_chunker_streams_in_order_with_indexes():
    chunker = SentenceChunker()
    out = []
    for piece in ["First one. Sec", "ond two. Third."]:
        out.extend(chunker.feed(piece))
    out.extend(chunker.flush())
    assert [s.index for s in out] == [0, 1, 2]
    assert [s.text for s in out] == ["First one.", "Second two.", "Third."]


def test_sentence_is_immutable_value():
    sentence = Sentence(index=3, text="Hello.")
    assert sentence.index == 3 and sentence.text == "Hello."


def test_queue_delivers_by_priority():
    order = []
    queue = SpeechQueue(sink=lambda req: order.append(req.text))
    queue.enqueue(SpeechRequest("background", SpeechPriority.BACKGROUND_STATUS))
    queue.enqueue(SpeechRequest("normal", SpeechPriority.NORMAL_QUEUE))
    queue.enqueue(SpeechRequest("urgent", SpeechPriority.INTERRUPT))

    queue.wait_until_idle(timeout=2)
    assert order == ["urgent", "normal", "background"]


def test_interrupt_preempts_current_narration(monkeypatch):
    seen = []
    release = threading.Event()
    queue = SpeechQueue(sink=lambda req: (seen.append(req.text), release.wait(2)))

    queue.enqueue(SpeechRequest("long narration", SpeechPriority.NORMAL_QUEUE))
    time.sleep(0.05)
    should_interrupt = queue.enqueue(SpeechRequest("Approval needed", SpeechPriority.INTERRUPT))
    assert should_interrupt is True

    release.set()
    queue.wait_until_idle(timeout=2)
    assert seen == ["long narration", "Approval needed"]


def test_second_interrupt_queues_instead_of_preempting_again():
    seen = []
    release = threading.Event()
    queue = SpeechQueue(sink=lambda req: (seen.append(req.text), release.wait(2)))

    queue.enqueue(SpeechRequest("first interrupt", SpeechPriority.INTERRUPT))
    time.sleep(0.05)
    should_interrupt = queue.enqueue(SpeechRequest("second interrupt", SpeechPriority.INTERRUPT))
    assert should_interrupt is False

    release.set()
    queue.wait_until_idle(timeout=2)
    assert seen == ["first interrupt", "second interrupt"]


def test_barge_in_drops_interruptible_queue_but_keeps_uninterruptible():
    seen = []
    release = threading.Event()
    queue = SpeechQueue(sink=lambda req: (seen.append(req.text), release.wait(2)))

    queue.enqueue(SpeechRequest("narration one", SpeechPriority.NORMAL_QUEUE))
    time.sleep(0.05)
    queue.enqueue(SpeechRequest("narration two", SpeechPriority.NORMAL_QUEUE))
    queue.enqueue(SpeechRequest("critical", SpeechPriority.INTERRUPT, interruptible=False))

    dropped = queue.clear_interruptible()
    assert dropped == 1  # the first narration is already being spoken

    release.set()
    queue.wait_until_idle(timeout=2)
    assert seen == ["narration one", "critical"]


def test_uninterruptible_current_is_not_cancelled_by_clear():
    seen = []
    release = threading.Event()
    queue = SpeechQueue(sink=lambda req: (seen.append(req.text), release.wait(2)))

    queue.enqueue(SpeechRequest("critical now", SpeechPriority.INTERRUPT, interruptible=False))
    time.sleep(0.05)
    queue.enqueue(SpeechRequest("narration", SpeechPriority.NORMAL_QUEUE))
    queue.clear_interruptible()

    release.set()
    queue.wait_until_idle(timeout=2)
    assert "critical now" in seen
    assert "narration" not in seen
