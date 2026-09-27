# omyphone contacts design

Date: 2026-09-28. Status: approved in conversation, written spec awaiting review.
Builds on the v1 design ([`2026-09-27-omyphone-v1-design.md`](2026-09-27-omyphone-v1-design.md)).
Background and test results: [`docs/research.md`](../../research.md).

## Goal

People remember two or three phone numbers, and an incoming call that shows only
a number does not say who is calling. This feature brings the phone's contacts
and call history into omyphone:

- The caller's name on the incoming-call card, the in-call screen, Recent, Missed
  and the missed-call notification.
- A Contacts tab to find someone by name and call them with one click.
- Recent and Missed show the phone's own call history, including calls made or
  taken on the phone itself.

Success: after one "Sync contacts" click (plus a password and one switch on the
phone), names appear everywhere a number appeared before, and stay in sync
without further clicks.

## How car kits do it, and why this design

A Bluetooth car kit uses two profiles: HFP for calls, which only carries the
caller's number, and PBAP (Phone Book Access Profile) to copy the phone's
contacts and call history. The car looks the incoming number up in its copy.
omyphone does the same.

Alternatives considered:
- **Caller name from HFP.** PipeWire 1.6.8 exposes a `Name` property on calls, but
  its HFP code parses only the number from `+CLIP` (`backend-native.c`), so `Name`
  is always empty. Not usable.
- **CarPlay / Android Auto.** The phone renders its own screen and streams it to
  the car; the car never gets the contacts. CarPlay needs Apple's MFi
  authentication chip. Not possible on a PC.
- **Own PBAP client in Python.** No extra package, but about 300 lines of OBEX
  protocol code to own, harder to fake in tests, and it would compete with obexd
  for the same profile if the user has it. Kept as a fallback if requiring a
  package turns out to be a problem.
- **Import a `.vcf` export.** No sync; rejected.
- **BlueZ obexd (chosen).** The standard Linux PBAP client, maintained with BlueZ,
  and what quattro-bt-phone uses too. Cost: it lives in the `bluez-obex` package,
  which Omarchy does not install, and plugins cannot declare package
  dependencies. So contacts are optional: without the package, omyphone works
  exactly like v1, and the Contacts tab offers a one-click install.

## Proven on the test machine (2026-09-28)

With `bluez-obex` 5.87 and the iPhone 13 (details added to `docs/research.md`):
- `org.bluez.obex` is D-Bus activatable on the session bus as soon as the package
  is installed; no service needs enabling.
- `Client1.CreateSession(addr, {Target: "PBAP"})` connects in under a second.
- **obexd removes a session when the D-Bus client that created it disconnects**,
  so the session must be owned by a long-running process (the helper), not a
  one-shot `busctl` call.
- **The iPhone shows "Sync Contacts" (Settings > Bluetooth > (i)) only after a PC
  has asked once.** Before it is switched on, every folder returns size 0 and an
  empty pull, with no error.
- After switching it on: `pb` (contacts), `cch` (combined history), `ich`, `och`,
  `mch` all pull, each in 0.6 to 1.2 s. History folders returned at most 100
  entries each (likely the phone's cap).
- vCard 3.0 fields seen: `FN`, `N`, `TEL` (with or without `TYPE=CELL`), `EMAIL`,
  `ORG`, `URL`, `PHOTO` (base64), `UID`; history cards add
  `X-IRMC-CALL-DATETIME;DIALED|MISSED|RECEIVED:YYYYMMDDTHHMMSS`.
- Numbers come in mixed formats: `+60123456789`, `012 345 6789`,
  `+60 12-345 6789`, `+60 (3) 2345-6789`. About a third of history entries have
  no name (unknown numbers).

## Scope

In:
- Pull contacts and call history over PBAP through obexd, and cache them.
- Name lookup by number for calls, recents, missed and notifications.
- Contacts tab with search and click to call.
- Recent and Missed from the phone's history, with the v1 local log as fallback.
- Onboarding: install `bluez-obex` from the popup, then guide the user to allow
  sharing on the phone.

Out (maybe later): contact photos, emails, adding or editing contacts, favourites,
SIM phonebook, SMS (MAP).

## Onboarding flow

```
Fresh install: Contacts tab shows "Sync contacts" button
  │ click
  ├─ bluez-obex missing ─► floating terminal runs `omarchy-pkg-add bluez-obex`
  │                        (asks for the sudo password), helper notices the
  │                        package appeared and continues automatically
  ▼
Pull contacts ─► got entries ─► done: contacts listed, button gone
            └─► empty ─────► "Allow contact sharing on your phone" hint,
                             helper retries every 5 s for up to 3 min,
                             "Try again" button as backup
```

- Above the button, when the package is missing: "Needs the bluez-obex package. A
  terminal will ask for your password." One click opens the terminal; there is no
  second confirmation button.
- If the package is already installed, the click goes straight to the pull.
- The hint text: "On your phone, allow contact sharing. iPhone: Settings >
  Bluetooth > (i) next to this PC > Sync Contacts." Android phones usually show
  an "Allow access to contacts?" prompt instead, which the first sentence covers.
- The pull must happen before the hint is shown, because the iPhone switch only
  appears after the first request.
- The first "Sync contacts" click **enables** contacts (saved in
  `contacts.json`). From then on the helper syncs by itself on every connect,
  even if the first pull was empty. Before that click, omyphone never contacts
  obexd (opt-in).

## Architecture

New helper modules:

| Module | Responsibility |
|---|---|
| `vcard.py` | Parse vCard 3.0 text: unfold lines, split params, unescape values. Returns contacts (`name`, `numbers` with labels) and history entries (`name`, `number`, `direction`, `start`). Drops photos, emails and everything else |
| `contacts.py` | Number keys and lookup; load and save `contacts.json` and `history.json` |
| `phonebook.py` | The obexd client: availability check, session, pulls, transfer tracking, the sync state machine and permission retries, the install command |

`engine.py` wires them in; `recents.py` and `calllog.py` stay as the local log.
All D-Bus calls are asynchronous on the existing GLib main loop, as in
`telephony.py`.

### Pulling (`phonebook.py`)

1. Check availability: `org.bluez.obex` is in the session bus's
   `ListActivatableNames` or `ListNames`. Not there: state `needs-install`.
2. `Client1.CreateSession(address, {Target: "PBAP"})` for the current phone.
3. For each folder: `PhonebookAccess1.Select("int", folder)`, then
   `PullAll(path, {Format: "vcard30"})`. Contacts sync pulls `pb`, `cch` and
   `mch`; a history-only sync pulls `cch` and `mch`.
4. Track each transfer through `org.bluez.obex.Transfer1` `PropertiesChanged`
   (`Status` `complete` or `error`); the object may also vanish on completion,
   which counts as complete if the file exists.
5. Files go to `$XDG_RUNTIME_DIR/omyphone/` (created mode 0700, tmpfs), are
   parsed, then deleted.
6. `Client1.RemoveSession`. Also removed on any error, and on helper stop.

One sync at a time. A request during a sync is queued once (repeats collapse).
A whole sync has a 60 s timeout.

When a sync runs:
- The user clicks "Sync contacts", "Try again" or the refresh button.
- The phone's gateway appears (connect), if contacts are enabled.
- A call ends, if contacts are enabled: history only, 3 s after the call is
  removed, so the phone has written its log.

### Result handling

- `pb` non-empty: replace the contacts cache. The first card of `pb` is the
  phone owner's own card (PBAP handle 0) and is skipped. **To confirm on the real
  phone**, see Testing.
- `pb` empty: state `needs-permission`. The cache is kept (the phone may have
  just stopped sharing; old names are better than none). If the sync came from a
  user click, retry every 5 s for up to 3 minutes.
- History non-empty: replace the history cache.
- Errors (session refused, phone not connected, timeout, transfer error): state
  `error` with the message; the cache is kept.

### Number matching (`contacts.py`)

`key(number)`: keep digits only. If 9 or more digits, the key is the last 9
digits; otherwise the whole digit string. Two numbers match when their keys are
equal.

- `012 345 6789`, `+60123456789` and `+60 12-345 6789` all give `123456789`.
- Short numbers (`999`, service codes) only match exactly.
- This needs no country code guessing. A false match needs two contacts whose
  numbers share the last 9 digits, which is rare enough to accept.
- When several contacts share a key, the first by name (case-insensitive) wins.
- History entries use the contacts lookup first and fall back to the history
  card's own `FN`.

### Storage

Under `$XDG_STATE_HOME/omyphone/` (default `~/.local/state/omyphone/`), next to
`recents.json`:

- `contacts.json`: `{"enabled": bool, "synced": epoch_s, "contacts": [{"name": s, "numbers": [{"number": s, "label": s}]}]}`
- `history.json`: `{"synced": epoch_s, "calls": [...], "missed": [...]}`, entries
  shaped like recents entries with `duration` absent.

Files are written mode 0600 through a temp file and `os.replace`, like
`recents.json`. A missing or corrupt file counts as empty (and not enabled).

### Recent and Missed

- If a phone history exists: Recent = `cch` entries, Missed = `mch` entries.
  Local-log entries newer than the newest phone entry are shown on top, so a call
  that just ended appears at once and is replaced when the history sync lands.
- Otherwise: the v1 local log, exactly as now.
- History timestamps have no time zone: parsed as local time; a trailing `Z`
  means UTC.
- Phone history has no durations; the row shows no duration for those entries.

### Protocol changes

New commands:

| Command | Action |
|---|---|
| `{"cmd":"sync-contacts"}` | Enable contacts and sync now (starts the permission retry if the result is empty) |
| `{"cmd":"install-contacts"}` | Run `omarchy-launch-floating-terminal-with-presentation omarchy-pkg-add bluez-obex` |

New and changed events:

| Event | Meaning |
|---|---|
| `{"event":"contacts","entries":[{"name":s,"number":s,"label":s}]}` | One row per number, sorted by name. Sent on start and on change |
| `{"event":"contacts-status","state":s,"enabled":bool,"synced":epoch_s,"message":s}` | `state`: `off` (never enabled), `needs-install`, `syncing`, `needs-permission`, `ready`, `error` |
| `call` | Gains `"name":s` (empty when unknown) |
| `recents` | Entries gain `"name":s`; entries from the phone have no `duration`. Gains `"missed":[...]`, the list for the Missed tab |

After `install-contacts`, while the state is `needs-install`, the helper rechecks
availability every 3 s (for up to 10 minutes) and runs the pending sync as soon as
obexd is available. Labels: `TYPE=CELL` → `Mobile`, `HOME` → `Home`, `WORK` →
`Work`, anything else → empty.

### Notifications

The missed-call notification body uses the name when known: "Missed call" /
"Ali Ahmad". Unknown: the number, as now.

## UI

Tabs: Keypad | Recent | Missed | Contacts.

**Contacts tab**
- A `qs.Ui` `TextField` search box at the top, focused when the tab opens, with a
  refresh button beside it.
- Filtering is case-insensitive on the name, and on the digits of the number.
  The filter function lives in `Format.js`.
- Rows sorted A-Z: name on top, number (and label, if any) below. Click calls the
  number. Enter calls the first (or selected) row; Up and Down move the selection.
- Footer: "Synced 2 min ago".
- States: `off` shows the "Sync contacts" button (plus the install note when
  `needs-install`); `needs-permission` shows the hint and "Try again"; `syncing`
  shows "Syncing…"; `error` shows the message and "Try again". Once contacts
  exist, the list shows and states appear only in the footer.

**Recent and Missed:** name on the top line when known, else the number. Second
line: number · direction · time (and duration for local entries).

**Incoming-call card and in-call screen:** the name large, the number small below.
No name: the number, as now.

`Service.qml` gains `contacts`, `contactsStatus`, `missed`, `syncContacts()` and
`installContacts()`.

## Error handling

| Situation | Behaviour |
|---|---|
| `bluez-obex` not installed | v1 behaviour everywhere; Contacts tab offers the install |
| Install terminal closed or failed | State stays `needs-install`; the button can be pressed again |
| Phone not sharing (empty pull) | `needs-permission` hint, retries after a user click, cache kept |
| Phone not connected | No sync attempted; cache used |
| obexd error or timeout | `contacts-status` `error`, cache kept, helper keeps running |
| Corrupt cache file | Treated as empty |
| Malformed vCard | Bad cards are skipped; the rest are used |

## Testing

Automated, through `tests/run.sh`:

- **Fixtures** (`tests/fixtures/`): fictional names and numbers only, in the
  shapes seen on the real phone: `+60...`, `012 345 6789`, `+60 12-345 6789`,
  brackets, a contact with two numbers, the owner card first, a folded base64
  `PHOTO`, Malay and Chinese names (UTF-8), escaped `\,` and `\;`, CRLF line ends,
  history cards with and without names.
- **Unit tests:** vCard parsing (fields, labels, dropped photo, unfolding, bad
  cards), number keys and lookup (the format equivalences, short numbers exact,
  collisions), storage (0600, atomic write, corrupt file), recents merging (phone
  history plus newer local entries), time parsing.
- **Fake obexd** (`tests/fakes/fake_obex.py`): serves `org.bluez.obex` on the
  private bus with `Client1`, `Session1`, `PhonebookAccess1` and `Transfer1`, and
  a test-control interface to switch modes: `normal` (serves the fixtures),
  `empty`, `error`, and absent (not started).
- **Integration tests** with the real helper: enable and sync on connect; call
  with a known number carries its name; unknown number has an empty name;
  `empty` gives `needs-permission`, then retries succeed after switching to
  `normal`; obexd absent gives `needs-install` and v1 still works;
  `install-contacts` runs the right command (stub
  `omarchy-launch-floating-terminal-with-presentation` on `PATH`); history
  re-sync after a call ends; obexd error gives an `error` status and no crash;
  no obexd traffic before the first `sync-contacts`.
- QML lint and `omarchy plugin validate .`, as now.

Manual checks with the real phone (the maintainer runs them; every step that
places or answers a call is asked first):
1. Fresh sync (cache deleted): the contact count matches the phone, and the owner
   card is not listed.
2. Search by name and call from the Contacts tab.
3. Incoming call from a saved number: the card shows the name.
4. Missed call from a saved number: the notification and Missed show the name.
5. A call made on the phone itself appears in Recent after it ends.
6. The install step, if the maintainer agrees to remove `bluez-obex` first;
   otherwise it is covered by the fake only.

## Repository changes

- `CLAUDE.md`: the dependency rule becomes "Python 3 stdlib, `gi`, `notify-send`,
  `wpctl`, plus `bluez-obex` as an optional package for contacts only".
- `README.md`: a Contacts section (what it does, the one-time setup).
- `docs/research.md`: the PBAP results above move from "Not yet tested" to
  "Proven".
