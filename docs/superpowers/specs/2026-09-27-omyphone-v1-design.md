# omyphone v1 design

Date: 2026-09-27. Status: approved in conversation. Revised the same day after the
Omarchy shell API research (see "Revision notes" at the end).
Background and test results: [`docs/research.md`](../../research.md).

## Goal

An Omarchy shell plugin that lets you make and take phone calls from the desktop
through a Bluetooth-paired phone (the PC acts as a Hands-Free unit, like a car kit).
It installs with one command, `omarchy plugin add <git-url>`, with no extra
packages or setup steps.

Success for v1: the owner uses it every day for normal calls without opening a
terminal, and it passes the real-phone checklist under Testing.

## Scope

In v1:
- Dial a number from a keypad
- Incoming call notification with Answer and Decline
- In-call screen with hang up, mic mute and keypad (DTMF, for "press 1" menus)
- Recent calls, kept locally by the plugin, with click to call back
- Automatic reconnect to the phone
- Works with any phone that supports HFP (tested on iPhone 13)

Not in v1, possibly later: contacts and caller names (PBAP), a custom incoming-call
popup window, moving call audio back to the phone, hold, call waiting, conference
calls, SMS, and support for more than one phone at a time.

## Architecture

```
omyphone/
├── manifest.json        kinds: service, bar-widget
├── Service.qml          background part, one instance, runs the helper
├── BarWidget.qml        bar icon + popup under it (one per monitor)
├── KeypadView.qml, RecentsView.qml, InCallView.qml   popup contents
├── Format.js            display helpers (timer, relative time)
├── helper/
│   ├── omyphone-helper  entry script
│   └── omyphone/        Python package: all call, Bluetooth, recents,
│                        mute and notification logic
├── tests/               Python unittest suite + fakes + QML lint
├── scripts/dev-sync.sh  copy the working tree into the installed plugin
├── README.md, LICENSE (MIT), CLAUDE.md
```

**The helper holds all the logic. The QML is a thin view.** The helper is a Python
process that talks to D-Bus and prints what happens. The QML only shows that state
and sends button presses back. This keeps the logic testable without a phone or a
running shell.

Why this shape (verified in Omarchy 4.0.4 and quickshell 0.3.1):
- Quickshell has no generic D-Bus client, so D-Bus goes through a helper process.
  Python 3 and `python-gobject` (Gio) are in Omarchy's base package list
  (`/usr/share/omarchy/install/omarchy-base.packages`), so every Omarchy install
  has them.
- A `service` plugin is one instance that runs while the plugin is enabled, whether
  or not the popup is open. Bar widgets are created once per monitor, so they hold
  no logic.
- `Quickshell.Bluetooth` does not expose device UUIDs, so it cannot tell which
  paired device is a phone. Phone detection and reconnect therefore live in the
  helper, which reads BlueZ over D-Bus.
- The popup follows the built-in Bluetooth widget's pattern: the bar-widget entry
  is a `qs.Ui` `Panel` holding a `BarIconButton` and a `KeyboardPanel`, so the
  popup opens anchored under the icon. There is no separate `panel` kind. A `panel`
  kind would give a free-floating window instead.

Alternatives we considered and rejected: calling `busctl` for every action and
parsing its output (fragile, no clean event stream), and a separate system daemon
like quattro-bt-phone (needs its own install and setup, which breaks the
one-command install).

### Helper (`helper/`)

Started by Service.qml as `python3 helper/omyphone-helper [--phone AA:BB:...]`.
It speaks JSON lines: one JSON object per line, commands on stdin and events on
stdout. It exits when stdin closes, so it dies with the shell.

Modules:

| Module | Responsibility |
|---|---|
| `protocol.py` | Parse and validate commands, encode events |
| `telephony.py` | `org.pipewire.Telephony` on the session bus: snapshot, signals, dial, answer, hangup, tones |
| `bluez.py` | `org.bluez` on the system bus: find the phone, report its status, reconnect |
| `calllog.py` | Turn call lifecycles into recents entries (direction, missed, duration) |
| `recents.py` | Load and save the recents file |
| `notifier.py` | Incoming-call and missed-call notifications via `notify-send` |
| `mic.py` | Mute and unmute the default microphone with `wpctl` |
| `engine.py` | Wires the modules together and handles commands |
| `main.py` | Arguments, GLib main loop, stdin reading |

Commands (stdin):

| Command | Action |
|---|---|
| `{"cmd":"dial","number":"..."}` | `AudioGateway1.Dial` on the first gateway |
| `{"cmd":"answer","call":"<path>"}` | `Call1.Answer` |
| `{"cmd":"hangup","call":"<path>"}` | `Call1.Hangup` |
| `{"cmd":"decline","call":"<path>"}` | Mark the call declined, then `Call1.Hangup` |
| `{"cmd":"tones","digits":"..."}` | `AudioGateway1.SendTones` |
| `{"cmd":"mute","on":true/false}` | Mute or unmute the mic for the current call |

Numbers have spaces, `-`, `(` and `)` removed, then must match `^\+?[0-9*#]{1,32}$`.
Tones must match `^[0-9*#ABCD]{1,32}$`. Call paths must match
`^/org/pipewire/Telephony/ag[0-9]+/call[0-9]+$`. Anything else, including bad JSON,
produces an `error` event, never a crash.

Events (stdout):

| Event | Meaning |
|---|---|
| `{"event":"phone","found":bool,"address":s,"name":s,"connected":bool,"powered":bool}` | Bluetooth status of the chosen phone. Sent on start and on change |
| `{"event":"gateway","path":s,"present":bool}` | The phone's call control appeared or disappeared |
| `{"event":"call","path":s,"number":s,"state":s}` | A call was added or its state changed. States as PipeWire reports them: `incoming`, `dialing`, `alerting`, `active`, `held`, `waiting`, `disconnected` |
| `{"event":"call-removed","path":s}` | A call ended |
| `{"event":"muted","muted":bool}` | Mic mute state for the call |
| `{"event":"recents","entries":[...]}` | The full recents list, newest first. Sent on start and on change |
| `{"event":"error","cmd":s,"message":s}` | A command failed |

**Telephony.** On start, and whenever the `org.pipewire.Telephony` name reappears
(for example after WirePlumber restarts), the helper reads `GetModems`, then
`GetCalls` on each gateway, and emits the current state. That way a shell restart
in the middle of a call picks the call straight back up. It listens to the
ofono-compatible signals `ModemAdded`, `ModemRemoved`, `CallAdded`, `CallRemoved`
and `org.ofono.VoiceCall.PropertyChanged`, as documented in PipeWire's
`spa/plugins/bluez5/README-Telephony.md` (1.6.8). When the name vanishes, every
known gateway and call is reported as gone.

**Phone detection and reconnect.** Every 5 seconds the helper reads BlueZ's
managed objects. The phone is the device whose address matches `--phone`, or, if
that is not given, the first paired device whose UUIDs include the HFP Audio Gateway
UUID `0000111f-0000-1000-8000-00805f9b34fb`. A `phone` event is emitted only when
something changed. If the adapter is powered and the phone is paired but not
connected, the helper calls `Device1.Connect`, at most once every 30 seconds.
Research showed that the iPhone never reconnects by itself, and that a PC-side
connect brings the call profile up within 2 seconds. Nothing is attempted while
the adapter is off.

**Recents.** One entry is added when a call ends:
`{"number":s,"direction":"incoming"|"outgoing"|"missed","start":epoch_s,"duration":s}`.
- The duration counts from when the call became `active`, and is 0 if it never did.
- An incoming call that ends without becoming active, and was not declined from the
  PC, is `missed`.
- A call declined from the PC is `incoming` with a duration of 0.

The list is capped at the 100 newest entries and saved as JSON to
`$XDG_STATE_HOME/omyphone/recents.json` (default
`~/.local/state/omyphone/recents.json`). A missing or corrupt file is treated as
an empty list.

**Notifications.**
- When a call enters `incoming`, the helper runs `notify-send -u critical -p
  -A answer=Answer -A decline=Decline "Incoming call" "<number>"`. Verified
  2026-09-27 with notify-send 0.8.8: `-p` prints the ID on the first line straight
  away, and the process waits.
- The chosen action name is printed on the next line: Answer → answer, Decline →
  hangup plus a "declined" mark.
- Omarchy's notification service lets critical notifications whose app name is
  `notify-send` through Do Not Disturb (`plugins/notifications/Service.qml`,
  `shouldBypassDnd`).
- If the call leaves `incoming` another way (answered on the phone, or the caller
  hung up), the helper closes the notification with
  `org.freedesktop.Notifications.CloseNotification(id)` (verified: notify-send then
  exits 0 with no action) and terminates the notify-send process.
- A missed call also sends a normal-urgency notification, "Missed call" /
  "<number>", with app name `omyphone` so it stays in notification history.

**Mute.** `wpctl set-mute @DEFAULT_AUDIO_SOURCE@ 1|0`. Before the first mute in a
call, the helper records whether the mic was already muted (`wpctl get-volume`
prints `[MUTED]`). When the last call ends it restores that state. Whether muting
the default source silences the call is checked in the real-phone checklist.

### Service.qml

- Root `Item`, with `property var shell: null`, which the host injects.
- Runs the helper with `Process` (`stdinEnabled: true`), reads stdout with
  `SplitParser`, and sends commands with `write()`.
- Exposes the state for the widgets: `phone`, `ready` (a gateway is present),
  `calls`, `currentCall`, `activeSince`, `muted`, `recents`, `lastError`.
- Functions: `dial(number)`, `answer(path)`, `decline(path)`, `hangup(path)`,
  `sendTones(digits)`, `setMuted(on)`.
- If the helper exits, it restarts it after 2 seconds. After 5 restarts within a
  minute, the delay becomes 30 seconds.
- **Settings:** a service gets no settings of its own. It finds its bar layout
  entry in `shell.barConfig.layout` (entries can be plain id strings or objects
  with an `id`) and reads `phoneAddress` from it. When `phoneAddress` changes, it
  restarts the helper.

### BarWidget.qml and the popup

- Root is a `qs.Ui` `Panel` (`moduleName` and `ipcTarget` set to `"omyphone"`),
  containing a `BarIconButton` and a `KeyboardPanel` anchored to it.
- It gets the service with `bar.shell.serviceFor("omyphone")`, retrying on a timer
  until the service exists, and again if it is recreated.
- **Icon:** dimmed when not ready. Accent-coloured (`active`) during a call, with a
  call timer (`03:12`) shown next to it. Left click toggles the popup.
- **Popup:**
  - When not ready: "Phone not connected" plus the phone name, or "No phone paired".
  - When ready and idle: a `ButtonGroup` with Keypad and Recent.
    - Keypad: the number display, a 3×4 grid (1-9, `*`, 0, `#`), `+`, backspace
      and Call. Typing digits on the keyboard works too, and Enter calls.
    - Recent: the newest entries (number, a direction label, relative time,
      duration). Click one to call it back.
  - During a call: the number, the state (`Calling…`, `Ringing…`, `Incoming call`,
    or the timer). An incoming call shows Answer and Decline. Other calls show Mute,
    Keypad (DTMF) and Hang up.
- Errors from the helper show inline for 4 seconds.
- Theme values come from `qs.Commons` (`Color`, `Style`) and `bar.foreground` /
  `bar.fontFamily`.

### Settings (manifest `barWidget.schema`)

- `phoneAddress` (string, optional): the Bluetooth address of the phone to use.
  Empty means auto-detect.

## Error handling summary

| Situation | Behaviour |
|---|---|
| Phone out of range or its Bluetooth off | Icon dimmed, reconnect every 30 s |
| PC Bluetooth off | Icon dimmed, no attempts |
| No HFP phone paired | Popup says "No phone paired" |
| Dial while not connected | Helper returns an error, and the popup shows "Phone not connected" |
| Helper crashes | Restarted in 2 s, backs off if it keeps crashing; the live call is unaffected |
| Shell or WirePlumber restarts during a call | The helper's snapshot restores the call state |
| Recents file missing or corrupt | Start with an empty list |
| Several monitors | One widget per bar, one service, so no duplicate notifications or connects |
| Invalid command | `error` event, helper keeps running |

## Testing

Automated, run with `tests/run.sh` (no phone needed):
- **Unit tests** (Python `unittest`, no pytest dependency): protocol validation,
  calllog rules (outgoing, answered, missed, declined, durations), recents
  (cap, corrupt file), and mic state restore with a stub `wpctl`.
- **Integration tests** inside a private bus (`dbus-run-session`):
  - A fake `org.pipewire.Telephony` and a fake `org.bluez`, each a small Python
    process with a test-control interface.
  - The real helper runs against them, with stub `notify-send` and `wpctl` first
    on `PATH`.
  - Scenarios: outgoing call, incoming answered from the notification, declined,
    missed, answered on the phone, remote hang-up, telephony service restart
    mid-call, reconnect when the phone is disconnected, no reconnect while the
    adapter is off, bad commands.
- `omarchy plugin validate .`
- QML lint (`qmllint` with `qs.Commons` / `qs.Ui` import paths), following the
  pattern of the installed omaplug plugin.

Manual checklist with a real phone, run once before release:
1. Outgoing call from the keypad
2. Incoming call answered from the notification
3. Incoming call declined
4. Incoming call left to ring out, then shown as missed
5. Incoming call answered on the phone
6. DTMF during a call (IVR menu)
7. Mute and unmute; the other side cannot hear you while muted
8. Phone taken out of range and brought back, then auto-reconnect
9. `omarchy restart shell` during a call

## Development loop

- Install once from the local repository: `omarchy plugin add
  ~/Projects/omyphone` (it runs `git clone`) and `omarchy plugin enable omyphone`.
- `scripts/dev-sync.sh` copies the working tree (except `.git` and `tests`) into
  `~/.config/omarchy/plugins/omyphone/`. The shell hot-reloads on save.
- Before a real install, reset the installed copy with `git reset --hard` and
  `git pull`, or remove and add it again.

## Distribution

- Git repository, pushed to GitHub, installed with
  `omarchy plugin add <git-url>`.
- README with a preview image. Submitted to the Omarchy plugin marketplace after the
  manual checklist passes. Pushing and submitting both need the owner's go-ahead.

## Revision notes (2026-09-27)

Changed after reading the Omarchy 4.0.4 shell source:
- Dropped the `panel` kind. The popup is anchored under the bar icon, like the
  built-in Bluetooth widget.
- Moved reconnect from QML into the helper, because `Quickshell.Bluetooth` does not
  expose UUIDs.
- Moved recents, mute and notification handling into the helper as well, so all
  logic is in one testable place.
- Settled the open questions: the dev loop, `notify-send` behaviour, and how the
  service reads settings. The mute mechanism is still to be confirmed on a real
  call.
