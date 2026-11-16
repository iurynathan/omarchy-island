#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SHELL_JSON="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/shell.json"
AUTOSTART_LUA="${XDG_CONFIG_HOME:-$HOME/.config}/hypr/autostart.lua"
STAMP="$(date +%s)"

if command -v omarchy >/dev/null 2>&1; then
  omarchy hook install theme-set "$HERE/hooks/20-omarchy-island-theme"
fi

if [[ -f "$SHELL_JSON" ]]; then
  cp "$SHELL_JSON" "${SHELL_JSON}.bak.${STAMP}"
  python3 - "$SHELL_JSON" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path) as f:
    data = json.load(f)

layout = data.setdefault("bar", {}).setdefault("layout", {})
drop_ids = {"omarchy.clock", "omarchy.weather", "omarchy.elsewhen"}

layout["centerBegin"] = [
    item for item in layout.get("centerBegin", [{"id": "omarchy.indicators"}])
    if isinstance(item, dict) and item.get("id") not in drop_ids
] or [{"id": "omarchy.indicators"}]

layout["center"] = [{"id": "omarchy.spacer", "size": 158}]

layout["centerEnd"] = [
    item for item in layout.get("centerEnd", [])
    if isinstance(item, dict) and item.get("id") not in drop_ids
]

with open(path, "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
PY
fi

if [[ -f "$AUTOSTART_LUA" ]]; then
  cp "$AUTOSTART_LUA" "${AUTOSTART_LUA}.bak.${STAMP}"
  LINE="o.launch_on_start(\"$HERE/run.sh\")"
  if ! grep -Fq "$HERE/run.sh" "$AUTOSTART_LUA"; then
    printf '\n%s\n' "$LINE" >> "$AUTOSTART_LUA"
  fi
  if command -v hyprctl >/dev/null 2>&1; then
    hyprctl reload >/dev/null 2>&1 || true
  fi
fi

echo "omarchy-island instalado e integrado ao Omarchy."
