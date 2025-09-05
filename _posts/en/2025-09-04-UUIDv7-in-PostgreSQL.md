---
layout: post
title: PostgreSQL 18 supports UUIDv7
lang: en
tags:
  - PostgreSQL
  - UUID
---

UUIDv7 was defined in [RFC 9562](https://www.rfc-editor.org/rfc/rfc9562.html). There are eight versions of UUID, and while they all have a size of 128 bits, the data stored in each version is different. Until I learned about UUIDv7, when I thought of UUIDs, I imagined random data - but that's version 4 UUID. The version 7 UUID (UUIDv7) has a significant feature: sortability thanks to a timestamp stored at the beginning of the data.

When you compare them, the difference is obvious:

```sql
=# select uuidv4(), uuidv7() from generate_series(1, 5);
                uuidv4                |                uuidv7
--------------------------------------+--------------------------------------
 216aae4c-6b02-4bea-bd84-7fea9617e0cc | 01991632-e3a0-7468-ac42-26afbc51df65
 55372a64-0351-40a1-a32c-318e581f4561 | 01991632-e3a0-748a-bb4c-9882ddaf0721
 e154c7a7-4a6b-4446-96be-6a1cb84b773e | 01991632-e3a0-749f-b429-d2ef56b9683e
 59adba82-8a88-4f4f-b859-036430d09045 | 01991632-e3a0-74b5-9a86-8107f1851200
 be096cb4-ee48-4bf8-ae30-3ca6d09af786 | 01991632-e3a0-74c9-a08a-1ec588e5a60d
(5 rows)
```

UUIDv7 offers many advantages when used as a primary key in databases. PostgreSQL uses Btree indexes for primary keys. Therefore, even when loading large amounts of data, the UUID values being inserted are always in ascending order, which provides high locality for index updates and leads to better performance. Additionally, in PostgreSQL, it helps reduce Full Page Writes (FPW).

Here are the results of inserting 5 million rows using SERIAL type (sequence) and UUID type (UUIDv4 and UUIDv7) as primary keys (verified on PostgreSQL 18 Beta):

|          | SERIAL  | UUIDv4  | UUIDv7   |
|----------|---------|---------|----------|
| Druation | 8.452 s | 42.24 s | 16.922 s |

# How to use UUID in PostgreSQL

PostgreSQL has a native [uuid data type](https://www.postgresql.jp/document/17/html/datatype-uuid.html), and (as of PostgreSQL 17) there are two main ways to generate UUIDs:

The first method is to use the built-in [gen_random_uuid() SQL function](https://www.postgresql.jp/document/17/html/functions-uuid.html). This generates a version 4 UUID (more details about UUID versions will be discussed later). It's PostgreSQL's own implementation.

The second method is to use the [uuid-ossp contrib module](https://www.postgresql.jp/document/17/html/uuid-ossp.html). This performs UUID generation using an external library, which varies depending on the platform. On Linux and macOS, it uses libuuid. This method can generate versions 1 through 5.

As mentioned above, PostgreSQL 17 currently doesn't support UUIDv7 generation, so if you want to use UUIDv7, you need to either use a published extension or implement it yourself. A search on GitHub reveals the following extensions:

- [pg_uuidv7](https://github.com/fboulnois/pg_uuidv7)
  - Implemented in C
- [postgres-uuidv7-sql](https://github.com/dverite/postgres-uuidv7-sql)
  - Implemented in SQL, so it can be used with just CREATE FUNCTION without needing to register it as an extension~

There's also a blog post about creating a UUIDv7 generation function using pg_tle + PL/Rust:

[https://aws.amazon.com/blogs/database/implement-uuidv7-in-amazon-rds-for-postgresql-using-trusted-language-extensions/](https://aws.amazon.com/blogs/database/implement-uuidv7-in-amazon-rds-for-postgresql-using-trusted-language-extensions/)

Since PL/Rust has limitations on crates can be used, the Rust uuid crate is not available. If you want to create a UUIDv7 generation function using a custom extension, using pgrx[^pgrx] is probably the easiest way. For just generating UUIDv7, you only need the following code:

[^pgrx]: A framework for creating PostgreSQL extensions in Rust

```rust
use pgrx::prelude::*;
use uuid::Uuid;

::pgrx::pg_module_magic!(name, version);

#[pg_extern]
fn pgrx_uuidv7() -> pgrx::Uuid {
    let uuid = Uuid::now_v7();

    pgrx::Uuid::from_bytes(uuid.into_bytes())
}
```

Great news is that upcomoing PostgreSQL 18 will introduce the [uuidv7() SQL function](https://www.postgresql.org/docs/devel/functions-uuid.html), making UUIDv7 available to all PostgreSQL users ([commit log](https://github.com/postgres/postgres/commit/78c5e141e9c139fc2ff36a220334e4aa25e1b0eb))!

For backward compatibility, `gen_random_uuid()` will continue to exist as a function that generates UUIDv4. Along with `uuidv7()`, `uuidv4()` has also been added, but it's just an alias for `gen_random_uuid()`.

# Data Format of UUIDv7

As per RFC, the data format of UUIDv7 is:

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                           unix_ts_ms                          |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|          unix_ts_ms           |  ver  |       rand_a          |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|var|                        rand_b                             |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                            rand_b                             |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

Every UUID data contains the number representing the version of UUID:

```
           Version
              |
              v
01937a3a-3d34-74d0-a1b7-e1f1b53064d8
```

In UUIDv7, the rough format is: millisecond-precision timestamp followed by the version number, and then random data (plus variant, to be precise) after the version.

```
  timestamp      random data(+var)
|-----------|  |-------------------|
01937a3a-3d34-74d0-a1b7-e1f1b53064d8

```

# Monotonicity in UUIDv7

For use cases where millisecond precision isn't sufficient, the RFC allows implementations to use the `rand_a` (12 bits) portion (and optionally `rand_b`) as additional data to maintain monotonicity of generated values. The RFC [introduces several methods](https://www.rfc-editor.org/rfc/rfc9562.html#name-monotonicity-and-counters) for how this can be done.

Different UUIDv7 generation function implementations use different approaches, but how `rand_a` and `rand_b` are used is crucial for maintaining data monotonicity in environments with high-frequency UUID generation. For example, in the simplest format of "millisecond timestamp + all random data," if more than 1000 UUIDs are generated per second, all leading timestamps will have the same value, so monotonicity of the generated UUIDv7 data isn't guaranteed. This means that in systems that might generate more than 1000 UUIDs per second, using such a UUIDv7 generation function won't fully leverage UUIDv7's advantages. It's important to choose the right UUIDv7 generation function based on your use case[^pg_uuidv7_analysis].

[^pg_uuidv7_analysis]: For example, looking at [pg_uuidv7's implementation](https://github.com/fboulnois/pg_uuidv7/blob/main/pg_uuidv7.c#L35), you can see it uses "millisecond timestamp + random data"

# PostgreSQL's UUIDv7 Implementation

PostgreSQL's UUIDv7 implementation adopts [Method 3 (Replace Leftmost Random Bits with Increased Clock Precision)](https://www.rfc-editor.org/rfc/rfc9562.html#name-monotonicity-and-counters) from the RFC. Specifically, it uses the `rand_a` portion for sub-millisecond timestamps, using 60 bits (=48+12) total for the timestamp. This allows it to handle about 4 million UUID generations per second. Furthermore, within the same process, it's guaranteed that the `rand_a` portion is increased by a certain step for each UUID generation, so UUIDv7 data generated from a single process is guaranteed to be monotonically increasing even at higher frequencies.

Additionally, it's possible to specify an interval value as an argument, allowing you to offset the timestamp stored in the UUID data by a specified period.

The source code can be found [here](https://github.com/postgres/postgres/blob/master/src/backend/utils/adt/uuid.c#L601).
