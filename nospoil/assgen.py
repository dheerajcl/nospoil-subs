"""Generate the .ass file with the invisible-until-spoken karaoke effect.

The trick: every dialogue line carries \\ko karaoke tags and the style's
SecondaryColour is fully transparent. \\ko (unlike plain \\k) also hides the
outline and shadow before a syllable's turn, so unspoken words are truly
invisible — but they still occupy layout space, so the line never reflows
when words appear.
"""

from __future__ import annotations

import pysubs2

from .align import CueTiming
from .srtprep import Cue

STYLE_NAME = "NoSpoil"

_CLAUSE_END = (",", ".", "?", "!", ";", ":", "—", "…")


def make_style(fontname: str = "Arial", fontsize: float = 60.0) -> pysubs2.SSAStyle:
    style = pysubs2.SSAStyle()
    style.fontname = fontname
    style.fontsize = fontsize
    style.primarycolor = pysubs2.Color(255, 255, 255, 0)
    # Fully transparent: with \ko this makes unspoken words invisible.
    style.secondarycolor = pysubs2.Color(0, 0, 0, 255)
    style.outlinecolor = pysubs2.Color(0, 0, 0, 0)
    style.backcolor = pysubs2.Color(0, 0, 0, 128)
    style.outline = 2.0
    # Shadow must stay off: libass's \ko hides the outline of unspoken
    # words but still draws their shadow, which would ghost the spoilers.
    style.shadow = 0.0
    style.bold = False
    style.marginv = 40
    style.alignment = pysubs2.Alignment.BOTTOM_CENTER
    return style


def _group_reveals(cue: Cue, reveals_ms: list[int], clause_size: int) -> list[int]:
    """Clause mode: words in the same group share the group's first reveal
    time. A group closes on strong punctuation or after clause_size words."""
    grouped = list(reveals_ms)
    tokens = cue.tokens
    i = 0
    while i < len(tokens):
        j = i
        while j < len(tokens) - 1 and (j - i + 1) < clause_size and not tokens[j].endswith(_CLAUSE_END):
            j += 1
        for k in range(i, j + 1):
            grouped[k] = reveals_ms[i]
        i = j + 1
    return grouped


def karaoke_text(cue: Cue, timing: CueTiming, mode: str = "word", clause_size: int = 4) -> str:
    """Build the ASS text for one cue: '{\\ko..}word {\\ko..}word ... \\N ...'"""
    duration = cue.end - cue.start

    # Token reveal times in ms relative to cue start, clamped into the cue
    # window and made non-decreasing. None inherits the previous token.
    reveals: list[int] = []
    prev = 0
    for s in timing.starts:
        ms = prev if s is None else int(s * 1000) - cue.start
        ms = max(prev, min(max(ms, 0), max(duration - 10, 0)))
        reveals.append(ms)
        prev = ms

    if mode == "clause":
        reveals = _group_reveals(cue, reveals, clause_size)

    # Cumulative centisecond rounding so errors don't drift.
    reveals_cs = [round(ms / 10) for ms in reveals]
    total_cs = max(round(duration / 10), reveals_cs[-1] if reveals_cs else 0)

    parts: list[str] = []
    if reveals_cs and reveals_cs[0] > 0:
        parts.append("{\\ko%d}" % reveals_cs[0])  # leading silent gap

    flat_idx = 0
    line_texts: list[str] = []
    for line in cue.lines:
        words: list[str] = []
        for tok in line:
            here = reveals_cs[flat_idx]
            nxt = reveals_cs[flat_idx + 1] if flat_idx + 1 < len(reveals_cs) else total_cs
            words.append("{\\ko%d}%s" % (max(nxt - here, 0), tok))
            flat_idx += 1
        line_texts.append(" ".join(words))
    text = "\\N".join(line_texts)

    if parts:
        return parts[0] + text
    return text


def build_ass(
    cues: list[Cue],
    timings: list[CueTiming],
    passthrough: list[pysubs2.SSAEvent],
    mode: str = "word",
    clause_size: int = 4,
    fontname: str = "Arial",
    fontsize: float = 60.0,
) -> pysubs2.SSAFile:
    subs = pysubs2.SSAFile()
    subs.info["PlayResX"] = "1920"
    subs.info["PlayResY"] = "1080"
    subs.info["ScaledBorderAndShadow"] = "yes"
    subs.styles[STYLE_NAME] = make_style(fontname, fontsize)

    for cue, timing in zip(cues, timings):
        ev = pysubs2.SSAEvent(start=cue.start, end=cue.end, style=STYLE_NAME)
        if timing.aligned:
            ev.text = karaoke_text(cue, timing, mode=mode, clause_size=clause_size)
        else:
            # Never worse than the original: plain line-level cue.
            ev.text = cue.original_text.replace("\n", "\\N")
        subs.events.append(ev)

    for src in passthrough:
        ev = pysubs2.SSAEvent(start=src.start, end=src.end, style=STYLE_NAME)
        ev.text = src.plaintext.strip().replace("\n", "\\N")
        subs.events.append(ev)

    subs.sort()
    return subs
