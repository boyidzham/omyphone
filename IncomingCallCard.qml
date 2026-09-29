import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui
import "Format.js" as Format

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

  // Answer is the theme's green, Decline its red. The shell only shares red
  // (Color.urgent), so green is read from the theme's colors.toml, again
  // whenever the shell's colors change (a theme switch).
  property color answerColor: "#4caf50"
  readonly property color declineColor: Color.urgent

  function textOn(fill) {
    return 0.299 * fill.r + 0.587 * fill.g + 0.114 * fill.b > 0.6 ? "#111111" : "#ffffff"
  }

  FileView {
    id: themeColors
    path: Color.currentThemePath + "/colors.toml"
    printErrors: false
    onLoaded: {
      var match = text().match(/^\s*(?:green|color2)\s*=\s*["']?(#[0-9A-Fa-f]{6})/m)
      if (match) root.answerColor = match[1]
    }
  }

  Connections {
    target: Color
    function onBackgroundChanged() { themeColors.reload() }
    function onUrgentChanged() { themeColors.reload() }
    function onAccentChanged() { themeColors.reload() }
  }

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
        textFormat: Text.PlainText
        color: Color.notifications.text
        font.family: "Liberation Sans"
        font.pixelSize: Style.font.title
        font.bold: true
      }

      Text {
        Layout.fillWidth: true
        text: Format.title(root.call)
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: Qt.darker(Color.notifications.text, 1.15)
        font.family: "Liberation Sans"
        font.pixelSize: Style.font.title
      }

      Text {
        Layout.fillWidth: true
        visible: root.call !== null && root.call.name !== ""
        text: root.call ? Format.displayNumber(root.call.number) : ""
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: Qt.darker(Color.notifications.text, 1.4)
        font.family: "Liberation Sans"
        font.pixelSize: Style.font.body
      }

      // A failed Answer or Decline (the popup may be closed, so say it here).
      Text {
        Layout.fillWidth: true
        visible: root.service !== null && root.service.lastError !== ""
          && (root.service.lastErrorCmd === "answer" || root.service.lastErrorCmd === "decline")
        text: root.service ? root.service.lastError : ""
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: Color.urgent
        font.family: "Liberation Sans"
        font.pixelSize: Style.font.body
      }

      RowLayout {
        Layout.topMargin: Style.space(8)
        spacing: Style.space(8)

        Button {
          text: "Answer"
          background: root.answerColor
          foreground: root.textOn(root.answerColor)
          color: hot ? Qt.lighter(root.answerColor, 1.15) : root.answerColor
          onClicked: if (root.call) root.service.answer(root.call.path)
        }
        Button {
          text: "Decline"
          background: root.declineColor
          foreground: root.textOn(root.declineColor)
          color: hot ? Qt.lighter(root.declineColor, 1.15) : root.declineColor
          onClicked: if (root.call) root.service.decline(root.call.path)
        }
      }
    }
  }
}
