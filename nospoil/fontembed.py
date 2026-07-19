"""Embed the bundled font directly inside the .ass file.

ASS files can carry font attachments in a [Fonts] section, encoded with a
uuencode variant (6 bits per char, offset 33, 80-char lines). libass — the
renderer inside VLC, mpv, Kodi, Jellyfin — loads these automatically, so the
subtitles look identical on every machine regardless of installed fonts.

The bundled face is Inter Regular (SIL Open Font License, see
fonts/LICENSE-Inter.txt).
"""

from __future__ import annotations

import importlib.resources

BUNDLED_FONT_FAMILY = "Inter"
_FONT_RESOURCE = "Inter-Regular.otf"
# VSFilter naming convention: <name>_<bold><italic>.<ext>; 0 = regular.
ATTACHMENT_NAME = "Inter-Regular_0.otf"


def ass_uuencode(data: bytes) -> list[str]:
    """ASS attachment encoding: 3 bytes -> 4 chars of (6 bits + 33).
    A 2-byte tail becomes 3 chars, a 1-byte tail 2 chars. 80-char lines."""
    chars: list[str] = []
    full = len(data) - len(data) % 3
    for i in range(0, full, 3):
        v = (data[i] << 16) | (data[i + 1] << 8) | data[i + 2]
        chars.append(chr(((v >> 18) & 0x3F) + 33))
        chars.append(chr(((v >> 12) & 0x3F) + 33))
        chars.append(chr(((v >> 6) & 0x3F) + 33))
        chars.append(chr((v & 0x3F) + 33))
    tail = data[full:]
    if len(tail) == 1:
        v = tail[0] << 16
        chars.append(chr(((v >> 18) & 0x3F) + 33))
        chars.append(chr(((v >> 12) & 0x3F) + 33))
    elif len(tail) == 2:
        v = (tail[0] << 16) | (tail[1] << 8)
        chars.append(chr(((v >> 18) & 0x3F) + 33))
        chars.append(chr(((v >> 12) & 0x3F) + 33))
        chars.append(chr(((v >> 6) & 0x3F) + 33))
    joined = "".join(chars)
    return [joined[i:i + 80] for i in range(0, len(joined), 80)]


def bundled_font_data() -> bytes:
    ref = importlib.resources.files("nospoil") / "fonts" / _FONT_RESOURCE
    return ref.read_bytes()


def attach_bundled_font(subs) -> None:
    """Add the bundled font to a pysubs2 SSAFile's [Fonts] section."""
    subs.fonts_opaque[ATTACHMENT_NAME] = ass_uuencode(bundled_font_data())
