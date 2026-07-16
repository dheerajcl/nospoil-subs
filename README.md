# nospoil-subs

**Spoiler-free subtitles: words appear on screen only as they're spoken.**

Normal subtitles show the whole line the moment it starts, so your eyes read
the punchline, the confession, the plot twist a second before the actor
delivers it. `nospoil` takes a video and its existing `.srt` file and writes
an `.ass` subtitle file where each word becomes visible at the exact moment
it's spoken — and the line never shifts or reflows while doing it.

![before/after demo](docs/demo.gif)

The output is an ordinary subtitle file. **No player plugins, no
re-encoding.** Load it in VLC, mpv, Kodi, Jellyfin, or anything else that
renders subtitles with libass.

```bash
nospoil movie.mkv
# auto-finds movie.srt next to the video, writes movie.nospoil.ass
# VLC: Subtitle > Add Subtitle File
```

## How it works

1. **Your SRT stays the source of truth.** Nothing is re-transcribed. The
   subtitle text is cleaned of non-speech markup (`[door slams]`,
   `♪ lyrics ♪`, `JOHN:` speaker labels) and force-aligned against the
   audio using Whisper in alignment mode ([stable-ts](https://github.com/jianfch/stable-ts)
   on [faster-whisper](https://github.com/SYSTRAN/faster-whisper)):
   the model is given both the audio and the exact text, and only has to
   answer *when* each word is spoken. That's ~10× cheaper than
   transcription and can't misquote your subtitles.
2. **Words are mapped back to their cues** by walking the aligned word
   stream and the SRT tokens together character-by-character, so it doesn't
   matter if the aligner splits or merges words differently than the SRT.
3. **Each line is written with ASS karaoke `\ko` tags** and a fully
   transparent secondary color. `\ko` hides a word's fill *and outline*
   until its timestamp, so unspoken words are invisible — but they still
   occupy their space, which is why the line never jumps. (Shadow is forced
   to 0 in the style: libass draws shadows of unspoken `\ko` words, which
   would ghost the spoilers back onto the screen.)

### Never worse than the original

- Cues whose alignment is unreliable — background music, overlapping
  dialogue, whispers — automatically fall back to normal full-line timing.
  On a real 55-minute TV episode this was 44 of 767 cues (~6%).
- Sound-effect-only cues like `[door slams]` pass through untouched.
- When fast dialogue outlives its subtitle window, the cue is extended
  (up to 2 s, never into the next cue) so the last words of a line stay
  readable instead of being cut off.

## Install

Not on PyPI yet — install from a clone:

```bash
git clone https://github.com/<you>/nospoil-subs
cd nospoil-subs
pip install .
```

Requirements: Python ≥ 3.9 and `ffmpeg` on your PATH. **No GPU needed.**

## Usage

```bash
nospoil movie.mkv                 # auto-detects the .srt next to the video
nospoil movie.mkv subs.srt        # or name it explicitly
nospoil movie.mkv -o out.ass --mode clause
```

| Flag | What it does |
|---|---|
| `--mode clause` | reveal 3–5 word chunks instead of single words (calmer on fast dialogue) |
| `--clause-size N` | max words per reveal group in clause mode (default 4) |
| `--model small` | better alignment than the default `base` (slower) |
| `--backend openai` | use openai-whisper instead of the default faster-whisper |
| `--language xx` | audio language code (default `en`) |
| `--device cuda` | use a GPU (default is CPU — see below) |
| `--min-prob 0.5` | stricter confidence: more cues fall back to normal timing |
| `--save-align w.json` / `--load-align w.json` | align once, regenerate styles instantly |
| `--font`, `--font-size` | output styling |

## Performance

Word-level *alignment* is far lighter than transcription. Measured on a
laptop CPU (i5-1135G7, 8 threads), aligning a 3.3-minute dialogue clip:

| Backend | Model | Wall time | Peak RAM |
|---|---|---|---|
| faster-whisper int8 (default) | base | 6 s (~32× realtime) | ~0.75 GB |
| openai-whisper | base | 10 s (~20× realtime) | ~0.95 GB |

In practice a full 55-minute episode (767 cues, 5 500 words) aligns in a
few minutes on the same laptop. The first run additionally downloads the
model (~75 MB for `base`).

Timing quality is the same on both backends: comparing word-by-word across
396 words, the median start-time difference was 0 ms (p95: 120 ms).

### Why CPU is the default

CTranslate2's GPU auto-detection happily selects laptop GPUs with
incomplete CUDA setups and crashes on a missing `libcublas`. Alignment is
fast enough on CPU that the safe default wins; pass `--device cuda` if you
have a working CUDA stack.

## Limitations (honest ones)

- **The subtitle language must match the audio language.** Word-level
  reveal is meaningless for translated subs — the words don't map 1:1 to
  the audio.
- **This is a mode, not "better subtitles."** Deaf and hard-of-hearing
  viewers usually want the full line early, because reading takes longer
  than listening. `nospoil` is for hearing viewers who use subtitles for
  clarity but keep getting jokes and twists spoiled.
- Very fast dialogue in `word` mode can feel strobe-y — try
  `--mode clause`.
- Songs, heavy score, and overlapping speakers reduce alignment confidence;
  those cues silently keep their original timing (by design).

## Development

```bash
python tests/test_core.py   # pure-logic tests, no model/audio needed
```

Project layout: `srtprep.py` (SRT loading and cleanup) → `align.py`
(forced alignment + word-to-cue mapping) → `assgen.py` (karaoke `.ass`
writer) → `cli.py`.

## License

MIT
