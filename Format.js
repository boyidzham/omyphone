.pragma library

// Display strings for the omyphone widgets.

function pad(n) { return (n < 10 ? "0" : "") + n }

// 75 -> "01:15", 3725 -> "1:02:05"
function duration(seconds) {
  var s = Math.max(0, Math.floor(seconds))
  var h = Math.floor(s / 3600)
  var m = Math.floor((s % 3600) / 60)
  var rest = s % 60
  return h > 0 ? h + ":" + pad(m) + ":" + pad(rest) : pad(m) + ":" + pad(rest)
}

// epochSeconds relative to nowMs: "just now", "5 min ago", "3 h ago", "27 Sep"
function relativeTime(epochSeconds, nowMs) {
  var diff = Math.floor(nowMs / 1000) - epochSeconds
  if (diff < 60) return "just now"
  if (diff < 3600) return Math.floor(diff / 60) + " min ago"
  if (diff < 86400) return Math.floor(diff / 3600) + " h ago"
  var d = new Date(epochSeconds * 1000)
  var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
  return d.getDate() + " " + months[d.getMonth()]
}

function directionLabel(direction) {
  return direction === "missed" ? "Missed" : direction === "incoming" ? "Incoming" : "Outgoing"
}

function recentDetail(entry, nowMs) {
  var parts = [directionLabel(entry.direction), relativeTime(entry.start, nowMs)]
  if (entry.duration > 0) parts.push(duration(entry.duration))
  return parts.join(" · ")
}

function callStatus(state, activeSince, nowMs) {
  switch (state) {
  case "dialing": return "Calling…"
  case "alerting": return "Ringing…"
  case "incoming":
  case "waiting": return "Incoming call"
  case "held": return "On hold"
  case "disconnected": return "Call ended"
  case "active": return activeSince > 0 ? duration((nowMs - activeSince) / 1000) : "Connected"
  }
  return state
}

function displayNumber(number) {
  return number && number !== "" ? number : "Unknown number"
}

// Title for a call or a recent entry: the contact name, else the number.
function title(entry) {
  return entry && entry.name ? entry.name : displayNumber(entry ? entry.number : "")
}

// Contacts search: every word of the query appears in the name, or the query's
// digits appear in the number's digits.
function matchesContact(row, query) {
  var q = query.trim().toLowerCase()
  if (q === "") return true
  var name = row.name.toLowerCase()
  if (q.split(/\s+/).every(function(word) { return name.indexOf(word) >= 0 })) return true
  var digits = q.replace(/\D/g, "")
  return digits !== "" && row.number.replace(/\D/g, "").indexOf(digits) >= 0
}

function syncedText(epochSeconds, nowMs) {
  return epochSeconds > 0 ? "Synced " + relativeTime(epochSeconds, nowMs) : ""
}

function contactsSetupText(status) {
  switch (status.state) {
  case "needs-install": return "Needs the bluez-obex package. A terminal will ask for your password."
  case "syncing": return "Syncing…"
  case "needs-permission": return "On your phone, allow contact sharing. iPhone: Settings > Bluetooth > (i) next to this PC > Sync Contacts."
  case "error": return status.message
  case "ready": return "No contacts on the phone."
  }
  return "Show caller names and call people by name, using the contacts on your phone."
}

function contactsSetupButton(state) {
  return state === "off" || state === "needs-install" ? "Sync contacts" : "Try again"
}
