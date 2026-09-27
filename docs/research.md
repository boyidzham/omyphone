# omyphone research notes

Feasibility work done on 2026-09-27, before the project started. Everything under
"Proven" was run and observed on the target machine. Everything else is labelled.

## Goal

An Omarchy bar plugin that lets you make and take real phone calls from the desktop
through a Bluetooth-paired phone: dialer/keypad, contacts, recent calls, answer and
hang up, incoming call popup. The phone stays in your pocket.

## How it works

The PC acts as a Bluetooth hands-free unit for the phone, the same way a car kit does
(Hands-Free Profile, HFP). Calls go over the phone's own number and plan. There is no
VoIP, no cloud and no app on the phone. Because HFP is a standard, any phone that
works with a car kit should work, iPhone or Android.

```
phone (HFP Audio Gateway)
   │ Bluetooth
   ▼
BlueZ ──► PipeWire bluez5 plugin (native HFP backend, PC = Hands-Free)
            ├─ D-Bus: org.pipewire.Telephony  → call control
            └─ audio nodes bluez_input / bluez_output → routed to default mic/speaker
BlueZ obexd ──► PBAP (contacts, call history)   [not yet tested]
```

## Test machine

| Component | Version |
|---|---|
| Omarchy | 4.0.4 (Quickshell shell, plugin support) |
| PipeWire | 1.6.8 |
| WirePlumber | 0.5.17 |
| BlueZ | 5.87 |
| Phone | iPhone 13 |

PipeWire 1.4 or newer is needed for `org.pipewire.Telephony`.

## Proven

1. **Pairing.** The iPhone paired and advertises these profiles:
   Handsfree Audio Gateway (`0000111f`), Phonebook Access Server (`0000112f`),
   Message Access Server (`00001132`, SMS), Audio Source (A2DP), AVRCP.
2. **Call control object.** After connecting the HFP profile, PipeWire exposes the
   phone as an AudioGateway:
   ```sh
   busctl --user call org.pipewire.Telephony /org/pipewire/Telephony \
     org.ofono.Manager GetModems
   # → /org/pipewire/Telephony/ag1
   ```
   Interfaces on `ag1`: `org.pipewire.Telephony.AudioGateway1`
   (Dial, HangupAll, HoldAndAnswer, ReleaseAndAnswer, ReleaseAndSwap, SwapCalls,
   SendTones, CreateMultiparty; properties Address, MicrophoneVolume, SpeakerVolume),
   `org.pipewire.Telephony.AudioGatewayTransport1` (Activate; Codec, State, RejectSCO),
   and ofono-compatible `org.ofono.VoiceCallManager` (GetCalls, CallAdded, CallRemoved).
3. **Outgoing call.** A real call was placed from the PC:
   ```sh
   busctl --user call org.pipewire.Telephony /org/pipewire/Telephony/ag1 \
     org.pipewire.Telephony.AudioGateway1 Dial s "<number>"
   ```
   `GetCalls` showed the call go `alerting` → `active`. When the other side hung up,
   the call disappeared and the phone ended it too.
4. **Audio.** With no extra config, WirePlumber linked the call both ways to the
   default devices (a USB headset in this test): `bluez_input` → speakers,
   mic → `bluez_output`. Both sides heard each other clearly.
5. **Answering an incoming call.** Tested on 2026-09-27. Polling
   `org.ofono.VoiceCallManager.GetCalls` on `ag1` showed
   `/org/pipewire/Telephony/ag1/call1` with `State "incoming"` and
   `LineIdentification` set to the caller's number. Call objects have
   `org.pipewire.Telephony.Call1` (Answer, Hangup) and `org.ofono.VoiceCall` (Answer,
   Hangup, GetProperties). Calling `org.ofono.VoiceCall.Answer` on the call answered
   it without touching the phone, and the state went to `active`. Audio was clear
   both ways. When the caller hung up, the call ended on the PC too.

## Gotchas found

- `busctl --user tree org.pipewire.Telephony` does **not** list `ag1`. Use
  `GetModems` or `GetManagedObjects` instead.
- The PipeWire card for the phone shows a single profile, `audio-gateway`, which is
  named after the phone's role, not the PC's.
- Omarchy ships `~/.config/wireplumber/wireplumber.conf.d/bluetooth-a2dp-autoconnect.conf`,
  which sets `bluez5.auto-connect = [ a2dp_sink a2dp_source ]` for every Bluetooth
  card. HFP did not come up on its own; it was connected by hand with
  `bluetoothctl connect <mac> 0000111f-0000-1000-8000-00805f9b34fb`.
- **Reconnect (tested 2026-09-27).** The WirePlumber auto-connect list is not the
  problem. After turning Bluetooth off and on at the iPhone, the iPhone did **not**
  reconnect to the PC at all. A plain `bluetoothctl connect <mac>` from the PC
  brought `ag1` up within 2 seconds, with or without adding `hfp_hf`/`hfp_ag` to
  `bluez5.auto-connect` (both were A/B tested; the extra config was then removed).
  So the PC has to start the connection, the way a car kit does. The plugin needs
  to retry `org.bluez.Device1.Connect` while the phone is paired but not connected.
  One retry right after a reconnect failed with `br-connection-page-timeout` and the
  next one worked, so retries need a short back-off.

## v1 checklist (2026-09-28)

Run with the installed plugin, the iPhone 13 and a second phone. All buttons were
pressed by the owner.

| # | Item | Result |
|---|---|---|
| 1 | Outgoing call from the keypad | Pass. Audio clear both ways |
| 2 | Incoming call answered | Pass, after a redesign (see below). Answered from the card and from the popup |
| 3 | Incoming call declined | Pass |
| 4 | Missed call | Pass. Shown as missed; the notification click opens the Missed tab |
| 5 | Incoming call answered on the phone | Not re-run after the card change |
| 6 | DTMF during a call | Not tested (no IVR number to hand) |
| 7 | Mute and unmute | Pass. The other side could not hear while muted, so the `wpctl` default-source approach works |
| 8 | Phone off and on, auto-reconnect | Pass. Reconnects by itself after a short wait |
| 9 | `omarchy restart shell` during a call | Pass. The call kept going and came back in the popup with its timer |

Surprises and changes made:
- Omarchy's notifications show **no action buttons**. A left click runs the
  `default` action, a right click dismisses. A sender's `CloseNotification` does
  not take the toast off screen either. So `notify-send -A answer/decline` did
  nothing useful, and the toast stayed after answering. Incoming calls now show
  omyphone's own card (Answer/Decline) in the notification corner of one monitor:
  the `callScreen` setting, or the focused monitor.
- A third-party `service` is created without a parent, outside the shell's object
  tree, so windows declared in it never appear. The card lives in the bar widget.
- `omarchy-shell shell rescanPlugins` reloads the service but not the bar widget's
  code. `scripts/dev-sync.sh` restarts the shell instead.
- Missed-call notifications use `-A default=...`, so a click opens the new Missed
  tab. Recent calls show direction icons, and missed calls use the urgent colour.
- With Num Lock off, numpad keys arrive as arrows. That is expected.

## Not yet tested

- DTMF (`SendTones`) during a call.
- An incoming call answered on the phone while the card is showing (the card
  should close by itself).
- Contacts and call history over PBAP. Needs `obexd`, which is in the `bluez-obex`
  package (not installed on the test machine). On iPhone, "Sync Contacts" must be on
  in the Bluetooth settings for the PC. Whether iPhone exposes call history over PBAP
  is unverified.
- SMS over MAP.
- Android phones on this code path (HFP is standard, and quattro-bt-phone below
  reports a Galaxy S25 FE working).
- Switching call audio back to the phone mid-call.

## Prior art

| Project | What it is | Relevance |
|---|---|---|
| [quattro-bt-phone](https://github.com/JJB-IT/quattro-bt-phone) | Omarchy panel + Rust daemon over `org.pipewire.Telephony` and PBAP. MIT. | Same idea. Early stage (created 2026-09-18), README says not ready for daily use, live-call audio unfinished, Nix-only install, Android-tested only. Its design notes: Quickshell has no generic D-Bus client, so a daemon owns the bus and the QML panel talks to it over a Unix socket. |
| [omaphone](https://github.com/tomdavenport/omaphone) | Tor push-to-talk walkie-talkie | Different product, name clash avoided |
| [omarchy-headphones (omaphones)](https://github.com/ncr/omarchy-headphones) | Headphone battery / ANC | Different product |
| [omacall](https://github.com/f360c4/omacall) | SIP softphone | Different product, needs a VoIP account |

The name **omyphone** ("oh my phone") was checked against the marketplace registry
and GitHub on 2026-09-27 and was free.

## References

- [Introducing Bluetooth telephony support in PipeWire](https://gkiagia.gr/2025-02-20-pipewire-telephony/)
- PipeWire `spa/plugins/bluez5/README-Telephony.md` (full D-Bus API)
- WirePlumber example config: `/usr/share/doc/wireplumber/examples/wireplumber.conf.d/bluetooth.conf`
- [Omarchy plugin marketplace](https://github.com/omacom/omarchy-plugin-marketplace) (see SUBMISSION.md)
- Omarchy plugin commands: `omarchy plugin validate <folder>`, `omarchy plugin add <git-url>`
