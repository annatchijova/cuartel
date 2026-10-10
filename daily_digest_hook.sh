#!/bin/bash
# ROADMAP.md Level 4: fires on every Claude Code SessionStart, but only
# actually runs `render.py digest` once per calendar day -- a marker file
# tracks the last day it ran. On a throttled day it exits silently with no
# systemMessage, so opening a dozen sessions in one day doesn't nag.
set -u

MARKER="/home/labestiadevigia/cuartel/.digest_last_run"
TODAY=$(date +%Y-%m-%d)

if [ -f "$MARKER" ] && [ "$(cat "$MARKER")" = "$TODAY" ]; then
    exit 0
fi

echo "$TODAY" > "$MARKER"
OUTPUT=$(cd /home/labestiadevigia/cuartel && /usr/bin/python3 render.py digest 2>&1)

/usr/bin/python3 -c "
import json, sys
print(json.dumps({'systemMessage': 'CUARTEL daily digest:\n' + sys.stdin.read()}))
" <<< "$OUTPUT"

exit 0
