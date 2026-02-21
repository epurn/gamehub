# Controller Autodetection Test Checklist (Windows + Bazzite)

## Common Setup
- [ ] If this branch was used before these fixes: run one non-dry sync with `--reseed-profiles` before retesting controller scenarios
- [x] launch_autoconfig = true (or GAMEHUB_CONTROLLER_LAUNCH_AUTOCONFIG=true)
- [x] Run one non-dry gamehub sync to seed profiles and generate Steam shortcuts
- [x] Launch from Steam shortcuts (PCSX2/Dolphin/Azahar)
- [x] Set the exact controller mix before each launch

## Windows — PCSX2
- [x] 0 Xbox -> profile kbm
- [x] PCSX2.ini: OpenPauseMenu = Keyboard/Escape
- [x] PCSX2.ini: Pad1/Pad2 keyboard mappings
- [x] 1 Xbox -> profile xbox_1p
- [x] PCSX2.ini: OpenPauseMenu = SDL-0/Back & SDL-0/Start
- [ ] PCSX2.ini: Pad1 SDL-0 mappings, Pad2 keyboard mappings NOT WORKING 
- [x] 2+ Xbox -> profile xbox_2p
- [x] PCSX2.ini: Pad1 SDL-0 mappings, Pad2 SDL-1 mappings

## Windows — Dolphin GC
- [x] Launch a GC title via Steam
- [x] 0 Xbox -> profile kbm
- [x] GCPadNew.ini: Device = DInput/0/Keyboard Mouse for P1, Device = None for P2
- [x] Hotkeys.ini: ESCAPE hotkeys present
- [x] Dolphin.ini: SIDevice0 = 6, SIDevice1 = 6
- [x] Dolphin.ini: WiimoteSource0 = 1, WiimoteSource1 = 1
- [ ] 1 Xbox -> profile xbox_1p
- [ ] GCPadNew.ini: Device = XInput/0/Gamepad for P1, Device = DInput/0/Keyboard Mouse for P2 - P1 WORKS, P2 Detected but controls not working, ensure for the second player in this scenario the controls and devices are the same as for p1 in the kbm only scenario
- [x] Hotkeys.ini: SELECT+START hotkeys present
- [x] 2+ Xbox -> profile xbox_2p
- [x] GCPadNew.ini: Device = XInput/0/Gamepad for P1, Device = XInput/1/Gamepad for P2

## Windows — Dolphin Wii
- [x] Launch a Wii title via Steam
- [x] 0 Xbox -> profile kbm
- [x] WiimoteNew.ini: Device = DInput/0/Keyboard Mouse for Wiimote1, Device = None for Wiimote2
- [x] Hotkeys.ini: ESCAPE hotkeys present
- [x] Dolphin.ini: SIDevice0 = 6, SIDevice1 = 6
- [x] Dolphin.ini: WiimoteSource0 = 1, WiimoteSource1 = 1
- [ ] 1 Xbox -> profile xbox_1p
- [ ] WiimoteNew.ini: Device = XInput/0/Gamepad for Wiimote1, Device = DInput/0/Keyboard Mouse for Wiimote2 - P1 WORKS, P2 Detected but controls not working, ensure for the second player in this scenario the controls and devices are the same as for p1 in the kbm only scenario
- [x] Hotkeys.ini: SELECT+START hotkeys present
- [x] 2+ Xbox -> profile xbox_2p
- [x] WiimoteNew.ini: Device = XInput/0/Gamepad for Wiimote1, Device = XInput/1/Gamepad for Wiimote2

## Windows — Azahar
- [x] 0 Xbox -> profile kbm
- [x] qt-config.ini: engine:keyboard mappings present
- [x] 1 Xbox -> profile xbox_1p
- [x] qt-config.ini: engine:sdl and port:0 mappings present
- [x] GUID present or preserved per policy
- [ ] 2+ Xbox -> profile xbox_2p * NOTE 3ds does noot support multiple controllers, so this was not tested*
- [ ] qt-config.ini: engine:sdl and port:0 mappings present

## Windows — Azahar GUID Policy
- [x] Default env: preserves existing GUID, port normalized
- [x] GAMEHUB_AZAHAR_SDL_DIR=<dir with SDL2.dll>: discovery uses that SDL
-The rest of these are unnecessary, guid detection will always be required
- [ ] GAMEHUB_AZAHAR_GUID_MODE=detect: uses discovered GUID when available
- [ ] GAMEHUB_AZAHAR_GUID_MODE=fixed + GAMEHUB_AZAHAR_FIXED_GUID=<32hex>: fixed GUID applied
- [ ] GAMEHUB_AZAHAR_GUID_MODE=off: GUID tokens removed
- [x] GAMEHUB_AZAHAR_FORCE_DISCOVERED_GUID=true: behaves like detect


## Bazzite — PCSX2 (Flatpak)
- [x] 0 Xbox -> profile kbm
- [ ] PCSX2.ini: OpenPauseMenu = Keyboard/Escape - Did not work
- [ ] WE SHOULD for ps2 kbm: unifiy windows behaviour i.e. set confirm on close to false, and esc to open the system menu
- [x] PCSX2.ini: Pad1/Pad2 keyboard mappings
- [x] 1 Xbox -> profile xbox_1p
- [x] PCSX2.ini: OpenPauseMenu = SDL-0/Back & SDL-0/Start
- [ ] PCSX2.ini: Pad1 SDL-0 mappings, Pad2 keyboard mappings Pad1 SDL-0 mappings, Pad2 keyboard mappings NOT WORKING 
- [x] 2+ Xbox -> profile xbox_2p
- [x] PCSX2.ini: Pad1 SDL-0 mappings, Pad2 SDL-1 mappings

## Bazzite — Dolphin GC (Flatpak)
- [x] Launch a GC title via Steam
- [x] 0 Xbox -> profile kbm
- [x] GCPadNew.ini: Device = XInput2/0/Virtual core pointer for P1, Device = None for P2
- [ ] Hotkeys.ini: Device = All Devices - Esc does not work perhaps the key code is wrong or all devices wont work? if you need me to manually set and verify let me know
- [x] Dolphin.ini: SIDevice0 = 6, SIDevice1 = 6
- [x] Dolphin.ini: WiimoteSource0 = 1, WiimoteSource1 = 1
- [x] 1 Xbox -> profile xbox_1p
- [ ] GCPadNew.ini: Device = evdev/0/Xbox name for P1, Device = XInput2/0/Virtual core pointer for P2 - P1 WORKS, P2 Detected but controls not working, ensure for the second player in this scenario the controls and devices are the same as for p1 in the kbm only scenario
- [x] Hotkeys.ini: Device = All Devices
- [x] 2+ Xbox -> profile xbox_2p
- [x] GCPadNew.ini: Device = evdev/0/name for P1, Device = evdev/1/name for P2
- [x] Hotkeys.ini: Device = All Devices

## Bazzite — Dolphin Wii (Flatpak)
- [x] Launch a Wii title via Steam
- [x] 0 Xbox -> profile kbm
- [x] WiimoteNew.ini: Device = XInput2/0/Virtual core pointer for Wiimote1, Device = None for Wiimote2
- [ ] Hotkeys.ini: Device = All Devices - Esc does not work (all devices didn't work on windows, maybe it won't on linux)
- [x] Dolphin.ini: SIDevice0 = 6, SIDevice1 = 6
- [x] Dolphin.ini: WiimoteSource0 = 1, WiimoteSource1 = 1
- [ ] 1 Xbox -> profile xbox_1p - P1 WORKS, P2 Detected but controls not working, ensure for the second player in this scenario the controls and devices are the same as for p1 in the kbm only scenario
- [x] WiimoteNew.ini: Device = evdev/0/Xbox name for Wiimote1, Device = XInput2/0/Virtual core pointer for Wiimote2 
- [x] Hotkeys.ini: Device = All Devices
- [x] 2+ Xbox -> profile xbox_2p
- [x] WiimoteNew.ini: Device = evdev/0/name for Wiimote1, Device = evdev/1/name for Wiimote2
- [x] Hotkeys.ini: Device = All Devices

## Bazzite — Azahar (Flatpak)
- [x] 0 Xbox -> profile kbm
- [x] qt-config.ini: engine:keyboard mappings present

- [ ] 1 Xbox -> profile xbox_1p
did not work SWITCH TO ALWYS detect guid - remove other modes
- [x] qt-config.ini: engine:sdl and port:0 mappings present
- [x] GUID present or preserved per policy

- [ ] 2+ Xbox -> profile xbox_2p * NOTE 3ds does noot support multiple controllers, so this was not tested*
- [ ] qt-config.ini: engine:sdl and port:0 mappings present


## Bazzite — Azahar GUID Policy
- IMPROTANT SWITCH TO ALWAYS detect like windows, remove other options (we will have to retest)
- [x] Default env: preserves existing GUID, port normalized
- [x] GAMEHUB_AZAHAR_GUID_MODE=detect: prefer Flatpak runtime GUID, fallback to host SDL
- [ ] GAMEHUB_AZAHAR_GUID_MODE=fixed + GAMEHUB_AZAHAR_FIXED_GUID=<32hex>: fixed GUID applied
- [ ] GAMEHUB_AZAHAR_GUID_MODE=off: GUID tokens removed
- [ ] Flatpak probe unavailable: host SDL or preserve existing GUID

## RetroArch — PS1 Should Always Be DualShock
- [x] Windows: retroarch-core-options.cfg has swanstation_Controller1.Type = "AnalogController"
- [x] Windows: retroarch-core-options.cfg has swanstation_Controller2.Type = "AnalogController"
- [x] Windows: Swanstation remap file sets input_libretro_device_p1 = "261"
- [x] Bazzite: retroarch-core-options.cfg has swanstation_Controller1.Type = "AnalogController"
- [x] Bazzite: retroarch-core-options.cfg has swanstation_Controller2.Type = "AnalogController"
- [x] Bazzite: Swanstation remap file sets input_libretro_device_p1 = "261"

## Wrapper Toggle (Both Platforms)
- [ ] launch_autoconfig = false -> shortcuts are not wrapped, no profile apply happens at launch
