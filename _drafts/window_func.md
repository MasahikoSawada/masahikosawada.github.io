---
layout: post
title: Window関数の基本
tags:
  - PostgreSQL
  - Window Function
---

最近久しぶりににWindow関数を見てみたのでいくつかの回に分けて詳細を解説しようと思います。

# Window関数とは？
Window関数は、誤解を恐れずに簡単に言うと「テーブルを区間毎に分割し、その分割した区間に対して実行する関数」です。`GROUP BY`では、集計対象はテーブルの全ての行で、それらの結果をまとめて返却します。Window関数では、特定の区間に対して集約関数を実行し、それの結果を算出します。まずは簡単な例を見てみましょう。

* テーブルの状態

```sql
=# SELECT * FROM w;
 color  | id | value 
--------+----+-------
 red    |  1 |   120
 blue   |  2 |   100
 red    |  2 |   250
 yellow |  1 |   160
 yellow |  2 |   210
 red    |  3 |   120
(6 rows)
```

* GROUP BYで集計

結果行数は３行になっています。

```sql
=# SELECT color, sum(value) FROM w GROUP BY color;
 color  | sum 
--------+-----
 yellow | 370
 blue   | 100
 red    | 490
(3 rows)
```

* Window関数で集計

結果行数は、変わらず６行です。`sum()`関数の結果は変わっていないことに注目です。

```sql
=# SELECT color, sum(value) over (partition by color) FROM w;
 color  | sum
--------+-----
 blue   | 100
 red    | 490
 red    | 490
 red    | 490
 yellow | 370
 yellow | 370
(6 rows)

```

ちなみに実行計画は以下のようになります。Seq Scanでテーブルをスキャンし、`color`列でソート、そして、その結果に対してWindowAggでWindow関数を実行します。なぜSortが必要かは、この後を読んでいけばきっと理解できます。

```sql
                            QUERY PLAN
------------------------------------------------------------------
 WindowAgg  (cost=83.37..104.37 rows=1200 width=40)
   ->  Sort  (cost=83.37..86.37 rows=1200 width=36)
         Sort Key: color
         ->  Seq Scan on w  (cost=0.00..22.00 rows=1200 width=36)
(4 rows)

```

# "Window"の考え方

Window関数ではWindowと呼ばれる区間を定義し、そのWindowに対して関数が実行されます。Window Frameは、以下の３つを指定することで決定されます。

* 分割する区間
  * `PARTITION BY`句
* フレーム境界
  * `RANGE`句、`ROW`句、`GROUP`句
  * __frame\_start__ and __frame\_end__

## Window Frame

### 分割する区間(`PARTITION BY`句)

``PARTITION BY`句でテーブルを論理的に分割します。例えば、Window関数で`OVER (PARTITION BY color)`を指定すると以下のように分割されます。


```
 color  | sum
--------+-----  -
 blue   | 100   |  (1) 'blue'のパーティション
--------+-----  -  -
 red    | 490      |
--------+-----     |
 red    | 490      |  (2) 'red'のパーティション
--------+-----     |
 red    | 490      |
--------+-----     -  -
 yellow | 370         |
--------+-----        |  (3) 'yellow'のパーティション
 yellow | 370         |
--------+-----        -
(6 rows)
```

### フレーム

そして、`PARTITION BY`句の次に具体的なフレームを指定します。

```sql
SELECT *, sum(value) OVER (
       PARTITION BY color
       ORDER BY id
       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
) ...
```
と指定すると、フレームは以下のように指定されます。

* ROWSモードで、
* フレームの始まりはパーティションの先頭(UNBOUND PRECEIDING)で、
* フレームの終わりは現在の行(CURRENT ROW)

RANGEモードとROWSモードの違いは、同一行（ソートした時の同じ値）をフレームの境界にするかどうかです。ROWSモードでは境界にして、RANGEモードでは境界にしません。
'red'のパーティションに注目してフレームの動きを見てみると以下のようになります。

```
 color  | value | sum
--------+-------+-----
 blue   |   100 | 100
--------+----+-------  -  =     =     =
 red(1) |   120 | 240  |  | (1) |     |
--------+----+-------  |  =     | (2) |
 red(2) |   120 | 240  |        |     | (3)
--------+----+-------  |        =     |
 red(3) |   250 | 490  |              |
--------+----+-------  -              =
 yellow |   160 | 160
--------+----+-------
 yellow |   210 | 370
(6 rows)
```

通常のスキャンと同じように一行ずつ処理をしていきます。現在の行が'red(1)`の時、(1)の箇所がフレームになります。そして、次の行(`red(2)`)の時のフレームは`(2)`です。フレームの指定が`RANGE UNBOUNDED PRECEDING AND CURRENT ROW`なので、このように現在の行が進むにつれて、フレームも広がっていきます。そしてその結果、処理対象のデータも変わるので、`sum()`を使うと、120 -> 240 -> 490と増えていきます。

例えば、`ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING`とすると、フレームの始まりはパーティションの先頭で、フレームの終わりはパーティションの末尾となり、以下のようになります。

```
 color  | value | sum
--------+-------+-----
 blue   |   100 | 100
--------+----+-------  -  =     =     =
 red(1) |   120 | 490  |  | (1) |     |
--------+----+-------  |  |     | (2) |
 red(2) |   120 | 490  |  |     |     | (3)
--------+----+-------  |  |     |     |
 red(3) |   250 | 490  |  |     |     |
--------+----+-------  -  =     =     =
 yellow |   160 | 160
--------+----+-------
 yellow |   210 | 370
(6 rows)
```

現在の行に関わらず、パーティションくの区間とフレームの区間が一致します。そのため、`sum()`関数の結果は同じ(=490)になります。

### 
