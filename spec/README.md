# spec/

Shared protocol test vectors (WS0, spec §20). `gen_vectors.py` generates `vectors.json` from fixed private keys; `server/tests/test_vectors.py` and `mobile/src/protocol/__tests__/vectors.test.ts` must both reproduce every canonical string and digest byte for byte.

**Nothing else merges until both vector test suites pass.** Once `vectors.json` exists the protocol (§7–§10) is frozen.

- **Reviewers:** B for the Python side, A for the TypeScript side

## Regenerate

```bash
server/.venv/bin/python spec/gen_vectors.py
```

Signing is deterministic (RFC 6979), so the output is identical on every run. `server/tests/test_vectors.py::test_vectors_file_is_current` fails if the committed file is stale. Any change to the file is a protocol change (§0 rule 1).

The keys in `keys` are **test keys only**. Never use them for the demo server or a phone.

## Layout

Bytes are lowercase hex everywhere except inside `json` blocks, which are the transport form (short keys, base64url without padding, §7.3). Scenario sections carry objects as `{type, fields, sig}`; `fields` uses the long field names from §7.4 / §9.2 in canonical order. Lists inside `fields` are deliberately unsorted in places: the canonical encoding must sort them.

| Section | Each entry checks |
|---|---|
| `constants` | `now`, clock tolerance, string and integer limits |
| `keys` | name → `{priv, pub}` for server, maya, pharmacy, gas_station, corner_store |
| `encoding` | one field rendering (§7.2): `rendered`, or `error: true` when the value must be rejected |
| `objects` | §20 shape: `canonical`, `digest`, `pub`, `sig`, `valid`, plus `json` (exact transport form) and `item_id` / `id8` for item kinds. `GEN` and `DGEN` entries have no signature |
| `pays` | PAY `{c, t, d}`: transport `json` and `item_id` (= tag_hash) |
| `signatures` | raw r‖s verification of `sig` over `digest` under `pub`; includes a high-S signature that must verify and malformed ones that must not |
| `der` | DER from Python `cryptography` → `raw` (exact) and `raw_low_s` |
| `contact_ids` | both sides compute the same `contact_id` (§9.2) |
| `single_tag` | single-tag validity (§8.3) |
| `equivocation` | `rules_fired` for the pair (either order) and the reported `rule` (R1–R3) |
| `proofs` | PROOF transport `json`, `item_id` (§10.2) and `valid` |
| `merchant_checks` | C1–C6 (§8.2) on a scanned PAY: `expect.{ok, check, reason, rule, conflict}` |
| `over_cap` | R4 after each settled tag, given the caps of all versions |
| `log_tamper` | R6 on one device's entries: `null` or `{kind: FORK \| BROKEN_LINK, seq}` |
| `merchant_knew` | R5 for tag `z` at `t_accept`: `expect.{fired, clause, conflict, contact_id}` |
