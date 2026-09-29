import QtQuick
import qs.Commons
import qs.Ui
import "Format.js" as Format

// Shown while a call exists: number, status or timer, and call controls.
Column {
  id: root

  property var phone: null
  property var call: null
  property real now: Date.now()
  property bool showKeypad: false
  property alias keypad: dtmfPad
  readonly property bool ringing: call !== null && (call.state === "incoming" || call.state === "waiting")

  spacing: Style.space(10)

  onCallChanged: if (!call) showKeypad = false

  Text {
    width: parent.width
    horizontalAlignment: Text.AlignHCenter
    elide: Text.ElideRight
    text: root.call ? Format.title(root.call) : ""
    textFormat: Text.PlainText
    color: Color.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.title
  }

  Text {
    visible: root.call !== null && root.call.name !== ""
    width: parent.width
    horizontalAlignment: Text.AlignHCenter
    elide: Text.ElideRight
    text: root.call ? Format.displayNumber(root.call.number) : ""
    textFormat: Text.PlainText
    color: Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }

  Text {
    width: parent.width
    horizontalAlignment: Text.AlignHCenter
    text: root.call ? Format.callStatus(root.call.state, root.call.since, root.now) : ""
    textFormat: Text.PlainText
    color: Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }

  KeypadView {
    id: dtmfPad
    visible: root.showKeypad
    width: parent.width
    dtmf: true
    phone: root.phone
  }

  Row {
    anchors.horizontalCenter: parent.horizontalCenter
    spacing: Style.space(6)

    Button {
      visible: root.ringing
      text: "Answer"
      active: true
      onClicked: root.phone.answer(root.call.path)
    }
    Button {
      visible: root.ringing
      text: "Decline"
      onClicked: root.phone.decline(root.call.path)
    }
    Button {
      visible: !root.ringing
      text: root.phone && root.phone.muted ? "Unmute" : "Mute"
      selected: root.phone ? root.phone.muted : false
      onClicked: root.phone.setMuted(!root.phone.muted)
    }
    Button {
      visible: !root.ringing
      text: "Keypad"
      selected: root.showKeypad
      onClicked: root.showKeypad = !root.showKeypad
    }
    Button {
      visible: !root.ringing
      text: "Hang up"
      onClicked: root.phone.hangup(root.call.path)
    }
  }
}
