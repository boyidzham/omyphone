#!/bin/bash
# Run every omyphone test. Integration tests get a private D-Bus session bus
# (dbus-run-session), so they never touch the real desktop bus.
set -euo pipefail
cd "$(dirname "$0")/.."
OMYPHONE_TEST_BUS=1 dbus-run-session -- python3 -m unittest discover -s tests -t . "$@"
