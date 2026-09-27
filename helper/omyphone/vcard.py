"""Parse the vCard text that phones send over PBAP (Phone Book Access Profile).

We ask for vCard 3.0, but Android phones may still send 2.1 (with
quoted-printable names), so the parser is lenient: it never raises, skips what
it does not understand, and keeps only names, numbers, labels and call times.
Photos and emails are dropped.
"""
import calendar
import codecs
import quopri
import re
import time

_ESCAPES = {"\\": "\\", ",": ",", ";": ";", "n": "\n", "N": "\n"}
_COMPONENTS = re.compile(r"(?<!\\);")
DIRECTIONS = {"DIALED": "outgoing", "RECEIVED": "incoming", "MISSED": "missed"}
LABELS = (("CELL", "Mobile"), ("HOME", "Home"), ("WORK", "Work"))


def _unescape(value):
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(1)), value)


def _params(parts):
    """Param words, upper-cased: TYPE=CELL,VOICE and bare CELL;VOICE both give {CELL, VOICE}."""
    words = set()
    for part in parts:
        for word in part.rpartition("=")[2].split(","):
            if word.strip():
                words.add(word.strip().upper())
    return words


def _quoted_printable(head):
    return "QUOTED-PRINTABLE" in head.upper()


def _logical_lines(text):
    """Join folded lines: a line starting with a space or tab continues the one
    before, and so does any line after a quoted-printable line ending in "="."""
    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        last = lines[-1] if lines else None
        if last is not None and last.endswith("=") and ":" in last and _quoted_printable(last.split(":", 1)[0]):
            lines[-1] = last[:-1] + line  # soft line break: the next line is all value
        elif last is not None and line[:1] in (" ", "\t"):
            lines[-1] = last + line[1:]
        else:
            lines.append(line)
    return lines


def _charset(parts):
    for part in parts:
        key, _, value = part.partition("=")
        if key.strip().upper() == "CHARSET" and value.strip():
            try:
                return codecs.lookup(value.strip()).name
            except LookupError:
                break
    return "utf-8"


def _decode(parts, value):
    """The value of a vCard 2.1 quoted-printable property as text; others as they are."""
    if not any(_quoted_printable(part) for part in parts):
        return value
    return quopri.decodestring(value.encode("utf-8", "replace")).decode(_charset(parts), "replace")


def parse_cards(text):
    """Split vCard text into cards. Each card is a list of (NAME, param words, raw value)."""
    cards, current = [], None
    for line in _logical_lines(text):
        if ":" not in line:
            continue
        head, value = line.split(":", 1)
        parts = head.split(";")
        value = _decode(parts[1:], value)
        name = parts[0].rsplit(".", 1)[-1].strip().upper()  # "item1.TEL" -> "TEL"
        if name == "BEGIN" and value.strip().upper() == "VCARD":
            current = []
        elif name == "END" and value.strip().upper() == "VCARD":
            if current is not None:
                cards.append(current)
            current = None
        elif current is not None:
            current.append((name, _params(parts[1:]), value))
    return cards


def _raw(card, prop):
    return next((value for name, _params, value in card if name == prop), "")


def _first_component(value):
    return _unescape(_COMPONENTS.split(value)[0]).strip()


def _name(card):
    fn = _unescape(_raw(card, "FN")).strip()
    if fn:
        return fn
    parts = [_unescape(p).strip() for p in _COMPONENTS.split(_raw(card, "N"))]
    family, given = (parts + ["", ""])[:2]
    name = " ".join(p for p in (given, family) if p)
    return name or _first_component(_raw(card, "ORG"))


def _label(params):
    return next((label for word, label in LABELS if word in params), "")


def contacts_from_cards(cards):
    """Contacts with at least one number: {"name", "numbers": [{"number", "label"}]}.
    The name is empty when the card has none (no FN, N or ORG)."""
    result = []
    for card in cards:
        numbers = []
        for name, params, value in card:
            number = _unescape(value).strip()
            if name == "TEL" and number:
                numbers.append({"number": number, "label": _label(params)})
        if numbers:
            result.append({"name": _name(card), "numbers": numbers})
    return result


def parse_time(value):
    """X-IRMC-CALL-DATETIME value to epoch seconds: local time, or UTC with a trailing Z."""
    value = value.strip()
    try:
        parsed = time.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    return int(calendar.timegm(parsed) if value.endswith("Z") else time.mktime(parsed))


def history_from_cards(cards, default_direction=None):
    """Call-history entries, newest first: {"name", "number", "direction", "start"}."""
    entries = []
    for card in cards:
        stamp = next(((params, value) for name, params, value in card if name == "X-IRMC-CALL-DATETIME"), None)
        if stamp is None:
            continue
        params, value = stamp
        direction = next((DIRECTIONS[w] for w in params if w in DIRECTIONS), default_direction)
        start = parse_time(value)
        if direction is None or start is None:
            continue
        entries.append({"name": _name(card), "number": _unescape(_raw(card, "TEL")).strip(),
                        "direction": direction, "start": start})
    entries.sort(key=lambda e: e["start"], reverse=True)
    return entries
