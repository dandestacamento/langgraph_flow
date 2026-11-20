# DW-400 / DW-600 Dishwasher - Service Advisory 2026-04

This advisory introduces a fault code added in the March 2026 firmware
update for the DW-400 and DW-600 dishwashers. It is not yet listed in the
printed manuals.

## New fault code E9 - turbidity sensor fouling

Error E9 means the turbidity sensor (the sensor that measures how dirty
the wash water is) is fouled and returning implausible readings. The
machine falls back to a fixed-length Normal cycle while E9 is active, so
dishes still get washed but cycles run longer and use more water.

To clear E9: remove the lower spray arm, lift out the coarse filter, and
wipe the turbidity sensor window (the clear plastic dome at the sump
centre) with a soft cloth and white vinegar. Run an empty Rinse cycle.
If E9 returns within three cycles, the sensor module (part TS-07) needs
replacement.

## Firmware note

Machines on firmware 4.2.0 or later display E9; older firmware logged the
same condition silently as maintenance flag M12 in the service menu.
A technician can read historic M12 counts in the service menu under
Diagnostics > History.
