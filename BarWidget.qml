import QtQuick
import qs.Commons
import qs.Ui
import "Format.js" as Format

// Bar icon plus the popup under it. The service (Service.qml) holds all state;
// this only shows it. One instance per monitor bar.
Panel {
  id: root
  moduleName: "omyphone"
  ipcTarget: "omyphone"

  property var phone: null
  property real now: Date.now()
  readonly property bool ready: phone ? phone.ready : false
  readonly property var call: phone ? phone.currentCall : null
  readonly property string timerText: call && phone.activeSince > 0 ? Format.duration((now - phone.activeSince) / 1000) : ""

  implicitWidth: row.implicitWidth
  implicitHeight: button.implicitHeight

  // The service may start after the widget, or be recreated on hot reload.
  Timer {
    interval: 1000
    repeat: true
    triggeredOnStart: true
    running: !root.phone
    onTriggered: if (root.bar && root.bar.shell) root.phone = root.bar.shell.serviceFor("omyphone")
  }

  Timer {
    interval: 1000
    repeat: true
    running: root.call !== null || root.opened
    onTriggered: root.now = Date.now()
  }

  Row {
    id: row
    anchors.fill: parent
    spacing: Style.space(4)

    BarIconButton {
      id: button
      bar: root.bar
      text: root.call ? "󰏶" : "󰏲"
      dimmed: !root.ready
      active: root.call !== null
      tooltipText: !root.phone ? "Phone" : root.call ? "In call" : root.ready ? "Phone ready" : "Phone not connected"
      onPressed: function(b) { if (b === Qt.LeftButton) root.toggle() }
    }

    Text {
      visible: root.timerText !== ""
      anchors.verticalCenter: parent.verticalCenter
      text: root.timerText
      color: root.bar ? root.bar.foreground : Color.foreground
      font.family: root.bar ? root.bar.fontFamily : Style.font.family
      font.pixelSize: Style.font.caption
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(320))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(text) { content.typeKey(text) }
      onDeleteRequested: content.typeKey("\b")
      onReturnRequested: content.submit()

      PhoneView {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        phone: root.phone
        now: root.now
      }
    }
  }
}
