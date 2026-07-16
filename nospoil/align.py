"""Forced alignment of subtitle text against the audio, and mapping the
aligned words back onto the original cues.

The transcript fed to the aligner is built by joining every cue's tokens in
order, so the aligner's output words cover the same character stream. The
aligner may merge or split tokens differently than our whitespace split, so
the mapping walks both sequences by normalized-character consumption instead
of assuming 1:1 words.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict

from .srtprep import Cue, full_transcript


@dataclass
class AlignedWord:
    text: str
    start: float  # seconds
    end: float  # seconds
    prob: float


@dataclass
class CueTiming:
    """Per-token reveal times for one cue. None entries inherit the previous
    token's time (pure-punctuation tokens, or tokens the mapping missed)."""

    starts: list[float | None]
    mean_prob: float
    aligned: bool  # False => render this cue as a plain line-level event


def run_alignment(
    media_path: str,
    cues: list[Cue],
    language: str = "en",
    model_name: str = "base",
    device: str | None = None,
) -> list[AlignedWord]:
    import stable_whisper

    model = stable_whisper.load_model(model_name, device=device)
    result = model.align(media_path, full_transcript(cues), language=language)
    words = []
    for w in result.all_words():
        words.append(
            AlignedWord(
                text=w.word.strip(),
                start=float(w.start),
                end=float(w.end),
                prob=float(w.probability),
            )
        )
    return words


def save_words(words: list[AlignedWord], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(w) for w in words], f, ensure_ascii=False, indent=1)


def load_words(path: str) -> list[AlignedWord]:
    with open(path, encoding="utf-8") as f:
        return [AlignedWord(**d) for d in json.load(f)]


def _norm(s: str) -> str:
    return "".join(ch for ch in s.casefold() if ch.isalnum())


def map_words_to_cues(
    cues: list[Cue],
    words: list[AlignedWord],
    min_prob: float = 0.35,
) -> list[CueTiming]:
    """Assign each cue token the start time of the aligned word that provides
    its first character. Cues whose alignment looks unreliable (low average
    probability, or tokens the word stream could not cover) are flagged
    aligned=False so the writer falls back to normal line-level timing."""
    timings: list[CueTiming] = []
    wi = 0  # index into words
    consumed = 0  # normalized chars already consumed from words[wi]

    for cue in cues:
        starts: list[float | None] = []
        probs: list[float] = []
        complete = True

        for tok in cue.tokens:
            need = len(_norm(tok))
            if need == 0:
                starts.append(None)
                continue
            first_start: float | None = None
            while need > 0 and wi < len(words):
                wnorm = _norm(words[wi].text)
                if not wnorm:
                    wi += 1
                    consumed = 0
                    continue
                if first_start is None:
                    first_start = words[wi].start
                    probs.append(words[wi].prob)
                take = min(len(wnorm) - consumed, need)
                need -= take
                consumed += take
                if consumed >= len(wnorm):
                    wi += 1
                    consumed = 0
            if first_start is None or need > 0:
                complete = False
            starts.append(first_start)

        mean_prob = sum(probs) / len(probs) if probs else 0.0
        timings.append(
            CueTiming(
                starts=starts,
                mean_prob=mean_prob,
                aligned=complete and mean_prob >= min_prob,
            )
        )
    return timings
