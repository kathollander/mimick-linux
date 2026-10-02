"""When each word is spoken, from a Piper voice model itself.

``estimate_marks`` guesses: it spreads a sentence's duration over its words by
their length in letters, and is out by up to a quarter of a second after a
pause. A Piper model already knows better -- it decides how many audio frames
every phoneme lasts, and only throws that away because nobody marked it as an
output. piper-tts ships a patch that does (``piper.patch_voice_with_alignment``)
but it needs the ``onnx`` package; ``patch_for_alignment`` makes the same change
to the model's bytes directly, so nothing new has to be installed and the file
on disk is never altered.

From there it is bookkeeping: phoneme ids to sample counts, phonemes to the
spoken groups espeak separates with spaces, and groups to the words of the
text -- which is the one part that takes judgement, because espeak runs "of
the" together and spreads "1,204" over four groups. See ``align_words``.

The browser version has the same code in ``mimick-web/js/timing.js``. Change
this one first and port it across.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

# Stress marks and punctuation take ids but are not sounds to count.
_NOT_A_SOUND = re.compile(r"^[ˈˌ.,;:!?¡¿—…\"«»“”()\-]$")


# -- the model patch -----------------------------------------------------------

# Just enough protobuf to find one field and append to another. ONNX model files
# are protobuf: ModelProto.graph is field 7; in the graph, nodes are field 1 and
# outputs field 12; in a node, outputs are field 2 and the operator field 4; a
# ValueInfoProto's name is field 1.

def _read_varint(data: bytes, at: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        byte = data[at]
        at += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return value, at


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _fields(data: bytes, start: int, end: int):
    """Yield (field, tag_at, body_start, body_end) for each length-delimited
    field in data[start:end], skipping everything else."""
    at = start
    while at < end:
        tag_at = at
        tag, at = _read_varint(data, at)
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            _, at = _read_varint(data, at)
        elif wire == 1:
            at += 8
        elif wire == 5:
            at += 4
        elif wire == 2:
            length, at = _read_varint(data, at)
            yield field, tag_at, at, at + length
            at += length
        else:
            raise ValueError(f"unexpected protobuf wire type {wire}")


def patch_for_alignment(model: bytes) -> tuple[bytes, str | None]:
    """The model with its phoneme durations exposed as a second output, and the
    name of that output.

    Returns the model unchanged, with the name ``None``, if it has no single
    Ceil node to expose -- timing then falls back to estimates.
    """
    graph = None
    for field, tag_at, start, end in _fields(model, 0, len(model)):
        if field == 7:
            graph = (tag_at, start, end)
    if graph is None:
        return model, None
    graph_tag_at, graph_start, graph_end = graph

    ceil: set[str] = set()
    outputs: set[str] = set()
    for field, _, start, end in _fields(model, graph_start, graph_end):
        if field == 1:
            op, produced = "", []
            for f, _, s, e in _fields(model, start, end):
                if f == 2:
                    produced.append(model[s:e].decode("utf-8"))
                elif f == 4:
                    op = model[s:e].decode("utf-8")
            if op == "Ceil":
                ceil.update(produced)
        elif field == 12:
            for f, _, s, e in _fields(model, start, end):
                if f == 1:
                    outputs.add(model[s:e].decode("utf-8"))
    if len(ceil) != 1:
        return model, None
    name = next(iter(ceil))
    if name in outputs:
        return model, name                          # already patched

    name_bytes = name.encode("utf-8")
    value_info = b"\x0a" + _varint(len(name_bytes)) + name_bytes
    addition = b"\x62" + _varint(len(value_info)) + value_info
    header = b"\x3a" + _varint(graph_end - graph_start + len(addition))
    patched = b"".join((model[:graph_tag_at], header, model[graph_start:graph_end],
                        addition, model[graph_end:]))
    return patched, name


# -- phonemes to spoken groups -------------------------------------------------

@dataclass
class Group:
    """One run of phonemes espeak put between spaces, in samples."""

    start: int
    end: int
    phonemes: int = 0


def spoken_groups(ids: list[int], phonemes: list[str], samples_per_id: list[int],
                  id_map: dict[str, list[int]], offset: int = 0) -> list[Group] | None:
    """Lay the phonemizer's phonemes and ids beside the model's samples per id,
    and cut at every space and sentence break.

    Ids run ``^ _ (p _)* $``, where ``_`` is padding. A phoneme missing from the
    voice's map has no id, so ids are matched to phonemes by looking each
    phoneme up rather than by counting. ``offset`` is added to every position,
    for a sentence espeak split into several.

    Returns ``None`` when the ids do not line up with the phonemes -- never a
    guess dressed as a fact.
    """
    if len(samples_per_id) != len(ids):
        return None
    pad = (id_map.get("_") or [0])[0]
    bos = (id_map.get("^") or [1])[0]
    eos = (id_map.get("$") or [2])[0]
    space = (id_map.get(" ") or [3])[0]

    offsets = [offset]
    for count in samples_per_id:
        offsets.append(offsets[-1] + int(count))

    groups: list[Group] = []
    current: Group | None = None
    following = 0
    for i, id_ in enumerate(ids):
        if id_ == pad:
            if current:
                current.end = offsets[i + 1]
            continue
        if id_ in (bos, eos, space):
            if id_ == space:
                # The space is itself a phoneme; step past it, and past anything
                # unmapped before it.
                while following < len(phonemes) and phonemes[following] != " ":
                    following += 1
                if following >= len(phonemes):
                    return None
                following += 1
            if current and current.phonemes:
                groups.append(current)
            current = None
            continue
        # A spoken phoneme: find it, skipping any the map had no id for.
        while following < len(phonemes) and id_ not in id_map.get(phonemes[following], ()):
            if phonemes[following] == " ":
                return None
            following += 1
        if following >= len(phonemes):
            return None
        following += 1
        if current is None:
            current = Group(start=offsets[i], end=offsets[i + 1])
        current.end = offsets[i + 1]
        if not _NOT_A_SOUND.match(phonemes[following - 1]):
            current.phonemes += 1
    if current and current.phonemes:
        groups.append(current)
    return groups


# -- groups to the words of the text -------------------------------------------

def _sound_count(phonemes: list[str]) -> int:
    return sum(1 for p in phonemes if p != " " and not _NOT_A_SOUND.match(p))


def _group_count(phonemes: list[str]) -> int:
    joined = "".join(phonemes).strip()
    return len(joined.split()) if joined and _sound_count(phonemes) else 0


def align_words(words: list[str], alone: list[list[str]],
                groups: list[Group]) -> list[int] | None:
    """Match the words of the text, in order, to the spoken groups.

    ``alone`` is each word phonemized on its own: how many sounds it has, and
    how many groups it makes by itself ("1,204" makes four). In the sentence,
    espeak may still join two words into one group ("of the"), so this is a
    shortest path over (words used, groups used), where a step is one word
    taking one or more groups, several words sharing one group, or a word with
    no sound (a dash) taking none. A step costs how far its sound counts
    disagree, and extra when it goes against what the word did alone.

    Returns the start of each word in samples, or ``None`` if no path exists.
    """
    W, G = len(words), len(groups)
    inf = math.inf
    cost = [[inf] * (G + 1) for _ in range(W + 1)]
    step: list[list[tuple[int, int, str] | None]] = [[None] * (G + 1) for _ in range(W + 1)]
    cost[0][0] = 0.0
    sounds = [_sound_count(p) for p in alone]
    expect = [_group_count(p) for p in alone]

    def mismatch(a: int, b: int) -> float:
        return abs(math.log((a + 1) / (b + 1)))

    for w in range(W + 1):
        for g in range(G + 1):
            here = cost[w][g]
            if here == inf:
                continue

            def relax(w2: int, g2: int, c: float, kind: str) -> None:
                if here + c < cost[w2][g2]:
                    cost[w2][g2] = here + c
                    step[w2][g2] = (w, g, kind)

            if w < W and expect[w] == 0:
                relax(w + 1, g, 0.0, "silent")
            if w < W and expect[w] > 0:
                have = 0
                for m in range(1, 7):
                    if g + m > G:
                        break
                    have += groups[g + m - 1].phonemes
                    relax(w + 1, g + m, mismatch(sounds[w], have) + 0.7 * abs(m - expect[w]), "word")
            if g < G:
                want = count = 0
                for n in range(1, 5):
                    if w + n > W or expect[w + n - 1] == 0:
                        break
                    want += sounds[w + n - 1]
                    count += expect[w + n - 1]
                    if n >= 2:
                        relax(w + n, g + 1, mismatch(want, groups[g].phonemes) + 0.5 * (count - 1),
                              "shared")
    if cost[W][G] == inf:
        return None

    starts: list[int | None] = [None] * W
    w, g = W, G
    while w > 0 or g > 0:
        w0, g0, kind = step[w][g]
        if kind == "word":
            starts[w0] = groups[g0].start
        elif kind == "shared":
            # Several words in one group: split its sound by their sound counts.
            group = groups[g0]
            total = sum(sounds[w0:w]) or 1
            done = 0
            for i in range(w0, w):
                starts[i] = round(group.start + (group.end - group.start) * done / total)
                done += sounds[i]
        w, g = w0, g0
    # A word with no sound starts where the next sounded word does.
    following = groups[-1].end if groups else 0
    for i in range(W - 1, -1, -1):
        if starts[i] is None:
            starts[i] = following
        else:
            following = starts[i]
    return starts  # type: ignore[return-value]
