"""JSON-lines protocol between Service.qml and the helper.

Commands arrive one JSON object per line on stdin; events leave the same way on
stdout. parse_command validates everything, because the values end up in D-Bus
calls.
"""
import json
import re

NUMBER_RE = re.compile(r"\+?[0-9*#]{1,32}")
TONES_RE = re.compile(r"[0-9*#ABCD]{1,32}")
CALL_RE = re.compile(r"/org/pipewire/Telephony/ag[0-9]+/call[0-9]+")
# Matched with fullmatch: "$" would also accept a trailing newline.
_FORMATTING = str.maketrans("", "", " -()")


class ProtocolError(ValueError):
    def __init__(self, cmd, message):
        super().__init__(message)
        self.cmd = cmd


def parse_command(line):
    """Return a validated command dict, or raise ProtocolError."""
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        raise ProtocolError("", "invalid JSON") from None
    if not isinstance(msg, dict) or not isinstance(msg.get("cmd"), str):
        raise ProtocolError("", "missing cmd")
    cmd = msg["cmd"]
    if cmd == "dial":
        number = msg.get("number")
        number = number.translate(_FORMATTING) if isinstance(number, str) else ""
        if not NUMBER_RE.fullmatch(number):
            raise ProtocolError(cmd, "invalid number")
        return {"cmd": cmd, "number": number}
    if cmd in ("answer", "hangup", "decline"):
        call = msg.get("call")
        if not isinstance(call, str) or not CALL_RE.fullmatch(call):
            raise ProtocolError(cmd, "invalid call path")
        return {"cmd": cmd, "call": call}
    if cmd == "tones":
        digits = msg.get("digits")
        if not isinstance(digits, str) or not TONES_RE.fullmatch(digits):
            raise ProtocolError(cmd, "invalid tones")
        return {"cmd": cmd, "digits": digits}
    if cmd == "mute":
        on = msg.get("on")
        if not isinstance(on, bool):
            raise ProtocolError(cmd, "invalid mute value")
        return {"cmd": cmd, "on": on}
    if cmd in ("sync-contacts", "install-contacts"):
        return {"cmd": cmd}
    raise ProtocolError(cmd, "unknown command")


def encode_event(event, **fields):
    """One event as a compact JSON line (without the trailing newline)."""
    return json.dumps({"event": event, **fields}, separators=(",", ":"))
