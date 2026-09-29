import QtQuick
import qs.Commons
import qs.Ui

// A call-control button filled with one color (Answer green, Decline and
// Hang up red), a little lighter under the mouse. The text is dark or light,
// whichever reads better on the fill. With filled false, only the text has the
// color (the keypad's Call before a number is typed).
Button {
  id: root

  property color fill: "transparent"
  property bool filled: true

  background: filled ? fill : "transparent"
  foreground: !filled ? fill
    : 0.299 * fill.r + 0.587 * fill.g + 0.114 * fill.b > 0.6 ? "#111111" : "#ffffff"
  color: filled ? (hot ? Qt.lighter(fill, 1.15) : fill)
    : (hot ? Style.hoverFillFor(foreground, accent) : "transparent")
}
