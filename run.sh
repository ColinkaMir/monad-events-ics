#!/usr/bin/env bash
# Rebuild the calendar and publish it only when it changed.
set -uo pipefail
cd "$(dirname "$0")"
python3 build.py; rc=$?
DST=/var/www/proofline-public/monad/events
for f in monad.ics index.html; do
    # The page carries an "Updated" stamp, so compare it without that line.
    if [ "$f" = index.html ]; then
        cmp -s <(grep -v 'Updated ' "out/$f") <(grep -v 'Updated ' "$DST/$f" 2>/dev/null) && continue
    else
        cmp -s "out/$f" "$DST/$f" && continue
    fi
    sudo -n install -o www-data -g www-data -m 644 "out/$f" "$DST/$f" && echo "published $f"
done
exit $rc
