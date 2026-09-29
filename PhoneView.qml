import QtQuick
import qs.Commons
import qs.Ui

// Popup body: not-connected notice, in-call controls, or Keypad/Recent/Missed/Contacts tabs.
Column {
  id: root

  property var phone: null
  property real now: Date.now()
  property string tab: "keypad"
  readonly property var call: phone ? phone.currentCall : null
  readonly property bool ready: phone ? phone.ready : false
  readonly property bool onContacts: ready && call === null && tab === "contacts"
  // The Contacts search field needs every key (the key catcher eats j/k/h/l/x).
  readonly property bool wantsKeys: onContacts && contactsView.searchField.activeFocus
  readonly property Item focusItem: onContacts && !contactsView.setup ? contactsView.searchField : null

  signal closeRequested()
  signal tabRequested(int direction)
  signal keysReleased()

  onWantsKeysChanged: if (!wantsKeys) keysReleased()
  onOnContactsChanged: if (onContacts) Qt.callLater(contactsView.focusSearch)

  spacing: Style.space(12)

  function typeKey(text) {
    if (call) { if (inCall.showKeypad) inCall.keypad.typeKey(text); return }
    if (ready && tab === "keypad") keypad.typeKey(text)
    if (onContacts) contactsView.typeKey(text)
  }
  function submit() {
    if (!call && ready && tab === "keypad") keypad.call()
    else if (onContacts) contactsView.callSelected()
  }

  onCallChanged: if (call) keypad.number = ""

  Connections {
    target: root.phone
    function onShowRequested(tab) { root.tab = tab }
  }

  PanelHero {
    width: parent.width
    title: "OMyPhone"
    meta: !root.phone || !root.phone.phone.found ? "No phone paired"
      : root.ready ? root.phone.phone.name + " · Connected"
      : root.phone.phone.name + " · Not connected"
    iconOpacity: root.ready ? 1.0 : 0.5
    iconComponent: Component {
      Text {
        text: "󰏲"
        textFormat: Text.PlainText
        color: Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.display
      }
    }
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
    textFormat: Text.PlainText
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
    options: [{ value: "keypad", label: "Keypad" }, { value: "recent", label: "Recent" }, { value: "missed", label: "Missed" }, { value: "contacts", label: "Contacts" }]
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

  ContactsView {
    id: contactsView
    visible: root.onContacts
    width: parent.width
    phone: root.phone
    now: root.now
    onCloseRequested: root.closeRequested()
    onTabRequested: function(direction) { root.tabRequested(direction) }
  }

  Text {
    visible: root.phone !== null && root.phone.lastError !== ""
    width: parent.width
    horizontalAlignment: Text.AlignHCenter
    wrapMode: Text.Wrap
    text: root.phone ? root.phone.lastError : ""
    textFormat: Text.PlainText
    color: Color.urgent
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
  }
}
