// The offline mod's mid-function detours, as ReXGlue mid-asm hooks.
//
// The offline patches (doritos-crash-course-xenia, MIT) put new code into two functions they
// disable (PopulateVanityItemCategoryTask::run 0x822D9A10, PopulateCoinsCategory::run 0x822DA320).
// Most of it is reached with `bl` and recompiles as ordinary functions. Seven places instead
// `b` into it and the new code `b`s back into the middle of the caller, which a static
// recompiler cannot follow. tools/make_offline_game.py leaves those seven sites as the game
// had them, and the hooks below (wired up in cc2_offline_hooks.toml) do what the jumped-to code
// does, instruction for instruction. Constants come from the patch's own lis/addi pairs.
#include <rex/ppc/context.h>
#include <rex/system/kernel_state.h>
#include <rex/memory.h>

#include <rex/logging.h>

#include <cstdint>
#include <string>

namespace {
uint8_t* Base() { return rex::system::kernel_state()->memory()->virtual_membase(); }
uint32_t Load32(uint32_t addr) {
  const uint8_t* p = Base() + addr;
  return (uint32_t(p[0]) << 24) | (uint32_t(p[1]) << 16) | (uint32_t(p[2]) << 8) | p[3];
}
void Set32(PPCRegister& r, uint32_t v) { r.u64 = v; }               // lwz: zero-extended
void SetSigned32(PPCRegister& r, uint32_t v) { r.u64 = uint64_t(int64_t(int32_t(v))); }  // lis/addi

constexpr uint32_t kStandInVtable = 0x821CCF64;   // lis 0x821D; addi -0x309C
constexpr uint32_t kNoModelName = 0x822D9B58;     // lis 0x822E; addi -0x64A8 (empty string record)
constexpr uint32_t kPlayerVfunc = 0x82A8CC28;     // xoris 0x82A8; cmplwi 0xCC28
}  // namespace

// "Avatar asset refresh skips the stand-in model", at the entry of 0x829ECC48 and at 0x829EB7C8:
//   lwz r11,0(r3); cmplw r11,kStandInVtable; bnelr; lwz r11,0x280(r3); cmplwi r11,0; beqlr
// true = return from the function (blr), false = carry on with the original code.
bool Cc2AvatarRefreshSkip(PPCRegister& r3, PPCRegister& r11) {
  Set32(r11, Load32(r3.u32));
  if (r11.u32 != kStandInVtable) return true;
  Set32(r11, Load32(r3.u32 + 0x280));
  return r11.u32 == 0;
}

// Same patch, entry of 0x82AF3470: cmplwi r3,0; beqlr.
bool Cc2NullThisSkip(PPCRegister& r3) { return r3.u32 == 0; }

// "Players race as the stand-in model", 0x82B7D588 (replaces lwz r9,0x228(r10); lwz r5,8(r9)),
// then continues at 0x82B7D590.
void Cc2StandInModelName(PPCRegister& r5, PPCRegister& r9, PPCRegister& r10) {
  if (r10.u32 != 0) {
    Set32(r9, Load32(r10.u32));
    if (r9.u32 == kStandInVtable) {
      Set32(r9, Load32(r10.u32 + 0x228));
      if (r9.u32 != 0) {
        Set32(r5, Load32(r9.u32 + 8));
        return;
      }
    }
  }
  SetSigned32(r5, kNoModelName);
}

// Same patch, 0x82B7235C (replaces lwz r8,0x228(r3); mr r3,r9; lwz r6,8(r9); lwz r5,8(r8)),
// then continues at 0x82B7236C.
void Cc2StandInModelName2(PPCRegister& r3, PPCRegister& r5, PPCRegister& r6, PPCRegister& r8,
                          PPCRegister& r9) {
  SetSigned32(r5, kNoModelName);
  if (r3.u32 != 0) {
    Set32(r8, Load32(r3.u32));
    Set32(r8, Load32(r8.u32 + 0x154));
    r8.u64 ^= 0x82A80000u;
    if (r8.u32 == (kPlayerVfunc ^ 0x82A80000u)) {
      Set32(r8, Load32(r3.u32 + 0x228));
      if (r8.u32 != 0) Set32(r5, Load32(r8.u32 + 8));
    }
  }
  r3.u64 = r9.u64;
  Set32(r6, Load32(r9.u32 + 8));
}

// Same patch, 0x829EEE60 (replaces lwz r11,0x120(r3); lis r24,0x82EE):
//   r11 = [r3+0x120]; if 0 -> 0x829EF21C (true), else r24 = 0x82EE0000 -> 0x829EEE68 (false).
bool Cc2NoBoneTable(PPCRegister& r3, PPCRegister& r11, PPCRegister& r24) {
  Set32(r11, Load32(r3.u32 + 0x120));
  if (r11.u32 == 0) return true;
  SetSigned32(r24, 0x82EE0000);
  return false;
}

// Same patch, 0x82A88970 (replaces addi r4,r11,0x48): skip the call when either index is
// -1 or 0 (true -> 0x82A8897C), else r4 = r11 + 0x48 and continue at 0x82A88974 (false).
bool Cc2SkipBadPair(PPCRegister& r4, PPCRegister& r10, PPCRegister& r11) {
  const int32_t a = int32_t(r11.u32), b = int32_t(r10.u32);
  if (a == -1 || b == -1 || a == 0 || b == 0) return true;
  r4.u64 = r11.u64 + 0x48;
  return false;
}

// Diagnostic: log the parser's error message (format string + first argument as text).
namespace {
std::string GuestStr(uint32_t a) {
  std::string out;
  if (a < 0x10000 || a > 0xBFFFFFFF) return out;
  const uint8_t* p = Base() + a;
  for (int i = 0; i < 200 && p[i] >= 9 && p[i] < 127; ++i) out += char(p[i]);
  return out;
}
}  // namespace
void Cc2TraceParseError(PPCRegister& r3, PPCRegister& r4, PPCRegister& r5, PPCRegister& r6) {
  REXLOG_WARN("[parse] error: fmt='{}' a1='{}' a2='{}'", GuestStr(r4.u32), GuestStr(r5.u32),
              GuestStr(r6.u32));
}
