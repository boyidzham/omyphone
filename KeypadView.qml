import QtQuick
import qs.Commons
import qs.Ui

// Number entry with a 3x4 keypad and Call. With dtmf: true it is the in-call
// keypad: each press is sent to the phone as a tone and there is no Call row.
Column {
  id: root

  property var phone: null
  property bool dtmf: false
  property string number: ""

  spacing: Style.space(8)

  function press(key) {
    if (dtmf && phone) phone.sendTones(key)
    if (number.length < 32) number += key
  }
  function backspace() { number = number.slice(0, -1) }
  function call() { if (phone && number !== "") phone.dial(number) }
  function typeKey(text) {
    if ("0123456789*#".indexOf(text) >= 0) press(text)
    else if (text === "+" && !dtmf && number === "") press(text)
    else if (text === "\b" || text === "\u007f") backspace()
  }

  Text {
    width: parent.width
    horizontalAlignment: Text.AlignHCenter
    elide: Text.ElideLeft
    text: root.number !== "" ? root.number : (root.dtmf ? " " : "Enter a number")
    color: root.number !== "" ? Color.foreground : Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.title
  }

  Grid {
    anchors.horizontalCenter: parent.horizontalCenter
    columns: 3
    spacing: Style.space(6)

    Repeater {
      model: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"]
      Button {
        required property string modelData
        width: Style.space(72)
        text: modelData
        onClicked: root.press(modelData)
      }
    }
  }

  Row {
    visible: !root.dtmf
    anchors.horizontalCenter: parent.horizontalCenter
    spacing: Style.space(6)

    Button {
      width: Style.space(72)
      text: "+"
      onClicked: if (root.number === "") root.press("+")
    }
    Button {
      width: Style.space(72)
      text: "⌫"
      tooltipText: "Delete"
      onClicked: root.backspace()
    }
    Button {
      width: Style.space(72)
      text: "Call"
      active: root.number !== ""
      onClicked: root.call()
    }
  }
}
