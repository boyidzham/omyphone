import QtQuick
import qs.Commons
import "Format.js" as Format

// The newest recent calls (or only the missed ones). Click one to call it back.
Column {
  id: root

  property var phone: null
  property real now: Date.now()
  property bool missedOnly: false
  readonly property var entries: phone
    ? phone.recents.filter(function(e) { return !missedOnly || e.direction === "missed" }).slice(0, 10)
    : []

  spacing: Style.space(2)

  Text {
    visible: root.entries.length === 0
    width: parent.width
    horizontalAlignment: Text.AlignHCenter
    text: root.missedOnly ? "No missed calls" : "No recent calls"
    color: Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }

  Repeater {
    model: root.entries

    MouseArea {
      id: row
      required property var modelData
      width: root.width
      height: Style.space(44)
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: if (root.phone && modelData.number !== "") root.phone.dial(modelData.number)

      Rectangle {
        anchors.fill: parent
        radius: Style.cornerRadius
        color: row.containsMouse ? Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.08) : "transparent"
      }

      readonly property bool missed: modelData.direction === "missed"

      // Nerd Font phone-missed / phone-incoming / phone-outgoing.
      Text {
        id: icon
        anchors.left: parent.left
        anchors.leftMargin: Style.space(8)
        anchors.verticalCenter: parent.verticalCenter
        text: row.missed ? "󰏺" : row.modelData.direction === "incoming" ? "󰏷" : "󰏻"
        color: row.missed ? Color.urgent : Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.title
      }

      Column {
        anchors.left: icon.right
        anchors.leftMargin: Style.space(10)
        anchors.verticalCenter: parent.verticalCenter

        Text {
          text: Format.displayNumber(row.modelData.number)
          color: row.missed ? Color.urgent : Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }
        Text {
          text: Format.recentDetail(row.modelData, root.now)
          color: row.missed ? Color.urgent : Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }
      }
    }
  }
}
