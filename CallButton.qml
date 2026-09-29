import QtQuick
import qs.Ui

// A call-control button filled with one color (Answer green, Decline and
// Hang up red), a little lighter under the mouse. The text is dark or light,
// whichever reads better on the fill.
Button {
  id: root

  property color fill: "transparent"

  background: fill
  foreground: 0.299 * fill.r + 0.587 * fill.g + 0.114 * fill.b > 0.6 ? "#111111" : "#ffffff"
  color: hot ? Qt.lighter(fill, 1.15) : fill
}
