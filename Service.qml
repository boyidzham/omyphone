import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io

// omyphone background service: one instance, runs while the plugin is enabled.
// Starts helper/omyphone-helper, keeps the phone and call state it reports, and
// forwards user actions to it. All logic lives in the helper; see the spec.
Item {
  id: root

  property var shell: null

  readonly property string helperPath: Qt.resolvedUrl("helper/omyphone-helper").toString().replace(/^file:\/\//, "")
  readonly property string phoneAddress: findSetting("phoneAddress", "")
  readonly property string callScreen: findSetting("callScreen", "")

  property var phone: ({ found: false, address: "", name: "", connected: false, powered: false })
  property var gateways: []
  // Each call: { path, number, state, name, since }. since is when it was
  // answered (epoch seconds), 0 before that or when unknown.
  property var calls: []
  property bool muted: false
  property var recents: []
  property var missed: []
  property var contacts: []
  property var contactsStatus: ({ state: "off", enabled: false, synced: 0, message: "" })
  property string lastError: ""
  // The command that failed ("answer", "dial", ...), so the incoming-call card
  // can show only its own errors.
  property string lastErrorCmd: ""
  property var restartTimes: []

  // A clicked missed-call notification asks for the popup on a given tab.
  signal showRequested(string tab)

  readonly property bool ready: gateways.length > 0
  readonly property var currentCall: {
    for (var i = 0; i < calls.length; i++) {
      if (calls[i].state === "incoming") return calls[i]
    }
    return calls.length > 0 ? calls[0] : null
  }
  readonly property var ringingCall: {
    for (var i = 0; i < calls.length; i++) {
      if (calls[i].state === "incoming") return calls[i]
    }
    return null
  }

  // Monitor for the incoming-call card: the "callScreen" setting if that monitor
  // is connected, otherwise the focused one. Picked when ringing starts and kept
  // until it stops, so the card never jumps. The card itself lives in
  // BarWidget.qml: windows need the shell's object tree, which third-party
  // services are kept out of.
  property string ringScreen: ""
  onRingingCallChanged: ringScreen = ringingCall ? (ringScreen || pickRingScreen()) : ""

  function pickRingScreen() {
    var names = Quickshell.screens.map(function(s) { return s.name })
    if (callScreen !== "" && names.indexOf(callScreen) >= 0) return callScreen
    var focused = Hyprland.focusedMonitor ? Hyprland.focusedMonitor.name : ""
    if (focused !== "" && names.indexOf(focused) >= 0) return focused
    return names.length > 0 ? names[0] : ""
  }

  // Settings live on the bar layout entry (bar.layout.<section>[] in shell.json);
  // entries are either plain id strings or objects with an id.
  function findSetting(key, fallback) {
    var layout = shell && shell.barConfig ? shell.barConfig.layout : null
    if (!layout) return fallback
    for (var section in layout) {
      var entries = layout[section] || []
      for (var i = 0; i < entries.length; i++) {
        var entry = entries[i]
        if (entry && typeof entry === "object" && entry.id === "omyphone"
            && entry[key] !== undefined && entry[key] !== null) return entry[key]
      }
    }
    return fallback
  }

  function send(message) {
    if (helper.running) helper.write(JSON.stringify(message) + "\n")
  }

  function dial(number) { send({ cmd: "dial", number: number }) }
  function answer(path) { send({ cmd: "answer", call: path }) }
  function decline(path) { send({ cmd: "decline", call: path }) }
  function hangup(path) { send({ cmd: "hangup", call: path }) }
  function sendTones(digits) { send({ cmd: "tones", digits: digits }) }
  function setMuted(on) { send({ cmd: "mute", on: on }) }
  function syncContacts() { send({ cmd: "sync-contacts" }) }
  function installContacts() { send({ cmd: "install-contacts" }) }

  function handleLine(line) {
    var msg
    try { msg = JSON.parse(line) } catch (e) { return }
    switch (msg.event) {
    case "phone": phone = msg; break
    case "gateway":
      gateways = msg.present
        ? gateways.filter(function(p) { return p !== msg.path }).concat([msg.path])
        : gateways.filter(function(p) { return p !== msg.path })
      break
    case "call": upsertCall(msg); break
    case "call-removed": removeCall(msg.path); break
    case "muted": muted = msg.muted; break
    case "recents": recents = msg.entries; missed = msg.missed || []; break
    case "contacts": contacts = msg.entries; break
    case "contacts-status": contactsStatus = msg; break
    case "error": showError(msg.message, msg.cmd || ""); break
    case "show": showPopup(msg.tab); break
    }
  }

  function upsertCall(msg) {
    var next = calls.filter(function(c) { return c.path !== msg.path })
    var index = calls.findIndex(function(c) { return c.path === msg.path })
    var call = { path: msg.path, number: msg.number, state: msg.state, name: msg.name || "", since: msg.since || 0 }
    if (index < 0) next.push(call)
    else next.splice(index, 0, call)
    calls = next
  }

  function removeCall(path) {
    calls = calls.filter(function(c) { return c.path !== path })
  }

  function showPopup(tab) {
    showRequested(tab)
    if (shell) shell.summon("omyphone")
  }

  function showError(message, cmd) {
    lastError = message
    lastErrorCmd = cmd
    errorTimer.restart()
  }

  function nextRestartDelay() {
    var now = Date.now()
    restartTimes = restartTimes.filter(function(t) { return now - t < 60000 }).concat([now])
    return restartTimes.length > 5 ? 30000 : 2000
  }

  onPhoneAddressChanged: if (helper.running) helper.running = false

  Process {
    id: helper
    // -B: no __pycache__ in the plugin folder, whose changes make the shell
    // reload the plugin (and so restart this helper).
    command: root.phoneAddress !== ""
      ? ["python3", "-B", root.helperPath, "--phone", root.phoneAddress]
      : ["python3", "-B", root.helperPath]
    running: true
    stdinEnabled: true
    stdout: SplitParser { onRead: function(line) { root.handleLine(line) } }
    stderr: SplitParser { onRead: function(line) { console.warn("omyphone helper: " + line) } }
    onExited: function(exitCode, exitStatus) {
      root.gateways = []
      root.calls = []
      restartTimer.interval = root.nextRestartDelay()
      restartTimer.restart()
    }
  }

  Timer {
    id: restartTimer
    repeat: false
    onTriggered: helper.running = true
  }

  Timer {
    id: errorTimer
    interval: 4000
    onTriggered: {
      root.lastError = ""
      root.lastErrorCmd = ""
    }
  }
}
