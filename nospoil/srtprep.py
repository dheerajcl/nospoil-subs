"""Load an SRT and prepare cues for word-level alignment.

Hearing-impaired annotations ([door slams], (SIGHS)), music markers and
speaker labels have no spoken words behind them, so they are stripped from
the text that gets aligned. Cues left with no speech at all are kept as
plain (non-karaoke) events so the output is never worse than the input.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pysubs2

_BRACKETS = re.compile(r"\[[^\]]*\]|\([^)]*\)|\{[^}]*\}")
_MUSIC = re.compile(r"[♪♫♩♬]+")
_SPEAKER = re.compile(r"^[A-Z][A-Z0-9 .'\-]{0,24}:\s*", re.MULTILINE)
_DASH = re.compile(r"^-+\s*", re.MULTILINE)
_SPACES = re.compile(r"[ \t]+")


@dataclass
class Cue:
    start: int  # ms
    end: int  # ms
    lines: list[list[str]] = field(default_factory=list)  # display tokens per line
    original_text: str = ""  # cleaned plaintext, used when alignment falls back

    @property
    def tokens(self) -> list[str]:
        return [tok for line in self.lines for tok in line]

    @property
    def has_speech(self) -> bool:
        return bool(self.tokens)


def clean_text(text: str) -> str:
    """Strip non-speech markup from a cue's plaintext ('\n' line breaks)."""
    t = _BRACKETS.sub(" ", text)
    t = _MUSIC.sub(" ", t)
    t = _SPEAKER.sub("", t)
    t = _DASH.sub("", t)
    lines = [_SPACES.sub(" ", ln).strip() for ln in t.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def load_cues(srt_path: str) -> tuple[list[Cue], list[pysubs2.SSAEvent]]:
    """Return (speech cues to align, non-speech events to pass through)."""
    try:
        subs = pysubs2.load(srt_path, encoding="utf-8")
    except UnicodeDecodeError:
        subs = pysubs2.load(srt_path, encoding="cp1252")

    cues: list[Cue] = []
    passthrough: list[pysubs2.SSAEvent] = []
    for ev in subs:
        if ev.is_comment or not ev.plaintext.strip():
            continue
        cleaned = clean_text(ev.plaintext)
        if not cleaned:
            # Pure sound-effect / music cue: keep it, timed as-is.
            passthrough.append(ev)
            continue
        lines = [ln.split(" ") for ln in cleaned.split("\n")]
        cues.append(
            Cue(start=ev.start, end=ev.end, lines=lines, original_text=cleaned)
        )
    return cues, passthrough


def full_transcript(cues: list[Cue]) -> str:
    """The exact text that gets force-aligned against the audio."""
    return " ".join(tok for cue in cues for tok in cue.tokens)
