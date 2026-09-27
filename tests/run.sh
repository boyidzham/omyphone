#!/bin/bash
# Run every omyphone test. Integration tests get a private D-Bus session bus
# (dbus-run-session), so they never touch the real desktop bus.
# Naming modules (tests/run.sh -v tests.test_protocol) runs only those.
set -euo pipefail
cd "$(dirname "$0")/.."
modules=0
for arg in "$@"; do [[ $arg == -* ]] || modules=1; done
if [ "$modules" = 1 ]; then
  OMYPHONE_TEST_BUS=1 dbus-run-session --config-file=tests/session.conf -- python3 -m unittest "$@"
else
  OMYPHONE_TEST_BUS=1 dbus-run-session --config-file=tests/session.conf -- python3 -m unittest discover -s tests -t . "$@"
  python3 tests/qml_lint.py
  omarchy plugin validate .
fi
