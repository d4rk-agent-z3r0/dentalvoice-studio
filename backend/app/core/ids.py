# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Time-ordered UUIDs (RFC 9562 version 7).

Python 3.14 adds ``uuid.uuid7``; until the runtime floor reaches 3.14 this small implementation is
used. Time-ordered keys keep B-tree inserts local, unlike random version 4 UUIDs.
"""

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    unix_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")  # 80 random bits; 74 are used
    value = (unix_ms & 0xFFFF_FFFF_FFFF) << 80  # 48-bit timestamp
    value |= 0x7 << 76  # version
    value |= ((rand >> 62) & 0x0FFF) << 64  # 12 bits rand_a
    value |= 0b10 << 62  # RFC 9562 variant
    value |= rand & 0x3FFF_FFFF_FFFF_FFFF  # 62 bits rand_b
    return uuid.UUID(int=value)
