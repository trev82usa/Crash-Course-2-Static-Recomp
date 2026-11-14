Crash Course 2 - native Linux build (ReXGlue static recompilation)
==================================================================

1. Make the game files. This build runs the OFFLINE version of the game (Title Update 2 merged and
   the community offline patches applied, so it never needs Xbox LIVE). You make it from your own
   files with one command; nothing of the game is included in this download:
     tools/build_offline_game.sh <folder with your original default.xex, data.pak ...> \
                                 <Title Update 2 file TU_1C424IF_000000K000000.00000000000G5> assets
   It needs python3 (3.11+), git, make and g++, and downloads two small MIT-licensed tool
   projects (crash-course-2-revived and doritos-crash-course-xenia) the first time.
   The result in "assets" is default.xex, data.pak, ArcadeInfo.xml, intro.wmv, bhvr.wmv and
   AvatarAwards. The original, unpatched default.xex will NOT work with this build.
2. Run ./crashcourse2 from this folder.

Requirements
  - 64-bit Linux with glibc 2.38 or newer (Ubuntu 24.04+, Fedora 39+, Arch, ...)
  - A Vulkan driver: Mesa RADV for AMD, the NVIDIA driver, or Mesa ANV for Intel
    (on Ubuntu: sudo apt install mesa-vulkan-drivers)
  - X11 or XWayland (Ubuntu's normal desktop has XWayland)
  - PulseAudio or PipeWire for sound (Ubuntu's default)
  - An Xbox or PlayStation controller is recommended

In game
  - F1 (or LB+RB+X on a controller, Q+E+X on the keyboard): settings menu - online name,
    password and server, graphics, sound, controls. Saves into crashcourse2.toml.
  - F3: FPS counter. The log also gets an "FPS: ..." line every 5 seconds.
  - F4: every advanced engine setting.
  - Keyboard: arrows/WASD = left stick, Enter/Space = A, Backspace = B, X/Y, Z/C = triggers,
    Q/E = bumpers, Escape/P = Start, Tab/R = Back. Hold Shift for half stick.

If something goes wrong
  - Logs are written to the "logs" folder next to the program. Keep the newest one,
    and crash.txt if there is one.
  - Settings can go in crashcourse2.toml next to the program.
  - Crashes a moment after start, or "default.xex is not the offline build": the assets folder
    still has the original default.xex. Redo step 1 (the output must be 15,142,912 bytes).
  - Saves and the shader cache live in ~/.local/share/crashcourse2 (or similar).

This is an early, work-in-progress build. Expect bugs.
