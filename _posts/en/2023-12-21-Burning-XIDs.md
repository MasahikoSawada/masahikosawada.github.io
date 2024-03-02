---
layout: post
title: Burning PostgreSQL transaction IDs.
tags:
  - PostgreSQL
  - Vacuum
lang: en
---

 PostgreSQL's transaction ID (hereafter XID) is internally represendted as a "monotoronicaly increasing 32-bit unsigned integer value", so after reaching 2^32-1 (approximately 4 billion) it wraps around back to 0. In PostgreSQL, each transaction that modifies the database such as INSERT, UPDATE and even DDLs is assigned a unique XID. Since the order of XIDs is used to check the visibility of tuples in tables, if XID wraps around after reaching the upper limit, this logic would break.

 To prevent this problem, PostgreSQL has a safety mechanis called "aggressive vacuum", runs automatically before the wraparound happens (specifically, before consumign approx. 2^31 XIDs). This clears old XIDs so new ones can continue to be consumed. In recent years, I've been working on improvements around this safety mechanism, so I often needed to test the mechanism itself, which requires consuming a massive number of XIDs and takes time.

For example, a poor-man's approach to complete 2 billion wirte transactions. Moreover, when issuing new XIDs, status data accociated eich each XID, like CLOG and Commit Timestamp, also need to expand. When testing those behaviors, actually consuming XIDs is important.

So in this post, I'll introduce various methods to consume XIDs quickly.

# 1. Consuming XIDs using PL/pgsSQL

Comsuming 1 billion XIDs using this use-defined function that internally generates 1 billion subtransactions.

```sql
CREATE PROCEDURE consume_xids(cnt int)
AS $$
DECLARE i int;
BEGIN
	FOR i in 1..cnt LOOP
		EXECUTE 'SELECT txid_current()';
		COMMIT;
	END LOOP;
END;
$$
LANGUAGE plpgsql;
=# select pg_current_xact_id();

=# call consume_xid(100_000_000);
Time: 797958.576 ms (13:17.959)

=# select pg_current_xact_id();
```

Took 13 minutes, quite slow. XID generation takes exclusive locks so parallelization doesn't help much.

# 2. Using pg_resetwal

The pg_resetwal resets PostgreSQL's internal data. We can force the next XID like this. Since it just overwrite the internal data so pg_resetwal should complete instanly.

```bash
$ psql -c "SELECT pg_current_xact_id()"
$ pg_ctl stop
$ pg_resetwal -x 2000027648
$ pg_ctl start
$ psql -c "SELECT pg_current_xact_id()"
```

Why is the next XID an odd number, 2000027648? This is because we need to make sure the next XID lang on a CLOG page (8kB) boundary. Otherwise on startup, we'd get erros that transaction status (e.g. committed, aborted etc) is inaccessible. This happens because on startup, if the current XID isN't a ta CLOG page boundary, statuses for unused XIDs in that page are initialied to 0 (see `TrimCLOG() for details). This applies to all pg_resetwal use case, although it's normally not an issue as XID skips are small.

This quickly and easily skips XIDs but not a "real" use case. We need to stop and start server, choose the next XID carefully, and it depends on page size.

# 3. C function

```c
PG_FUNCTION_INFO_V1(set_next_xid);
Datum
set_next_xid(PG_FUNCTION_ARGS)
{
    TransactionId next_xid = PG_GETARG_TRANSACTIONID(0);
    TransactionId xid;
    uint32 epoch;

    if (!TransactionIdIsNormal(next_xid))
        elog(ERROR, "cannot set invalid transaction id");

    LWLockAcquire(XidGenLock, LW_EXCLUSIVE);

    if (TransactionIdPrecedes(next_xid,
                              XidFromFullTransactionId(TransamVariables->nextXid)))
    {
        LWLockRelease(XidGenLock);
        elog(ERROR, "cannot set transaction id older than the current transaction id");
    }

    /*
     * If the new XID is past xidVacLimit, start trying to force autovacuum
     * cycles.
     */
    if (TransactionIdFollowsOrEquals(next_xid, TransamVariables->xidVacLimit))
    {
        /* For safety, we release XidGenLock while sending signal */
        LWLockRelease(XidGenLock);
        SendPostmasterSignal(PMSIGNAL_START_AUTOVAC_LAUNCHER);
        LWLockAcquire(XidGenLock, LW_EXCLUSIVE);
    }

    ExtendCLOG(next_xid);
    ExtendCommitTs(next_xid);
    ExtendSUBTRANS(next_xid);

    /* Construct the new XID */
    epoch = EpochFromFullTransactionId(TransamVariables->nextXid);
    xid = XidFromFullTransactionId(TransamVariables->nextXid);
    if (unlikely(xid > next_xid))
        ++epoch;
    TransamVariables->nextXid =
        FullTransactionIdFromEpochAndXid(epoch, next_xid);

    LWLockRelease(XidGenLock);

    PG_RETURN_VOID();
}
```

It can avoid serer restart unlike previous method. Expands CLOG and CommitTS etc near new XID. It can trigger autovacuum launcher for aggressive vacuum if new XID is old enough. Also, it should complete instantly.

```sql
=# select txid_current();
 txid_current
--------------
          737
(1 row)

Time: 0.850 ms
=# select set_next_xid('999981056'::xid);
 set_next_xid
--------------

(1 row)

Time: 0.483 ms
=# select txid_current();
 txid_current
--------------
    999981056
(1 row)

Time: 0.926 ms
```

However, `ExtendCLOG()` only create pages if th eapssed XID lands on a page boundary, so the next XID must be calculated carefully same as before. This jumps XIDs more than incrementing them. Expands CLOG near new XID but does nothing for preceding XIDs.

# 4. "Fast Forward" XID internally

Finally, the approach used by the `xid_wraparound` testing extension I recently pushed to the PostgreSQL source code.

Tough written for regression tests, the SQL functions in the exntesion can work if you installed it to your system.

```sql
=# CREATE EXTENSION xid_wraparound;
CREATE EXTENSION

=# \dx xid_wraparound
                 List of installed extensions
      Name      | Version | Schema |       Description
----------------+---------+--------+--------------------------
 xid_wraparound | 1.0     | public | Tests for XID wraparound
(1 row)
=# \dx+ xid_wraparound
Objects in extension "xid_wraparound"
        Object description
-----------------------------------
 function consume_xids(bigint)
 function consume_xids_until(xid8)
(2 rows)
```

The key point of this method that differs from previous method is to move XIDs forward by "skiping while consuming" XIDs; it consume XIDs normally near "intereting XIDs" (those needing CLOG expansion etc) and skip XIDs internally elsewhere.

```sql
=# select txid_current();
 txid_current
--------------
          737
(1 row)

=# select consume_xids('1000000000');
NOTICE:  consumed 10000071 / 1000000000 XIDs, latest 0:10000809
NOTICE:  consumed 20000880 / 1000000000 XIDs, latest 0:20001618
NOTICE:  consumed 30001689 / 1000000000 XIDs, latest 0:30002427
NOTICE:  consumed 40002498 / 1000000000 XIDs, latest 0:40003236
NOTICE:  consumed 50003230 / 1000000000 XIDs, latest 0:50003968
NOTICE:  consumed 60003297 / 1000000000 XIDs, latest 0:60004035
NOTICE:  consumed 70003998 / 1000000000 XIDs, latest 0:70004736
NOTICE:  consumed 80004096 / 1000000000 XIDs, latest 0:80004834
NOTICE:  consumed 90004766 / 1000000000 XIDs, latest 0:90005504
NOTICE:  consumed 100004895 / 1000000000 XIDs, latest 0:100005633
NOTICE:  consumed 110005534 / 1000000000 XIDs, latest 0:110006272
NOTICE:  consumed 120005694 / 1000000000 XIDs, latest 0:120006432
NOTICE:  consumed 130006302 / 1000000000 XIDs, latest 0:130007040
NOTICE:  consumed 140006493 / 1000000000 XIDs, latest 0:140007231
NOTICE:  consumed 150007070 / 1000000000 XIDs, latest 0:150007808
NOTICE:  consumed 160007292 / 1000000000 XIDs, latest 0:160008030
NOTICE:  consumed 170007838 / 1000000000 XIDs, latest 0:170008576
NOTICE:  consumed 180008091 / 1000000000 XIDs, latest 0:180008829
NOTICE:  consumed 190008606 / 1000000000 XIDs, latest 0:190009344
NOTICE:  consumed 200008890 / 1000000000 XIDs, latest 0:200009628
:
:
NOTICE:  consumed 960038174 / 1000000000 XIDs, latest 0:960038912
NOTICE:  consumed 970038423 / 1000000000 XIDs, latest 0:970039161
NOTICE:  consumed 980038942 / 1000000000 XIDs, latest 0:980039680
NOTICE:  consumed 990039222 / 1000000000 XIDs, latest 0:990039960
 consume_xids
--------------
   1000000738
(1 row)

Time: 2893.244 ms (00:02.893)
=# select txid_current();
 txid_current
--------------
   1000000739
(1 row)
```

Good, reasonably fast. It can simulate more "real" XID consumption by doing normal consuming and related processing.

Note that it doesn't trigger autovacuum launcher for aggressive vacuum so timing depends on the new XID and `autovacuum_naptime`. This may change in the future.

Thank you for reading.
