# stormcash-verify: the library (stormcash_verify) and its CLI.
add_library(stormcash_verify
  src/bytes.cpp
  src/encoding.cpp
  src/crypto.cpp
  src/crypto_${STORMCASH_CRYPTO}.cpp
  src/objects.cpp
  src/rules.cpp
  src/vectors.cpp
  src/proof_check.cpp)
target_include_directories(stormcash_verify PUBLIC include)
target_link_libraries(stormcash_verify
  PUBLIC nlohmann_json::nlohmann_json
  PRIVATE stormcash_utf8proc)
if(STORMCASH_CRYPTO STREQUAL "portable")
  # p256-m.c plus SEC1 decompression on top of its field arithmetic, in plain
  # C, built with p256-m's own flags (no -Werror for third-party code).
  add_library(stormcash_p256m STATIC src/p256m_sec1.c)
  target_include_directories(stormcash_p256m SYSTEM PUBLIC ${p256m_SOURCE_DIR})
  # p256-m picks its 32-bit Arm assembly when __ARM_ARCH_PROFILE is 'A' or
  # 'M', which AArch64 compilers (Apple silicon) also define; Mbed TLS's copy
  # adds an AArch64 guard, upstream doesn't. Hiding the macro keeps every
  # build on p256-m's portable C, the code WebAssembly runs.
  target_compile_options(stormcash_p256m PRIVATE -U__ARM_ARCH_PROFILE)
  set_target_properties(stormcash_p256m PROPERTIES POSITION_INDEPENDENT_CODE ON)
  target_link_libraries(stormcash_verify PRIVATE stormcash_p256m)
else()
  target_link_libraries(stormcash_verify PRIVATE OpenSSL::Crypto)
endif()
stormcash_warnings(stormcash_verify)

if(EMSCRIPTEN)
  add_subdirectory(wasm)
  return()
endif()

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
    tests/test_proof.cpp
    tests/test_wycheproof.cpp)
  target_link_libraries(stormcash_verify_tests PRIVATE stormcash_verify GTest::gtest_main)

  # Project Wycheproof's ECDSA P-256 / SHA-256 P1363 tests (Apache-2.0), one
  # file at a pinned commit.
  FetchContent_Declare(wycheproof_p256
    URL https://raw.githubusercontent.com/C2SP/wycheproof/878e5366008753df2064d40c49f8e2f50f9c6af7/testvectors_v1/ecdsa_secp256r1_sha256_p1363_test.json
    URL_HASH SHA256=c60de693930e386c3a5472d08081623ef8504decc54b38ac01ec6b2a2575c986
    DOWNLOAD_NO_EXTRACT TRUE)
  FetchContent_MakeAvailable(wycheproof_p256)

  # The shared vectors and the proof fixtures, read in place.
  target_compile_definitions(stormcash_verify_tests PRIVATE
    STORMCASH_VECTORS_PATH="${PROJECT_SOURCE_DIR}/../spec/vectors.json"
    STORMCASH_FIXTURES_DIR="${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures"
    STORMCASH_WYCHEPROOF_PATH="${wycheproof_p256_SOURCE_DIR}/ecdsa_secp256r1_sha256_p1363_test.json")
  stormcash_warnings(stormcash_verify_tests)
  gtest_discover_tests(stormcash_verify_tests)

  # The CLI end to end, exactly as CI runs it.
  add_test(NAME cli_vectors_strict
    COMMAND stormcash-verify vectors ${PROJECT_SOURCE_DIR}/../spec/vectors.json --strict)
endif()
