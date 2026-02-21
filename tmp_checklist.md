# Controller Autodetection Test Checklist (Windows + Bazzite)

## Common Setup
- [ ] launch_autoconfig = true (or GAMEHUB_CONTROLLER_LAUNCH_AUTOCONFIG=true)
- [ ] Run one non-dry gamehub sync to seed profiles and generate Steam shortcuts
- [ ] Launch from Steam shortcuts (PCSX2/Dolphin/Azahar)
- [ ] Set the exact controller mix before each launch

## Windows — PCSX2
- [ ] 0 Xbox -> profile kbm
- [ ] PCSX2.ini: OpenPauseMenu = Keyboard/Escape
- [ ] PCSX2.ini: Pad1/Pad2 keyboard mappings
- [ ] 1 Xbox -> profile xbox_1p
- [ ] PCSX2.ini: OpenPauseMenu = SDL-0/Back & SDL-0/Start
- [ ] PCSX2.ini: Pad1 SDL-0 mappings, Pad2 keyboard mappings
- [ ] 2+ Xbox -> profile xbox_2p
- [ ] PCSX2.ini: Pad1 SDL-0 mappings, Pad2 SDL-1 mappings

## Windows — Dolphin GC
- [ ] Launch a GC title via Steam
- [ ] 0 Xbox -> profile kbm
- [ ] GCPadNew.ini: Device = DInput/0/Keyboard Mouse for P1, Device = None for P2
- [ ] Hotkeys.ini: ESCAPE hotkeys present
- [ ] Dolphin.ini: SIDevice0 = 6, SIDevice1 = 6
- [ ] Dolphin.ini: WiimoteSource0 = 1, WiimoteSource1 = 1
- [ ] 1 Xbox -> profile xbox_1p
- [ ] GCPadNew.ini: Device = XInput/0/Gamepad for P1, Device = DInput/0/Keyboard Mouse for P2
- [ ] Hotkeys.ini: SELECT+START hotkeys present
- [ ] 2+ Xbox -> profile xbox_2p
- [ ] GCPadNew.ini: Device = XInput/0/Gamepad for P1, Device = XInput/1/Gamepad for P2

## Windows — Dolphin Wii
- [ ] Launch a Wii title via Steam
- [ ] 0 Xbox -> profile kbm
- [ ] WiimoteNew.ini: Device = DInput/0/Keyboard Mouse for Wiimote1, Device = None for Wiimote2
- [ ] Hotkeys.ini: ESCAPE hotkeys present
- [ ] Dolphin.ini: SIDevice0 = 6, SIDevice1 = 6
- [ ] Dolphin.ini: WiimoteSource0 = 1, WiimoteSource1 = 1
- [ ] 1 Xbox -> profile xbox_1p
- [ ] WiimoteNew.ini: Device = XInput/0/Gamepad for Wiimote1, Device = DInput/0/Keyboard Mouse for Wiimote2
- [ ] Hotkeys.ini: SELECT+START hotkeys present
- [ ] 2+ Xbox -> profile xbox_2p
- [ ] WiimoteNew.ini: Device = XInput/0/Gamepad for Wiimote1, Device = XInput/1/Gamepad for Wiimote2

## Windows — Azahar
- [ ] 0 Xbox -> profile kbm
- [ ] qt-config.ini: engine:keyboard mappings present
- [ ] 1 Xbox -> profile xbox_1p
- [ ] qt-config.ini: engine:sdl and port:0 mappings present
- [ ] GUID present or preserved per policy
- [ ] 2+ Xbox -> profile xbox_2p
- [ ] qt-config.ini: engine:sdl and port:0 mappings present

## Windows — Edge Cases
- [ ] 1 non-Xbox only -> profile kbm
- [ ] 1 Xbox + 1 non-Xbox -> profile xbox_1p
- [ ] 2 non-Xbox -> profile kbm
- [ ] Plug controller within ~0.5s after launch -> detects and selects Xbox profile
- [ ] Force detection failure -> warning + kbm fallback

## Windows — Azahar GUID Policy
- [ ] Default env: preserves existing GUID, port normalized
- [ ] GAMEHUB_AZAHAR_GUID_MODE=detect: uses discovered GUID when available
- [ ] GAMEHUB_AZAHAR_GUID_MODE=fixed + GAMEHUB_AZAHAR_FIXED_GUID=<32hex>: fixed GUID applied
- [ ] GAMEHUB_AZAHAR_GUID_MODE=off: GUID tokens removed
- [ ] GAMEHUB_AZAHAR_FORCE_DISCOVERED_GUID=true: behaves like detect
- [ ] GAMEHUB_AZAHAR_SDL_DIR=<dir with SDL2.dll>: discovery uses that SDL

## Bazzite — PCSX2 (Flatpak)
- [ ] 0 Xbox -> profile kbm
- [ ] PCSX2.ini: OpenPauseMenu = Keyboard/Escape
- [ ] PCSX2.ini: Pad1/Pad2 keyboard mappings
- [ ] 1 Xbox -> profile xbox_1p
- [ ] PCSX2.ini: OpenPauseMenu = SDL-0/Back & SDL-0/Start
- [ ] PCSX2.ini: Pad1 SDL-0 mappings, Pad2 keyboard mappings
- [ ] 2+ Xbox -> profile xbox_2p
- [ ] PCSX2.ini: Pad1 SDL-0 mappings, Pad2 SDL-1 mappings

## Bazzite — Dolphin GC (Flatpak)
- [ ] Launch a GC title via Steam
- [ ] 0 Xbox -> profile kbm
- [ ] GCPadNew.ini: Device = XInput2/0/Virtual core pointer for P1, Device = None for P2
- [ ] Hotkeys.ini: Device = All Devices
- [ ] Dolphin.ini: SIDevice0 = 6, SIDevice1 = 6
- [ ] Dolphin.ini: WiimoteSource0 = 1, WiimoteSource1 = 1
- [ ] 1 Xbox -> profile xbox_1p
- [ ] GCPadNew.ini: Device = evdev/0/<Xbox name> for P1, Device = XInput2/0/Virtual core pointer for P2
- [ ] Hotkeys.ini: Device = All Devices
- [ ] 2+ Xbox -> profile xbox_2p
- [ ] GCPadNew.ini: Device = evdev/0/<name> for P1, Device = evdev/1/<name> for P2
- [ ] Hotkeys.ini: Device = All Devices

## Bazzite — Dolphin Wii (Flatpak)
- [ ] Launch a Wii title via Steam
- [ ] 0 Xbox -> profile kbm
- [ ] WiimoteNew.ini: Device = XInput2/0/Virtual core pointer for Wiimote1, Device = None for Wiimote2
- [ ] Hotkeys.ini: Device = All Devices
- [ ] Dolphin.ini: SIDevice0 = 6, SIDevice1 = 6
- [ ] Dolphin.ini: WiimoteSource0 = 1, WiimoteSource1 = 1
- [ ] 1 Xbox -> profile xbox_1p
- [ ] WiimoteNew.ini: Device = evdev/0/<Xbox name> for Wiimote1, Device = XInput2/0/Virtual core pointer for Wiimote2
- [ ] Hotkeys.ini: Device = All Devices
- [ ] 2+ Xbox -> profile xbox_2p
- [ ] WiimoteNew.ini: Device = evdev/0/<name> for Wiimote1, Device = evdev/1/<name> for Wiimote2
- [ ] Hotkeys.ini: Device = All Devices

## Bazzite — Azahar (Flatpak)
- [ ] 0 Xbox -> profile kbm
- [ ] qt-config.ini: engine:keyboard mappings present
- [ ] 1 Xbox -> profile xbox_1p
- [ ] qt-config.ini: engine:sdl and port:0 mappings present
- [ ] GUID present or preserved per policy
- [ ] 2+ Xbox -> profile xbox_2p
- [ ] qt-config.ini: engine:sdl and port:0 mappings present

## Bazzite — Edge Cases
- [ ] 1 non-Xbox only -> profile kbm
- [ ] 1 Xbox + 1 non-Xbox -> profile xbox_1p
- [ ] 2 non-Xbox -> profile kbm
- [ ] Plug controller within ~0.5s after launch -> detects and selects Xbox profile
- [ ] Force detection failure (block /dev/input) -> warning + kbm fallback

## Bazzite — Azahar GUID Policy
- [ ] Default env: preserves existing GUID, port normalized
- [ ] GAMEHUB_AZAHAR_GUID_MODE=detect: prefer Flatpak runtime GUID, fallback to host SDL
- [ ] GAMEHUB_AZAHAR_GUID_MODE=fixed + GAMEHUB_AZAHAR_FIXED_GUID=<32hex>: fixed GUID applied
- [ ] GAMEHUB_AZAHAR_GUID_MODE=off: GUID tokens removed
- [ ] Flatpak probe unavailable: host SDL or preserve existing GUID

## RetroArch — PS1 Should Always Be DualShock
- [ ] Windows: retroarch-core-options.cfg has swanstation_Controller1.Type = "AnalogController"
- [ ] Windows: retroarch-core-options.cfg has swanstation_Controller2.Type = "AnalogController"
- [ ] Windows: Swanstation remap file sets input_libretro_device_p1 = "261"
- [ ] Bazzite: retroarch-core-options.cfg has swanstation_Controller1.Type = "AnalogController"
- [ ] Bazzite: retroarch-core-options.cfg has swanstation_Controller2.Type = "AnalogController"
- [ ] Bazzite: Swanstation remap file sets input_libretro_device_p1 = "261"

## Wrapper Toggle (Both Platforms)
- [ ] launch_autoconfig = false -> shortcuts are not wrapped, no profile apply happens at launch
