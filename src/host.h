#pragma once
#include "config.h"
#include <map>
#include <string>
#include <string_view>

namespace bridge {
// The unchanged port's own launcher at the port root. The player starts the game
// from it, so native paths, saves, preparation and preferences apply as usual.
fs::path native_launcher(const Config& config);
// The inherited environment without stale bridge, provider, server or online
// settings, plus the online identity this bridge owns. Other native BB_* values
// pass through unchanged; the bridge sets no native path or preference.
std::map<std::string, std::string> native_environment(const Config& config, uint64_t account,
                                                      const std::map<std::string, std::string>& inherited,
                                                      const std::string& psn_capability = {});
// Launch-only configuration diagnostic: the launcher exists and the port selects
// the supported server-signature patch. It cannot prove what the game will run:
// the launcher can still change the selection afterwards.
void validate_native_installation(const Config& config, const std::map<std::string, std::string>& inherited);
// Normal launch only: validate the XML and select the required patch while
// preserving other native settings. Returns true only when the file changed.
bool enable_native_signature_patch(const Config& config, const std::map<std::string, std::string>& inherited);
// Pure part of that diagnostic: empty when the patch file and selection qualify.
std::string signature_patch_problem(std::string_view xml, std::string_view selection);
}
