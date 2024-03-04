---
layout: post
title: Implementing a new PostgreSQL Table AM for archiving tables
lang: en
tags:
  - PostgreSQL
  - Table AM
---

I recently published my hobby project [pgroad](https://github.com/MasahikoSawada/pgroad), a new PostgreSQL Table Access Method (Table AM). pgroad is an PostgreSQL extension that adds a new table format called `road` to PostgreSQL. ROAD stands for "Read Only Archived Data" and is used to convert exsiting tables that are access infrequently but cannot be dropped into compact, read-only tables.

**CAUTION: since `pgroad` is still in development and a hobby project, it's not production ready**

# How It Works

You can register `pgroad` in the database using `CREATE EXTENSION` command (you also need to add `pgroad` to `shared_preload_libraries` first):

```
=# CREATE EXTENSION pgroad;
CREATE EXTENSION
```

Create sample tables using pgbench:

```
$ pgbench -i -s 100
dropping old tables...
creating tables...
generating data (client-side)...
vacuuming...
creating primary keys...
done in 10.43 s (drop tables 0.00 s, create tables 0.01 s, client-side generate 7.41 s, vacuum 0.16 s, primary keys 2.86 s).
$ psql
=# \dt+ pgbench_accounts
                                         List of relations
 Schema |       Name       | Type  |  Owner   | Persistence | Access method |  Size   | Description
--------+------------------+-------+----------+-------------+---------------+---------+-------------
 public | pgbench_accounts | table | masahiko | permanent   | heap          | 1281 MB |
(1 row)
```

The `pgbench_accounts` table is a `heap` table, and we convert it into a `road` table:

```
=# ALTER TABLE pgbench_accounts SET ACCESS METHOD road;
ALTER TABLE
=# \dt+ pgbench_accounts
                                         List of relations
 Schema |       Name       | Type  |  Owner   | Persistence | Access method |  Size  | Description
--------+------------------+-------+----------+-------------+---------------+--------+-------------
 public | pgbench_accounts | table | masahiko | permanent   | road          | 118 MB |
(1 row)
```

You can see that the table has shrunk from 1281MB to 118MB. Once converted into a `road` table, you cannot modify the table:

```
=# DELETE FROM pgbench_accounts ;
ERROR:  road_tuple_delete is not supported
=# INSERT INTO pgbench_accounts (aid) VALUES (1);
ERROR:  cannot insert tuple directly into a ROAD table
HINT:  Use ALTER TABLE ... SET ACCESS METHOD or CREATE TABLE ... AS to insert tuples
```

# Architecture

The implementation is very simple. It scans the exsiting table, store tuples into 16kB chunks (in memory), compresses it, and writes them to the `road` table.

```
+-------------------+     +------------+  compression   +---------+
|                   | --> |   chunk    | -------------> |xxxxxxxxx| \
|                   |     |  (16kB)    |                +---------+   \
|                   |     +------------+                                \     +--------------------+
|  original table   |                                                    \    |                    |
| (heap, 8kB pages) |     +------------+  compression   +---------+       `-> |     new table      |
|                   | --> |   chunk    | -------------> |xxxxxxxxx| --------> |  (road, 8kB pages) |
|                   |     |  (16kB)    |                +---------+       .-> |                    |
|                   |     +------------+                                 /    |                    |
|                   |                                                   /     +--------------------+
|                   |     +------------+ compression    +---------+   /
|                   | --> |   chunk    | -------------> |xxxxxxxxx| /
|                   |     |  (16kB)    |                +---------+
|                   |     +------------+
+-------------------+
```

Currently `road` table internally utilizes heap tuples. However, heap tuple headers contain some data like xmin and xmax that `road` doesn't need, so I would like to add support for a custom (more compact) tuple format some day.

Chunk pages are compressed using `pglz` by default, but `lz4` can also be chosen if enabled in the PostgreSQL.

# Supported Features

I've implemented basic features for now:

- Table creation
- Index creation (excluding BRIN)
- Scanning
  - Seq Scan
  - Index Scan
- TOAST
- WAL (Generic WAL)

# Converting exsting tables to road tables

Since `pgroad` focuses specifically on archiving exsiting data, `road` tables can only be creaetd in the following two ways:

- `ALTER TABLE ... SET ACCESS METHOD road`
- `CREATE TABLE ... USING road AS ...`

Also, you cannot create a `road` table inside a transaction block.

## Utilizing ProcessUtility_hook

PostgreSQL provides hook points that extensions can tap into by registering their own function. `ProcessUtility_hook` is one such hook point that gets called when DDL statements are executed. `pgroad` uses `ProcessUtility_hook` to detect if the SQL statement was `CREATE TABLE AS` or `ALTER TABLE ... SET ACCESS METHOD road`:

```c
static void
road_ProcessUtility(PlannedStmt *pstmt, const char *queryString,
                    bool readOnlyTree,
                    ProcessUtilityContext context, ParamListInfo params,
                    QueryEnvironment *queryEnv,
                    DestReceiver *dest, QueryCompletion *qc)
{
    NodeTag     tag = nodeTag(pstmt->utilityStmt);

    if (tag == T_CreateTableAsStmt)
    {
        RoadInsertState.called_in_ctas = true;
        Assert(!RoadInsertState.called_in_atsam);
    }
    else if (tag == T_AlterTableStmt)
    {
        AlterTableStmt *atstmt = (AlterTableStmt *) pstmt->utilityStmt;
        ListCell   *cell;

        foreach(cell, atstmt->cmds)
        {
            AlterTableCmd *cmd = (AlterTableCmd *) lfirst(cell);

            if (cmd->subtype == AT_SetAccessMethod)
            {
                Relation    rel = relation_openrv(atstmt->relation, ShareLock);

                /*
                 * Are we about to change the access method of the relation to
                 * ROAD table AM?
                 */
                if (strcmp(cmd->name, "road") == 0)
                {
                    /* Remember the original table's OID */
                    RoadInsertState.atsam_relid = RelationGetRelid(rel);

                    RoadInsertState.called_in_atsam = true;
                }

                RelationClose(rel);

                break;
            }
        }
        Assert(!RoadInsertState.called_in_ctas);
    }

    prev_ProcessUtility(pstmt, queryString, false, context,
                        params, queryEnv, dest, qc);
}
```

We remember if either of the two DDL is executed, and raise an error in the insert callback if necessary:

```c
static void
road_tuple_insert(Relation relation, TupleTableSlot *slot,
                  CommandId cid, int options, BulkInsertState bistate)
{
    RoadInsertStateData *state;
    ItemPointerData tid;
    RowNumber   rownum;
    bool        shouldFree;
    HeapTuple   tuple = ExecFetchSlotHeapTuple(slot, true, &shouldFree);

    state = road_get_insert_state(relation);

    if (!(state->called_in_atsam || state->called_in_ctas))
        ereport(ERROR,
                (errmsg("cannot insert tuple directly into a ROAD table"),
                 errhint("Use %s or %s to insert tuples",
                         "ALTER TABLE ... SET ACCESS METHOD",
                         "CREATE TABLE ... AS")));
```

# Try Creating Your Own Table AMs

The Table AM is actually a collection of callbacks. Table AM developer implements callbacks that get invoked for functionality like scans, index creation etc. that the table AM wants to support. Table AMs are nicely abstracted from other PostgreSQL components, so you can implement yours fairly independently. PostgreSQL provides transaction mamager, buffer manager etc. so AMs can choose whether or not to leverage those facilitities. For example, using the buffer manager provided by PostgreSQL core allows Table AM developers to implement their access method without having to consider the lower levels than the shared buffer.

That said, there is a lot more to consider when implementing a table AM:

- How to store data?
  - Row, columnar, and page format.
- Concurrency control and lock granularity.
- Crash recovery and replication.
- Handling ROLLBACK and failed transactions (including handling garbage data).
- Handling data bigger than page size.

While designing a idea, robust Table AM is great, for hobby projects I recommend constraining the use cases as much as possible. More constraints means less cases to handle an dsimpler implementation. Start with a "minimally viable" table AM - something that works for a narrow use case, even if it's not fully practical. Getting something working will be motivating you! The learning is in the process more than the end product.

`pgroad` has the following limitations that made its implementation very straightforward:

- Table creation only by converting exsting tables.
  - `road` tables can only be made with an exclusive lock on the source table.
    - No concurrency
- Cannot create `road` tables in transaction blocks
  - Entire table i slost on failed creation.
  - No need to handle SAVEPOINTs.
  - No need to handle CURSOR and to consider CommandId.
- Read only (no INSERT/UPDATE/DELETE)
  - Fewer callbaccks to implement.
  - No garbage in tables.

While `pgorad` focuses on archival, some other fun Table AM ideas:

- Automatic row IDs.
- Heap table with [PAX page format]((https://www.pdl.cmu.edu/PDL-FTP/Database/pax.pdf).
- Write ahead log only tables.

I encourage you to try developmeing your own PostgreSQL Table AM extension!
