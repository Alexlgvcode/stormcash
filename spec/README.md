# spec/

Shared protocol test vectors (WS0, spec §20). `gen_vectors.py` generates `vectors.json` from fixed private keys; `server/tests/test_vectors.py` and `mobile/src/protocol/__tests__/vectors.test.ts` must both reproduce every canonical string and digest byte for byte.

**Nothing else merges until both vector test suites pass.** Once `vectors.json` exists the protocol (§7–§10) is frozen.

- **Reviewers:** B for the Python side, A for the TypeScript side
