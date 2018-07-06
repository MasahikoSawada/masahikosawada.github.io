---
layout: post
title: Window関数と集約関数
tags:
  - PostgreSQL
  - Window Function
---





今回は、Window関数について、また集約関数をWindow関数として使う方法についてまとめます。

# Window関数は特定の関数ではなく一つの機能

[以前の記事]({% post_url 2018-07-04-Basics-of-Window-Function %})でも解説したように、Window関数は集約（`GROUP BY`句）と似ていますが、あくまでも関数なので結果は一つの列として出力されます。（`GROUP BY`は複数行の結果を一つの行に集約する）

Window関数というと、`row_number()`や`lag()`などの特定の関数を思い浮かべる人もいるかもしれませんが、[PostgreSQLの公式マニュアル](https://www.postgresql.org/docs/11/static/tutorial-window.html)では、以下のように説明されています。

> A window function performs a calculation across a set of table rows that are somehow related to the current row.
>
> ウィンドウ関数は現在の問い合わせ行に関連した行集合に渡っての計算処理機能を提供します。

つまり、Window関数は「テーブル（や結果セット）の一部に対して関数を実行する機能」であり、特定の関数群を指しているわけではないことがわかります。

Window関数として利用できる関数は、「Window関数としてしか利用できない関数（組み込みWindow関数と呼びます）」と、「Window関数としても利用できる集約関数」の2種類があります。

* 組み込みWindow関数
  * `row_number()`、`rank()`など。
  * Window関数としてしか呼ぶことができない。つまり、`OVER`句が必須。
* 組み込み集約関数
  * `sum()`、`count()`など、`GROUP BY`でも使える関数。
  * 集約（`GROUP BY`句）でも、Window関数（`OVER`句）としても使える

# 組み込みWindow関数

[PostgreSQL](https://www.postgresql.jp/document/10/html/functions-window.html)では、以下の組み込みWindow関数を用意しています。[MySQL 8.0](https://dev.mysql.com/doc/refman/8.0/en/window-function-descriptions.html)でも同じです。公式マニュアルから図を持ってきます。

|関数|説明|
|----|----|
|row\_number()|現在行のパーティション内での行番号（1から数える）|
|rank()|ギャップを含んだ現在行の順位。先頭ピアのrow_numberと同じになる。|
|dense\_rank()|ギャップを含まない現在行の順位。この関数はピアのグループ数を数える。|
|percent\_rank()|現在行の相対順位。 (rank - 1) / (パーティションの総行数 - 1)|
|cume\_dist()|現在行の相対順位。 (現在行より先行する行およびピアの行数) / (パーティションの総行数)|
|ntile(*num\_buckets* integer)|できるだけ等価にパーティションを分割した、1から引数値までの整数|
|lag(*value* anyelement [, *offset* integer [, *default* anyelement]])|パーティション内の現在行よりoffset行だけ前の行で評価されたvalueを返す。 該当する行がない場合、その代わりとしてdefault(valueと同じ型でなければならない)を返す。 offsetとdefaultは共に現在行について評価される。 省略された場合、offsetは1となり、defaultはNULLになる。 |
|lead(*value* anyelement [, *offset* integer [, *default* anyelement]])|パーティション内の現在行よりoffset行だけ後の行で評価されたvalueを返す。 該当する行がない場合、その代わりとしてdefault(valueと同じ型でなければならない)を返す。 offsetとdefaultは共に現在行について評価される。 省略された場合、offsetは1となり、defaultはNULLになる。 |
|first\_value(*value* any)|ウィンドウフレームの最初の行である行で評価されたvalue を返す |
|last\_value(*value* any)|ウィンドウフレームの最後の行である行で評価されたvalue を返す |
|nth\_value(*value* any, *nth* integer)|ウィンドウフレームの（１から数えて）nth番目の行である行で評価されたvalueを返す。行が存在しない場合はNULLを返す |

組み込みWindow関数は、Window関数としてしか利用できないため、`OVER`句が必須です。
例えば、`rank()`関数を使うと部署別にランキングが出せます。（PostgreSQL公式マニュアルに載っている例を使っています）。

```sql
SELECT depname, empno, salary,
       rank() OVER (PARTITION BY depname ORDER BY salary DESC)
FROM empsalary;

 depname  | empno | salary | rank 
-----------+-------+--------+------
 develop   |     8 |   6000 |    1
 develop   |    10 |   5200 |    2
 develop   |    11 |   5200 |    2
 develop   |     9 |   4500 |    4
 develop   |     7 |   4200 |    5
 personnel |     2 |   3900 |    1
 personnel |     5 |   3500 |    2
 sales     |     1 |   5000 |    1
 sales     |     4 |   4800 |    2
 sales     |     3 |   4800 |    2
```

# 集約関数

集約関数は、馴染みのある`sum()`、`count()`、`min()`、`max()`などの関数です。これらの関数は集約関数としても利用できますが、`OVER`句を使うことでWindow関数としても利用できます。

PostgreSQLは[多くの集約関数](https://www.postgresql.jp/document/10/html/functions-aggregate.html)を持っていますが、その中でも「汎用集約関数(`sum()`等）」と、「統計処理用の集約関数(`stddev()`等)」がWindow関数として利用でき、「順序集合集約関数(`percentile_cont()`等)」や、「仮定集合集約関数(`rank() WITHIN GROUP()`等)」はWindow関数として利用できません。(集約関数の種類はマニュアルを参照ください）

例えば、`sum()`関数を使うと、フレーム毎の合計値が算出できます。（これもPostgreSQL公式マニュアルに載っている例を使っています）。

```sql
SELECT salary, sum(salary) OVER (ORDER BY salary) FROM empsalary;

 salary |  sum
--------+-------
  3500  | 3500
  3900  | 7400
  4200  | 11600
  4500  | 16100
  4800  | 25700
  4800  | 25700
  5000  | 30700
  5200  | 41100
  5200  | 41100
  6000  | 47100
(10 rows)
```

また、汎用集約関数はWindow関数として利用できるので、`jsonb_agg()`のような関数も利用できます。

```sql
-- テーブルの中味
=# SELECT *  FROM jb;

color |       v
-------+---------------
 red   | {"val": 300}
 red   | {"val": 400}
 blue  | {"val": 100}
 blue  | {"val": 1200}
 blue  | {"val": 130}
(5 rows)

-- 集約関数を実行
=# SELECT *, jsonb_agg(v->'val') FROM jb;

	    jsonb_agg
----------------------------
  [300, 400, 100, 1200, 130]
(1 row)

-- 集約関数をWindow関数として実行
=# SELECT *, jsonb_agg(v->'val') OVER (PARTITION BY color ORDER BY color) from jb;

 color |       v       |    jsonb_agg
-------+---------------+------------------
 blue  | {"val": 100}  | [100, 1200, 130]
 blue  | {"val": 1200} | [100, 1200, 130]
 blue  | {"val": 130}  | [100, 1200, 130]
 red   | {"val": 300}  | [300, 400]
 red   | {"val": 400}  | [300, 400]
(5 rows)
```

# まとめ
Window関数、集約関数についてまとめました。この辺の違いを理解してると、ドキュメント等を読むときの助けになるので良いですね。ざっくりWindow関数について説明したので、次はフレーム指定方法とかを解説しようかな。

---

こまでにまとめた記事もあわせてどうぞ。

{% assign posts_list = site.posts | sort: 'date', 'last' %}
{% for post in posts_list %}
	{% if post.title contains 'Window' and post.title != page.title %}
* [{{ post.title }} ({{post.date | date: "%Y/%m/%d"}})]({{ post.url }})
	{% endif %}
{% endfor %}
