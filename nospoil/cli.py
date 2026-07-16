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
from .align import map_words_to_cues, pick_backend, run_alignment, save_words, load_words
from .assgen import build_ass


def find_srt(media_path: str) -> str | None:
    """Look for a subtitle file next to the video: same name first, then a
    lone .srt in the same folder."""
    stem = os.path.splitext(media_path)[0]
    for cand in (stem + ".srt", stem + ".en.srt", stem + ".eng.srt"):
        if os.path.isfile(cand):
            return cand
    folder = os.path.dirname(os.path.abspath(media_path))
    srts = [f for f in os.listdir(folder) if f.lower().endswith(".srt")]
    if len(srts) == 1:
        return os.path.join(folder, srts[0])
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="nospoil",
        description="Generate spoiler-free subtitles: words appear only as "
        "they are spoken. Output is a normal .ass file that VLC (libass) "
        "plays without any plugins.",
    )
    p.add_argument("media", help="video or audio file (audio is decoded via ffmpeg)")
    p.add_argument("srt", nargs="?",
                   help="matching subtitle file (.srt), same language as the audio "
                   "(default: auto-detected next to the video)")
    p.add_argument("-o", "--output", help="output .ass path (default: <srt>.nospoil.ass)")
    p.add_argument("--model", default="base",
                   help="whisper model for alignment: tiny/base/small/medium (default: base)")
    p.add_argument("--backend", choices=["auto", "faster", "openai"], default="auto",
                   help="alignment engine: faster-whisper (fast, low memory, great on "
                   "CPU) or openai-whisper (default: faster if installed)")
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

    if not args.srt:
        args.srt = find_srt(args.media)
        if not args.srt:
            print("error: no .srt found next to the video; pass it explicitly",
                  file=sys.stderr)
            return 1
        print(f"using subtitles: {args.srt}")

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
        backend = pick_backend(args.backend)
        print(f"aligning with {'faster-whisper' if backend == 'faster' else 'openai-whisper'} "
              f"'{args.model}' (this is the slow part; CPU is fine)...")
        t0 = time.time()
        words = run_alignment(args.media, cues, language=args.language,
                              model_name=args.model, device=args.device,
                              backend=backend)
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
