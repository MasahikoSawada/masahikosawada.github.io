---
layout: post
title: PostgreSQLで「圧縮＋読み取り専用テーブル」をテーブルAMを使って自作してみた
lang: jp
tags:
  - PostgreSQL
  - Table AM
---

先日、趣味でPostgreSQL用の自作テーブルAM、[pgroad](https://github.com/MasahikoSawada/pgroad)を公開しました。pgroadは、PostgreSQLに新しいテーブル形式であるroadを追加する拡張機能です。roadはRead Only Archived Dataの略で、使用頻度が低くなったけど削除するほどではない既存のテーブルを、コンパクトにそして読み取り専用に変換する形で使います。

**趣味実装かつ、作成途中なのでプロダクション環境では利用しないでください！**

# 動作サンプル

`CREATE EXTENSION`で`pgroad`をデータベースに登録します(あらかじめ`shared_preload_libraies`へ`pgroad`の追加する必要があります)。

```
=# CREATE EXTENSION pgroad;
CREATE EXTENSION
```

サンプルデータとしてpgbenchでテーブルを作成します。

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

`pgbench_accounts`テーブルは現在`heap`テーブルですが、これを`road`テーブルに変換します。

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

テーブルサイズが1281MB → 118MBに小さくなったことがわかります。一度`road`テーブルへ変換すると、新しいデータを変更、追加、削除することはできません。

```
=# DELETE FROM pgbench_accounts ;
ERROR:  road_tuple_delete is not supported
=# INSERT INTO pgbench_accounts (aid) VALUES (1);
ERROR:  cannot insert tuple directly into a ROAD table
HINT:  Use ALTER TABLE ... SET ACCESS METHOD or CREATE TABLE ... AS to insert tuples
```

# アーキテクチャ

作りは非常に単純です。既存のテーブルをスキャンしながら、16KBページ（メモリ上）にタプルを格納していき、ページが満杯になったら圧縮して`road`テーブルに書き込みます。

```
+-------------------+     +------------+  compression   +---------+
|                   | --> |   chunk    | -------------> |         | \
|                   |     |  (16kB)    |                +---------+   \
|                   |     +------------+                                \     +--------------------+
|  original table   |                                                    \    |                    |
| (heap, 8kB pages) |     +------------+  compression   +---------+       `-> |     new table      |
|                   | --> |   chunk    | -------------> +---------+ --------> |  (road, 8kB pages) |
|                   |     |  (16kB)    |                                  .-> |                    |
|                   |     +------------+                                 /    |                    |
|                   |                                                   /     +--------------------+
|                   |     +------------+ compression    +---------+   /
|                   | --> |   chunk    | -------------> |         | /
|                   |     |  (16kB)    |                +---------+
|                   |     +------------+
+-------------------+
```

（今のところ）`road`テーブル内のタプルはHeap Tupleを利用しています。ですが、Heap Tupleのヘッダには`road`が必要としていないデータがいくつかあるので(xminやxmaxなど)、独自のタプルフォーマットをサポートしてみたいなと思っています。

圧縮方法はデフォルトは`pglz`。対応していれば`lz4`も指定可能です。

# ROADテーブルの作成

「既存のテーブルを`road`へ変換する」というユースケースに絞って作成したので、`road`テーブルを作成する方法は以下の2つ限られています：

- `ALTER TABLE ... SET ACCESS METHOD road`
- `CREATE TABLE ... USING road AS ...`

また、トランザクション内では作成できません。

## ProcessUtility_hookの利用

特定のDDLコマンドが実行されたかどうかを知るには`ProcessUtility_hook`が利用できます。PostgreSQLにはhookポイントと呼ばれる箇所がいくつかあり、拡張機能内で自身の関数を差し込むことが可能です。`ProcessUtility_hook`はPostgreSQLが提供するHookポイントの一つで、DDLが実行されるときに呼ばれます。

pgroadではこの`ProcessUtility_hook`を使って、実行されたSQLが`CREATE TABLE AS`もしくは`ALTER TABLE ... SET ACCESS METHOD road`かどうかを判別しています。

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

                ROAD_DEBUG_LOG("ProcessUtility: rel %s am %s",
                               RelationGetRelationName(rel), cmd->name);

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
```

この関数で「どのようなDDLが実行されたのか」を覚えておき、後に呼ばれるINSERTのためのコールバックで実際のエラーを出しています。

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

# 最後に：趣味テーブルAMのすすめ

PostgreSQLの自作テーブルAMの実体は「コールバックのまとまり」であり、自作テーブルAMがサポートしたいテーブルに関する機能（例えば、シーケンシャルスキャン、インデックススキャン、インデックス構築など）に応じて、必要なコールバックを実装する必要があります。そして、テーブルAMはPostgreSQLの中でうまく抽象化されており、他のコンポーネントとは独立して実装することが可能です。PostgreSQL本体がトランザクションやバッファマネージャなどの機能を提供しているので、テーブルAM内でそれを使うか使わないかは、実装者が選択することができます。例えば、PostgreSQL本体のバッファマネージャの機能を利用することで、自作テーブルAM開発者は、共有バッファより下の層を意識することなく実装できます。

ただし、自作テーブルAMを実装するとなると、コールバックの実装以外にも考えることはたくさんあります。

- データを保存する形式はどうするか？
  - 行指向、列指向、ページフォーマットなど
- テーブルが同時に更新された場合どうするか？
  - ロックの粒度（行レベル、テーブルレベルなど）
  - ロックマネージャ自体はPostgreSQL本体を提供するものを利用できます
- リカバリに対応するのか？
  - レプリケーションへの対応も一緒に考えても良いかも
- ROLLBACKした時どうするか？
  - Vacuumみたいに後でまとめてゴミを回収する、それともundoログ的なものを実装する、など
- ページサイズよりも大きいデータへの対応
  - PostgreSQL本体が提供するTOASTの仕組みを使うことは可能

これらをじっくり考えて理想のテーブルAMを作るもの良しですが、とりあえず作ってみたいという場合は、ユースケースをできるだけ絞ることをおすすめします。ユースケースを絞ることで制約が増えますが、考慮しなくてはいけないことが減り、実装量も減り、実装もシンプルになり易いです。まずは「単純で実用的ではないかもしれないけど動く物」を作ることで、モチベーションも上がります。テーブルAMに限らずですが、手を動かして実装してみるその過程自体が一番大切なので、実際中身は何でも良いです。

pgroadは以下のような制約があります。思い切ってこれらの制約をつけることで実装が格段に楽になりました。

- テーブルの作成は、既存のテーブルからの変更のみ（詳細は後述）
  - 既存テーブルに排他ロックを取った状態でしか、roadテーブルはつくられない
	- 同時更新を考慮しなくて良い
- 明示的なトランザクションブロック内では作れない
  - SAVEPOINTを気にしなくて良い
    - 途中で失敗したらテーブル全体がなくなる
- 読み取り専用（INSERT、UPDATE、DELETEを禁止）
  - 実装するコールバックが減る
  - 更新途中でトランザクションがAbortした場合を考えなくて良い
  - テーブル内にゴミ（不可視なタプル）が存在することはない

pgroadはアーカイブ用のTable AMでしたが、他にも実装してみると面白そうなアイディアがいくつかあります。

- 自動的に全てのタプルにRowIDが付くテーブル
- Heapがベースだけど[PAXページ](https://www.pdl.cmu.edu/PDL-FTP/Database/pax.pdf)を実装したテーブル
- WALしか出さないテーブル

などなど。

ぜひ自作Table AMの作成を通して、PostgreSQLの拡張機能開発に挑戦してみてください！
