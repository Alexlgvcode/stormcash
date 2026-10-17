# cpp/: the C++ toolkit

`stormcash-verify` is a third, independent implementation of the checking side of the StormCash protocol (spec §7–§10), next to the Python server (`server/stormcash/protocol/`) and the TypeScript phones (`mobile/src/protocol/`). It was written from the spec in C++20, and it agrees with the other two on every one of the 124 shared test vectors. It can also check a case proof offline, the way the public proof page does in a browser.

It is off the demo path: nothing in the server, phones or dashboard depends on it.

## Build and run

Needs CMake ≥ 3.25, a C++20 compiler and OpenSSL 3. On macOS, `brew install cmake openssl@3` (CMake finds Homebrew's OpenSSL by itself); on Ubuntu, `apt install cmake g++ libssl-dev`. The other dependencies are fetched at configure time, pinned to a release and its SHA-256: nlohmann/json 3.12.0, utf8proc 2.9.0 and GoogleTest 1.17.0.

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

CI (the `cpp` job) builds in Debug with AddressSanitizer, UndefinedBehaviorSanitizer and `-Werror`, then runs the unit tests and the vectors. The options are `-DSTORMCASH_SANITIZE=ON` and `-DSTORMCASH_WERROR=ON`.

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

## Design

```
bytes.hpp         hex, strict base64url                         (§7.2, §7.3)
encoding.hpp      field renderers, canonical(), digest()        (§7.2)
crypto.hpp        SHA-256, ECDSA P-256 verify, DER, low-S       (§7.1)   OpenSSL 3
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
- **ECDSA.** The digest is verified as the prehashed message with `EVP_PKEY_verify`, with no digest set on the context, so OpenSSL doesn't hash it again. r and s are range-checked against the group order explicitly. High-S is accepted. Low-S normalization (n − s) is plain 32-byte big-endian arithmetic, so those rules are visible in the code. Keys are SEC1 compressed, decompressed by OpenSSL and then checked with `EVP_PKEY_public_check`. A malformed input is "not valid", never an exception.
- **DER** is parsed with OpenSSL and then re-encoded, and the result must equal the input byte for byte. That rejects BER forms such as long-form lengths, and trailing bytes.
- **Rules follow the spec's precedence.** For a pair, R1, then R2, then R3, and the lowest-numbered rule is reported. C6 takes stored tags in (counter, tag_hash) order and reports the first conflict, then COUNTER_NOT_NEW. R5 checks clause (a) before (b), dates a contact by the merchant's own entry, and needs it to be paired. R6 checks links only where the previous entry is known, and reports a fork before a broken link.

## Tests

`ctest` runs 89 tests:

- **Unit tests** for each layer (`verify/tests/test_*.cpp`). They cover RFC 4648 base64 vectors, NIST SHA-256 vectors, every encoding edge (NFC, astral characters, embedded NUL, invalid UTF-8, sort order), a key that isn't on the curve (x = 1), BER and trailing-byte DER, codec strictness, and each equivocation condition on hand-built tags.
- **All of `spec/vectors.json`**, with 124 vectors and nothing skipped.
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

- **This toolkit only verifies.** It has no signing code. The test keys' private halves in `vectors.json` are never read.
- **It is independent at the protocol layer.** The encoding, codecs and rules are a separate implementation. SHA-256 and ECDSA come from OpenSSL 3, and Python's `cryptography` also links OpenSSL, so the elliptic-curve math is not independent of the server's. The TypeScript phones use a separate library (noble).
- **NFC depends on the Unicode version.** utf8proc 2.9.0 is Unicode 15.1; the CI's Python 3.11 is Unicode 14.0. NFC is stable for characters both versions know, so the two can only differ on a character assigned after Unicode 14 that has a decomposition. No vector has one.
