---
layout: post
title: An interactive TUI for reading PostgreSQL WAL (pg_walview)
description: >-
  pg_walview is a TUI for reading PostgreSQL WAL files interactively. It draws a graph
  line through the records that share a transaction ID, so a single transaction can be
  followed without filtering the surrounding records away.
lang: en
image: /assets/images/og/en/pg-walview-ed6e5f59.png
translated: true
tags:
  - PostgreSQL
  - WAL
  - Rust
---

A while ago I wrote [pg_walview](https://github.com/MasahikoSawada/pg_walview), a TUI for reading PostgreSQL WAL (Write-Ahead Log) files. It does not print everything at once the way `pg_waldump` does, and instead lets you move a cursor through the records one at a time in your terminal, which is the whole point of it. It is written in Rust.

<video src="/images/2026-08-18/pg_walview-demo.mp4" poster="/images/2026-08-18/pg_walview-demo-poster.jpg"
       width="1200" height="600" autoplay muted loop playsinline preload="none"
       style="max-width:100%;height:auto"
       aria-label="pg_walview opening a WAL file, moving through records and showing the record details and the hex dump">
</video>

`pg_waldump` can filter in most of the ways you would want. `-x` for a transaction ID, `-r` for a resource manager, `-R` and `-B` for a relation and a block. But once you filter, you lose sight of what was going on around the records you kept. I kept running it with `-x` to find the transaction I cared about, then running it again without `-x` because I wanted to see what else was going on around those records, and after doing that a few too many times I thought it would be nicer to load the whole segment up front and change the view in place instead.

## The Panes

The screen is split into three panes. `Tab` moves the focus between them.

### WAL records (left)

A list of the records. LSN, XID, record length, whether the record carries a full-page image, resource manager, a description.

The graph line down the left edge is the part I wanted most. The records sharing the transaction ID of the record under the cursor are connected by it.

```
    0/100 13840   171  Heap      UPDATE
 ┏━ 0/100 13841  8135  Heap      LOCK        <- first record of this XID
 ┃  0/100 13839  8135  Heap      LOCK
 ┣━ 0/100 13841   171  Heap      UPDATE      <- cursor
 ┃  0/100 13840  8135  Heap      LOCK
 ┃  0/100 13839   171  Heap      UPDATE
 ┣━ 0/100 13841    64  Btree     INSERT_LEAF
 ┗━ 0/100 13841    34  Transact  COMMIT      <- last record of this XID
```

The records of other transactions stay where they are, so you can follow one transaction and still see everything that happened in between. `s` and `r` jump to the next and previous record with the same XID[^xid].

[^xid]: The jump is disabled when the XID is 0, 1 or 2. Those are `InvalidTransactionId`, `BootstrapTransactionId` and `FrozenTransactionId`, and since a lot of records carry no XID at all, connecting them would not mean anything.

The colour of the line comes from the last record of that XID. That is, from how the transaction ended.

| State      | Condition                                                                               |
|------------|-----------------------------------------------------------------------------------------|
| Committed  | ends with `COMMIT` or `COMMIT_PREPARED`                                                 |
| Aborted    | ends with `ABORT` or `ABORT_PREPARED`                                                   |
| Pending    | ends with a Transaction record that is neither a commit nor an abort, such as `PREPARE` |
| Unfinished | does not end with a Transaction record at all                                           |

That last one turns out to be quietly useful. It means the transaction does not finish inside this WAL file, the rest of it is in the next segment, and so you know whether you need to open another file before you go looking for a commit that is not there.

Only the 16 ANSI colours are used, by the way. What they look like is up to your terminal theme. `NO_COLOR` turns them off.

### DETAILS (top right)

The details of the selected record. The `XLogRecord` header, the block references (`RelFileLocator`, fork, block number, flags), and the fields decoded per resource manager.

It is an accordion, and `Enter` expands or collapses a block. For a Heap `UPDATE` it expands `t_infomask` and `t_infomask2` of `xl_heap_header` into flag names, so checking whether something like `HEAP_XMAX_INVALID` is set no longer means leaving the tool and looking the bits up. Handy.

### HEX DUMP (bottom right)

The bytes of the whole WAL segment. Each line is addressed twice, by its LSN and by its offset in the file, which means you can read a record and see which of the 8kB pages it happens to be sitting on without doing the arithmetic yourself.

Only the bytes of the selected record get colour. And they are coloured by what they are: the `XLogRecord` header, the descriptors, a full-page image, block data, main data. A record crossing a page boundary is coloured as the two or more pieces it really occupies. The page header that splits it is not part of the record, so it stays uncoloured.

Whatever the DETAILS cursor sits on is picked out in the dump too, so the accordion doubles as a navigator over the bytes. Having the decoded fields and the raw bytes next to each other also helped while writing the `*desc.c` equivalents[^desc].

[^desc]: The per-resource-manager decoding does the same job as the `*desc.c` files under `src/backend/access/rmgrdesc/` in PostgreSQL itself. I kept the structure close to that, on the assumption that it should be easier to follow upstream changes later.

## Usage

If `pg_config` is in your `PATH`, the build needs nothing else. The definitions of `XLogRecord` and friends come from the server headers at build time, so those headers have to be there[^version].

[^version]: Which also means a binary only reads WAL from the version it was built against. Opening a segment from another version reports a page magic mismatch rather than misreading it. `--version` prints which PostgreSQL a given binary was built for.

```bash
git clone https://github.com/MasahikoSawada/pg_walview.git
cd pg_walview
cargo build --release

# If PostgreSQL is installed somewhere of your own
PG_INCLUDE_DIR=/path/to/pgsql/include/server cargo build --release
```

Then pass the path to a WAL file. It does not connect to a server, so the instance does not have to be running, and a file you copied off a machine somewhere is enough.

```bash
pg_walview /path/to/pg_wal/000000010000000000000001
```

The main keybindings:

| Key           | Action                                     |
|---------------|--------------------------------------------|
| `j` / `k`     | Next / previous record                     |
| `g` / `G`     | First / last record                        |
| `s` / `r`     | Next / previous record with the same XID   |
| `Space` / `-` | Page down / page up                        |
| `Tab`         | Switch pane                                |
| `q`           | Quit                                       |

## Limitations

- Only one segment file can be open at a time. A transaction spanning segments cannot be followed all the way. The "unfinished" state of the graph line is the other side of this limitation.
- Every record in the file is read into memory. Segments are 16MB by default, so this has not bothered me yet, but it may start to matter with a larger `--wal-segsize`. The segment size itself is read from the long page header, so a non-default one is read correctly.
- The per-resource-manager decoders are incomplete. Heap, Heap2, Btree, Transaction and XLOG are done. GiST, GIN, SP-GiST and others still just report the size of the main data.
- Compressed full-page images (FPI) are not decompressed. The compression method is shown, but not the contents.

## Wrapping Up

`pg_waldump` and [pg_walinspect](https://www.postgresql.org/docs/18/pgwalinspect.html) are both there for looking inside WAL, and they have more features. pg_walview does one thing. It lets you move around.

In my case I spend a fair amount of time on logical replication debugging. Where did this transaction commit? What came between these two records? For that kind of question it has been worth writing.

The source is on [GitHub](https://github.com/MasahikoSawada/pg_walview), under the MIT License. Contributions are welcome!
