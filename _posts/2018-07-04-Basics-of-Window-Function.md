---
layout: post
title: Window関数の基本
tags:
  - PostgreSQL
  - Window Function
---

最近久しぶりにWindow関数を詳しく見てみたので、何回かに分けて解説しようと思います。以降、PostgreSQLを例にして解説しますが、PostgreSQLのWindow関数はSQL標準に対応している部分が多いので、他のDBMSでも同じよう使える部分が多いと思います。

# Window関数とは？

[Wikipedia](https://ja.wikipedia.org/wiki/%E7%AA%93%E9%96%A2%E6%95%B0_(SQL))より、

> SQL において、窓関数もしくはウィンドウ関数 (英: window function) は結果セットを部分的に切り出した領域に集約関数を適用できる、拡張された SELECT ステートメントである。

一見`GROUP BY`句に似ていますが、Window関数はあくまでも関数なので返却される行数には影響しません。

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

結果行数は3行になっています。

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

結果行数は、変わらず6行です。`sum()`関数の結果は変わっていないことに注目です。

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
-------------------------------------------------------------
  WindowAgg  (cost=1.14..1.24 rows=6 width=13)
    ->  Sort  (cost=1.14..1.15 rows=6 width=9)
        Sort Key: color
        ->  Seq Scan on w  (cost=0.00..1.06 rows=6 width=9)
 (4 rows)
```

# Window関数の考え方

Window関数ではWindow Frame（以下、フレームと呼びます）と呼ばれる区間を定義し、そのフレーム内の行に対して関数が実行されます。フレームは、以下の3つを指定することで決定されます。

* 分割する区間（パーティション）
  * `PARTITION BY`句で指定
* フレーム境界
  * `RANGE`句、`ROW`句、`GROUP`句でモードを指定して、
  * _frame\_start_ and _frame\_end_　で具体的な境界を指定する

以下、順番に説明します。

## パーティション分割をする（`PARTITION BY`句）

``PARTITION BY`句でテーブルを論理的に分割します。例えば、Window関数で`OVER (PARTITION BY color)`を指定すると以下のように分割されます。

**※見やすくするために各行の間に追加で境界線を入れています**


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

この時、上記の結果が`color列`でソートされていることに注意してください。`PARTITION BY`句で指定すると、指定した列でソートが行われます。このソートをすることによって、パーティションの境界が明確になります。ちなみに、`PARTITION BY`句を指定しないでWindow関数を実行すると、テーブルの先頭から末尾までが一つのパーティションとなります。

## フレーム境界を指定する

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

**※わかりやすくするためにcolor列の'red'を'red(1)', 'red(2)', 'red(3)'に分けています。**

```
 color  | value | sum
--------+-------+-----
 blue   |   100 | 100
--------+-------+-----  =     =     =      <---- フレームの始まり(UNBOUNDED PRECEDING)
 red(1) |   120 | 120   | (1) |     |
--------+-------+-----  =     | (2) |      <---- 現在行 = 'red(1)'の時のフレームの終わり(CURRENT ROW)
 red(2) |   120 | 240         |     | (3)
--------+-------+-----        =     |      <---- 現在行 = 'red(2)'の時のフレームの終わり(CURRENT ROW)
 red(3) |   250 | 490               |
--------+-------+-----              =      <---- 現在行 = 'red(3)'の時のフレームの終わり(CURRENT ROW)
 yellow |   160 | 160
--------+-------+-----
 yellow |   210 | 370
(6 rows)
```

通常のスキャンと同じように一行ずつ処理をしていきます。現在の行が`red(1)`の時、(1)の箇所がフレームになります。そして、次の行(`red(2)`)の時のフレームは`(2)`です。フレームの指定が`RANGE UNBOUNDED PRECEDING AND **CURRENT ROW**`なので、このように現在の行が進むにつれて、フレームも広がっていきます。そしてその結果、処理対象のデータも変わるので、`sum()`を使うと、120 -> 240 -> 490と増えていきます。

例えば、フレーム境界のを常にパーティションの先頭・末尾に指定する(`ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING`)と、各行を処理しているときのフレームは以下のようになります。

```
 color  | value | sum
--------+-------+-----
 blue   |   100 | 100
--------+-------+-----  =     =     =     <----- フレームの始まり(UNBOUNDED PRECEDING)
 red(1) |   120 | 490   |     |     |
--------+-------+-----  |     |     |
 red(2) |   120 | 490   | (1) | (2) | (3)
--------+-------+-----  |     |     |
 red(3) |   250 | 490   |     |     |
--------+-------+-----  =     =     =     <----- フレームの終わり(UNBOUNDED FOLLOWING)
 yellow |   160 | 160
--------+----+-------
 yellow |   210 | 370
(6 rows)
```

現在の行に関わらず、パーティションくの区間とフレームの区間が一致します。そのため、`sum()`関数の結果は同じ(=490)になります。

# まとめ
まずはパーティションやフレームの概念について説明しました。
パーティションやフレームが理解できれば、Window関数を使いこなす準備はできていると思います。
