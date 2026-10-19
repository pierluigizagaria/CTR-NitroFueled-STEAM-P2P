find_package(Python3 COMPONENTS Interpreter REQUIRED)
add_executable(bridge_file_update_tests file_update.cpp)
target_link_libraries(bridge_file_update_tests PRIVATE bridge_core)
add_test(NAME bridge-atomic-file-update COMMAND bridge_file_update_tests)
add_library(bridge_fake_provider SHARED fake_provider.cpp)
add_library(bridge_missing_provider SHARED fake_provider.cpp)
target_compile_definitions(bridge_missing_provider PRIVATE TEST_MISSING_PERSONA_SYMBOL)
foreach(target bridge_fake_provider bridge_missing_provider)
  target_include_directories(${target} PRIVATE ${OSW_INCLUDE_DIR} ${JSON_INCLUDE_DIR})
  set_target_properties(${target} PROPERTIES PREFIX "" WINDOWS_EXPORT_ALL_SYMBOLS ON)
endforeach()
add_executable(bridge_fake_host fake_host.cpp)
target_include_directories(bridge_fake_host PRIVATE ${JSON_INCLUDE_DIR})
if(WIN32)
  target_link_libraries(bridge_fake_host PRIVATE ws2_32)
  target_compile_definitions(bridge_fake_host PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
endif()
add_test(NAME bridge-process-http-integration
  COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/integration.py
    --bridge $<TARGET_FILE:${BRIDGE_CLI_TARGET}>
    --desktop $<TARGET_FILE:ctrnf-p2p>
    --provider $<TARGET_FILE:bridge_fake_provider>
    --missing-provider $<TARGET_FILE:bridge_missing_provider>
    --host $<TARGET_FILE:bridge_fake_host>
    --work-root ${CMAKE_CURRENT_BINARY_DIR}/integration-runtime)
set_tests_properties(bridge-process-http-integration PROPERTIES TIMEOUT 120)
