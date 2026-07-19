"""Generate the .ass file with the invisible-until-spoken effect.

Two transitions:

- "fade" (default): each word is fully transparent until its reveal time,
  then fades in over ~120 ms via an animated alpha transform
  ({\\alpha&HFF&\\t(t1,t2,\\alpha&H00&)}). Softer on the eyes than an
  instant pop — word-by-word reveal is otherwise distracting on fast
  dialogue.
- "pop": classic karaoke \\ko tags with a fully transparent secondary
  colour; words appear instantly. Slightly smaller files, and works on
  ancient VSFilter renderers that can't animate alpha.

In both cases the full line is laid out from the start (invisible words
still occupy their space), so the text never shifts or reflows.
"""

from __future__ import annotations

import subprocess

import pysubs2

from .align import CueTiming
from .srtprep import Cue

STYLE_NAME = "NoSpoil"

_CLAUSE_END = (",", ".", "?", "!", ";", ":", "—", "…")

# Reveal words slightly before they're spoken: the eye needs a moment, and
# it keeps tail words of fast lines from arriving too late to read.
DEFAULT_LEAD_MS = 150
# Extra lead for the final word/group of a line. Whisper's cross-attention
# gets diffuse at phrase boundaries (trailing music, phrase-final
# lengthening), so last-word timestamps skew late; compensate by revealing
# the tail earlier than the aligner claims.
DEFAULT_TAIL_LEAD_MS = 250
# No word may reveal later than this before its line disappears.
DEFAULT_MIN_SHOW_MS = 350
DEFAULT_FADE_MS = 120

# Subtle, screen-friendly faces in preference order; first installed wins.
PREFERRED_FONTS = [
    "Inter",
    "Open Sans",
    "Roboto",
    "Lato",
    "Source Sans 3",
    "Source Sans Pro",
    "Noto Sans",
    "Segoe UI",
    "Helvetica Neue",
    "DejaVu Sans",
    "Liberation Sans",
    "Arial",
]


def pick_font() -> str:
    """Best installed font from PREFERRED_FONTS (via fontconfig), else Arial."""
    try:
        out = subprocess.run(
            ["fc-list", ":", "family"], capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return "Arial"
    installed = {fam.strip().casefold() for line in out.splitlines()
                 for fam in line.split(",")}
    for name in PREFERRED_FONTS:
        if name.casefold() in installed:
            return name
    return "Arial"


def make_style(fontname: str = "embedded", fontsize: float = 50.0) -> pysubs2.SSAStyle:
    from .fontembed import BUNDLED_FONT_FAMILY

    style = pysubs2.SSAStyle()
    if fontname == "embedded":
        style.fontname = BUNDLED_FONT_FAMILY
    elif fontname == "auto":
        style.fontname = pick_font()
    else:
        style.fontname = fontname
    style.fontsize = fontsize
    # Soft off-white (Netflix-ish) reads calmer than pure white.
    style.primarycolor = pysubs2.Color(245, 245, 241, 0)
    # Fully transparent: with \ko this makes unspoken words invisible.
    style.secondarycolor = pysubs2.Color(0, 0, 0, 255)
    style.outlinecolor = pysubs2.Color(16, 16, 16, 0)
    style.backcolor = pysubs2.Color(0, 0, 0, 128)
    style.outline = 1.6
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


# Fast dialogue often outlives its SRT window: the cue ends while the last
# word is still being spoken, which used to push that word's reveal into the
# final milliseconds (effectively invisible). We extend the cue instead.
EXTEND_PAD_MS = 300
EXTEND_MAX_MS = 2000
EXTEND_GAP_MS = 50  # keep this much clearance before the next cue


def extended_end(cue: Cue, timing: CueTiming, next_start: int | None) -> int:
    if not timing.aligned or timing.last_end is None:
        return cue.end
    needed = int(timing.last_end * 1000) + EXTEND_PAD_MS
    if needed <= cue.end:
        return cue.end
    cap = cue.end + EXTEND_MAX_MS
    if next_start is not None:
        cap = min(cap, next_start - EXTEND_GAP_MS)
    return max(cue.end, min(needed, cap))


def reveal_times(cue: Cue, timing: CueTiming, duration: int,
                 mode: str, clause_size: int,
                 lead_ms: int, min_show_ms: int,
                 tail_lead_ms: int = DEFAULT_TAIL_LEAD_MS) -> list[int]:
    """Per-token reveal times in ms relative to cue start: clamped into the
    cue window, non-decreasing, pulled earlier by lead_ms (the line's final
    reveal earlier still by tail_lead_ms), and guaranteed at least
    min_show_ms of screen time before the line disappears."""
    reveals: list[int] = []
    prev = 0
    for s in timing.starts:
        ms = prev if s is None else int(s * 1000) - cue.start
        ms = max(prev, min(max(ms, 0), max(duration - 10, 0)))
        reveals.append(ms)
        prev = ms

    lead = max(lead_ms, 0)
    cap = max(duration - min_show_ms, 0)
    # Both ops preserve the non-decreasing order.
    reveals = [min(max(ms - lead, 0), cap) for ms in reveals]

    if mode == "clause":
        reveals = _group_reveals(cue, reveals, clause_size)

    # Pull the line's final reveal (the last word, or the whole trailing
    # group sharing its time) earlier by tail_lead_ms, never before the
    # preceding reveal.
    if reveals and tail_lead_ms > 0:
        last = reveals[-1]
        i = len(reveals) - 1
        while i > 0 and reveals[i - 1] == last:
            i -= 1
        floor = reveals[i - 1] if i > 0 else 0
        boosted = max(floor, last - tail_lead_ms, 0)
        for k in range(i, len(reveals)):
            reveals[k] = boosted
    return reveals


def _fade_text(cue: Cue, reveals: list[int], fade_ms: int) -> str:
    parts: list[str] = []
    i = 0
    for line in cue.lines:
        words = []
        for tok in line:
            r = reveals[i]
            if r <= 0:
                words.append("{\\alpha&HFF&\\t(0,%d,\\alpha&H00&)}%s" % (max(fade_ms, 1), tok))
            else:
                words.append("{\\alpha&HFF&\\t(%d,%d,\\alpha&H00&)}%s" % (r, r + fade_ms, tok))
            i += 1
        parts.append(" ".join(words))
    return "\\N".join(parts)


def _pop_text(cue: Cue, reveals: list[int], duration: int) -> str:
    reveals_cs = [round(ms / 10) for ms in reveals]
    total_cs = max(round(duration / 10), reveals_cs[-1] if reveals_cs else 0)

    head = "{\\ko%d}" % reveals_cs[0] if reveals_cs and reveals_cs[0] > 0 else ""
    i = 0
    parts: list[str] = []
    for line in cue.lines:
        words = []
        for tok in line:
            here = reveals_cs[i]
            nxt = reveals_cs[i + 1] if i + 1 < len(reveals_cs) else total_cs
            words.append("{\\ko%d}%s" % (max(nxt - here, 0), tok))
            i += 1
        parts.append(" ".join(words))
    return head + "\\N".join(parts)


def karaoke_text(cue: Cue, timing: CueTiming, mode: str = "word",
                 clause_size: int = 4, end: int | None = None,
                 transition: str = "fade", fade_ms: int = DEFAULT_FADE_MS,
                 lead_ms: int = DEFAULT_LEAD_MS,
                 min_show_ms: int = DEFAULT_MIN_SHOW_MS,
                 tail_lead_ms: int = DEFAULT_TAIL_LEAD_MS) -> str:
    """Build the ASS text for one cue."""
    duration = (end if end is not None else cue.end) - cue.start
    reveals = reveal_times(cue, timing, duration, mode, clause_size,
                           lead_ms, min_show_ms, tail_lead_ms)
    if transition == "pop":
        return _pop_text(cue, reveals, duration)
    return _fade_text(cue, reveals, fade_ms)


def build_ass(
    cues: list[Cue],
    timings: list[CueTiming],
    passthrough: list[pysubs2.SSAEvent],
    mode: str = "word",
    clause_size: int = 4,
    fontname: str = "embedded",
    fontsize: float = 50.0,
    transition: str = "fade",
    fade_ms: int = DEFAULT_FADE_MS,
    lead_ms: int = DEFAULT_LEAD_MS,
    min_show_ms: int = DEFAULT_MIN_SHOW_MS,
    tail_lead_ms: int = DEFAULT_TAIL_LEAD_MS,
) -> pysubs2.SSAFile:
    subs = pysubs2.SSAFile()
    subs.info["PlayResX"] = "1920"
    subs.info["PlayResY"] = "1080"
    subs.info["ScaledBorderAndShadow"] = "yes"
    subs.styles[STYLE_NAME] = make_style(fontname, fontsize)
    if fontname == "embedded":
        from .fontembed import attach_bundled_font

        attach_bundled_font(subs)

    for i, (cue, timing) in enumerate(zip(cues, timings)):
        next_start = cues[i + 1].start if i + 1 < len(cues) else None
        end = extended_end(cue, timing, next_start)
        ev = pysubs2.SSAEvent(start=cue.start, end=end, style=STYLE_NAME)
        if timing.aligned:
            ev.text = karaoke_text(cue, timing, mode=mode,
                                   clause_size=clause_size, end=end,
                                   transition=transition, fade_ms=fade_ms,
                                   lead_ms=lead_ms, min_show_ms=min_show_ms,
                                   tail_lead_ms=tail_lead_ms)
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
