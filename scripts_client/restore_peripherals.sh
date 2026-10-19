#!/bin/bash
if [ -d /sys/bus/usb/devices ]; then
    for f in /sys/bus/usb/devices/*/power/control; do [ -w "$f" ] && echo on > "$f" 2>/dev/null || true; done
    for f in /sys/bus/usb/devices/*/power/autosuspend; do [ -w "$f" ] && echo -1 > "$f" 2>/dev/null || true; done
fi
udevadm trigger --subsystem-match=input --action=change 2>/dev/null || true
udevadm trigger --subsystem-match=hid --action=change 2>/dev/null || true
if command -v xinput &>/dev/null; then
    MK=$(xinput list 2>/dev/null | awk '/Virtual core keyboard|master keyboard/ {for(i=1;i<=NF;i++) if($i ~ /^id=[0-9]+$/) {split($i,a,"="); print a[2]}}' | head -n 1)
    [ -z "$MK" ] && MK=3
    MP=$(xinput list 2>/dev/null | awk '/Virtual core pointer|master pointer/ {for(i=1;i<=NF;i++) if($i ~ /^id=[0-9]+$/) {split($i,a,"="); print a[2]}}' | head -n 1)
    [ -z "$MP" ] && MP=2
    M_IDS=$(xinput list 2>/dev/null | awk '/master/ {for(i=1;i<=NF;i++) if($i ~ /^id=[0-9]+$/) {split($i,a,"="); print a[2]}}')
    for m in $M_IDS; do
        xinput enable "$m" 2>/dev/null || true
        xinput set-prop "$m" "Device Enabled" 1 2>/dev/null || true
    done
    for id in $(xinput list --id-only 2>/dev/null); do
        DN=$(xinput list --name-only "$id" 2>/dev/null || true)
        if echo "$DN" | grep -qi "XTEST"; then continue; fi
        if echo " $M_IDS " | grep -q " $id "; then continue; fi
        xinput enable "$id" 2>/dev/null || true
        xinput set-prop "$id" "Device Enabled" 1 2>/dev/null || true
        DI=$(xinput list "$id" 2>/dev/null || true)
        if echo "$DI" | grep -qi "KeyClass" || echo "$DN" | grep -qi -E "keyboard|key|kbd"; then
            xinput reattach "$id" "$MK" 2>/dev/null || true
        fi
        if echo "$DI" | grep -qi -E "ButtonClass|ValuatorClass" || echo "$DN" | grep -qi -E "mouse|pointer|touchpad|trackpoint|touchscreen"; then
            xinput reattach "$id" "$MP" 2>/dev/null || true
        fi
    done
    setxkbmap br 2>/dev/null || setxkbmap us 2>/dev/null || true
fi
