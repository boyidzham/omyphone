# omyphone v1 design

Date: 2026-09-27. Status: approved in conversation, pending review of this written spec.
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
- Recent calls, kept locally by the plugin, with tap to call back
- Automatic reconnect to the phone
- Works with any phone that supports HFP (tested on iPhone 13)

Not in v1, possibly later: contacts and caller names (PBAP), a custom incoming-call
popup window, moving call audio back to the phone, hold, call waiting, conference
calls, SMS, and support for more than one phone at a time.

## Architecture

The plugin is a single folder (`omyphone/`) with four parts:

```
omyphone/
├── manifest.json        kinds: service, bar-widget, panel
├── Service.qml          background part, one instance, always running
├── BarWidget.qml        phone icon in the bar, one per monitor
├── Panel.qml            keypad / recents / in-call screen
├── helper/omyphone-helper.py
├── tests/
├── README.md, LICENSE (MIT), preview.png
```

Why this shape (verified in Omarchy 4.0.4 and quickshell 0.3.1, see research):
- Quickshell has no generic D-Bus client, so the call control goes through a
  helper process. Python 3 and `python-gobject` (Gio) are in Omarchy's base package
  list (`/usr/share/omarchy/install/omarchy-base.packages`), so every Omarchy install
  has them.
- A `service` plugin kind is a single instance that runs while the plugin is
  enabled, whether or not a panel is open. Bar widgets are created once per monitor,
  so no background logic lives in `BarWidget.qml`.
- `Quickshell.Bluetooth` exposes BlueZ devices with `connect()` and `connected`, so
  reconnect is done in QML, not in the helper.

Alternatives we considered and rejected: calling `busctl` for every action and
parsing its output (fragile, no clean event stream), and a separate system daemon
like quattro-bt-phone (needs its own install and setup, which breaks the
one-command install).

### Service.qml (background)

- Starts the helper with `Process` and reads its stdout line by line with a
  `SplitParser`. It writes commands to the helper's stdin.
- Holds the state that the widget and panel read: `phone` (name, address,
  connected), `calls` (list of current calls), `muted`, `recents`, `lastError`.
- If the helper exits, it restarts the helper after 2 seconds. It also backs off to
  30 seconds after 5 restarts in a minute, so a broken helper cannot spin.
- **Phone selection:** uses the paired device whose address is set in the plugin
  setting `phoneAddress`. If that setting is empty, it uses the first paired device
  that advertises the HFP Audio Gateway UUID `0000111f-0000-1000-8000-00805f9b34fb`.
- **Reconnect:** while the adapter is powered and the chosen phone is paired but not
  connected, it calls `connect()` every 30 seconds. It does nothing while the PC's
  Bluetooth is off. Research showed that the iPhone never reconnects by itself, and
  that a PC-side connect brings the call profile up within 2 seconds.
- **Recents:** it appends one entry when a call ends: number, direction
  (`incoming` / `outgoing` / `missed`), start time and duration. The list is capped
  at the 100 newest entries and saved as JSON to
  `$XDG_STATE_HOME/omyphone/recents.json` (default
  `~/.local/state/omyphone/recents.json`). A missing or corrupt file is treated as
  an empty list.
- **Mute:** mutes the default microphone while a call is active and restores the
  previous mute state when the call ends. The exact mechanism (`wpctl` on the
  default source, or the AudioGateway `MicrophoneVolume` property) is chosen during
  implementation by testing which one actually silences the call.

### Helper (`helper/omyphone-helper.py`)

A small Python process. It talks to `org.pipewire.Telephony` on the session bus
using Gio, and it is the only code that touches that bus.

It speaks JSON lines: one JSON object per line, commands on stdin and events on
stdout.

Commands:

| Command | Action |
|---|---|
| `{"cmd":"dial","number":"..."}` | `AudioGateway1.Dial` |
| `{"cmd":"answer","call":"<path>"}` | `Call1.Answer` |
| `{"cmd":"hangup","call":"<path>"}` | `Call1.Hangup` |
| `{"cmd":"tones","digits":"..."}` | `AudioGateway1.SendTones` |

Events:

| Event | When |
|---|---|
| `{"event":"gateway","path":...,"present":true/false}` | A phone appears or disappears on the telephony bus |
| `{"event":"call","path":...,"number":...,"state":...}` | A call is added or its state changes. States are passed through as reported, e.g. `incoming`, `dialing`, `alerting`, `active`, `held` |
| `{"event":"call-removed","path":...}` | A call ends |
| `{"event":"notification-action","call":...,"action":"answer"/"decline"}` | The user clicked a button on the incoming-call notification |
| `{"event":"error","cmd":...,"message":...}` | A command failed |

On start, and after any restart, the helper emits the current gateway and calls
(`GetModems`, then `GetCalls` on each gateway) before listening for signals. That
way a shell restart in the middle of a call picks the call straight back up. Signal
names and interfaces are taken from PipeWire's `README-Telephony.md` and checked
against the live bus during implementation.

Unknown or malformed commands produce an `error` event, never a crash.

### Incoming-call notification

- When a call enters `incoming`, the helper runs `notify-send -u critical -p
  -A answer=Answer -A decline=Decline "Incoming call" "<number>"`. It reads back the
  notification ID and, later, the chosen action.
- Omarchy's notification service lets critical notifications from `notify-send`
  through Do Not Disturb (`plugins/notifications/Service.qml`, `shouldBypassDnd`).
- Answer → `answer`, Decline → `hangup`.
- If the call leaves `incoming` some other way (answered on the phone, or the
  caller hung up), the helper closes the notification with
  `org.freedesktop.Notifications.CloseNotification(id)`.
- A call that goes from `incoming` straight to removed, without becoming `active`
  and without being declined from the PC, is recorded as `missed`. A call declined
  from the PC is recorded as `incoming` with a duration of 0. A separate normal-urgency notification, "Missed call from
  <number>", is sent with app name `omyphone` so it stays in notification history.

### BarWidget.qml

- Phone icon. Muted colour when the phone is not connected, normal when connected.
  During a call it turns to the accent colour and shows the call timer (`03:12`).
- Click toggles the panel.
- Uses Omarchy theme values (`bar.foreground`, `bar.fontFamily`, `qs.Commons`).

### Panel.qml

Built from the `qs.Ui` kit so it matches Omarchy.
- **Idle:** two tabs, Keypad and Recent.
  - Keypad: a number field plus 0-9, `*`, `#`, `+`, backspace and Call. Typing on
    the keyboard works too.
  - Recent: a list of entries (number, direction icon, relative time, duration).
    Click to call back.
- **In call:** number, state (`Calling…`, `Ringing`, timer when active), and Mute,
  Keypad (sends DTMF) and Hang up buttons.
- **Not connected:** shows "Phone not connected" and the phone name, and Call is
  disabled.
- Errors from the helper are shown inline for a few seconds.

The panel only reads the service's state and sends it actions. It holds no state of
its own apart from what is typed.

### Settings (manifest `barWidget.schema`)

- `phoneAddress` (string, optional): the Bluetooth address of the phone to use.
  Empty means auto-detect.

## Error handling summary

| Situation | Behaviour |
|---|---|
| Phone out of range or its Bluetooth off | Icon muted, retry every 30 s |
| PC Bluetooth off | Icon muted, no retries |
| Dial while not connected | Inline "Phone not connected", no call |
| Helper crashes | Restarted in 2 s, backs off if it keeps crashing; the live call is unaffected |
| Shell restarts during a call | The helper's startup snapshot restores the in-call screen |
| Recents file missing or corrupt | Start with an empty list |
| Several monitors | One widget per bar, one service, so no duplicate notifications or connects |

## Testing

Automated (no phone needed):
- **Fake telephony bus:** a Python fake of `org.pipewire.Telephony` (Manager,
  AudioGateway1, Call1, VoiceCallManager signals) on a private session bus
  (`dbus-run-session`). The tests drive it to simulate outgoing, incoming, answer,
  decline, remote hangup and missed calls, and assert on the helper's JSON events
  and on the D-Bus calls it makes.
- The notification step is covered by pointing the helper at a stub `notify-send`
  on `PATH` in tests.
- Recents logic: append, cap at 100, corrupt file.
- `omarchy plugin validate <folder>`.
- A headless QML load test of the plugin files, following the pattern used by the
  installed omaplug plugin.

Manual checklist with a real phone, run once before release:
1. Outgoing call from the keypad
2. Incoming call answered from the notification
3. Incoming call declined
4. Incoming call left to ring out, then shown as missed
5. Incoming call answered on the phone
6. DTMF during a call (IVR menu)
7. Mute and unmute
8. Phone taken out of range and brought back, then auto-reconnect
9. `omarchy restart shell` during a call

## Distribution

- Git repository, pushed to GitHub, installed with
  `omarchy plugin add <git-url>`.
- README with a preview image. Submitted to the Omarchy plugin marketplace after the
  manual checklist passes. Pushing and submitting both need the owner's go-ahead.

## To settle during implementation planning

- **Dev loop:** how to develop in `~/Projects/omyphone` and run it as a real plugin.
  Plugin folders may not contain symlinks, and whether `omarchy plugin add` accepts
  a local path is unverified.
- **`notify-send` behaviour:** check that `-p` together with `-A` prints the ID
  first and then the action, and that it keeps waiting until a button is clicked or
  the notification is closed.
- **Mute mechanism** (see Service.qml).
- **Panel wiring:** use the `panel` kind (summoned by ID) or a `Loader` inside the
  widget like omaplug; pick whichever the Omarchy README recommends for third-party
  plugins.
- **Settings access:** the `phoneAddress` setting is declared on the bar widget.
  Check how the service reads it (the Omarchy shell API or `shell.json`), or whether
  a service can declare its own settings.
