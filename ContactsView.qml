import QtQuick
import qs.Commons
import qs.Ui
import "Format.js" as Format

// Contacts synced from the phone: type to search, click (or Enter) to call.
// Before the first sync it shows the setup: install bluez-obex, then allow
// sharing on the phone. The helper does the work; this only shows its state.
Column {
  id: root

  property var phone: null
  property real now: Date.now()
  property int selected: 0
  readonly property Item searchField: search
  readonly property var status: phone ? phone.contactsStatus : ({ state: "off", enabled: false, synced: 0, message: "" })
  readonly property var all: phone ? phone.contacts : []
  readonly property bool setup: all.length === 0
  readonly property var shown: all.filter(function(r) { return Format.matchesContact(r, search.text) })
  readonly property int rowHeight: Style.space(44)

  signal closeRequested()
  signal tabRequested(int direction)

  spacing: Style.space(8)

  onShownChanged: selected = 0

  function focusSearch() { if (!setup) search.forceActiveFocus() }
  function typeKey(text) {
    if (setup) return
    if (text === "\b" || text === "\u007f") search.text = search.text.slice(0, -1)
    else search.text += text
    search.forceActiveFocus()
  }
  function callSelected() {
    if (phone && shown.length > 0) phone.dial(shown[Math.min(selected, shown.length - 1)].number)
  }

  // Setup: shown until the phone has sent contacts.
  Column {
    visible: root.setup
    width: parent.width
    spacing: Style.space(10)

    Text {
      width: parent.width
      horizontalAlignment: Text.AlignHCenter
      wrapMode: Text.Wrap
      text: Format.contactsSetupText(root.status)
      color: root.status.state === "error" ? Color.urgent : Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }

    Button {
      anchors.horizontalCenter: parent.horizontalCenter
      visible: root.status.state !== "syncing"
      text: Format.contactsSetupButton(root.status.state)
      active: true
      onClicked: {
        if (!root.phone) return
        if (root.status.state === "needs-install") root.phone.installContacts()
        else root.phone.syncContacts()
      }
    }
  }

  Row {
    visible: !root.setup
    width: parent.width
    spacing: Style.space(6)

    TextField {
      id: search
      width: parent.width - refresh.width - parent.spacing
      placeholderText: "Search " + root.all.length + " contacts"
      rightPadding: horizontalPadding + Border.right(_borderSpec) + clear.width
      Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Escape) {
          // First Esc clears the search, the next one closes the popup.
          if (search.text !== "") search.clear()
          else root.closeRequested()
        } else if (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab) {
          root.tabRequested((event.modifiers & Qt.ShiftModifier) || event.key === Qt.Key_Backtab ? -1 : 1)
        } else if (event.key === Qt.Key_Down) {
          root.selected = Math.min(root.selected + 1, root.shown.length - 1)
        } else if (event.key === Qt.Key_Up) {
          root.selected = Math.max(root.selected - 1, 0)
        } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
          root.callSelected()
        } else {
          return
        }
        event.accepted = true
      }

      // Clear button, shown only while there is text.
      MouseArea {
        id: clear
        visible: search.text !== ""
        anchors.right: parent.right
        anchors.rightMargin: Style.space(4)
        anchors.verticalCenter: parent.verticalCenter
        width: Style.space(20)
        height: Style.space(20)
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
          search.clear()
          search.forceActiveFocus()
        }

        Text {
          anchors.centerIn: parent
          text: "✕"
          color: clear.containsMouse ? Color.foreground : Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }
      }
    }

    Button {
      id: refresh
      anchors.verticalCenter: parent.verticalCenter
      text: "󰑐"
      onClicked: if (root.phone) root.phone.syncContacts()
    }
  }

  Text {
    visible: !root.setup && root.shown.length === 0
    width: parent.width
    horizontalAlignment: Text.AlignHCenter
    text: "No matches"
    color: Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }

  // All matches, 8 rows high; scroll with the wheel, or Up/Down from the search.
  ListView {
    id: list
    visible: !root.setup && count > 0
    width: parent.width
    height: Math.min(count, 8) * (root.rowHeight + spacing) - spacing
    spacing: Style.space(2)
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    model: root.shown
    currentIndex: root.selected
    highlightFollowsCurrentItem: false
    onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)

    delegate: MouseArea {
      id: row
      required property var modelData
      required property int index
      width: list.width
      height: root.rowHeight
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: if (root.phone) root.phone.dial(modelData.number)

      Rectangle {
        anchors.fill: parent
        radius: Style.cornerRadius
        color: row.containsMouse || row.index === root.selected
          ? Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.08) : "transparent"
      }

      Column {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: Style.space(8)
        anchors.rightMargin: Style.space(8)
        anchors.verticalCenter: parent.verticalCenter

        // A contact without a name shows its number on top, and only the label below.
        Text {
          width: parent.width
          elide: Text.ElideRight
          text: Format.title(row.modelData)
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }
        Text {
          width: parent.width
          elide: Text.ElideRight
          text: [row.modelData.name ? row.modelData.number : "", row.modelData.label]
            .filter(function(part) { return part !== "" }).join(" · ")
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }
      }
    }
  }

  Text {
    visible: !root.setup
    width: parent.width
    horizontalAlignment: Text.AlignHCenter
    wrapMode: Text.Wrap
    text: root.status.state === "error" ? root.status.message
      : root.status.state === "needs-permission" ? "The phone is not sharing contacts"
      : root.status.state === "syncing" ? "Syncing…"
      : Format.syncedText(root.status.synced, root.now)
    color: root.status.state === "error" ? Color.urgent : Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
  }
}
