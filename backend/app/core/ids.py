# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Time-ordered UUIDs (RFC 9562 version 7), monotonic within the process.

Python 3.14 adds ``uuid.uuid7``; until the runtime floor reaches 3.14 this implementation is used.
Time-ordered keys keep B-tree inserts local. Within one millisecond the 12-bit ``rand_a`` field is
used as a counter (RFC 9562 §6.2, method 1), so ids generated one after another always sort in
generation order. Rows written in one transaction share ``created_at``; their ids keep their order.
"""

import os
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = 0
_counter = 0
_COUNTER_MAX = 0x0FFF


def uuid7() -> uuid.UUID:
    global _last_ms, _counter  # process-wide monotonic state
    with _lock:
        now_ms = time.time_ns() // 1_000_000
        if now_ms > _last_ms:
            _last_ms = now_ms
            _counter = int.from_bytes(os.urandom(2), "big") & 0x01FF  # leave room to count up
        else:
            _counter += 1
            if _counter > _COUNTER_MAX:  # >3,500 ids in one millisecond: borrow the next one
                _last_ms += 1
                _counter = 0
        unix_ms, counter = _last_ms, _counter
    rand_b = int.from_bytes(os.urandom(8), "big") & 0x3FFF_FFFF_FFFF_FFFF
    value = (unix_ms & 0xFFFF_FFFF_FFFF) << 80  # 48-bit timestamp
    value |= 0x7 << 76  # version
    value |= counter << 64  # 12-bit rand_a used as a monotonic counter
    value |= 0b10 << 62  # RFC 9562 variant
    value |= rand_b
    return uuid.UUID(int=value)
