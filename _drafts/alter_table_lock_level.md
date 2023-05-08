---
layout: post
title: ALTER TABLEの各コマンドのロックレベル
tags:
  - PostgreSQL
---

`ALTER TABLE`コマンドは各サブコマンドによってテーブルへのロックレベルが異なります。[ソース](https://github.com/postgres/postgres/blob/REL_15_STABLE/src/backend/commands/tablecmds.c#L4161)を見るのが一番正確なのですが、いつも確認するのが面倒なのでまとめてみました。

**※ PostgreSQL 15 の情報です。**

PostgreSQLのロックレベルは[こちら](https://www.postgresql.jp/document/14/html/explicit-locking.html#TABLE-LOCK-COMPATIBILITY)に載っています。`ALTER TABLE`に関連する主なロックレベルと、大体の雰囲気は以下の通り。

* `AccessExclusiveLock`: SELECTさえもできなくなる、一番強いロック。
* `ShareRowExclusiveLock`: SELECTはできるけど、UPDATE、DELETE、INSERTはできない。同じコマンド同士も競合する。
* `ShareUpdateExclusiveLock`: SELECT、INSERT、UPDATE、DELETEはできる。同じコマンド同時は競合する。

基本的にテーブルの書き換えが必要なもの（例えば列のデータ型をINTからTEXTにするなど）は、`AccessExclusiveLock`が必要となります。ただ、一部`ShareRowExsluveLock`や`ShareUpdateExclusiveLock`などの弱いロックが使われていて、SELECTやINSERT、UPDATE、DELETEが同時に実行できる、というイメージ。

## `ALTER TABLE`のサブコマンドとロックレベルの一覧（PG15版）

| サブコマンド                               | ロックレベル                                                                              |
|--------------------------------------------|-------------------------------------------------------------------------------------------|
| ADD COLUMN                                 | AccessExclusiveLock                                                                       |
| ATTACH PARTITION                           | ShareUpdateExclusiveLock                                                                  |
| DROP COLUMN                                | AccessExclusiveLock                                                                       |
| ALTER COLUMN ... SET DATA TYPE             | AccessExclusiveLock                                                                       |
| ALTER COLUMN ... SET DEFAULT               | AccessExclusiveLock                                                                       |
| ALTER COLUMN ... DROP DEFAULT              | AccessExclusiveLock                                                                       |
| ALTER COLUMN ... SET NOT NULL              | AccessExclusiveLock                                                                       |
| ALTER COLUMN ... DROP NOT NULL             | AccessExclusiveLock                                                                       |
| ALTER COLUMN ... DROP EXPRESSION           | AccessExclusiveLock                                                                       |
| ALTER COLUMN ... ADD GENERATED AS IDENTITY | AccessExclusiveLock                                                                       |
| ALTER COLUMN ... SET GENERATED             | AccessExclusiveLock                                                                       |
| ALTER COLUMN ... DROP IDENTITY             | AccessExclusiveLock                                                                       |
| ALTER COLUMN ... SET STATISTICS            | ShareUpdateExclusiveLock                                                                  |
| ALTER COLUMN ... SET (...)                 | ShareUpdateExclusiveLock                                                                  |
| ALTER COLUMN ... RESET (...)               | ShareUpdateExclusiveLock                                                                  |
| ALTER COLUMN ... SET STORAGE               | AccessExclusiveLock                                                                       |
| ALTER COLUMN ... SET COMPRESSION           | AccessExclusiveLock                                                                       |
| ADD table_constraint                       | AccessExclusiveLock or ShareRowExclusiveLock [^table_constraint]                          |
| ALTER CONSTRAINT ...                       | AccessExclusiveLock                                                                       |
| VALIDATE CONSTRAINT                        | ShareUpdateExclusiveLock                                                                  |
| DETACH PARTITION                           | ShareUpdateExclusiveLock or AccessExclusiveLock [^detach_partition]                       |
| DROP CONSTRAINT                            | AccessExclusiveLock                                                                       |
| DISABLE TRIGGER                            | ShareRowExclusiveLock                                                                     |
| ENABLE TRIGGER                             | ShareRowExclusiveLock                                                                     |
| ENABLE REPLICA TRIGGER                     | ShareRowExclusiveLock                                                                     |
| ENABLE ALWAYS TRIGGER                      | ShareRowExclusiveLock                                                                     |
| DISABLE RULE                               | AccessExclusiveLock                                                                       |
| ENABLE RULE                                | AccessExclusiveLock                                                                       |
| ENABLE REPLICA RULE                        | AccessExclusiveLock                                                                       |
| ENABLE ALWAYS RULE                         | AccessExclusiveLock                                                                       |
| DISABLE ROW LEVEL SECURITY                 | AccessExclusiveLock                                                                       |
| ENABLE ROW LEVEL SECURITY                  | AccessExclusiveLock                                                                       |
| NO FORCE ROW LEVEL SECURITY                | AccessExclusiveLock                                                                       |
| CLUSTER ON                                 | ShareUpdateExclusiveLock                                                                  |
| SET WITHOUT CLUSTER                        | ShareUpdateExclusiveLock                                                                  |
| SET WITHOUT OIDS                           | AccessExclusiveLock                                                                       |
| SET ACCESS METHOD                          | AccessExclusiveLock                                                                       |
| SET TABLESPACE                             | AccessExclusiveLock                                                                       |
| SET LOGGED/UNLOGGED                        | AccessExclusiveLock                                                                       |
| SET (...)                                  | パラメータによって異なる（大体が`ShareUpdateExclusiveLock`、たまに`AccessExclusiveLock`） |
| RESET (...)                                | パラメータによって異なる（大体が`ShareUpdateExclusiveLock`、たまに`AccessExclusiveLock`） |
| INHERIT                                    | AccessExclusiveLock                                                                       |
| NO INHERIT                                 | AccessExclusiveLock                                                                       |
| OF                                         | AccessExclusiveLock                                                                       |
| NOT OF                                     | AccessExclusiveLock                                                                       |
| OWNER TO                                   | AccessExclusiveLock                                                                       |
| RENAME                                     | AccessExclusiveLock                                                                       |
| REPLICA IDENTITY                           | AccessExclusiveLock                                                                       |
| SET SCHEMA                                 | AccessExclusiveLock                                                                       |
| SET TABLESPACE                             | AccessExclusiveLock                                                                       |

 [^table_constraint]: 外部キーに関するものの場合は`ShareRowExclusiveLock`、それ以外（主キーなど）は`AccessExclusiveLock`
 [^detach_partition]: `CONCURRENTLY`オプションがついていれば`ShareUpdateExclusiveLock`、そうでない場合は`AccessExclusiveLock`

抜け漏れ、誤り等あればぜひご指摘ください。
