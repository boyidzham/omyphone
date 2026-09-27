# omyphone

An Omarchy shell plugin for making and taking phone calls from the desktop through a
Bluetooth-paired phone. The PC acts as an HFP hands-free unit, like a car kit.

Read these first:
- `docs/research.md`: what was proven on the real machine, plus the gotchas
- `docs/superpowers/specs/2026-09-27-omyphone-v1-design.md`: the v1 design
- `docs/superpowers/plans/2026-09-27-omyphone-v1.md`: the implementation plan

## Layout

- `helper/`: Python helper (stdlib + PyGObject only). **All logic lives here**:
  D-Bus to `org.pipewire.Telephony` (session bus) and `org.bluez` (system bus),
  recents, mute and notifications. It speaks JSON lines: commands on stdin, events
  on stdout.
- `Service.qml`: the plugin's `service` kind. It runs the helper and holds its
  state.
- `BarWidget.qml` and `*View.qml`: a thin UI, `qs.Ui` `Panel` + `KeyboardPanel`.
  No logic.
- `tests/`: `unittest` suites, fake D-Bus services (`tests/fakes/`), and stub
  commands (`tests/stubs/`).

## Commands

```sh
tests/run.sh                       # all tests on a private D-Bus bus, + QML lint + plugin validate
tests/run.sh -v tests.test_protocol  # one module
scripts/dev-sync.sh                # copy the working tree into the installed plugin (hot reload)
omarchy plugin validate .
```

Integration tests only run through `tests/run.sh`, which uses `dbus-run-session`
and sets `OMYPHONE_TEST_BUS=1`. Run directly, they skip. Keep it that way, so tests
never touch the real desktop bus.

## Rules

- Never edit `/usr/share/omarchy/` (it is overwritten by updates). Reading the shell
  source there is the way to check `qs.Ui` / `qs.Commons` APIs.
- No dependencies beyond what Omarchy installs: Python 3 stdlib, `gi`, `notify-send`,
  `wpctl`. No pip packages, and no pytest.
- No symlinks in the plugin folder, because `omarchy plugin validate` rejects them.
- The helper must never crash on input. Every failure becomes an `error` event or
  a stderr line.
- UI text is in English, since the plugin is aimed at the marketplace.
- **Real calls cost money and reach real people.** Never dial, answer or hang up on
  the real phone without asking Boss first. Automated tests use the fakes only.
- Pushing to GitHub and submitting to the Omarchy marketplace need Boss's go-ahead.

## Development loop

1. Install once: `omarchy plugin add ~/Projects/omyphone --enable` (a git clone of
   the local repo into `~/.config/omarchy/plugins/omyphone`).
2. Edit here, run `tests/run.sh`, then `scripts/dev-sync.sh`. The shell reloads
   the plugin.
3. For a clean install: `omarchy plugin remove omyphone`, then add it again.

## Machine facts (2026-09-27)

- Omarchy 4.0.4, quickshell 0.3.1, PipeWire 1.6.8, WirePlumber 0.5.17, BlueZ 5.87,
  Python 3.14, notify-send 0.8.8.
- Test phone: iPhone 13, "Test iPhone", `AA:BB:CC:DD:EE:FF`. Headset: Logitech
  G733 (USB).
- Phone status: `busctl --user call org.pipewire.Telephony /org/pipewire/Telephony org.ofono.Manager GetModems`
  (`busctl tree` does not show `ag1`).
- The iPhone never reconnects by itself; the PC must call `Device1.Connect`. No
  WirePlumber config is needed.
- Quickshell has no generic D-Bus client, and `Quickshell.Bluetooth` does not
  expose UUIDs. That is why the helper exists.
