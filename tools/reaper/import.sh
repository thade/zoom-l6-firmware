#!/bin/bash
# Import a take from the mixer's card into a REAPER project, asking which take
# and what to call the project.
#
#   tools/reaper/import.sh [folder] [card]
#
# folder: where the project folder goes (default: the folder you run it from).
# card:   the card's top folder (default: the one L6 card mounted under /Volumes).
#
# With no card mounted, the mixer is put into File Transfer Mode over USB
# (connect it by USB and quit ZOOM L6 Editor first). Then the script lists
# the last five takes on the card, asks which one, asks for a project name
# (default: the take's name) and a tempo, and runs import_take.py, which copies the take
# and everything it contains to <folder>/<name>/ and writes <name>.RPP there.
# When the script put the mixer into File Transfer Mode, it ejects the card
# and leaves that mode afterwards, also when it is interrupted or fails.
# See import_take.py for what the project holds.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
python="$root/.venv/bin/python"
[ -x "$python" ] || python=python3
volumes=${L6_VOLUMES:-/Volumes}                                     # the checks point these three at stand-ins
transfer=${L6_TRANSFER_MODE:-$root/tools/device/l6_transfer_mode.py}
eject=${L6_EJECT:-diskutil eject}
dest=${1:-.}
card=${2:-}
entered=

leave() {   # runs on every exit once the script has put the mixer into File Transfer Mode
  [ -n "$entered" ] || return 0
  entered=
  echo "Ejecting the card and leaving File Transfer Mode..."
  $eject "$card" || echo "Could not eject the card: eject it yourself, then leave File Transfer Mode from ZOOM L6 Editor" >&2
  "$python" "$transfer" exit >/dev/null || echo "Could not leave File Transfer Mode: leave it from ZOOM L6 Editor, or switch the mixer off and on" >&2
}
trap leave EXIT
trap 'exit 130' INT TERM

mounted_cards() {
  found=()
  for v in "$volumes"/*/; do
    [ -d "$v/SOUND_PAD/PAD4" ] && [ -d "$v/RECORDER" ] && found+=("${v%/}")
  done
  echo "${#found[@]}"
}

if [ -z "$card" ]; then
  if [ "$(mounted_cards)" -eq 0 ]; then
    echo "No card is mounted. Putting the mixer into File Transfer Mode (it must be connected by USB, with ZOOM L6 Editor closed)..."
    if result=$("$python" "$transfer" enter 2>&1); then
      case $result in
        *'"card_mounted": true'*) entered=1 ;;
        *) echo "The mixer did not show its card: $result" >&2; exit 1 ;;
      esac
    else
      echo "No mixer found: $result" >&2
      echo "Connect the mixer by USB, or put the card in a card reader, or name the card's folder: $0 [folder] [card]" >&2
      exit 1
    fi
  fi
  mounted_cards >/dev/null
  case ${#found[@]} in
    1) card=${found[0]} ;;
    0) echo "No L6 card is mounted under $volumes" >&2; exit 1 ;;
    *) echo "More than one L6 card is mounted (${found[*]}). Name one: $0 [folder] [card]" >&2; exit 1 ;;
  esac
fi
[ -d "$card/RECORDER" ] || { echo "$card has no RECORDER folder" >&2; exit 1; }

lines=()
while IFS= read -r line; do lines+=("$line"); done < <("$python" "$here/import_take.py" --list 5 "$card")
[ ${#lines[@]} -gt 0 ] || { echo "No takes on $card" >&2; exit 1; }
echo "The last ${#lines[@]} takes on $card:"
i=1
for line in "${lines[@]}"; do
  printf '  %d) %s\n' "$i" "$line"
  i=$((i+1))
done
while :; do
  read -r -p "Which take? [1-${#lines[@]}] " choice
  [[ $choice =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#lines[@]}" ] && break
done
take=${lines[$((choice-1))]%% *}
read -r -p "Project name [$take]: " name
name=${name:-$take}
case $name in
  */*) echo "A project name cannot contain /" >&2; exit 1 ;;
esac
while :; do
  read -r -p "Project tempo in BPM [120]: " bpm
  bpm=${bpm:-120}
  [[ $bpm =~ ^[0-9]+([.][0-9]+)?$ ]] && break
done
echo
"$python" "$here/import_take.py" "$card" "$take" --out "$dest/$name" --name "$name" --bpm "$bpm"
