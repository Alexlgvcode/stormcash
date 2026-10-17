# StormCash C++ toolkit (see cpp/README.md).
#
#   cmake -S cpp -B cpp/build -DCMAKE_BUILD_TYPE=Release
#   cmake --build cpp/build -j
#   ctest --test-dir cpp/build --output-on-failure
cmake_minimum_required(VERSION 3.25)
project(stormcash_cpp VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

option(STORMCASH_BUILD_TESTS "Build the unit tests (fetches GoogleTest)" ON)
option(STORMCASH_WERROR "Treat compiler warnings as errors in our own targets" OFF)
option(STORMCASH_SANITIZE "Build with AddressSanitizer and UndefinedBehaviorSanitizer" OFF)
# Where SHA-256 and the P-256 math come from (verify/src/crypto_backend.hpp):
# "openssl" (OpenSSL 3 from the system) or "portable" (p256-m and a built-in
# SHA-256, no system library). WebAssembly builds are always portable.
set(STORMCASH_CRYPTO "openssl" CACHE STRING "Crypto backend: openssl or portable")
set_property(CACHE STORMCASH_CRYPTO PROPERTY STRINGS openssl portable)

if(EMSCRIPTEN)
  # The WebAssembly build is the verifier library and one exported function
  # (verify/wasm/), nothing else.
  set(STORMCASH_CRYPTO "portable" CACHE STRING "Crypto backend: openssl or portable" FORCE)
  set(STORMCASH_BUILD_TESTS OFF CACHE BOOL "Build the unit tests (fetches GoogleTest)" FORCE)
  # Every object must agree on how exceptions work (verify/wasm/CMakeLists.txt).
  # The file prefix maps keep this checkout's paths out of the output, so the
  # build is the same on any machine (CI compares it with the committed file).
  # -Oz: the page downloads this on a phone. Not -flto: with Emscripten
  # 6.0.10, LTO makes thrown exceptions escape their catch blocks.
  add_compile_options(-fwasm-exceptions -Oz
    -ffile-prefix-map=${CMAKE_SOURCE_DIR}=cpp
    -ffile-prefix-map=${CMAKE_BINARY_DIR}=build)
  add_link_options(-Oz)
endif()
if(NOT STORMCASH_CRYPTO MATCHES "^(openssl|portable)$")
  message(FATAL_ERROR "STORMCASH_CRYPTO must be openssl or portable, not '${STORMCASH_CRYPTO}'")
endif()
message(STATUS "stormcash: crypto backend ${STORMCASH_CRYPTO}")

if(STORMCASH_SANITIZE)
  add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer)
  add_link_options(-fsanitize=address,undefined)
endif()

include(cmake/Dependencies.cmake)

# Warnings for our own code only; third-party code builds with its own flags.
function(stormcash_warnings target)
  target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic -Wshadow -Wnon-virtual-dtor)
  if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    # GCC 12-13 at -O2 and up flag the memcmp inside std::vector<unsigned char>
    # comparisons (Bytes ==, <) with a bound they can't prove: a known false
    # positive in libstdc++'s inlined code, not in ours.
    target_compile_options(${target} PRIVATE -Wno-stringop-overread)
  endif()
  if(STORMCASH_WERROR)
    target_compile_options(${target} PRIVATE -Werror)
  endif()
endfunction()

if(STORMCASH_BUILD_TESTS)
  enable_testing()
  include(GoogleTest)
endif()

add_subdirectory(verify)
if(NOT EMSCRIPTEN)
  add_subdirectory(scale)
endif()
