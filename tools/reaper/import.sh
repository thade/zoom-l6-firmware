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
# and leaves that mode afterwards, also when it is interrupted or fails. When
# the mixer was already in that mode, the script asks whether to do the same.
# See import_take.py for what the project holds.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
python="$root/.venv/bin/python"
[ -x "$python" ] || python=python3
volumes=${L6_VOLUMES:-/Volumes}                                     # the checks point these four at stand-ins
transfer=${L6_TRANSFER_MODE:-$root/tools/device/l6_transfer_mode.py}
eject=${L6_EJECT:-diskutil eject}
diskinfo=${L6_DISKINFO:-diskutil info}
dest=${1:-.}
card=${2:-}
restore=

leave() {   # runs on every exit once the mixer is to be taken out of File Transfer Mode
  [ -n "$restore" ] || return 0
  restore=
  echo "Ejecting the card and leaving File Transfer Mode..."
  $eject "$card" || echo "Could not eject the card: eject it yourself, then leave File Transfer Mode from ZOOM L6 Editor" >&2
  "$python" "$transfer" exit >/dev/null || echo "Could not leave File Transfer Mode: leave it from ZOOM L6 Editor, or switch the mixer off and on" >&2
}
trap leave EXIT
trap 'exit 130' INT TERM

mounted_cards() {   # the volumes laid out as an L6 card, as l6_transfer_mode.py counts them
  found=()
  for v in "$volumes"/*/; do
    [ -d "$v/RECORDER" ] && [ -d "$v/SOUND_PAD/PAD1" ] && [ -d "$v/SOUND_PAD/PAD2" ] && [ -d "$v/SOUND_PAD/PAD3" ] && [ -d "$v/SOUND_PAD/PAD4" ] && found+=("${v%/}")
  done
  echo "${#found[@]}"
}

on_mixer() {   # true when the card's disk is the mixer in File Transfer Mode, which calls itself "L6 SD R&W"; a reader has its own name
  local whole
  whole=$($diskinfo "$card" 2>/dev/null | sed -n 's/^ *Part of Whole: *//p')
  [ -n "$whole" ] && $diskinfo "$whole" 2>/dev/null | grep -q '^ *Device / Media Name: *L6 SD'
}

if [ -z "$card" ]; then
  if [ "$(mounted_cards)" -eq 0 ]; then
    echo "No card is mounted. Putting the mixer into File Transfer Mode (it must be connected by USB, with ZOOM L6 Editor closed)..."
    if result=$("$python" "$transfer" enter 2>&1); then
      case $result in
        *'"already": true'*) ;;   # the mixer was in the mode before the script: asked about below, like a card found mounted
        *) restore=1 ;;
      esac
    else
      case $result in
        *'"session": false'*) echo "The mixer did not answer. Quit ZOOM L6 Editor, check the USB cable, and try again" >&2 ;;
        *'"card_mounted": false'*) echo "The mixer did not show its card: $result" >&2 ;;
        *) echo "No mixer found: $result" >&2
           echo "Connect the mixer by USB, or put the card in a card reader, or name the card's folder: $0 [folder] [card]" >&2 ;;
      esac
      exit 1
    fi
  fi
  mounted_cards >/dev/null
  case ${#found[@]} in
    1) card=${found[0]} ;;
    0) echo "No L6 card is mounted under $volumes" >&2; exit 1 ;;
    *) echo "More than one L6 card is mounted (${found[*]}). Name one: $0 [folder] [card]" >&2; exit 1 ;;
  esac
  if [ -z "$restore" ] && on_mixer; then
    # The card was mounted from the mixer before the script ran, so the mixer
    # is in File Transfer Mode and would stay there afterwards. Offer to leave
    # it. A card in a reader is left alone.
    echo "The mixer is already in File Transfer Mode, so this card is mounted from it."
    read -r -p "Eject the card and leave File Transfer Mode when done (quit ZOOM L6 Editor first)? [Y/n] " answer
    case $answer in
      [nN]*) echo "The card stays mounted. Eject it yourself, then leave File Transfer Mode from ZOOM L6 Editor." ;;
      *) restore=1 ;;
    esac
  fi
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
"$python" "$here/import_take.py" "$card" "$take" --out="$dest/$name" --name="$name" --bpm="$bpm"
