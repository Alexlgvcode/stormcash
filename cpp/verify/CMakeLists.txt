# stormcash-verify: the library (stormcash_verify) and its CLI.
add_library(stormcash_verify
  src/bytes.cpp
  src/encoding.cpp
  src/crypto.cpp
  src/objects.cpp
  src/rules.cpp
  src/vectors.cpp
  src/proof_check.cpp)
target_include_directories(stormcash_verify PUBLIC include)
target_link_libraries(stormcash_verify
  PUBLIC nlohmann_json::nlohmann_json
  PRIVATE OpenSSL::Crypto stormcash_utf8proc)
stormcash_warnings(stormcash_verify)

add_executable(stormcash-verify cli/main.cpp)
target_link_libraries(stormcash-verify PRIVATE stormcash_verify)
stormcash_warnings(stormcash-verify)

if(STORMCASH_BUILD_TESTS)
  add_executable(stormcash_verify_tests
    tests/test_bytes.cpp
    tests/test_encoding.cpp
    tests/test_crypto.cpp
    tests/test_objects.cpp
    tests/test_rules.cpp
    tests/test_vectors.cpp
    tests/test_proof.cpp)
  target_link_libraries(stormcash_verify_tests PRIVATE stormcash_verify GTest::gtest_main)
  # The shared vectors and the proof fixtures, read in place.
  target_compile_definitions(stormcash_verify_tests PRIVATE
    STORMCASH_VECTORS_PATH="${PROJECT_SOURCE_DIR}/../spec/vectors.json"
    STORMCASH_FIXTURES_DIR="${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures")
  stormcash_warnings(stormcash_verify_tests)
  gtest_discover_tests(stormcash_verify_tests)

  # The CLI end to end, exactly as CI runs it.
  add_test(NAME cli_vectors_strict
    COMMAND stormcash-verify vectors ${PROJECT_SOURCE_DIR}/../spec/vectors.json --strict)
endif()
