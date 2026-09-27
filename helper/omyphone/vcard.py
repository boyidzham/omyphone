"""Parse the vCard text that phones send over PBAP (Phone Book Access Profile).

We ask for vCard 3.0, but Android phones may still send 2.1, so the parser is
lenient: it never raises, skips what it does not understand, and keeps only
names, numbers, labels and call times. Photos and emails are dropped.
"""
import calendar
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


def parse_cards(text):
    """Split vCard text into cards. Each card is a list of (NAME, param words, raw value)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n[ \t]", "", text)  # unfold continuation lines
    cards, current = [], None
    for line in text.split("\n"):
        if ":" not in line:
            continue
        head, value = line.split(":", 1)
        parts = head.split(";")
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
    """Contacts with at least one number: {"name", "numbers": [{"number", "label"}]}."""
    result = []
    for card in cards:
        numbers = []
        for name, params, value in card:
            number = _unescape(value).strip()
            if name == "TEL" and number:
                numbers.append({"number": number, "label": _label(params)})
        if numbers:
            result.append({"name": _name(card) or numbers[0]["number"], "numbers": numbers})
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
