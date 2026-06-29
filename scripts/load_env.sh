#!/usr/bin/env bash
# Safely export a .env file WITHOUT letting the shell evaluate it.
#
# `source .env` is dangerous: a value with a space (e.g. SAT_OWNER=Samaraho
# Mukherjee) makes bash try to run `Mukherjee` as a command. This reads each
# KEY=VALUE line literally and exports it as a single argument, so spaces and
# special characters never break anything. Surrounding quotes are stripped.
#
# Usage:  source scripts/load_env.sh ; load_env [path-to-.env]
load_env() {
  local f="${1:-.env}" line key val
  [[ -f "$f" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"                       # strip CR (CRLF files)
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" != *=* ]] && continue
    key="${line%%=*}"; key="${key//[[:space:]]/}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    val="${line#*=}"
    if [[ "$val" == \"*\" && ${#val} -ge 2 ]]; then val="${val:1:${#val}-2}"
    elif [[ "$val" == \'*\' && ${#val} -ge 2 ]]; then val="${val:1:${#val}-2}"; fi
    export "$key=$val"                         # one arg → spaces are safe
  done < "$f"
}
