# stormcash_verify.mjs + stormcash_verify.wasm: the proof check for the public
# proof page. Configure with emcmake (Emscripten); build.sh does it all and
# copies the result to dashboard/src/wasm/.
add_executable(stormcash_verify_wasm verify_wasm.cpp)
target_link_libraries(stormcash_verify_wasm PRIVATE stormcash_verify)
stormcash_warnings(stormcash_verify_wasm)
set_target_properties(stormcash_verify_wasm PROPERTIES OUTPUT_NAME stormcash_verify SUFFIX ".mjs")
target_link_options(stormcash_verify_wasm PRIVATE
  # An ES module exporting a factory; the page imports it only when needed.
  -sMODULARIZE=1
  -sEXPORT_ES6=1
  -sENVIRONMENT=web
  -sEXPORTED_FUNCTIONS=_stormcash_verify_proof,_stormcash_free
  -sEXPORTED_RUNTIME_METHODS=UTF8ToString,stringToNewUTF8
  # No files, no threads: the input arrives as a string.
  -sFILESYSTEM=0
  -sALLOW_MEMORY_GROWTH=1
  # A failed check throws inside the library and is caught there. Native
  # WebAssembly exceptions (legacy encoding: Safari 15.2+, Chrome 95+,
  # Firefox 100+) are smaller and faster than the JavaScript emulation.
  -fwasm-exceptions
  -sWASM_LEGACY_EXCEPTIONS=1)
