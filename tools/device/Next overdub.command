#!/bin/zsh
cd -- "${0:A:h}/../.." || exit 1
while true; do
  python3 tools/device/l6_overdub.py cycle --timeout 900
  result=$?
  if (( result != 0 )); then
    print '\nThe workflow stopped. See the message above; the pads may need a retry.'
    read 'reply?Press Return to close. '
    exit "$result"
  fi
  print '\nRecord the next pass using pad 1 for the newest master.'
  read 'reply?After stopping recording, press Return to process it, or type q to quit: '
  [[ "$reply" == [qQ] ]] && exit 0
done
