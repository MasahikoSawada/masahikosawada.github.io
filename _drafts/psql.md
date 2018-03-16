---
layout: post
title: "よく使うpsqlの便利技"
tags:
  - PostgreSQL
  - psql
---

普段よく使っているpsqlの便利だと思う使い方を紹介します。運用で使うシェルスクリプトとかでもpsqlは使う事があると思うので、psql派でない人にも多少は役に立つはず。
最近色々便利になっているのでまとめておく。

# メタコマンドとSQLを一緒に使う

拡張表現(`\x`コマンド)を有効にしながらSQLコマンドを実行したい、という時とかに便利です。
`-cオプション`を使うと、メタコマンドのみが実行されてしまうので、`echo`コマンドでメタコマンドとSQLを出力してパイプでpsqlに流す、みたいなことをやる必要があります。
メタコマンドは、バックスラッシュで区切る事ができるので、複数のメタコマンドを使うこともできます。

## 実行例

```bash
$ echo '\x \\ SELECT * FROM pg_class' | psql 
Expanded display is on.
-[ RECORD 1 ]-------+----------------------------
relname             | pg_statistic
relnamespace        | 11
reltype             | 11318
reloftype           | 0
relowner            | 10
relam               | 0
relfilenode         | 2619
reltablespace       | 0
relpages            | 16
(snip)
```

# SELECT結果の値だけを取得する

psqlでのSELECT結果は、テーブルの形に整形されて出力されるので、SELECT結果の値をパースしたい時とかには不便です。
`-Aqtc`オプションを利用するとシェルスクリプトとかで、実行結果だけを取得してその値をなにかに使う、という時とかにに便利です。
さらに~-Fオプション`も併用すると、区切り文字を変更できます。

## 実行例

```bash
$ psql -Atqc "SELECT * FROM pg_class LIMIT 1"
pg_statistic|11|11318|0|10|0|2619|0|16|393|16|2840|t|f|p|r|26|0|f|f|f|f|f|f|t|n|f|550|1|{masahiko=arwdDxt/masahiko}||

# 区切り文字を変更して実行
$ psql -F ',' -Atqc "SELECT * FROM pg_class LIMIT 1"
pg_statistic,11,11318,0,10,0,2619,0,16,393,16,2840,t,f,p,r,26,0,f,f,f,f,f,f,t,n,f,550,1,{masahiko=arwdDxt/masahiko},,
```
# SQLでSQLを作り実行

`\gexec`コマンドを利用します。`\gexec`は直前のSELECT結果を再度PostgreSQLに投げる、というものです。
これを使うと、SELECTでSQLを作成しそれを実行する、とかができるので、例えば、テスト用に大量のテーブルを作る、大量のテーブルの設定値を一斉に変更する、とかに便利です。
これが無いときは、一旦テーブル名をファイルに出してそれを読み込みながらSQLを実行する、みたいなことをしていました。

## 実行例

{% highlight sql %}
-- テーブルを100個作るDDLを生成し実行
=# SELECT 'CREATE TABLE tbl_' || genereate_series(1,100) || ' (c int)'; \gexec
           ?column?
------------------------------
 CREATE TABLE tbl_1 (c int)
 CREATE TABLE tbl_2 (c int)
 CREATE TABLE tbl_3 (c int)
 CREATE TABLE tbl_4 (c int)
 CREATE TABLE tbl_5 (c int)
:
CREATE TABLE
CREATE TABLE
CREATE TABLE
CREATE TABLE
CREATE TABLE
CREATE TABLE

-- 特定のテーブル('hoge_'で始まるテーブル)のautovacuumを無効にする
=# SELECT 'ALTER TABLE ' || relname || ' SET (autovacuum_enabled = off)' FROM pg_class WHERE relname LIKE 'hoge_%'; \gexec
                       ?column?
------------------------------------------------------
 ALTER TABLE hoge_2017 SET (autovacuum_enabled = off)
 ALTER TABLE hoge_2018 SET (autovacuum_enabled = off)
 ALTER TABLE hoge_2019 SET (autovacuum_enabled = off)
(3 rows)

ALTER TABLE
ALTER TABLE
ALTER TABLE
{% endhighlight %}

# サーバに応じて実行するSQLを変える

psqlに備わっている`\if`、`\else`、`\endif`を使います。
レプリケーション構成でマスタ、スタンバイに投げるSQLを変えたい場合や、複数サーバが混在する環境で便利です。

## 実行例

```bash
$ cat repl_status.sql
SELECT split_part(version(), ' ', 2) == '10' as version_10;\gset
\if :version_10
-- PostgreSQL 10用の関数
SELECT pg_current_wal_lsn();
\else
-- PostgreSQL 9.6以前用の関数
SELECT pg_current_xlog_location();
\endif
$ psql -f repl_status.sql
```

# 忘れたDDLのシンタックスを確認する

「このDDLってどうやって書くんだっけ？」というような時に便利です。psqlを使っていればわざわざググる必要はなく、`\help`を使えます。

## 実行例

```sql
=# \help CREATE TABLE
Command:     CREATE TABLE
Description: define a new table
Syntax:
CREATE [ [ GLOBAL | LOCAL ] { TEMPORARY | TEMP } | UNLOGGED ] TABLE [ IF NOT EXISTS ] table_name ( [
  { column_name data_type [ COLLATE collation ] [ column_constraint [ ... ] ]
    | table_constraint
    | LIKE source_table [ like_option ... ] }
    [, ... ]
] )
[ INHERITS ( parent_table [, ... ] ) ]
[ PARTITION BY { RANGE | LIST } ( { column_name | ( expression ) } [ COLLATE collation ] [ opclass ] [, ... ] ) ]
[ WITH ( storage_parameter [= value] [, ... ] ) | WITH OIDS | WITHOUT OIDS ]
[ ON COMMIT { PRESERVE ROWS | DELETE ROWS | DROP } ]
[ TABLESPACE tablespace_name ]

CREATE [ [ GLOBAL | LOCAL ] { TEMPORARY | TEMP } | UNLOGGED ] TABLE [ IF NOT EXISTS ] table_name
    OF type_name [ (
  { column_name [ WITH OPTIONS ] [ column_constraint [ ... ] ]
    | table_constraint }
    [, ... ]
) ]
[ PARTITION BY { RANGE | LIST } ( { column_name | ( expression ) } [ COLLATE collation ] [ opclass ] [, ... ] ) ]
[ WITH ( storage_parameter [= value] [, ... ] ) | WITH OIDS | WITHOUT OIDS ]
[ ON COMMIT { PRESERVE ROWS | DELETE ROWS | DROP } ]
[ TABLESPACE tablespace_name ]

CREATE [ [ GLOBAL | LOCAL ] { TEMPORARY | TEMP } | UNLOGGED ] TABLE [ IF NOT EXISTS ] table_name
    PARTITION OF parent_table [ (
  { column_name [ WITH OPTIONS ] [ column_constraint [ ... ] ]
    | table_constraint }
    [, ... ]
) ] FOR VALUES partition_bound_spec
[ PARTITION BY { RANGE | LIST } ( { column_name | ( expression ) } [ COLLATE collation ] [ opclass ] [, ... ] ) ]
[ WITH ( storage_parameter [= value] [, ... ] ) | WITH OIDS | WITHOUT OIDS ]
[ ON COMMIT { PRESERVE ROWS | DELETE ROWS | DROP } ]
[ TABLESPACE tablespace_name ]

where column_constraint is:

[ CONSTRAINT constraint_name ]
:
:
```

# SQLファイルの内容を一行ずつ確認しながら実行する

`--single-step`オプションを使うことで、SQLファイルの内容を一行ずつ確認しながら、インタラクティブに実行できます。
スクリプトのデバッグや、デモの時に便利です。

## 実行例

```bash
$ cat /tmp/test.sql
SELECT 1;
SELECT now();
$ psql --sigle-step -f /tmp/test.sql
***(Single step mode: verify command)*******************************************
SELECT 1;
***(press return to proceed or enter x and return to cancel)********************

 ?column?
----------
        1
(1 row)

***(Single step mode: verify command)*******************************************
SELECT now();
***(press return to proceed or enter x and return to cancel)********************
x
```

# 特定のコマンドを定期的に実行したい

`\watch`コマンドを使うことで指定した秒数間隔でSQLを実行してくれます。監視SQLを流し続けたい時とかに便利です。
Ctl-cを押下するまで続きます。1秒以下も指定できます。

## 実行例

```sql
=# SELECT write_lag, flush_lag, replay_lag FROM pg_stat_replication; \watch 1
     Fri 16 Mar 2018 10:56:18 PM JST (every 1s)

    write_lag    |    flush_lag    |   replay_lag
-----------------+-----------------+-----------------
 00:00:00.000132 | 00:00:00.000323 | 00:00:00.000347
(1 row)

     Fri 16 Mar 2018 10:56:19 PM JST (every 1s)

    write_lag    |   flush_lag    |   replay_lag
-----------------+----------------+-----------------
 00:00:00.000096 | 00:00:00.00027 | 00:00:00.000285
(1 row)
:
```

# psqlを起動した時に実行されるコマンドを設定する

余り需要は無いかもしれませんが、`.psqlrc`にpsql起動時に自動的に実行するコマンドを定義できます。
私のの場合、プロンプトの表示を変えたり、alias的なものを設定することに使っています。

### 実行例

```sql
\set PROMPT1 '%/(%l:%p)%R%# '
\set PROMPT2 '%/(%l:%p)%R%# '
\set 100 'select ''create table t'' || generate_series(1,100) || '' (c int)'';\\gexec'
\set hoge 'create table hoge (c int);'
\timing on
```

# SELECTの結果をCSV形式で出力

最後はpsqlは関係ないですが、[COPYコマンド](https://www.postgresql.jp/document/10/html/sql-copy.html)の機能を使って、ファイル出力します。
区切り文字やNULL値を表す文字列とかを変えることも可能です。


### 実行例
```bash
# pg_classテーブルの中身をCSV形式でファイル(/tmp/data.csv)出力する。
$ psql -c "COPY (SELECT * FROM hoge) to '/tmp/data.csv' (format csv);"
```



