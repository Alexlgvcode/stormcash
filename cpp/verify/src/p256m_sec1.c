/*
 * SEC1 compressed P-256 keys for p256-m (the portable crypto backend, see
 * crypto_portable.cpp).
 *
 * p256-m takes public keys as uncompressed x || y; StormCash keys are
 * compressed (spec §7.1). p256-m's field arithmetic is internal to p256-m.c,
 * so this file includes p256-m.c and adds one function on top of it. p256-m.c
 * itself is unmodified and is compiled only through this file.
 */
#include "p256-m.c"

#include <string.h>

#include "p256m_sec1.h"

/*
 * p256-m's key generation and signing draw randomness from this function,
 * which the user must provide. This toolkit only verifies, so it never gives
 * any, and those functions fail.
 */
int p256_generate_random(uint8_t *output, unsigned output_size)
{
    (void) output;
    (void) output_size;
    return P256_RANDOM_FAILED;
}

/* (p + 1) / 4, little-endian 32-bit limbs. */
static const uint32_t sqrt_exponent[8] = {
    0x00000000, 0x00000000, 0x40000000, 0x00000000,
    0x00000000, 0x40000000, 0xc0000000, 0x3fffffff,
};

int stormcash_p256_decompress(uint8_t pub[64], const uint8_t compressed[33])
{
    uint32_t x[8], rhs[8], y[8], t[8];

    if (compressed[0] != 0x02 && compressed[0] != 0x03)
        return -1;
    if (m256_from_bytes(x, compressed + 1, &p256_p) != 0) /* x >= p */
        return -1;

    /* rhs = x^3 - 3x + b, as in point_check() */
    m256_mul_p(rhs, x, x);
    m256_mul_p(rhs, rhs, x);
    for (unsigned i = 0; i < 3; i++)
        m256_sub_p(rhs, rhs, x);
    m256_add_p(rhs, rhs, p256_b);

    /* y = rhs^((p + 1) / 4), a square root of rhs if it has one (p = 3 mod 4).
     * Left-to-right square-and-multiply; the exponent is public. */
    m256_set32(y, 1, &p256_p);
    for (int i = 255; i >= 0; i--) {
        m256_mul_p(y, y, y);
        if ((sqrt_exponent[i / 32] >> (i % 32)) & 1)
            m256_mul_p(y, y, rhs);
    }

    /* Only a square has a root: no point has this x unless y^2 = rhs. */
    m256_mul_p(t, y, y);
    if (u256_diff(t, rhs) != 0)
        return -1;

    /* Of y and p - y, take the one whose parity the prefix names. P-256 has
     * no point with y = 0, so the two always differ in parity. */
    m256_done(y, &p256_p);
    if ((y[0] & 1) != (uint32_t) (compressed[0] & 1)) {
        if (u256_diff0(y) == 0)
            return -1;
        u256_sub(y, p256_p.m, y);
    }

    memcpy(pub, compressed + 1, 32);
    u256_to_bytes(pub + 32, y);

    /* The point p256-m will verify with must pass p256-m's own check. */
    return point_from_bytes(x, t, pub) == 0 ? 0 : -1;
}
