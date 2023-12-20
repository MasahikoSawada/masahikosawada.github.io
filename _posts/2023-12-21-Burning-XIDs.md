---
layout: post
title: PostgreSQLでトランザクションIDをできるだけ早く消費する方法
tags:
  - PostgreSQL
  - Vacuum
---

本記事は[PostgreSQL Advent Calendar 2023](https://qiita.com/advent-calendar/2023/postgresql) 21日目の記事です。

PostgreSQLのトランザクションID（以下XID）は内部的には「単調増加する32bitの非負整数値」なので、2^32-1に達した後は0に戻ります。PostgreSQLでは、データベースに変更を加えるトランザクションに対して1つXIDが割り当てられます。XIDの大小関係を利用してテーブル内の行の可視性判断[^visibility]をしているので、XIDが上限に達して周回してしまうとそのロジックが壊れてしまいます。

そこでPostgreSQLでは周回が起こる前（具体的にはXIDを2^31(≒約20億)個消費する前）に、aggressive vacuumと呼ばれる安全装置のようなものが自動的に走り、XIDを更に消費できるようにします（詳細は[公式ドキュメント](https://www.postgresql.jp/document/14/html/routine-vacuuming.html#VACUUM-FOR-WRAPAROUND)をご参照ください）。ここ数年この安全装置周りの改善に取り組んでいたので、安全装置自体をテストや、安全装置の動作完了が間に合わなかった場合のテストなどすることが多くありました。ただ、XIDと安全装置の性質上、XIDを大量に消費しないと適切なテストができず、これには時間がかかります。例えばナイーブにやろうとすると、約20億のトランザクションを実行する必要があり、時間がかかります。また、新しいXIDを発行する際には各XIDにステータスを持つようなデータ、例えばCLOGやCommit Timestampなどの領域も合わせて拡張されます。それらの動作をテストするときにも、実際にXIDを消費することが重要になる時があります。

そこで、早くXID消費するための色々な方法を紹介します。

# 1. ストアドプロシージャを使ってトランザクションを消費する

次のようなユーザ定義関数を使って10億XIDを消費します。内部的にはサブトランザクションを10億個生成することで、XIDを消費しています。

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
```

```sql
=# select pg_current_xact_id();

=# call consume_xid(100_000_000);
Time: 797958.576 ms (13:17.959)

=# select pg_current_xact_id();
```

13分と結構時間がかかりました。XIDの生成は排他ロックを取るので並列化しても大きな改善は見込めません。

# 2. pg_resetwalを使う

`pg_resetwal`というPostgreSQL内部情報を初期化するツールを使い、次のXIDを強制的に設定します。内部情報を書き換えているだけなので、`pg_resetwal`は一瞬で完了するはずです。

```
$ psql -c "SELECT pg_current_xact_id()"
$ pg_ctl stop
$ pg_resetwal -x 2000027648
$ pg_ctl start
$ psql -c "SELECT pg_current_xact_id()"
```

XIDを`2000027648`に進めるのは、次のXIDをCLOGのページ（8kB）境界にするためです。そうしないと、起動するときにトランザクションのステータス（CommitとかAbortとか）にアクセスできない旨のエラーがでてしまいます。これは、サーバ起動時に現在のXIDのステータスがCLOGページの境界にない場合、そのページ内のまだ使っていないXIDのStatusを0に初期化するがあるためです（詳細は`TrimCLOG()`参照）。さらに、XIDをかなり大きくスキップしているのでそれに対応するCLOGページはまだできておらず、ファイルアクセスエラーになります。

これは、pg_resetwalを使うすべてのケースに当てはまるので注意が必要です（ただし通常のユースケースでは、こんなに大きくXIDをスキップさせないので問題にならない）。

CLOGのページ境界に次のXIDを持っていくために、8kBのCLOGページに32768個のXIDについての情報を格納できるので、`32768 * (2000000000/32768 + 1) = 2000027648`と計算しています。

`pg_resetwal`でXIDを大幅にスキップした後にあとは`txid_current()`等の関数でXIDを消費します。

簡単に、かつ高速にXIDを進めることができるますが、"リアル"なユースケースではないというのが欠点です。XIDを消費していく中で実行されていく処理（例えばCLOGの拡張など）はスキップしてます。再起動も必要だし、新しいXIDは狙い撃ちする必要があります。ページサイズにも依存します。

# 3. 内部的にXIDをスキップする

今度は自分で作った関数で内部的にXIDを設定してみます。

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

C言語でユーザ定義関数を書く必要があるますが、1つ前の方法とは異なり、サーバの再起動は不要になりました。さらに、新しいXID付近のCLOGやCommitTsも拡張するし、新しく設定するXIDが十分に古い場合は、aggressive vacuumをしてもらうためにautovacuum launcherを起こすようにもなっています。この関数も一瞬で完了するはずです。

```
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

しかし、`ExtendCLOG()`等の関数は、受け取ったXIDがページ内の最初のXIDである場合のみ、対応するページを作成するため、依然XIDは狙い撃ちする必要があります。CLOGの場合、1ページ内にXIDが32768個(= 8192 * 4)入るため、XID 999981056はちょうど30517番目のページの先頭のXIDとなります。また、この関数はXIDを進めているというよりもジャンプしている、という感じです。新しく設定したXID周辺のCLOGは拡張されますが、それまでのXIDについては何もしていません。

# 4. 内部的にXIDを高速に"進める"

最後に紹介するのは、最近masterブランチ（開発用ブランチ）に[コミット](https://git.postgresql.org/gitweb/?p=postgresql.git;a=commit;h=e255b646a16b45823c338dadf787813fc9e191dc)した`xid_wraparound`というテスト用の拡張で採用している方法です。

`xid_wraparound`は、リグレッションテスト用に作られましたが、そこで定義されているSQL関数は、`xid_wraparound`の拡張をインストールすればどの環境でも使えます。

```
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

`これまでの方法と異なるのは、XIDを"スキップしながら進めている"という所です。CLOGやCommitTsを拡張する必要があるXID（コード内では"interesting xids"と呼ばれている）周辺では通常通りのやり方でXIDを消費しますが、それ以外のところは1つ前に紹介した方法のように、内部的にXIDを設定してスキップしています。

```
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

実行速度もそれなりに早いです。そこそこはやくXIDを消費しつつ、XID消費に伴う処理も従来通りの方法で行われるので、より"リアル"なXID消費をシミュレーションできます。

autovacuum launcherを起こす処理は入れていないので、autovacuum launcherがaggressive vacuumのために起きるタイミングは、設定したXIDや`autovacuum_naptime`に依存します。このあたりは将来変わる可能性があります。

ぜひこの方法を使ってXIDを大量消費し、XID周回を起こしてみてください！
