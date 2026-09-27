# OMyPhone

Make and take phone calls from your Omarchy desktop through your Bluetooth-paired
phone. Your PC becomes a hands-free unit for the phone, like a car kit: calls use
your phone's own number and plan, with no app on the phone and no VoIP account.

- Dial from a keypad in the bar, or call back from recent calls
- Incoming calls pop up as a notification with Answer and Decline
- Mute, keypad tones and hang up during a call
- Reconnects to your phone automatically

Works with any phone that supports Bluetooth hands-free (tested on iPhone 13).

## Install

```sh
omarchy plugin add https://github.com/<owner>/omyphone --enable
```

Pair your phone once in Omarchy's Bluetooth panel. That's all. omyphone finds the
paired phone and connects to it.

## Settings

- `phoneAddress`: the Bluetooth address of the phone to use, if you have more than
  one paired. Leave it empty to pick the first phone automatically.

## Requirements

Omarchy 4.0 or newer (PipeWire 1.4 or newer, with WirePlumber). Nothing else to
install.

## How it works

PipeWire's Bluetooth plugin exposes the phone's call controls on D-Bus
(`org.pipewire.Telephony`). A small Python helper in this plugin talks to it and
to BlueZ, and the bar widget shows what the helper reports. See `docs/` for the
design.

## Development

```sh
tests/run.sh           # all tests; no phone needed
scripts/dev-sync.sh    # copy your working tree into the installed plugin
```

## Licence

MIT
