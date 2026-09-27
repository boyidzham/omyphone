import QtQuick
import qs.Commons
import "Format.js" as Format

// The newest recent calls. Click one to call it back.
Column {
  id: root

  property var phone: null
  property real now: Date.now()
  readonly property var entries: phone ? phone.recents.slice(0, 10) : []

  spacing: Style.space(2)

  Text {
    visible: root.entries.length === 0
    width: parent.width
    horizontalAlignment: Text.AlignHCenter
    text: "No recent calls"
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

      Column {
        anchors.left: parent.left
        anchors.leftMargin: Style.space(8)
        anchors.verticalCenter: parent.verticalCenter

        Text {
          text: Format.displayNumber(row.modelData.number)
          color: row.modelData.direction === "missed" ? Color.urgent : Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }
        Text {
          text: Format.recentDetail(row.modelData, root.now)
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }
      }
    }
  }
}
