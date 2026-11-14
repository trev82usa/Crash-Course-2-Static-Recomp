# crashcourse2 - ReXGlue Recompiled Project
#
# SDK boilerplate lives in generated/rexglue.cmake.

cmake_minimum_required(VERSION 3.25)
project(crashcourse2 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(generated/rexglue.cmake)

# Sources
set(CRASHCOURSE2_SOURCES
    src/main.cpp
    src/usbcam_stubs.cpp
    src/cc2_menu.cpp
    src/crash_handler.cpp
    src/game_exit.cpp
    src/http_client.cpp
    src/input_lock.cpp
    src/offline_detours.cpp
    src/keyboard_input.cpp
    src/online.cpp
    src/perf_tools.cpp
    src/player_name.cpp
)

if(WIN32)
    add_executable(crashcourse2 WIN32 ${CRASHCOURSE2_SOURCES})
else()
    add_executable(crashcourse2 ${CRASHCOURSE2_SOURCES})
endif()

# Stage the Xenos GPU emulation plugin next to the program (loaded at runtime).
rexglue_setup_target(crashcourse2 GPU_PLUGINS xenos)
