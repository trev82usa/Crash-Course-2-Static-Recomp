// crashcourse2 - ReXGlue Recompiled Project
//
// App hooks, following the Trials HD port: F1 settings menu, F3 FPS counter (fed from the
// game's present function), keyboard controls, crash.txt, clean exit from the game's menu.

#pragma once

#include <rex/cvar.h>
#include <rex/filesystem.h>
#include <rex/input/device_assignment.h>
#include <rex/input/input_system.h>
#include <rex/logging/api.h>
#include <rex/rex_app.h>
#include <rex/runtime.h>
#include <rex/ui/keybinds.h>

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <mutex>
#include <thread>

#include "cc2_menu.h"
#include "crash_handler.h"
#include "keyboard_input.h"
#include "perf_tools.h"

void StartTitleExitWatch();                      // game_exit.cpp
void RemoveSharedMemoryFiles(const char* when);  // game_exit.cpp

class CrashCourse2App : public rex::ReXApp {
 public:
  using rex::ReXApp::ReXApp;

  static std::unique_ptr<rex::ui::WindowedApp> Create(
      rex::ui::WindowedAppContext& ctx) {
    return std::unique_ptr<CrashCourse2App>(new CrashCourse2App(ctx, "crashcourse2",
        PPCImageConfig));
  }

  // Use the Xenos GPU backend unless --gpu_plugin says otherwise (no graphics otherwise).
  // CC2_NO_GPU=1 runs headless (testing on machines without a GPU).
  void OnPreSetup(rex::RuntimeConfig& config) override {
    SetHighTimerResolution();
    RemoveSharedMemoryFiles("left over from earlier runs");
    if (!config.graphics && config.gpu_plugin.empty() && !std::getenv("CC2_NO_GPU"))
      config.gpu_plugin = "xenos";
    // Full game rather than the Xbox Live Arcade trial: report every license bit as granted to
    // XamContentGetLicenseMask (ReXGlue defaults to 0 = trial).
    rex::cvar::SetFlagByName("license_mask", "4294967295");
  }

  // Installed after setup so nothing in the runtime replaces it.
  void OnPostSetup() override {
    if (rex::cvar::Query<bool>("cc2_crash_handler")) InstallCrashHandler();
    SetGuestFrameStats([] { return GetGuestFrameStats(); });  // F3 overlay
    StartProfilerIfEnabled();
    StartTitleExitWatch();
    RemoveSharedMemoryFiles("(this run's; freed automatically when the game closes)");
    // After the SDK set its own input rule (in ConstructRuntime), so ours replaces it.
    if (runtime() && runtime()->input_system()) {
      auto* input = static_cast<rex::input::InputSystem*>(runtime()->input_system());
      input->AddDriver(CreateKeyboardDriver(window()));  // before the callback is set
      // Crash Course 2 is single-player and only player 1 has the (signed-in) profile. The SDK
      // gives each physical pad its own player slot, so with a second device present (Steam
      // Input's virtual pad, a pad seen twice, a wheel...) the pad you press A on can be
      // player 2, which the game sees as "not signed in" and loops on "Press A to sign in".
      // Route every controller and the keyboard to player 1 instead.
      if (rex::cvar::Query<bool>("cc2_all_controllers_player1"))
        input->SetDeviceAssignment(std::make_unique<rex::input::SharedAssignment>());
      ConnectCc2MenuInput(input);
    }
  }

  // F1: the Crash Course 2 settings menu. Controller: LB+RB+X.
  void OnCreateDialogs(rex::ui::ImGuiDrawer* drawer) override {
    InitCc2Menu(drawer, window(),
                rex::filesystem::GetExecutableFolder() / "crashcourse2.toml");
    rex::ui::RegisterBind("bind_cc2_menu", "F1", "Toggle the Crash Course 2 settings menu",
                          [] { ToggleCc2Menu(); });
  }

  // Closing the window runs the engine's full teardown, which can hang on a game thread that
  // never stops (the process then lingers invisibly). Give it a few seconds, then save the log
  // and end the process.
  bool OnWindowCloseRequested() override {
    StartExitWatchdog();
    return true;
  }
  void OnShutdown() override { StartExitWatchdog(); }
  void OnGuestThreadExit(rex::system::XThread* thread) override {
    (void)thread;
    REXLOG_WARN("[exit] the game's main thread returned (the game chose to quit)");
    rex::FlushLogging();
  }

  static void StartExitWatchdog() {
    static std::once_flag once;
    std::call_once(once, [] {
      std::thread([] {
        std::this_thread::sleep_for(std::chrono::seconds(3));
        rex::FlushLogging();
        std::_Exit(0);
      }).detach();
    });
  }

  // Find the game files without a command-line argument: an "assets" folder next to the
  // program, or default.xex placed right next to it.
  void OnConfigurePaths(rex::PathConfig& paths) override {
    if (paths.game_data_root.empty()) {
      auto exe_dir = rex::filesystem::GetExecutableFolder();
      paths.game_data_root = exe_dir / "assets";  // so the error message names the right folder
      for (const auto& dir : {exe_dir / "assets", exe_dir}) {
        std::error_code ec;
        if (std::filesystem::exists(dir / "default.xex", ec)) {
          paths.game_data_root = dir;
          break;
        }
      }
    }
    CheckOfflineGameFiles(paths.game_data_root);
  }

  // This program is recompiled from the offline build of default.xex (Title Update 2 merged,
  // offline patches applied: tools/build_offline_game.sh). Run against the original file its
  // code and the game's data no longer match, and it dies a moment after start with a
  // meaningless crash (a null graphics device). Catch that and say what to do.
  static void CheckOfflineGameFiles(const std::filesystem::path& root) {
    constexpr uintmax_t kOfflineXexSize = 15142912;
    std::error_code ec;
    auto size = std::filesystem::file_size(root / "default.xex", ec);
    if (ec || size == kOfflineXexSize) return;  // missing: the SDK's own message says so
    std::fprintf(stderr,
                 "\nCrash Course 2: %s/default.xex is not the offline build (%ju bytes, expected "
                 "%ju).\nThis version needs game files made with tools/build_offline_game.sh "
                 "(Title Update 2 + offline patches).\nSee step 1 in README.txt.\n\n",
                 root.string().c_str(), uintmax_t(size), kOfflineXexSize);
    std::fflush(stderr);
    std::_Exit(2);
  }
};
