# nospoil-subs

**Spoiler-free subtitles: words appear only as they're spoken.**

Normal subtitles show the whole line the moment it starts — so your eyes read
the punchline, the plot twist, the "I would do it again" a second before the
actor says it. `nospoil` takes your video and its existing `.srt` file,
force-aligns the subtitle text against the audio at word level (Whisper via
[stable-ts](https://github.com/jianfch/stable-ts)), and writes an `.ass`
subtitle file where each word becomes visible exactly when it's spoken.

![before/after demo](docs/demo.gif)

The output is a plain subtitle file. **No player plugins, no re-encoding** —
drop it into VLC (or anything using libass: mpv, Kodi, Jellyfin) like any
other subtitle track.

## How it works

- Your SRT's text is kept as the source of truth — nothing is re-transcribed,
  so human-made subtitles stay word-for-word intact.
- The text is force-aligned against the audio to get a timestamp per word.
- Each line is written with ASS karaoke `\ko` tags and a fully transparent
  secondary color: unspoken words are invisible but still occupy their space,
  so the line never shifts or reflows — words simply fade into existence
  on cue.
- Cues where alignment is unreliable (background music, overlapping dialogue)
  automatically fall back to normal line-level timing. Sound-effect cues like
  `[door slams]` are passed through untouched. **The result is never worse
  than the original subtitle.**

## Install

```bash
pip install stable-ts pysubs2
pip install .          # from a clone of this repo
```

Requires Python ≥ 3.9 and `ffmpeg` on your PATH. No GPU needed — alignment is
far cheaper than transcription and runs fine on CPU.

## Usage

```bash
nospoil movie.mkv movie.srt
# -> writes movie.nospoil.ass; load it in VLC via Subtitle > Add Subtitle File
```

Useful options:

| Flag | What it does |
|---|---|
| `--mode clause` | reveal 3–5 word chunks instead of single words (calmer on fast dialogue) |
| `--model small` | better alignment than the default `base` (slower) |
| `--min-prob 0.5` | stricter confidence: more cues fall back to normal timing |
| `--save-align w.json` / `--load-align w.json` | align once, re-style many times |
| `--font`, `--font-size` | output styling |

## Limitations (honest ones)

- **Subtitle language must match the audio language.** Word-level reveal is
  meaningless for translated subs — the words don't map 1:1 to the audio.
- This is a *mode*, not "better subtitles." Deaf/hard-of-hearing viewers
  usually want the full line early, because reading takes longer than
  listening. `nospoil` is for hearing viewers who use subs for clarity but
  keep getting jokes and twists spoiled.
- Very fast dialogue in `word` mode can feel strobe-y — try `--mode clause`.

## Development

```bash
python tests/test_core.py
```

MIT licensed.
