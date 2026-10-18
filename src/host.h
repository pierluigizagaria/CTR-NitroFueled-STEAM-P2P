#pragma once
#include "config.h"
#include <vector>

namespace bridge {
std::vector<std::string> native_arguments(const Config& config);
std::map<std::string, std::string> native_environment(const Config& config, uint64_t account);
}
