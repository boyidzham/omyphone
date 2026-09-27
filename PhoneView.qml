import QtQuick
import qs.Commons
import qs.Ui

// Popup body: not-connected notice, in-call controls, or Keypad/Recent tabs.
Column {
  id: root

  property var phone: null
  property real now: Date.now()
  property string tab: "keypad"
  readonly property var call: phone ? phone.currentCall : null
  readonly property bool ready: phone ? phone.ready : false

  spacing: Style.space(12)

  function typeKey(text) {
    if (call) { if (inCall.showKeypad) inCall.keypad.typeKey(text); return }
    if (ready && tab === "keypad") keypad.typeKey(text)
  }
  function submit() {
    if (!call && ready && tab === "keypad") keypad.call()
  }

  onCallChanged: if (call) keypad.number = ""

  Connections {
    target: root.phone
    function onShowRequested(tab) { root.tab = tab }
  }

  Text {
    visible: !root.ready
    width: parent.width
    horizontalAlignment: Text.AlignHCenter
    wrapMode: Text.Wrap
    text: !root.phone ? "Starting…"
      : !root.phone.phone.found ? "No phone paired"
      : !root.phone.phone.powered ? "Bluetooth is off"
      : "Phone not connected\n" + root.phone.phone.name
    color: Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }

  InCallView {
    id: inCall
    visible: root.call !== null
    width: parent.width
    phone: root.phone
    call: root.call
    now: root.now
  }

  ButtonGroup {
    visible: root.ready && root.call === null
    width: parent.width
    options: [{ value: "keypad", label: "Keypad" }, { value: "recent", label: "Recent" }, { value: "missed", label: "Missed" }]
    value: root.tab
    onChanged: function(value) { root.tab = value }
  }

  KeypadView {
    id: keypad
    visible: root.ready && root.call === null && root.tab === "keypad"
    width: parent.width
    phone: root.phone
  }

  RecentsView {
    visible: root.ready && root.call === null && root.tab === "recent"
    width: parent.width
    phone: root.phone
    now: root.now
  }

  RecentsView {
    visible: root.ready && root.call === null && root.tab === "missed"
    width: parent.width
    phone: root.phone
    now: root.now
    missedOnly: true
  }

  Text {
    visible: root.phone !== null && root.phone.lastError !== ""
    width: parent.width
    horizontalAlignment: Text.AlignHCenter
    wrapMode: Text.Wrap
    text: root.phone ? root.phone.lastError : ""
    color: Color.urgent
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
  }
}
