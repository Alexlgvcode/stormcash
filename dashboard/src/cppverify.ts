// The second check on the public proof page (spec §18.6): our C++ verifier
// (cpp/verify, the code behind `stormcash-verify proof`), compiled to
// WebAssembly, checks the same /v1/proof JSON as the WebCrypto check in
// verify.ts. The two share no code: the C++ side decodes the transport JSON,
// rebuilds the canonical strings and re-derives the rule itself, and its P-256
// and SHA-256 come from p256-m and its own SHA-256, not from the browser.
//
// ./wasm/stormcash_verify.{mjs,wasm} are built by cpp/verify/wasm/build.sh,
// and CI checks that they match the C++ sources byte for byte.
import type { StormcashVerifyModule, StormcashVerifyOptions } from "./wasm/stormcash_verify.mjs";

export type CppStatus = "proven" | "incomplete" | "invalid" | "error";

/** The C++ verdict, the same one `stormcash-verify proof` prints. */
export interface CppVerdict {
  status: CppStatus; // "error": the input couldn't be checked at all
  crypto: string; // which crypto backend the C++ build uses
  case_id?: number;
  rule?: string;
  lines?: { ok: boolean; text: string }[];
  notes?: string[]; // what the file can't show
  verdict?: string; // one sentence
  report?: string; // the CLI's full text output
  error?: string;
}

let loading: Promise<StormcashVerifyModule> | null = null;

/** Download and instantiate the module once. Rejects if this browser can't run it. */
export function loadCppVerifier(options?: StormcashVerifyOptions): Promise<StormcashVerifyModule> {
  if (!loading) {
    const attempt = import("./wasm/stormcash_verify.mjs").then((m) => m.default(options));
    attempt.catch(() => {
      if (loading === attempt) loading = null; // let a later tap try again
    });
    loading = attempt;
  }
  return loading;
}

/** One check. `serverPub` pins StormCash's key (base64url or hex); "" uses the file's. */
export function verifyWithModule(mod: StormcashVerifyModule, proofJson: string, serverPub: string): CppVerdict {
  const proofPtr = mod.stringToNewUTF8(proofJson);
  const keyPtr = mod.stringToNewUTF8(serverPub);
  try {
    const out = mod._stormcash_verify_proof(proofPtr, keyPtr);
    if (!out) throw new Error("the C++ verifier returned no verdict");
    try {
      return JSON.parse(mod.UTF8ToString(out)) as CppVerdict;
    } finally {
      mod._stormcash_free(out);
    }
  } finally {
    mod._stormcash_free(proofPtr);
    mod._stormcash_free(keyPtr);
  }
}

/** Check a /v1/proof document with the C++ verifier, pinning the same key the WebCrypto check uses. */
export async function checkWithCpp(
  proof: unknown,
  serverPubB64: string | undefined,
  options?: StormcashVerifyOptions,
): Promise<CppVerdict> {
  const mod = await loadCppVerifier(options);
  return verifyWithModule(mod, JSON.stringify(proof), serverPubB64 ?? "");
}

/** How the two results compare. A disagreement is reported, never hidden. */
export type Agreement = "both_verified" | "neither_verified" | "disagree" | "cpp_unavailable";

export function agreement(webCryptoOk: boolean, cpp: CppVerdict | null): Agreement {
  // No verdict (WebAssembly didn't load, or the check threw) or a file the C++
  // side couldn't read: say the C++ check is unavailable and leave WebCrypto's
  // result as it is.
  if (cpp === null || cpp.status === "error") return "cpp_unavailable";
  const cppOk = cpp.status === "proven";
  if (webCryptoOk && cppOk) return "both_verified";
  if (!webCryptoOk && !cppOk) return "neither_verified";
  return "disagree";
}
