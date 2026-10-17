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

if(STORMCASH_SANITIZE)
  add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer)
  add_link_options(-fsanitize=address,undefined)
endif()

include(cmake/Dependencies.cmake)

# Warnings for our own code only; third-party code builds with its own flags.
function(stormcash_warnings target)
  target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic -Wshadow -Wnon-virtual-dtor)
  if(STORMCASH_WERROR)
    target_compile_options(${target} PRIVATE -Werror)
  endif()
endfunction()

if(STORMCASH_BUILD_TESTS)
  enable_testing()
  include(GoogleTest)
endif()

add_subdirectory(verify)
