---
layout: post
title: SQLからHINT句を生成するツール(phint)を作ってみた
tags:
  - PostgreSQL
  - Planner
  - Planner Hints
---

タイトルの通り、SQLからHINT句を生成するツールを作ってみました。正確に言うと、 **SQLを実行して実行計画の代わりに、その実行計画を再現するためのHINT句を生成する** ツールです。

今回はgo言語で作ってみました。ソースは[github]()に公開しています。

# 使ってみる

## 0. phintとpg_hint_planをインストールする

インストール方法等はRAEADMEをご参照ください(phintは`go get`するだけです)。phintの実行自体には[pg_hint_plan](http://pghintplan.osdn.jp/pg_hint_plan-ja.html)は必要ありませんが、phintで作ったHINT句をPostgreSQLで使用するためにpg_hint_planが必要です。[公式マニュアル](http://pghintplan.osdn.jp/pg_hint_plan-ja.html#install)を参照し、インストールしてください。

## 1. PostgreSQLサーバを起動

phintは、PostgreSQLにSQLを送信して実行計画を取得し、それをパースしてHINT句を生成します。そのため、事前にPostgreSQLを起動しておきます。

```bash
$ pg_ctl start
```

## 2. 適当なテーブルを作る

```sql
CREATE TABLE t1 (a int primary key, b int);
CREATE TABLE t2 (a int primary key, b int);
CREATE TABLE t3 (a int primary key, b int);
INSERT INTO t1 SELECT c, c % 100 FROM generate_series(1,10000) c;
INSERT INTO t2 SELECT c, c % 100 FROM generate_series(1,1000) c;
INSERT INTO t3 SELECT c, c % 100 FROM generate_series(1,100) c;
ANALYZE t1, t2, t3;
```

## 3. phintでSQLを実行する

適当なSQLを実行します。オプションは`psql`とほぼ同じにしています。

```bash
$ phint -c "SELECT * FROM t1, t2 WHERE t1.a = t2.b AND EXISTS (SELECT * FROM t3 WHERE a = t1.a);"
/*+
Leading((t2 (t1 t3)))
HashJoin(t2 t1 t3)
MergeJoin(t1 t3)
SeqScan(t2)
IndexScan(t1 t1_pkey)
SeqScan(t3)
*/
SELECT * FROM t1, t2 WHERE t1.a = t2.b AND EXISTS (SELECT * FROM t3 WHERE a = t1.a);
```

HIINT句と使用したSQLが標準出力に出力されます。

## 4. おまけ

実際に実行計画はどうなっているかを確認してみます。

```bash
$ psql -c "EXPLAIN SELECT * FROM t1, t2 WHERE t1.a = t2.b AND EXISTS (SELECT * FROM t3 WHERE a = t1.a);"

                                        QUERY PLAN
------------------------------------------------------------------------------------------
 Hash Join  (cost=11.80..196.30 rows=100 width=16)
   Hash Cond: (t2.b = t1.a)
   ->  Seq Scan on t2  (cost=0.00..146.00 rows=10000 width=8)
   ->  Hash  (cost=10.55..10.55 rows=100 width=12)
         ->  Merge Join  (cost=5.61..10.55 rows=100 width=12)
               Merge Cond: (t1.a = t3.a)
               ->  Index Scan using t1_pkey on t1  (cost=0.29..319.29 rows=10000 width=8)
               ->  Sort  (cost=5.32..5.57 rows=100 width=4)
                     Sort Key: t3.a
                     ->  Seq Scan on t3  (cost=0.00..2.00 rows=100 width=4)
(10 rows)
```

それっぽいHINT句が生成できている気がします。

## 5. おまけ2

phintはjson形式の実行計画を標準入力から直接受け取ることができます。`--input-plan`を使います。

```bash
$ psql -Atqc "SELECT * FROM t1, t2 WHERE t1.a = t2.b AND EXISTS (SELECT * FROM t3 WHERE a = t1.a);" | phint --input-plan
/*+
Leading((t2 (t1 t3)))
HashJoin(t2 t1 t3)
MergeJoin(t1 t3)
SeqScan(t2)
IndexScan(t1 t1_pkey)
SeqScan(t3)
*/
```

もともと、既にファイルなどに保存している実行計画からHINT句を作るために作ったオプションですが、今はjson形式しか対応していないので、今は出番はなさそうです。

# 使い道

元々実行計画を操作して色々試したいなと思い、その初期値を生成するツールとしてphintを作ったので、そのような用途には使えると思います。その他、以下の用途でも使えるかもしれません。

* 実行計画を固定化するためのHINT句を生成する
* 実行計画を分析する
  * JSON形式の実行計画をパースする処理、そこからHINT句を生成する処理はモジュール化(`phint/pgplan`)しています

# おわりに

基本的なプランノードには対応できていると思いますが、パラレルクエリやテーブル・パーティショニングなど、対応していない機能は多くあります。なにか不具合を見つけたらぜひPR下さい。