"""nospoil command line interface.

    nospoil movie.mkv movie.srt -o movie.nospoil.ass
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from . import __version__
from .srtprep import load_cues
from .align import map_words_to_cues, run_alignment, save_words, load_words
from .assgen import build_ass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="nospoil",
        description="Generate spoiler-free subtitles: words appear only as "
        "they are spoken. Output is a normal .ass file that VLC (libass) "
        "plays without any plugins.",
    )
    p.add_argument("media", help="video or audio file (audio is decoded via ffmpeg)")
    p.add_argument("srt", help="matching subtitle file (.srt), same language as the audio")
    p.add_argument("-o", "--output", help="output .ass path (default: <srt>.nospoil.ass)")
    p.add_argument("--model", default="base",
                   help="whisper model for alignment: tiny/base/small/medium (default: base)")
    p.add_argument("--language", default="en", help="audio language code (default: en)")
    p.add_argument("--device", default=None, help="torch device, e.g. cpu or cuda (default: auto)")
    p.add_argument("--mode", choices=["word", "clause"], default="word",
                   help="reveal word-by-word, or in small clauses (less strobe-y on fast dialogue)")
    p.add_argument("--clause-size", type=int, default=4,
                   help="max words per reveal group in clause mode (default: 4)")
    p.add_argument("--min-prob", type=float, default=0.35,
                   help="below this mean alignment confidence a cue falls back to "
                   "normal line-level timing (default: 0.35)")
    p.add_argument("--font", default="Arial", help="subtitle font (default: Arial)")
    p.add_argument("--font-size", type=float, default=60.0, help="font size at 1080p (default: 60)")
    p.add_argument("--save-align", metavar="JSON",
                   help="save word timings to JSON (re-style later without re-aligning)")
    p.add_argument("--load-align", metavar="JSON",
                   help="reuse word timings from a previous --save-align run")
    p.add_argument("--version", action="version", version=f"nospoil-subs {__version__}")
    args = p.parse_args(argv)

    out_path = args.output or os.path.splitext(args.srt)[0] + ".nospoil.ass"

    cues, passthrough = load_cues(args.srt)
    if not cues:
        print("error: no speech cues found in the SRT", file=sys.stderr)
        return 1
    print(f"loaded {len(cues)} speech cues "
          f"(+{len(passthrough)} sound-effect cues passed through)")

    if args.load_align:
        words = load_words(args.load_align)
        print(f"loaded {len(words)} word timings from {args.load_align}")
    else:
        print(f"aligning against audio with whisper '{args.model}' "
              f"(this is the slow part; CPU is fine)...")
        t0 = time.time()
        words = run_alignment(args.media, cues, language=args.language,
                              model_name=args.model, device=args.device)
        print(f"aligned {len(words)} words in {time.time() - t0:.0f}s")

    if args.save_align:
        save_words(words, args.save_align)
        print(f"saved word timings to {args.save_align}")

    timings = map_words_to_cues(cues, words, min_prob=args.min_prob)
    fallbacks = sum(1 for t in timings if not t.aligned)
    if fallbacks:
        print(f"{fallbacks}/{len(timings)} cues had unreliable alignment and "
              f"keep normal line-level timing")

    subs = build_ass(cues, timings, passthrough, mode=args.mode,
                     clause_size=args.clause_size,
                     fontname=args.font, fontsize=args.font_size)
    subs.save(out_path)
    print(f"wrote {out_path}")
    print("open your video in VLC and load this file "
          "(Subtitle > Add Subtitle File)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
