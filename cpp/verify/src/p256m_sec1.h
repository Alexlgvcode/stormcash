/* SEC1 compressed P-256 keys for p256-m (the portable crypto backend). */
#ifndef STORMCASH_P256M_SEC1_H
#define STORMCASH_P256M_SEC1_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * compressed: 0x02 or 0x03, then x as 32 big-endian bytes (spec §7.1).
 * pub: x || y, the uncompressed form p256_ecdsa_verify() takes.
 * Returns 0, or -1 if the prefix is wrong, x >= p, or x has no point on the
 * curve. A returned point has also passed p256-m's own on-curve check.
 */
int stormcash_p256_decompress(uint8_t pub[64], const uint8_t compressed[33]);

#ifdef __cplusplus
}
#endif

#endif
