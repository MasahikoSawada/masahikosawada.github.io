---
layout: post
title: Parallel Queryの概要
decription: PostgreSQLのパラレルクエリ(Parallel Query)について、その概要、実行計画(EXPLAIN)の読み方などを解説
tags:
  - PostgreSQL
  - Parallel Query
---

PostgreSQLでは、バージョン9.6からパラレルクエリが利用可能です。Oracle、DB2でもパラレルクエリは実装されていますが、PostgreSQLのパラレルクエリはどのような特徴があるのでしょうか。簡単にパラレルクエリの概要を紹介します。

# パラレルクエリの目的
パラレルクエリは、複数のCPUを使ってクエリを並列(Parallel)に処理する機能です。そのため、クエリの実行時間の短縮が期待できます。並行(Concurrent)とは異なるので注意。

# EXPLAIN(実行計画)の見方
パラレルクエリが使われた場合の実行計画の読み方は注意が必要です。

まずは、パラレルクエリOFFの実行計画(ANALYZE, VERBOSE)。
```
=# explain (costs off, analyze on, verbose on) select count(*) from hoge;
                                   QUERY PLAN
---------------------------------------------------------------------------------
 Aggregate (actual time=756.651..756.651 rows=1 loops=1)
   Output: count(*)
   ->  Seq Scan on public.hoge (actual time=0.038..425.255 rows=3000000 loops=1)
         Output: a, b
```

で、同じクエリをパラレルクエリを使って実行した実行計画。

```
=# explain (costs off, analyze on, verbose on) select count(*) from hoge;
                                              QUERY PLAN
------------------------------------------------------------------------------------------------------
 Finalize Aggregate (actual time=374.581..374.581 rows=1 loops=1)
   Output: count(*)
   ->  Gather (actual time=374.412..377.035 rows=3 loops=1)
         Output: (PARTIAL count(*))
         Workers Planned: 2
         Workers Launched: 2
         ->  Partial Aggregate (actual time=370.802..370.802 rows=1 loops=3)
               Output: PARTIAL count(*)
               Worker 0: actual time=368.338..368.338 rows=1 loops=1
               Worker 1: actual time=369.962..369.962 rows=1 loops=1
               ->  Parallel Seq Scan on public.hoge (actual time=0.022..216.928 rows=1000000 loops=3)
                     Output: a, b
                     Worker 0: actual time=0.029..215.807 rows=1345152 loops=1
                     Worker 1: actual time=0.019..219.587 rows=796876 loops=1
```

`Aggregate`が`Finalize Aggregate`と`Partial Aggregate`に変わっていること、`Seq Scan`が`Parallel Seq Scan`に変わっていることがわかります。また、`Workers 0: ...`の様な情報が増え、なにかしらのワーカーと一緒に動作していることがわかります。

少し分かり難いですが、この実行計画はリーダー（SQLを受け付けたプロセス）1つ、ワーカー（パラレルクエリ実行時に起動された補助プロセス）２つの合計３プロセスで並列動作しています。更にリーダーは、`Finalize Aggregate`を含む全ノードを実行しているのに対して、ワーカーは、`Partial Aggragate`から下のノードを実行しています。つまり、`Partial Aggragate` -> `Parallel Seq Scan`は、全プロセスが実行し、リーダは、その結果を集めながら(`Gatherノード`)、最終的な集約(`Finalize Aggragate`)をしています。クエリが何並列で動作したのかは、`Workers Launchedの値 + 1`か、並列処理になっている部分の`loops`の値を確認することで可能です。

`Workers Planned`は実行計画作成時に必要だと算出された並列度で、`Workers Launched`は実際に起動したワーカーの数です。他にもパラレルクエリが走っていたりすると、`Workers Launched < Workers Planned`になることがあります。

さらにパラレルクエリ全体で処理した行数、リーダープロセス・ワーカープロセスで処理した行数の見方は、以下のような感じになります。
* ノード全体で処理した行数: `(ノードのactual rows) * loops`
  * 上記の例では、`1000000 * 3 = 3000000行`
* ワーカーが処理した行数: `Worker ...`に書いてある`actual rows`
  * 上記の例では、`1345152行`と`796876行`
* リーダーが処理した行数: `ノード全体の行数 - ワーカーで処理した行数の合計`
  * 上記の例では、`3000000 - (1345152 + 796876) = 857972行`

パラレルクエリの実行計画のイメージは、以前に発表した資料で図解していますので、そちらもご覧ください。

<center><iframe src="//www.slideshare.net/slideshow/embed_code/key/gsYirIoV8Trhrl?startSlide=30" width="595" height="485" frameborder="0" marginwidth="0" marginheight="0" scrolling="no" style="border:1px solid #CCC; border-width:1px; margin-bottom:5px; max-width: 100%;" allowfullscreen> </iframe> <div style="margin-bottom:5px"> <strong> <a href="//www.slideshare.net/masahikosawada98/postgresql11" title="今秋リリース予定のPostgreSQL11を徹底解説" target="_blank">今秋リリース予定のPostgreSQL11を徹底解説</a> </strong> from <strong><a href="//www.slideshare.net/masahikosawada98" target="_blank">Masahiko Sawada</a></strong> </div></center>

# 対応している操作
## 9.6
* Seq Scan
* Nested Loops Join
* Hash Join

## 10
* Merge Join(Gather Merge)
* Index Scan
* Index Only Scan
* Bitmap Heap Scan

## 11
* (Parallel-aware) Hash Join
* Append
* CREATE INDEX / REINDEX
* CREATE TABLE ... AS
* SELECT INTO ...
* CREATE MATERIALIZED VIEW

# 対応していない操作
* UPDATE
* DELETE
* CTE(WITH句)
* VACUUM
* Window関数(ソート部分はパラレルクエリ利用可)
* 拡張プロトコル(PREPARE/EXECUTE、Prepared Statement)
* トランザクション分離レベルがSerializable
ほかにも色々あります。

# 読み込み専用
現在のパラレルクエリは読み込み操作のみがに対応しています。CRAETE INDEX、CREATE TABLE AS、CREATE MATERIALIZED VIEW等は書き込みを伴う処理ですが、一連の操作の中の読み込み処理のみ（例えば、CRAETE INDEXではテーブルをソートする処理）が並列に実行されます。各パラレルクエリの操作の詳細については後日まとめようと思います。

# 参考資料
本記事は以下の参考資料を元に執筆しました

* [公式マニュアル](https://www.postgresql.jp/document/10/html/parallel-query.html)
* [Parallel Query in PostgreSQL: How not to (mis)use it?](https://www.postgresql.eu/events/pgconfeu2018/sessions/session/2140/slides/141/PQ_PGCON_EU_2018.pdf)
* [Next-Generation Parallel Query](https://www.pgcon.org/2017/schedule/attachments/445_Next-Generation%20Parallel%20Query%20-%20PGCon.pdf)
