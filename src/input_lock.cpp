// The SDK's InputSystem has no lock, and every read (GetState / GetCapabilities / SetState)
// rebuilds its device list (RefreshDevices). The game reads controllers on its own thread and
// the F1 menu reads them on the window thread, so two rebuilds could run at once and corrupt
// memory (seen as a crash with signal 6 inside RefreshDevices). Every reader takes this lock:
// the game through the three XamInput* imports below, the menu in cc2_menu.cpp.
#include <rex/hook.h>

#include <mutex>

#if defined(__linux__)
#include <dlfcn.h>
#endif

std::recursive_mutex& Cc2InputMutex() {
  static std::recursive_mutex m;
  return m;
}

namespace {
PPCFunc* Sdk(const char* symbol) {
#if defined(__linux__)
  return reinterpret_cast<PPCFunc*>(dlsym(RTLD_NEXT, symbol));
#else
  return nullptr;
#endif
}
}  // namespace

#define CC2_LOCKED_IMPORT(name)                                                       \
  REX_HOOK_RAW(__imp__##name) {                                                       \
    static PPCFunc* sdk = Sdk("__imp__" #name);                                       \
    std::lock_guard<std::recursive_mutex> lock(Cc2InputMutex());                      \
    if (sdk) sdk(ctx, base); else ctx.r3.u64 = 0x48F; /* DEVICE_NOT_CONNECTED */      \
  }                                                                                   \
  static rex::ppc::detail::PPCFuncRegistrar _cc2_lock_##name("__imp__" #name,         \
                                                             &__imp__##name);

CC2_LOCKED_IMPORT(XamInputGetState)
CC2_LOCKED_IMPORT(XamInputGetCapabilities)
CC2_LOCKED_IMPORT(XamInputSetState)
