"""Unit tests for the pieces that don't need audio or a model."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nospoil.srtprep import Cue, clean_text, load_cues, full_transcript
from nospoil.align import AlignedWord, map_words_to_cues
from nospoil.assgen import build_ass, karaoke_text


SAMPLE_SRT = """\
1
00:00:01,000 --> 00:00:03,000
- [door slams]
- Who's there?

2
00:00:04,000 --> 00:00:07,500
JOHN: I killed the butler,
and I'd do it again.

3
00:00:08,000 --> 00:00:09,000
[dramatic music]

4
00:00:10,000 --> 00:00:12,000
♪ la la la ♪
"""


def make_srt(tmpdir):
    path = os.path.join(tmpdir, "sample.srt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(SAMPLE_SRT)
    return path


def test_clean_text():
    assert clean_text("[door slams]\n- Who's there?") == "Who's there?"
    assert clean_text("JOHN: I killed the butler,\nand I'd do it again.") == \
        "I killed the butler,\nand I'd do it again."
    assert clean_text("[dramatic music]") == ""
    assert clean_text("♪ la la la ♪") == "la la la"


def test_load_cues():
    with tempfile.TemporaryDirectory() as d:
        cues, passthrough = load_cues(make_srt(d))
    # cue 3 is pure sound effect -> passthrough; cues 1, 2, 4 have words
    assert len(cues) == 3
    assert len(passthrough) == 1
    assert cues[0].tokens == ["Who's", "there?"]
    assert cues[1].lines == [["I", "killed", "the", "butler,"],
                             ["and", "I'd", "do", "it", "again."]]
    assert full_transcript(cues[:2]) == \
        "Who's there? I killed the butler, and I'd do it again."


def _words(spec):
    """spec: list of (text, start_sec) with prob 0.9, end = start + 0.2"""
    return [AlignedWord(text=t, start=s, end=s + 0.2, prob=0.9) for t, s in spec]


def test_mapping_one_to_one():
    cues = [Cue(start=1000, end=3000, lines=[["Who's", "there?"]])]
    words = _words([("Who's", 1.2), ("there?", 1.8)])
    (t,) = map_words_to_cues(cues, words)
    assert t.aligned
    assert t.starts == [1.2, 1.8]


def test_mapping_split_and_merge():
    # aligner split "butler," into "but" + "ler," and merged "do it"
    cues = [Cue(start=0, end=5000,
                lines=[["the", "butler,", "do", "it"]])]
    words = _words([("the", 0.5), ("but", 1.0), ("ler,", 1.3), ("do it", 2.0)])
    (t,) = map_words_to_cues(cues, words)
    assert t.aligned
    assert t.starts == [0.5, 1.0, 2.0, 2.0]


def test_low_confidence_falls_back():
    cues = [Cue(start=0, end=2000, lines=[["mumble", "mumble"]])]
    words = [AlignedWord("mumble", 0.1, 0.3, 0.05),
             AlignedWord("mumble", 0.5, 0.7, 0.05)]
    (t,) = map_words_to_cues(cues, words, min_prob=0.35)
    assert not t.aligned


def test_missing_words_falls_back():
    cues = [Cue(start=0, end=2000, lines=[["hello", "world"]])]
    words = _words([("hello", 0.2)])  # aligner ran out
    (t,) = map_words_to_cues(cues, words)
    assert not t.aligned


def test_karaoke_text():
    cue = Cue(start=1000, end=4000, lines=[["Who's", "there?"]])
    from nospoil.align import CueTiming
    timing = CueTiming(starts=[1.5, 2.5], mean_prob=0.9, aligned=True)
    text = karaoke_text(cue, timing)
    # 500ms lead gap = 50cs, first word lasts 100cs until second reveals,
    # last word runs to the cue end (300cs total - 150cs reveal)
    assert text == "{\\ko50}{\\ko100}Who's {\\ko150}there?"


def test_karaoke_clause_mode():
    cue = Cue(start=0, end=4000,
              lines=[["I", "killed", "the", "butler,", "and", "more"]])
    from nospoil.align import CueTiming
    timing = CueTiming(starts=[0.1, 0.4, 0.7, 1.0, 2.0, 2.4],
                       mean_prob=0.9, aligned=True)
    text = karaoke_text(cue, timing, mode="clause", clause_size=4)
    # first clause ends at "butler," (punctuation) -> all 4 reveal at 10cs,
    # second clause reveals at 200cs
    assert text == ("{\\ko10}{\\ko0}I {\\ko0}killed {\\ko0}the "
                    "{\\ko190}butler, {\\ko0}and {\\ko200}more")


def test_build_ass_end_to_end():
    with tempfile.TemporaryDirectory() as d:
        cues, passthrough = load_cues(make_srt(d))
        words = _words([
            ("Who's", 1.2), ("there?", 1.8),
            ("I", 4.1), ("killed", 4.3), ("the", 4.8), ("butler,", 5.0),
            ("and", 5.8), ("I'd", 6.0), ("do", 6.3), ("it", 6.5), ("again.", 6.8),
            ("la", 10.2), ("la", 10.5), ("la", 10.8),
        ])
        timings = map_words_to_cues(cues, words)
        assert all(t.aligned for t in timings)
        subs = build_ass(cues, timings, passthrough)
        out = os.path.join(d, "out.ass")
        subs.save(out)
        with open(out, encoding="utf-8") as f:
            content = f.read()
    assert "\\ko" in content
    # transparent secondary colour is the core of the invisibility trick
    assert "&HFF000000" in content
    # passthrough sound-effect cue survives untouched
    assert "dramatic music" in content
    # line break preserved inside the karaoke cue
    assert "butler, \\N" in content or "butler,\\N" in content


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
