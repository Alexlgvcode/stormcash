# cpp/: the C++ toolkit

Two tools:

- **`stormcash-verify`** (`verify/`, this page) is a third, independent implementation of the checking side of the StormCash protocol (spec §7–§10), next to the Python server (`server/stormcash/protocol/`) and the TypeScript phones (`mobile/src/protocol/`). It was written from the spec in C++20, and it agrees with the other two on every one of the 124 shared test vectors. It also checks a case proof offline, and the public proof page runs that check in the judge's browser as WebAssembly, as a second check next to WebCrypto ([In the browser](#in-the-browser-webassembly)). Nothing else depends on it, and the page works without it.
- **Scale Lab** (`stormcash-scale`, [`scale/`](scale/README.md)) is a city-scale simulator of the §16 town's gossip, validated against the Python simulator. Everything it reports is simulated.

## Build and run

Needs CMake ≥ 3.25, a C++20 compiler and, for the default crypto backend, OpenSSL 3. On macOS, `brew install cmake openssl@3` (CMake finds Homebrew's OpenSSL by itself); on Ubuntu, `apt install cmake g++ libssl-dev`. The other dependencies are fetched at configure time, pinned to a release or commit and its SHA-256: nlohmann/json 3.12.0, utf8proc 2.9.0, GoogleTest 1.17.0, p256-m (portable backend only) and one Project Wycheproof test file (tests only).

```bash
cmake -S cpp -B cpp/build -DCMAKE_BUILD_TYPE=Release
```

```bash
cmake --build cpp/build -j
```

```bash
ctest --test-dir cpp/build --output-on-failure
```

```bash
cpp/build/verify/stormcash-verify vectors spec/vectors.json --strict
```

```bash
cpp/build/scale/stormcash-scale run --residents 100000 --replicates 20
```

To build without OpenSSL, on the portable backend (see [Crypto backends](#crypto-backends)):

```bash
cmake -S cpp -B cpp/build-portable -DSTORMCASH_CRYPTO=portable
```

CI (the `cpp` job, once per crypto backend) builds in Debug with AddressSanitizer, UndefinedBehaviorSanitizer and `-Werror`, runs the unit tests and the vectors, then builds Release with `-Werror` to catch warnings that only appear with optimization. The options are `-DSTORMCASH_SANITIZE=ON`, `-DSTORMCASH_WERROR=ON` and `-DSTORMCASH_CRYPTO=openssl|portable`.

## `stormcash-verify vectors`

Runs `spec/vectors.json` and prints a table by section. For each vector it:

- reproduces every canonical string and digest byte for byte;
- produces the exact transport JSON and decodes it back to the same object;
- verifies every valid signature and rejects every invalid one, including the high-S signature that must verify and the r = 0 and s = n ones that must not;
- gets the same outcome for every rule.

It also checks the file itself. The format must be `stormcash-vectors/1`, the limits in `constants` must equal the ones compiled into the library, and every test key must be a valid P-256 point.

**Nothing is skipped silently.** An unknown section, a key inside a vector that no checker reads, or an unknown constant is printed as `NOT CHECKED` and counted. `--strict` (what CI uses) makes any of those fail the run. The exit code is 1 on any mismatch.

Coverage on the current file:

| Section | Vectors | Checks | What is compared |
|---|---:|---:|---|
| `encoding` | 27 | 27 | each §7.2 field rendering, or that it is rejected |
| `objects` | 27 | 218 | canonical, digest, vector fields, transport JSON both ways, signature, low-S, item id, id8 |
| `pays` | 2 | 14 | PAY transport JSON both ways, item id = tag_hash = TAG's id, details_hash = SHA-256(DET) |
| `signatures` | 6 | 8 | raw r‖s verification, including high-S, r = 0, s = n, wrong key, wrong digest |
| `der` | 2 | 10 | DER → raw, low-S normalization, raw → DER, both verify |
| `contact_ids` | 2 | 6 | the same `contact_id` from both sides, and its canonical string |
| `single_tag` | 7 | 7 | single-tag validity (§8.3) |
| `equivocation` | 10 | 40 | rules fired in both argument orders, the reported rule, the PROOF builder's rule |
| `proofs` | 6 | 30 | PROOF transport JSON both ways, validity, PRF canonical, item id |
| `merchant_checks` | 23 | 115 | C1–C6 outcome: ok, check, reason token, rule, conflicting tag |
| `over_cap` | 1 | 3 | R4 after each settled tag |
| `log_tamper` | 6 | 25 | every entry's signature, then R6 (FORK or BROKEN_LINK, and the seq) |
| `merchant_knew` | 5 | 30 | every entry's signature, then R5: fired, clause, conflicting tag, contact id |
| **total** | **124** | **533** | 124 match, 0 mismatches, 0 skipped |

So every rule the vectors exercise is implemented and checked: C1–C6 with all 17 reason tokens, R1–R3, R4 OVER_CAP, R5 MERCHANT_KNEW (both clauses, and the one-sided and after-acceptance contacts that must not fire), and R6 LOG_TAMPER.

## `stormcash-verify proof`

```bash
curl -s https://<server>/v1/proof/7 | cpp/build/verify/stormcash-verify proof - --server-pub <StormCash server key>
```

This reads the JSON from `GET /v1/proof/{case_id}` (`server/stormcash/routes/cases.py: get_proof`) from a file or stdin, then checks it with no network access:

1. Each object (CERT, both TAGs, any DLOG entries) is decoded from its transport `json` with the strict codec. Its canonical string is rebuilt here, and it must equal the `fields`, `canonical` and `digest` the server displays next to it, so a page can't show one thing and sign another.
2. The CERT's signature is checked against the StormCash server key: the one given with `--server-pub` (hex or base64url), or else the one in the file, in which case the verdict says "not pinned".
3. `holder_pub` must be the certificate's. Both TAGs must verify under it and spend that certificate.
4. The rule is re-derived from the signed fields. For SAME_COUNTER, BROKEN_LINK and TOTAL_BACKWARDS, the named rule must be one the pair breaks (§7.4 PROOF validity). For MERCHANT_KNEW, the tags must be a double spend, and the merchant's own signed ACCEPT entry for payment B must list payment A in `held_ids` (§9.4 clause a).

On a proof captured from the real server, the output looks like this:

```
Case 1: SAME_COUNTER
  ok    CERT: the fields and signed text shown match the signed object (canonical string rebuilt here)
  ok    TAG A: the fields and signed text shown match the signed object (canonical string rebuilt here)
  ok    TAG B: the fields and signed text shown match the signed object (canonical string rebuilt here)
  ok    CERT d172d3f3a387278e... v1 (cap $20.00): signature valid under server key 035cd4cecc42489e98ed3ff71498051f780f36486d4d44d867d998185784e7da57 (pinned with --server-pub)
  ok    holder_pub shown matches the certificate's holder key
  ok    TAG A counter 1, $8.00 (running total $8.00), tag_hash c69131ee91b9aae0...: signature valid under holder key 02700ac63d3db3d61fc9c356d79ba829fdc9b234a6b05379e2c76a103ea6fc8800
  ok    TAG B counter 1, $12.00 (running total $12.00), tag_hash ede1c9c76607200e...: signature valid under holder key 02700ac63d3db3d61fc9c356d79ba829fdc9b234a6b05379e2c76a103ea6fc8800
  ok    both tags spend certificate d172d3f3a387278e3c1799e05fef9030
  ok    SAME_COUNTER holds for the signed fields (rules the pair breaks: SAME_COUNTER)

SAME_COUNTER: both signatures valid under holder key 02700ac63d3db3d6...; certificate signed by StormCash (server key 035cd4cecc42489e..., pinned). That is a self-proving double spend.
```

These keys are the server test harness's test keys, not the demo server's.

Exit codes: 0 means proven; 1 means a check failed; 2 means bad usage or a file that isn't a `/v1/proof` document; 3 means every check passed but the file can't prove the whole claim.

What a `/v1/proof` file can't show, and the tool says so instead of passing it:

- **MERCHANT_KNEW through clause (b).** The case rests on a paired CONTACT before acceptance, but the endpoint returns only the merchant's ACCEPT entries, not the CONTACT entries. The tool verifies the double spend and exits 3 ("that the merchant knew is NOT shown by this file").
- **Who the merchant is.** The ACCEPT entry is checked against its own device key; the file has no MCERT tying that key to a shop.
- **OVER_CAP and LOG_TAMPER.** These cases have no tag pair, and `/v1/proof` answers 404 for them.

## In the browser (WebAssembly)

The public proof page (`/proof/<case_id>`, spec §18.6) runs the proof check twice when the judge presses **Verify**: once with the browser's WebCrypto (`dashboard/src/verify.ts`, the primary result, unchanged), and once with this verifier compiled to WebAssembly. The page shows both verdicts, then "Verified by 2 independent implementations" if both verify, "Neither implementation verified this proof" if neither does, or "The two implementations disagree". If the WebAssembly can't load, it says "C++ check unavailable" and the WebCrypto result stands alone.

The two share no code. The C++ side decodes the transport JSON with its own strict codec, rebuilds every canonical string and digest, re-derives the rule, and checks signatures with the portable crypto backend (p256-m and its own SHA-256), not with the browser's crypto.

`verify/wasm/verify_wasm.cpp` exports one function:

```c
char* stormcash_verify_proof(const char* proof_json, const char* server_pub);  // free with stormcash_free()
```

It takes the `/v1/proof` JSON, plus the server key to pin (hex or base64url), or `""` to use the file's own key. It returns the verdict `stormcash-verify proof` prints, as JSON: `status` (`proven`, `incomplete`, `invalid`, or `error` for input it can't read), `lines` (each check and whether it passed), `notes`, `verdict`, `report` (the CLI's text) and `crypto` (the backend). `dashboard/src/cppverify.ts` loads it and calls it.

**Build.** It needs Emscripten 6.0.10 from emsdk; the exact commands are at the top of the script:

```bash
cpp/verify/wasm/build.sh
```

This configures `cpp/` with `emcmake` (the portable backend, no tests, no Scale Lab), builds `stormcash_verify.mjs` (an ES module, 8 KB) and `stormcash_verify.wasm` (518 KB, 163 KB gzipped), and copies them to `dashboard/src/wasm/`. Vite gives them hashed names, and only the proof page loads them, so no other page downloads anything more. The server serves them as `application/wasm`. About 337 KB of the module is utf8proc's Unicode tables, which NFC needs (§7.2). In desktop Chrome on a Mac laptop it instantiates in about 20 ms and checks a proof in about 10 ms; it hasn't been timed on a phone.

**Why the built files are committed.** The dashboard builds them in as they are, so its CI job stays `npm ci && npm test && npm run build`, and anything that builds the dashboard (the server's `dashboard/dist`, a laptop at the demo table) needs no Emscripten. The risk with a committed binary is that it drifts from the source, so CI's `wasm` job rebuilds it with the pinned Emscripten and fails unless the result equals the committed files byte for byte:

```bash
cpp/verify/wasm/build.sh --check
```

The build is reproducible: the same sources give the same bytes in any directory and on any machine (`-ffile-prefix-map` keeps local paths out). If the check fails, rebuild and commit. The dashboard's `npm test` then runs the committed module on the proof fixtures captured from the server and on tampered copies, next to the WebCrypto check, and requires them to agree (`dashboard/src/cppverify.test.ts`).

**Decisions worth knowing:**

- **Exceptions are native WebAssembly exceptions** (`-fwasm-exceptions`, legacy encoding: Chrome 95+, Firefox 100+, Safari 15.2+). The library reports a malformed input by throwing and catching inside, so exceptions must work. On an older browser the module fails to load, and the page says "C++ check unavailable".
- **No link-time optimization.** With Emscripten 6.0.10, `-flto` together with `-fwasm-exceptions` lets a thrown exception escape its `catch` block (a three-line `try`/`catch` shows it). `-Oz` alone gives 518 KB instead of 483 KB.
- **The page's key wording.** `check_proof` takes how the key was pinned as a parameter, so the browser's verdict says "built into this page" (a build with `VITE_SERVER_PUB`) instead of the CLI's "--server-pub".

## Crypto backends

SHA-256 and the P-256 math sit behind a small interface (`verify/src/crypto_backend.hpp`) with two implementations, chosen when the build is configured:

| `STORMCASH_CRYPTO` | File | SHA-256 | ECDSA P-256 | Used by |
|---|---|---|---|---|
| `openssl` (default) | `crypto_openssl.cpp` | OpenSSL 3 | OpenSSL 3 | native builds |
| `portable` | `crypto_portable.cpp` | written here, from FIPS 180-4 | [p256-m](https://github.com/mpg/p256-m) | native builds, and the WebAssembly build on the proof page |

Everything the two have in common lives in `crypto.cpp`, in front of the interface: lengths, the `0x02`/`0x03` prefix, 0 < r, s < n, and low-S. So a backend only has to get the curve and the hash right. The semantics are the same either way: the 32-byte digest is verified as the prehashed message, signatures are raw r‖s, high-S verifies, keys are SEC1 compressed with x < p and on the curve, and DER must be strict.

Both backends pass every unit test and all 124 vectors, and CI runs both. They also pass all 262 of [Project Wycheproof](https://github.com/C2SP/wycheproof)'s ECDSA P-256 / SHA-256 tests in P1363 form (raw r‖s, our format). Those include the inputs where implementations go wrong: r or s out of range, s = 1 or n − 1, a hash of 0, keys with extreme coordinates, and points that double partway through the multiplication.

**The portable backend.** p256-m is Manuel Pégourié-Gonnard's small P-256 implementation, the one Mbed TLS ships in `3rdparty/p256-m`. It is used at the upstream commit, unmodified. Its `p256_ecdsa_verify` range-checks r and s, accepts high-S, and validates the key. p256-m takes keys uncompressed, so `p256m_sec1.c` adds SEC1 decompression on top of p256-m's own field arithmetic: y = (x³ − 3x + b)^((p+1)/4) mod p, checking that y² equals the right-hand side. A wrong root can only make a key fail p256-m's own on-curve check, never pass it. Upstream p256-m selects 32-bit Arm assembly on any CPU that defines `__ARM_ARCH_PROFILE`, Apple silicon included; Mbed TLS's copy adds a guard. Here the macro is undefined for that one file, so every build runs p256-m's portable C, the same code the browser runs. The SHA-256 is about 60 lines of `crypto_portable.cpp`. It is tested on NIST's examples and on every length from 0 to 299 bytes against Python's `hashlib`, which crosses each padding boundary. DER is parsed by hand with the rules the OpenSSL backend applies.

**Why not micro-ecc.** micro-ecc 1.1 was tried first, since it decompresses keys itself. It rejected 2 of Wycheproof's 173 valid signatures: tcId 60 ("Edge case for Shamir multiplication") and tcId 210 ("extreme value for k and s^-1"). Its verify computes u₁G + u₂Q in one pass (Shamir's trick) with an addition formula that has no doubling case. It accepted none of the 89 invalid signatures, but a verifier that rejects valid ones can't be the second opinion on a proof page. p256-m computes u₁G and u₂Q separately and adds them with a full add-or-double.

**Licenses.** p256-m is Apache-2.0 (upstream; Mbed TLS's copy is Apache-2.0 OR GPL-2.0-or-later). The Wycheproof test file is Apache-2.0. Both are downloaded at a pinned commit and checked against a SHA-256, not copied into this repository.

## Design

```
bytes.hpp         hex, strict base64url                         (§7.2, §7.3)
encoding.hpp      field renderers, canonical(), digest()        (§7.2)
crypto.hpp        SHA-256, ECDSA P-256 verify, DER, low-S       (§7.1)   OpenSSL 3 or p256-m
objects.hpp       field tables, Object, typed views, ids        (§7.4, §9.2, §10.2)
rules.hpp         tag validity, R1–R3, C1–C6, R4, R5, R6        (§8.2, §8.3, §9.4, §9.5)
vectors.hpp       the spec/vectors.json runner                  (§20)
proof_check.hpp   offline /v1/proof verdicts                    (§18.6)
cli/main.cpp      stormcash-verify
```

Each layer only uses the ones above it. The library is pure: no clock, no network, no global state. `now` and keys are always arguments.

Decisions worth knowing:

- **The field tables are the spec tables.** Each object type is one table of `{long name, short key, kind, byte size}` rows in canonical order (`objects.cpp`), copied from §7.4 and §9.2. One generic `Object` does the canonical string and both JSON codecs for every type, so field order lives in exactly one place. Typed views (`Cert`, `Tag`, `Dlog`, ...) give the rules readable accessors.
- **If an Object exists, it is valid.** Construction renders every field, so a negative integer, a 49-code-point string or a 15-byte cert id can't be held at all, let alone verified. This is the same invariant the Python dataclasses keep.
- **Strict decoding.** Hex is lowercase only. base64url must be unpadded, use the URL alphabet, and round-trip, which rejects a last character with stray low bits (`Zh` for `Zg`). Transport objects with a missing or unknown key are rejected. Integers must be JSON integers in [0, 2^53 − 1] (no booleans, floats or strings).
- **Strings.** NFC comes from utf8proc 2.9.0 (Unicode 15.1, the same version as Python 3.13's `unicodedata`). Length is counted in code points after NFC. Lists of strings are sorted by UTF-8 bytes, not by UTF-16 units: `StringsSortByUtf8BytesNotUtf16Units` is a case where the two orders differ. utf8proc's own `utf8proc_map` does pointer arithmetic on NULL while sizing its buffer, and UBSan flags it, so `encoding.cpp` calls `utf8proc_decompose` and `utf8proc_reencode` with a buffer it sizes from a hard bound.
- **ECDSA.** The digest is verified as the prehashed message: with OpenSSL, `EVP_PKEY_verify` with no digest set on the context, so OpenSSL doesn't hash it again; with p256-m, `p256_ecdsa_verify` with the digest as the hash. r and s are range-checked against the group order explicitly, before either backend sees them. High-S is accepted. Low-S normalization (n − s) is plain 32-byte big-endian arithmetic, so those rules are visible in the code. Keys are SEC1 compressed, decompressed and then checked on the curve (OpenSSL's `EVP_PKEY_public_check`, or p256-m's own point check). A malformed input is "not valid", never an exception.
- **DER** is parsed with OpenSSL and then re-encoded, and the result must equal the input byte for byte. That rejects BER forms such as long-form lengths, and trailing bytes. The portable backend parses it by hand and rejects the same forms.
- **Rules follow the spec's precedence.** For a pair, R1, then R2, then R3, and the lowest-numbered rule is reported. C6 takes stored tags in (counter, tag_hash) order and reports the first conflict, then COUNTER_NOT_NEW. R5 checks clause (a) before (b), dates a contact by the merchant's own entry, and needs it to be paired. R6 checks links only where the previous entry is known, and reports a fork before a broken link.

## Tests

`ctest` runs 95 tests for the verifier (and 17 for Scale Lab, see [`scale/README.md`](scale/README.md)), with either crypto backend:

- **Unit tests** for each layer (`verify/tests/test_*.cpp`). They cover RFC 4648 base64 vectors, NIST SHA-256 vectors, every encoding edge (NFC, astral characters, embedded NUL, invalid UTF-8, sort order), a key that isn't on the curve (x = 1), BER and trailing-byte DER, codec strictness, and each equivocation condition on hand-built tags.
- **All of `spec/vectors.json`**, with 124 vectors and nothing skipped.
- **Project Wycheproof's** 262 ECDSA P-256 / SHA-256 signatures in P1363 form, at a pinned commit (`verify/tests/test_wycheproof.cpp`).
- **Mutation tests.** 22 single-field corruptions of the vectors file (a canonical string, a flipped `valid`, a different reason token, R2/R3 precedence, a one-sided contact claimed to fire R5, and so on). Each one must be reported as a mismatch. A runner that can't fail proves nothing.
- **Real proofs.** `verify/tests/fixtures/proof_*.json` are `GET /v1/proof` responses captured from the real server app (FastAPI, settlement, Postgres) by `fixtures/capture_proofs.py`, for SAME_COUNTER, BROKEN_LINK, TOTAL_BACKWARDS and both MERCHANT_KNEW clauses. Tampered copies must fail: a changed signed field, a displayed field that differs from the signed one, a changed canonical string, the wrong rule, the wrong holder key, the wrong server key, and an edited log entry.
- **The CLI**, end to end: `stormcash-verify vectors spec/vectors.json --strict`.

To re-capture the proof fixtures after a change to `routes/cases.py`, run this with a throwaway Postgres. The harness creates and drops its own `stormcash_test` database:

```bash
cd server && TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres python -m pytest -p tests.conftest ../cpp/verify/tests/fixtures/capture_proofs.py -q
```

## Where it differs from the Python reference

All of these differences are stricter, and none of them changes a vector outcome:

- `bytes.fromhex` in Python accepts spaces between bytes; `from_hex` here doesn't.
- A DET (unsigned) given a `sig` is rejected; Python's `from_fields` ignores the argument.
- Transport JSON is compared as a JSON value, the same equality the Python and TypeScript vector tests use. The output also happens to keep the reference's key order.

## Limits

- **This toolkit only verifies.** It has no signing code of its own. p256-m's key generation and signing are compiled in with the portable backend, but they can't run: the random-number function they need always fails here (`p256m_sec1.c`). The test keys' private halves in `vectors.json` are never read.
- **It is independent at the protocol layer.** The encoding, codecs and rules are a separate implementation. With the default backend, SHA-256 and ECDSA come from OpenSSL 3, and Python's `cryptography` also links OpenSSL, so that build's elliptic-curve math is not independent of the server's. The portable backend (p256-m and the SHA-256 here) shares no crypto code with OpenSSL, with noble (the phones) or with a browser's WebCrypto. That is the build the proof page runs.
- **NFC depends on the Unicode version.** utf8proc 2.9.0 is Unicode 15.1; the CI's Python 3.11 is Unicode 14.0. NFC is stable for characters both versions know, so the two can only differ on a character assigned after Unicode 14 that has a decomposition. No vector has one.
