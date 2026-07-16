"""Forced alignment of subtitle text against the audio, and mapping the
aligned words back onto the original cues.

Two backends:
- "faster" (default when installed): faster-whisper / CTranslate2 with int8
  quantization — much faster and lighter on CPU, ideal for low-spec machines.
- "openai": the original openai-whisper implementation via torch.

The transcript fed to the aligner is built by joining every cue's tokens in
order, so the aligner's output words cover the same character stream. The
aligner may merge or split tokens differently than our whitespace split, so
the mapping walks both sequences by normalized-character consumption instead
of assuming 1:1 words.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
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
    last_end: float | None = None  # seconds: end of the cue's final aligned word


def pick_backend(requested: str = "auto") -> str:
    if requested in ("faster", "openai"):
        return requested
    try:
        import faster_whisper  # noqa: F401
        return "faster"
    except ImportError:
        return "openai"


def extract_audio(media_path: str) -> str:
    """Decode to 16 kHz mono wav ourselves so the aligner never touches the
    original container (whisper's internal ffmpeg piping is noisy and slower
    on big mkv files). Returns a temp file path the caller must delete."""
    fd, wav_path = tempfile.mkstemp(suffix=".wav", prefix="nospoil_")
    os.close(fd)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", media_path,
         "-vn", "-ac", "1", "-ar", "16000", wav_path],
        check=True,
    )
    return wav_path


def run_alignment(
    media_path: str,
    cues: list[Cue],
    language: str = "en",
    model_name: str = "base",
    device: str | None = None,
    backend: str = "auto",
) -> list[AlignedWord]:
    backend = pick_backend(backend)
    text = full_transcript(cues)

    wav_path = extract_audio(media_path)
    try:
        if backend == "faster":
            import stable_whisper

            # Default to CPU: CTranslate2's "auto" happily picks half-broken
            # CUDA setups (laptop GPUs without cuBLAS) and crashes. int8
            # quantization keeps CPU fast and memory low.
            dev = device or "cpu"
            model = stable_whisper.load_faster_whisper(
                model_name,
                device=dev,
                compute_type="int8" if dev == "cpu" else "default",
            )
        else:
            import stable_whisper

            model = stable_whisper.load_model(model_name, device=device)
        result = model.align(wav_path, text, language=language)
    finally:
        os.unlink(wav_path)

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
        last_end: float | None = None

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
                last_end = words[wi].end
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
                last_end=last_end,
            )
        )
    return timings
