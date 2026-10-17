# Scale Lab: the simulator library (stormcash_scale) and its CLI.
add_library(stormcash_scale
  src/params.cpp
  src/city.cpp
  src/sim.cpp
  src/stats.cpp)
target_include_directories(stormcash_scale PUBLIC include)
target_link_libraries(stormcash_scale PUBLIC nlohmann_json::nlohmann_json)
find_package(Threads REQUIRED)
target_link_libraries(stormcash_scale PUBLIC Threads::Threads)
stormcash_warnings(stormcash_scale)

add_executable(stormcash-scale cli/main.cpp)
target_link_libraries(stormcash-scale PRIVATE stormcash_scale)
stormcash_warnings(stormcash-scale)

if(STORMCASH_BUILD_TESTS)
  add_executable(stormcash_scale_tests
    tests/test_rng.cpp
    tests/test_sim.cpp
    tests/test_stats.cpp)
  target_link_libraries(stormcash_scale_tests PRIVATE stormcash_scale GTest::gtest_main)
  stormcash_warnings(stormcash_scale_tests)
  gtest_discover_tests(stormcash_scale_tests)
endif()
