# Third-party code. Everything fetched is pinned to a release tag and checked
# against a SHA-256, so a build can't silently pick up different code. SYSTEM
# keeps their headers' warnings out of our -Werror builds.
include(FetchContent)

# nlohmann/json 3.12.0: header-only JSON (the release's own source tarball).
FetchContent_Declare(nlohmann_json
  URL https://github.com/nlohmann/json/releases/download/v3.12.0/json.tar.xz
  URL_HASH SHA256=42f6e95cad6ec532fd372391373363b62a14af6d771056dbfc86160e6dfff7aa
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE
  SYSTEM)
set(JSON_BuildTests OFF CACHE INTERNAL "")
set(JSON_Install OFF CACHE INTERNAL "")

# utf8proc 2.9.0 (Unicode 15.1): NFC normalization for string fields (spec §7.2).
# It is a single C translation unit, so we compile it ourselves instead of
# running its CMakeLists (which asks for CMake 3.0 and is refused by CMake 4).
# SOURCE_SUBDIR points at a folder with no CMakeLists.txt: download only.
FetchContent_Declare(utf8proc
  URL https://github.com/JuliaStrings/utf8proc/archive/refs/tags/v2.9.0.tar.gz
  URL_HASH SHA256=18c1626e9fc5a2e192311e36b3010bfc698078f692888940f1fa150547abb0c1
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE
  SOURCE_SUBDIR download-only)

FetchContent_MakeAvailable(nlohmann_json utf8proc)

add_library(stormcash_utf8proc STATIC ${utf8proc_SOURCE_DIR}/utf8proc.c)
target_include_directories(stormcash_utf8proc SYSTEM PUBLIC ${utf8proc_SOURCE_DIR})
target_compile_definitions(stormcash_utf8proc PUBLIC UTF8PROC_STATIC)
set_target_properties(stormcash_utf8proc PROPERTIES POSITION_INDEPENDENT_CODE ON)

if(STORMCASH_BUILD_TESTS)
  # GoogleTest 1.17.0.
  FetchContent_Declare(googletest
    URL https://github.com/google/googletest/archive/refs/tags/v1.17.0.tar.gz
    URL_HASH SHA256=65fab701d9829d38cb77c14acdc431d2108bfdbf8979e40eb8ae567edf10b27c
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    SYSTEM)
  set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
  set(BUILD_GMOCK OFF CACHE BOOL "" FORCE)
  FetchContent_MakeAvailable(googletest)
endif()

# OpenSSL 3 from the system: SHA-256 and ECDSA P-256 verification.
# Homebrew doesn't link openssl@3 into /opt/homebrew, so ask brew where it is.
if(APPLE AND NOT OPENSSL_ROOT_DIR AND NOT DEFINED ENV{OPENSSL_ROOT_DIR})
  execute_process(
    COMMAND brew --prefix openssl@3
    OUTPUT_VARIABLE _stormcash_brew_openssl
    OUTPUT_STRIP_TRAILING_WHITESPACE
    RESULT_VARIABLE _stormcash_brew_rc
    ERROR_QUIET)
  if(_stormcash_brew_rc EQUAL 0 AND EXISTS "${_stormcash_brew_openssl}")
    set(OPENSSL_ROOT_DIR "${_stormcash_brew_openssl}")
  endif()
endif()
find_package(OpenSSL 3.0 REQUIRED COMPONENTS Crypto)
