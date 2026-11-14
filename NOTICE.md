# Third-party notices

## ReXGlue SDK

This port is built with and links against the ReXGlue SDK
(https://github.com/rexglue/rexglue-sdk), BSD-3-Clause:

    Copyright (c) 2026, Tom Clay <tomc@tctechstuff.com>

    Portions of this software are derived from the Xenia project:
    Copyright (c) 2022, Ben Vanik and Xenia project contributors
    https://xenia.jp

The release archive ships `librexruntime.so` and `librexgpu-xenos.so` from the SDK. Their full
licence text is in the SDK's `LICENSE` file.

## Offline patches (downloaded at build time, not included here)

- crash-course-2-revived (https://github.com/LegendaryFire/crash-course-2-revived), MIT,
  Copyright (c) 2026 Doritos Crash Course 2 console mod contributors.
- doritos-crash-course-xenia (https://github.com/Lken-cmd/doritos-crash-course-xenia), MIT,
  Copyright (c) 2026 Doritos Crash Course Xenia mod contributors.

`tools/make_offline_game.py` uses their patch definitions and tools to build the game files
from your own copy. `src/offline_detours.cpp` reimplements seven of their patches as hooks.
