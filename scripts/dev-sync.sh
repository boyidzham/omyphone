#!/bin/bash
# Copy the working tree into the installed plugin so the Omarchy shell reloads it.
# Install once first:  omarchy plugin add ~/Projects/omyphone --enable
# Before a clean reinstall: omarchy plugin remove omyphone, then add it again.
set -euo pipefail
src="$(cd "$(dirname "$0")/.." && pwd)"
dest="$HOME/.config/omarchy/plugins/omyphone"
if [ ! -d "$dest" ]; then
  echo "omyphone is not installed at $dest; run: omarchy plugin add $src --enable" >&2
  exit 1
fi
rsync -a --delete --exclude .git --exclude tests --exclude docs --exclude scripts --exclude '__pycache__' "$src/" "$dest/"
# A plugin rescan reloads the service but not the bar widget's code, so restart
# the whole shell (the bar blinks for a second).
omarchy restart shell >/dev/null 2>&1 || true
echo "synced to $dest"
