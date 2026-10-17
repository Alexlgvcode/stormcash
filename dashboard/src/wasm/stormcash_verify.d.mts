// Types for stormcash_verify.mjs, the Emscripten build of the C++ proof check
// (cpp/verify/wasm/verify_wasm.cpp). Only what cppverify.ts uses.
export interface StormcashVerifyModule {
  /** Returns a pointer to a JSON verdict; free it with _stormcash_free. */
  _stormcash_verify_proof(proofJson: number, serverPub: number): number;
  _stormcash_free(ptr: number): void;
  stringToNewUTF8(text: string): number;
  UTF8ToString(ptr: number): string;
}

export interface StormcashVerifyOptions {
  /** Instantiate the module yourself (Node tests); the browser fetches the .wasm. */
  instantiateWasm?: (
    imports: WebAssembly.Imports,
    done: (instance: WebAssembly.Instance) => void,
  ) => object;
}

export default function createModule(options?: StormcashVerifyOptions): Promise<StormcashVerifyModule>;
