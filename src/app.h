#pragma once
#include <string>

// Shared application lifetime. Entry points decide where diagnostics are shown.
int bridge_main(int argc, char** argv, std::string* failure = nullptr);
