import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Ui

// Incoming-call card with Answer and Decline, in the top-right corner where
// Omarchy's notifications appear. Omarchy's notifications cannot show buttons,
// so ringing calls use this card instead. Each bar widget has one; only the one
// on the service's chosen monitor (ringScreen) shows it.
PanelWindow {
  id: root

  property var service: null
  // The bar's screen this card belongs to.
  property var barScreen: null
  readonly property var call: service ? service.ringingCall : null

  // The bar this card belongs to (placement follows its position and size).
  property var bar: null
  readonly property string barPosition: bar ? String(bar.position || "top") : "top"
  readonly property int barSize: bar && bar.barSize > 0
    ? bar.barSize
    : (barPosition === "left" || barPosition === "right" ? Style.bar.sizeVertical : Style.bar.sizeHorizontal)

  screen: barScreen
  visible: call !== null && barScreen !== null && service.ringScreen === barScreen.name
  color: "transparent"
  exclusionMode: ExclusionMode.Ignore
  WlrLayershell.namespace: "omyphone-incoming-call"
  WlrLayershell.layer: WlrLayer.Overlay
  WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

  // Full-screen and click-through except over the card, like Omarchy's
  // notification popups.
  anchors { top: true; bottom: true; left: true; right: true }
  mask: Region { item: card }

  BorderSurface {
    id: card
    anchors.top: parent.top
    anchors.right: parent.right
    anchors.topMargin: root.barPosition === "top" ? root.barSize + Style.gapsOut : Style.gapsOut
    anchors.rightMargin: root.barPosition === "right" ? root.barSize + Style.gapsOut : Style.gapsOut
    implicitWidth: Style.space(380)
    implicitHeight: column.implicitHeight + borderTop + borderBottom + Style.space(20)
    radius: Style.cornerRadius
    color: Color.notifications.background
    borderSpec: Border.surfaceSpec("notifications", "border", Color.notifications.border, Math.max(1, Style.space(2)))

    ColumnLayout {
      id: column
      anchors.fill: parent
      anchors.margins: Style.space(12)
      anchors.topMargin: card.borderTop + Style.space(10)
      spacing: Style.space(4)

      Text {
        Layout.fillWidth: true
        text: "Incoming call"
        color: Color.notifications.text
        font.family: "Liberation Sans"
        font.pixelSize: Style.font.title
        font.bold: true
      }

      Text {
        Layout.fillWidth: true
        text: root.call && root.call.number ? root.call.number : "Unknown number"
        elide: Text.ElideRight
        color: Qt.darker(Color.notifications.text, 1.15)
        font.family: "Liberation Sans"
        font.pixelSize: Style.font.title
      }

      RowLayout {
        Layout.topMargin: Style.space(8)
        spacing: Style.space(8)

        Button {
          text: "Answer"
          active: true
          onClicked: if (root.call) root.service.answer(root.call.path)
        }
        Button {
          text: "Decline"
          onClicked: if (root.call) root.service.decline(root.call.path)
        }
      }
    }
  }
}
