#!/bin/bash
# Copy the working tree into the installed plugin so the Omarchy shell reloads it.
# Install once first:  omarchy plugin add ~/Projects/omyphone --enable
# Before a clean reinstall: omarchy plugin remove omyphone, then add it again.
#
# Only the plugin's own files are copied: what git tracks or would track (so
# git-ignored and local-only files stay out), minus what only
# development needs. Anything else in the installed copy is deleted, except its
# .git (the plugin manager's clone).
set -euo pipefail
export LC_ALL=C  # the same sort order for sort and comm
src="$(cd "$(dirname "$0")/.." && pwd)"
dest="$HOME/.config/omarchy/plugins/omyphone"
if [ ! -d "$dest" ]; then
  echo "omyphone is not installed at $dest; run: omarchy plugin add $src --enable" >&2
  exit 1
fi
list="$(mktemp)"
trap 'rm -f "$list"' EXIT
git -C "$src" ls-files -z --cached --others --exclude-standard \
  | grep -zv -e '^tests/' -e '^docs/' -e '^scripts/' \
  | while IFS= read -r -d '' file; do if [ -e "$src/$file" ]; then printf '%s\0' "$file"; fi; done \
  | sort -zu > "$list"
rsync -a --from0 --files-from="$list" "$src/" "$dest/"
# --files-from never deletes, so remove every other file (and emptied folder).
( cd "$dest" && find . -path ./.git -prune -o -type f -printf '%P\0' | sort -z ) \
  | comm -z -23 - "$list" | ( cd "$dest" && xargs -0 -r rm -f -- )
find "$dest" -mindepth 1 -type d -empty -not -path "$dest/.git" -not -path "$dest/.git/*" -delete
# A plugin rescan reloads the service but not the bar widget's code, so restart
# the whole shell (the bar blinks for a second).
omarchy restart shell >/dev/null 2>&1 || true
echo "synced to $dest"
