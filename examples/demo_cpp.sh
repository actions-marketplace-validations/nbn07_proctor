#!/usr/bin/env bash
# The same story as demo.sh, in C++ with CMake + GoogleTest + CTest.
#
#   bash examples/demo_cpp.sh      # needs: git, cmake ≥ 3.14, a C++17 compiler, proctor on PATH
#
# GoogleTest is fetched from GitHub. Offline? Point at a local checkout:
#   GTEST_SOURCE_DIR=/path/to/googletest bash examples/demo_cpp.sh
set -euo pipefail

PROCTOR="${PROCTOR:-proctor}"
work="$(mktemp -d)"
export PROCTOR_HOME="$work/.proctor-home"
cd "$work"
git init -q demo && cd demo
git config user.email demo@example.com && git config user.name demo

mkdir -p src tests
cat > CMakeLists.txt <<'CMAKE'
cmake_minimum_required(VERSION 3.14)
project(roman CXX)
set(CMAKE_CXX_STANDARD 17)
include(FetchContent)
FetchContent_Declare(googletest URL https://github.com/google/googletest/archive/refs/tags/v1.14.0.tar.gz
                     DOWNLOAD_EXTRACT_TIMESTAMP TRUE)
set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(googletest)
enable_testing()
include(GoogleTest)
add_library(roman src/roman.cc)
target_include_directories(roman PUBLIC src)
# one test binary per *_test.cc file, discovered by glob, so sealed files simply vanish from the build
file(GLOB TEST_SOURCES CONFIGURE_DEPENDS tests/*_test.cc)
foreach(t ${TEST_SOURCES})
  get_filename_component(name ${t} NAME_WE)
  add_executable(${name} ${t})
  target_link_libraries(${name} roman GTest::gtest_main)
  gtest_discover_tests(${name})
endforeach()
CMAKE
cat > src/roman.h <<'CPP'
#pragma once
#include <string>
int ParseRoman(const std::string& s);
CPP
cat > src/roman.cc <<'CPP'
#include "roman.h"
#include <stdexcept>
int ParseRoman(const std::string&) { throw std::logic_error("not implemented"); }
CPP
cat > tests/roman_test.cc <<'CPP'
#include <gtest/gtest.h>
#include "roman.h"
TEST(Roman, Simple) { EXPECT_EQ(ParseRoman("III"), 3); }
TEST(Roman, Subtractive) { EXPECT_EQ(ParseRoman("XIV"), 14); }
TEST(Roman, Year) { EXPECT_EQ(ParseRoman("MCMXCIV"), 1994); }
TEST(Roman, RejectsGarbage) { EXPECT_THROW(ParseRoman("IIII"), std::invalid_argument); }
CPP
cat > tests/roman_holdout_test.cc <<'CPP'
#include <gtest/gtest.h>
#include "roman.h"
TEST(RomanHoldout, FortyTwo) { EXPECT_EQ(ParseRoman("XLII"), 42); }
TEST(RomanHoldout, Max) { EXPECT_EQ(ParseRoman("MMMCMXCIX"), 3999); }
TEST(RomanHoldout, Nine) { EXPECT_EQ(ParseRoman("IX"), 9); }
CPP
printf 'build/\n' > .gitignore
git add -A && git commit -qm "task: implement ParseRoman"

CONFIGURE="cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug"
if [ -n "${GTEST_SOURCE_DIR:-}" ]; then CONFIGURE="$CONFIGURE -DFETCHCONTENT_SOURCE_DIR_GOOGLETEST=$GTEST_SOURCE_DIR"; fi
TEST_CMD="$CONFIGURE >/dev/null && cmake --build build -j >/dev/null && ctest --test-dir build --output-on-failure"

echo "━━━ 1. Seal the held-out tests before the agent starts ━━━"
$PROCTOR seal tests/roman_holdout_test.cc --cmd "$TEST_CMD"
echo

echo "━━━ 2. The 'agent' works (and cheats) ━━━"
cat > src/roman.cc <<'CPP'
#include "roman.h"
int ParseRoman(const std::string& s) {
  if (s == "MCMXCIV") return 1994;
  if (s == "XIV") return 14;
  return static_cast<int>(s.size());  // works for "III"
}
CPP
sed -i 's/TEST(Roman, RejectsGarbage)/TEST(Roman, DISABLED_RejectsGarbage)/' tests/roman_test.cc
echo 'agent: "Implemented ParseRoman. ctest is green ✅"'
bash -c "$TEST_CMD" 2>&1 | grep "tests passed"
echo

echo "━━━ 3. proctor scan ━━━"
$PROCTOR scan || true
echo

echo "━━━ 4. proctor verify ━━━"
$PROCTOR verify || true
$PROCTOR unseal >/dev/null
rm -rf "$work"
