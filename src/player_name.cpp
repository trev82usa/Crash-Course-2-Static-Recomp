// Player identity and Xbox Live status.
//
// Crash Course 2 refuses to start unless the profile is signed in to Xbox LIVE ("You must be
// signed into Xbox LIVE to play this game"), but ReXGlue presents an offline console: profile
// signed in locally only (with a non-Live XUID), every Live privilege denied, network cable
// unplugged. With cc2_xbox_live = true we present a normal Live-connected console
// instead; no Microsoft service is contacted, and leaderboards go to cc2_server_url if set.
//
// The profile shows cc2_player_name (F1 menu / crashcourse2.toml) instead of the SDK's fixed
// "User", with a stable online-style XUID (0x0009...) derived from that name, the same one the
// leaderboard server computes.
//
// ReXGlue hard-codes the profile, so we replace the kernel imports the game reads it from:
// XamUserGetName, XamUserGetSigninInfo, XamUserGetSigninState and XamUserGetXUID. The game's code
// calls these by symbol, and a definition in the program wins over the one in librexruntime.so,
// so ours run. Each calls the SDK's own version first (dlsym(RTLD_NEXT)) and then changes only
// the name / XUID / sign-in state. With an empty cc2_player_name everything stays as the SDK
// reports it ("User", the SDK's XUID). Trials HD did the same on the game's XUser* wrappers.
//
// Note: games tie save data to the XUID, so setting (or changing) the name starts a fresh
// profile, as in Trials HD.
#include <rex/cvar.h>
#include <rex/hook.h>
#include <rex/logging.h>

REXCVAR_DEFINE_BOOL(cc2_xbox_live, false, "CrashCourse2",
                    "Present the profile as signed in to Xbox LIVE (the game requires it). "
                    "Nothing connects to Microsoft; leaderboards use cc2_server_url");

#include <algorithm>
#include <atomic>
#include <cctype>
#include <cstring>
#include <string>

#if defined(__linux__)
#include <dlfcn.h>
#endif

// online.cpp
std::string Cc2PlayerName();
uint64_t Cc2PlayerXuid();
bool Cc2Online();
// live_trace.cpp
// Diagnostic hook (formerly logged each distinct call); kept as a no-op so the hooks stay simple.
static inline void Cc2TraceCall(const char*, uint32_t, uint32_t, uint32_t, uint32_t, uint32_t,
                                uint64_t) {}

namespace {

constexpr uint32_t kNameSize = 16;                // XUSER_NAME_SIZE, including the terminator
constexpr uint32_t kSigninInfoFlagsOffset = 0x08; // X_USER_SIGNIN_INFO.info_flags
constexpr uint32_t kInfoFlagLiveEnabled = 0x1, kInfoFlagGuest = 0x2;
constexpr uint32_t kSigninInfoStateOffset = 0x0C; // X_USER_SIGNIN_INFO.signin_state
constexpr uint32_t kSigninInfoNameOffset = 0x18;  // X_USER_SIGNIN_INFO.name
constexpr uint32_t kSignedInLocally = 1, kSignedInToLive = 2;

bool Live() { return rex::cvar::Query<bool>("cc2_xbox_live"); }

// The XUID to report: name-based (0x0009... = an online XUID) when Live or a name is set.
bool OverrideXuid(const std::string& name) { return Live() || !name.empty(); }

// The configured name, or "" to keep the SDK's. Same rules as the F1 menu: 1-15 letters,
// digits, spaces, _ or -.
std::string ConfiguredName() {
  std::string n = Cc2PlayerName();
  if (n.empty() || n.size() > kNameSize - 1) return {};
  bool ok = std::all_of(n.begin(), n.end(), [](unsigned char c) {
    return std::isalnum(c) || c == ' ' || c == '_' || c == '-';
  });
  return ok ? n : std::string();
}

void Store32(uint8_t* base, uint32_t a, uint32_t v) {
  v = __builtin_bswap32(v);
  std::memcpy(base + a, &v, 4);
}
void Store64(uint8_t* base, uint32_t a, uint64_t v) {
  v = __builtin_bswap64(v);
  std::memcpy(base + a, &v, 8);
}

void WriteName(uint8_t* base, uint32_t guest_addr, uint32_t size, const std::string& name) {
  if (!guest_addr || size == 0) return;
  uint32_t n = std::min<uint32_t>({size, kNameSize, uint32_t(name.size()) + 1});
  char* dst = reinterpret_cast<char*>(base + guest_addr);
  std::memset(dst, 0, std::min(size, kNameSize));
  std::memcpy(dst, name.data(), n - 1);
}

PPCFunc* SdkFunction(const char* symbol) {
#if defined(__linux__)
  return reinterpret_cast<PPCFunc*>(dlsym(RTLD_NEXT, symbol));
#else
  return nullptr;
#endif
}

void LogOnce(const std::string& name) {
  static std::atomic<bool> logged{false};
  if (!logged.exchange(true))
    REXLOG_WARN("[profile] player {} (XUID {:016X}){}{}", name, Cc2PlayerXuid(),
                Live() ? ", signed in to Xbox LIVE" : ", local profile",
                Cc2Online() ? ", leaderboard server set" : "");
}

}  // namespace

// u32 XamUserGetName(u32 user_index, char* buffer, u32 buffer_len)
static void XamUserGetName_impl(PPCContext& __restrict ctx, uint8_t* base);
REX_HOOK_RAW(__imp__XamUserGetName) {
  const uint32_t a0 = ctx.r3.u32, a1 = ctx.r4.u32, a2 = ctx.r5.u32, a3 = ctx.r6.u32;
  const uint64_t lr = ctx.lr;
  XamUserGetName_impl(ctx, base);
  Cc2TraceCall("XamUserGetName", a0, a1, a2, a3, ctx.r3.u32, lr);
}
static void XamUserGetName_impl(PPCContext& __restrict ctx, uint8_t* base) {
  static PPCFunc* sdk = SdkFunction("__imp__XamUserGetName");
  const uint32_t user = ctx.r3.u32, buffer = ctx.r4.u32, len = ctx.r5.u32;
  if (sdk) {
    sdk(ctx, base);
  } else {
    ctx.r3.u64 = user == 0 ? 0 : 0x80070525;  // X_E_SUCCESS / X_E_NO_SUCH_USER
  }
  const std::string name = ConfiguredName();
  if (user == 0 && ctx.r3.u32 == 0 && !name.empty()) {
    WriteName(base, buffer, len, name);
    LogOnce(name);
  }
}

// i32 XamUserGetSigninInfo(u32 user_index, u32 flags, X_USER_SIGNIN_INFO* info)
//   X_USER_SIGNIN_INFO { XUID @0; DWORD @8; DWORD signin_state @0xC; DWORD @0x10, @0x14;
//                        CHAR name[16] @0x18 }
static void XamUserGetSigninInfo_impl(PPCContext& __restrict ctx, uint8_t* base);
REX_HOOK_RAW(__imp__XamUserGetSigninInfo) {
  const uint32_t a0 = ctx.r3.u32, a1 = ctx.r4.u32, a2 = ctx.r5.u32, a3 = ctx.r6.u32;
  const uint64_t lr = ctx.lr;
  XamUserGetSigninInfo_impl(ctx, base);
  Cc2TraceCall("XamUserGetSigninInfo", a0, a1, a2, a3, ctx.r3.u32, lr);
}
static void XamUserGetSigninInfo_impl(PPCContext& __restrict ctx, uint8_t* base) {
  static PPCFunc* sdk = SdkFunction("__imp__XamUserGetSigninInfo");
  const uint32_t user = ctx.r3.u32, info = ctx.r5.u32;
  if (!sdk) {
    ctx.r3.u64 = 0x80070057;  // X_E_INVALIDARG: no SDK function to defer to
    return;
  }
  sdk(ctx, base);
  const std::string name = ConfiguredName();
  if (user != 0 || !info) return;
  // The SDK may refuse flag 2 (XUSER_GET_SIGNIN_INFO_ONLINE_XUID_ONLY) for its offline profile.
  if (ctx.r3.u32 != 0 && !Live()) return;
  ctx.r3.u64 = 0;
  if (OverrideXuid(name)) Store64(base, info, Cc2PlayerXuid());
  if (Live() || Cc2Online()) {
    // The game decides "online-enabled profile" from this flag (otherwise: "Press A to sign
    // in", which opens the sign-in UI filtered to online-enabled profiles, in a loop).
    uint32_t flags = __builtin_bswap32(*reinterpret_cast<uint32_t*>(base + info + kSigninInfoFlagsOffset));
    Store32(base, info + kSigninInfoFlagsOffset, (flags | kInfoFlagLiveEnabled) & ~kInfoFlagGuest);
    Store32(base, info + kSigninInfoStateOffset, kSignedInToLive);
  }
  if (!name.empty()) WriteName(base, info + kSigninInfoNameOffset, kNameSize, name);
  LogOnce(name.empty() ? std::string("User") : name);
}

// u32 XamUserGetSigninState(u32 user_index)
static void XamUserGetSigninState_impl(PPCContext& __restrict ctx, uint8_t* base);
REX_HOOK_RAW(__imp__XamUserGetSigninState) {
  const uint32_t a0 = ctx.r3.u32, a1 = ctx.r4.u32, a2 = ctx.r5.u32, a3 = ctx.r6.u32;
  const uint64_t lr = ctx.lr;
  XamUserGetSigninState_impl(ctx, base);
  Cc2TraceCall("XamUserGetSigninState", a0, a1, a2, a3, ctx.r3.u32, lr);
}
static void XamUserGetSigninState_impl(PPCContext& __restrict ctx, uint8_t* base) {
  static PPCFunc* sdk = SdkFunction("__imp__XamUserGetSigninState");
  const uint32_t user = ctx.r3.u32;
  if (sdk) {
    sdk(ctx, base);
  } else {
    ctx.r3.u64 = user == 0 ? kSignedInLocally : 0;
  }
  if (user == 0 && ctx.r3.u32 == kSignedInLocally && (Live() || Cc2Online()))
    ctx.r3.u64 = kSignedInToLive;
}

// u32 XamShowSigninUI(u32 panes, u32 flags): logged so a sign-in loop shows up in the log.
static void XamShowSigninUI_impl(PPCContext& __restrict ctx, uint8_t* base);
REX_HOOK_RAW(__imp__XamShowSigninUI) {
  const uint32_t a0 = ctx.r3.u32, a1 = ctx.r4.u32, a2 = ctx.r5.u32, a3 = ctx.r6.u32;
  const uint64_t lr = ctx.lr;
  XamShowSigninUI_impl(ctx, base);
  Cc2TraceCall("XamShowSigninUI", a0, a1, a2, a3, ctx.r3.u32, lr);
}
static void XamShowSigninUI_impl(PPCContext& __restrict ctx, uint8_t* base) {
  static PPCFunc* sdk = SdkFunction("__imp__XamShowSigninUI");
  REXLOG_WARN("[profile] game opened the sign-in screen (panes {}, flags {:08X})", ctx.r3.u32,
              ctx.r4.u32);
  if (sdk) sdk(ctx, base); else ctx.r3.u64 = 0;
}

// i32 XamUserGetXUID(u32 user_index, u32 type_mask, u64* xuid)
static void XamUserGetXUID_impl(PPCContext& __restrict ctx, uint8_t* base);
REX_HOOK_RAW(__imp__XamUserGetXUID) {
  const uint32_t a0 = ctx.r3.u32, a1 = ctx.r4.u32, a2 = ctx.r5.u32, a3 = ctx.r6.u32;
  const uint64_t lr = ctx.lr;
  XamUserGetXUID_impl(ctx, base);
  Cc2TraceCall("XamUserGetXUID", a0, a1, a2, a3, ctx.r3.u32, lr);
}
static void XamUserGetXUID_impl(PPCContext& __restrict ctx, uint8_t* base) {
  static PPCFunc* sdk = SdkFunction("__imp__XamUserGetXUID");
  const uint32_t user = ctx.r3.u32, out = ctx.r5.u32;
  if (!sdk) {
    ctx.r3.u64 = 0x80070057;
    return;
  }
  sdk(ctx, base);
  if (user != 0 || !out) return;
  if (Live()) {
    // Online XUIDs (type 2) too, which the SDK only gives for some profile types.
    Store64(base, out, Cc2PlayerXuid());
    ctx.r3.u64 = 0;
  } else if (ctx.r3.u32 == 0 && !ConfiguredName().empty()) {
    Store64(base, out, Cc2PlayerXuid());
  }
}

// u32 XamUserCheckPrivilege(u32 user_index, u32 privilege, u32* allowed): the SDK denies every
// privilege; a Live account normally has them (online play, leaderboards, ...).
static void XamUserCheckPrivilege_impl(PPCContext& __restrict ctx, uint8_t* base);
REX_HOOK_RAW(__imp__XamUserCheckPrivilege) {
  const uint32_t a0 = ctx.r3.u32, a1 = ctx.r4.u32, a2 = ctx.r5.u32, a3 = ctx.r6.u32;
  const uint64_t lr = ctx.lr;
  XamUserCheckPrivilege_impl(ctx, base);
  Cc2TraceCall("XamUserCheckPrivilege", a0, a1, a2, a3, ctx.r3.u32, lr);
}
static void XamUserCheckPrivilege_impl(PPCContext& __restrict ctx, uint8_t* base) {
  static PPCFunc* sdk = SdkFunction("__imp__XamUserCheckPrivilege");
  const uint32_t user = ctx.r3.u32, out = ctx.r5.u32;
  if (sdk) sdk(ctx, base);
  if (Live() && out && (user == 0 || user == 0xFF)) {
    Store32(base, out, 1);
    ctx.r3.u64 = 0;
  }
}

// u32 XNetGetEthernetLinkStatus(caller): the SDK reports no cable. Report a 100 Mbit full-duplex
// link (XNET_ETHERNET_LINK_ACTIVE | 100MBPS | FULL_DUPLEX).
static void NetDll_XNetGetEthernetLinkStatus_impl(PPCContext& __restrict ctx, uint8_t* base);
REX_HOOK_RAW(__imp__NetDll_XNetGetEthernetLinkStatus) {
  const uint32_t a0 = ctx.r3.u32, a1 = ctx.r4.u32, a2 = ctx.r5.u32, a3 = ctx.r6.u32;
  const uint64_t lr = ctx.lr;
  NetDll_XNetGetEthernetLinkStatus_impl(ctx, base);
  Cc2TraceCall("NetDll_XNetGetEthernetLinkStatus", a0, a1, a2, a3, ctx.r3.u32, lr);
}
static void NetDll_XNetGetEthernetLinkStatus_impl(PPCContext& __restrict ctx, uint8_t* base) {
  static PPCFunc* sdk = SdkFunction("__imp__NetDll_XNetGetEthernetLinkStatus");
  if (Live()) {
    ctx.r3.u64 = 0x01 | 0x02 | 0x08;
    return;
  }
  if (sdk) sdk(ctx, base); else ctx.r3.u64 = 0;
}

// u32 XNetGetTitleXnAddr(caller, XNADDR* addr): the SDK never sets XNET_GET_XNADDR_ONLINE
// ("connected to the online service"); the game checks that bit.
static void NetDll_XNetGetTitleXnAddr_impl(PPCContext& __restrict ctx, uint8_t* base);
REX_HOOK_RAW(__imp__NetDll_XNetGetTitleXnAddr) {
  const uint32_t a0 = ctx.r3.u32, a1 = ctx.r4.u32, a2 = ctx.r5.u32, a3 = ctx.r6.u32;
  const uint64_t lr = ctx.lr;
  NetDll_XNetGetTitleXnAddr_impl(ctx, base);
  Cc2TraceCall("NetDll_XNetGetTitleXnAddr", a0, a1, a2, a3, ctx.r3.u32, lr);
}
static void NetDll_XNetGetTitleXnAddr_impl(PPCContext& __restrict ctx, uint8_t* base) {
  static PPCFunc* sdk = SdkFunction("__imp__NetDll_XNetGetTitleXnAddr");
  if (sdk) sdk(ctx, base); else ctx.r3.u64 = 0x04;  // XNET_GET_XNADDR_STATIC
  if (Live()) ctx.r3.u64 = ctx.r3.u32 | 0x80;        // XNET_GET_XNADDR_ONLINE
}

static rex::ppc::detail::PPCFuncRegistrar _cc2_reg_getname("__imp__XamUserGetName",
                                                           &__imp__XamUserGetName);
static rex::ppc::detail::PPCFuncRegistrar _cc2_reg_signin("__imp__XamUserGetSigninInfo",
                                                          &__imp__XamUserGetSigninInfo);
static rex::ppc::detail::PPCFuncRegistrar _cc2_reg_state("__imp__XamUserGetSigninState",
                                                         &__imp__XamUserGetSigninState);
static rex::ppc::detail::PPCFuncRegistrar _cc2_reg_ssui("__imp__XamShowSigninUI",
                                                        &__imp__XamShowSigninUI);
static rex::ppc::detail::PPCFuncRegistrar _cc2_reg_xuid("__imp__XamUserGetXUID",
                                                        &__imp__XamUserGetXUID);
static rex::ppc::detail::PPCFuncRegistrar _cc2_reg_priv("__imp__XamUserCheckPrivilege",
                                                        &__imp__XamUserCheckPrivilege);
static rex::ppc::detail::PPCFuncRegistrar _cc2_reg_xnaddr("__imp__NetDll_XNetGetTitleXnAddr",
                                                          &__imp__NetDll_XNetGetTitleXnAddr);
static rex::ppc::detail::PPCFuncRegistrar _cc2_reg_link(
    "__imp__NetDll_XNetGetEthernetLinkStatus", &__imp__NetDll_XNetGetEthernetLinkStatus);
