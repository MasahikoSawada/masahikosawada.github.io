---
layout: post
title: Window関数のFILTER句を極める
description: Window関数のFILTERオプションについて、その機能、WHERE句との違い等を徹底解説。
tags:
  - PostgreSQL
  - Window Function
lang: jp
---

この記事は、[PostgreSQL Advent Calendar 2018](https://qiita.com/advent-calendar/2018/postgresql)の17日目の記事です。

久しぶりの更新では、Window関数のFILTER句について解説します。まずは文法を確認します。FILTER句は、関数名の後、OVER句の前の指定します。

```
function_name ([expression [, expression ... ]]) [ FILTER ( WHERE filter_clause ) ] OVER window_name
function_name ([expression [, expression ... ]]) [ FILTER ( WHERE filter_clause ) ] OVER ( window_definition )
function_name ( * ) [ FILTER ( WHERE filter_clause ) ] OVER window_name
function_name ( * ) [ FILTER ( WHERE filter_clause ) ] OVER ( window_definition )
```

Window関数のメインとも言えるフレーム指定は、上記の`window_definition`や`window_name`にあたる部分で指定するため、FILTER句はその前にしておくものだということがわかります。

# 使ってみる
FILTER句はその名前からも推測できるように、入力値をフィルターする役割を持ちます。
指定する際には、`FILTER (WHERE a < 10)`の様に、WHERE句も一緒に記載します。これは、SQL標準に準拠した文法です。

以下のようなテーブルを用意します。

```sql
CREATE TABLE test (a int, b int);
INSERT INTO test VALUES (1, 1),  (1, 2), (1, 3), (2, 1), (2, 2), (2, 3), (2, 4);
SELECT * FROM test ORDER BY a, b;
  a | b
 ---+---
  1 | 1
  1 | 2
  1 | 3
  2 | 1
  2 | 2
  2 | 3
  2 | 4
(7 rows)
```

次に、**FILTER句なし** でa列でパーティションを区切り、b列に対して集約関数(`string_agg())`を実行します。

```sql
=# SELECT a, b,
	string_agg(b::text, ',')
	OVER (
		PARTITION BY a
		ORDER BY a,b
	)
   FROM test;

　a | b | string_agg
 ---+---+------------
  1 | 1 | 1
  1 | 2 | 1,2
  1 | 3 | 1,2,3
  2 | 1 | 1
  2 | 2 | 1,2
  2 | 3 | 1,2,3
  2 | 4 | 1,2,3,4
 (7 rows)
```

ここまでは簡単で、`string_agg()`の結果には、徐々にb列の値が加えられていることがわかります。ここまでの内容についていけない場合は、[以前の記事]({% post_url 2018-07-04-Basics-of-Window-Function %}) をご確認ください。

次に、FILTER句に適当な条件を入れてを入れて実行してみます。

```sql
=# SELECT a, b,
	string_agg(b::text, ',')
	FILTER (WHERE b != 2)         -- 追加した行
	OVER (
		PARTITION BY a
		ORDER BY a,b
	)
   FROM test;

  a | b | string_agg
 ---+---+------------
  1 | 1 | 1
  1 | 2 | 1
  1 | 3 | 1,3
　2 | 1 | 1
  2 | 2 | 1
  2 | 3 | 1,3
  2 | 4 | 1,3,4
(7 rows)
```

FILTER句には、`WHERE b != 2`と指定したため、`b != 2`の条件に一致する行のみに集約関数(`string_agg()`)が実行されました。

ここで注意したいのは、 **b = 2の行の出力自体はフィルタされていない**ことです。もう少し詳細に見ていきます。


# FILTER句とWHERE句の違い

FILTER句では、入力行に対してある条件を指定することができました。一方で、`SELECT .. FROM .. WHERE`のWHERE句(ややこしい)でも行の入力を制限することが可能です。これらにはどのような違いがあるのでしょうか？

実際にやってみると違いは一目瞭然です。

* FILTER句で`b != 2`

```sql
=#  SELECT a, b,
       string_agg(b::text, ',')
       FILTER (WHERE b != 2)
       OVER (
       	    PARTITION BY a
       	    ORDER BY a,b
       )
   FROM test;

 a | b | string_agg
---+---+------------
 1 | 1 | 1
 1 | 2 | 1
 1 | 3 | 1,3
 2 | 1 | 1
 2 | 2 | 1
 2 | 3 | 1,3
 2 | 4 | 1,3,4
 (7 rows)
```

* WHERE句で`b != 2`

```sql
=#  SELECT a, b,
	string_agg(b::text, ',')
        OVER (
        PARTITION BY a
	ORDER BY a,b
        )
   FROM test
   WHERE b != 2;

 a | b | string_agg
---+---+------------
 1 | 1 | 1
 1 | 3 | 1,3
 2 | 1 | 1
 2 | 3 | 1,3
 2 | 4 | 1,3,4
(5 rows)
```

FILTER句は「集約関数にその値を渡すかどうか」に影響し、値を渡しても渡さなくても集約関数は各出力行に対して実行します。一方、WHERE句は、「集約関数に行を渡すかどうか」に影響するため、条件に一致しない行は出力にも現れてこず、当然集約関数も実行されません。

実行計画を見てもわかります。

* FILTER句で`b != 2`

```sql
=# EXPLAIN (analyze on, costs off) SELECT a, b,
   	   string_agg(b::text, ',')
	   FILTER (WHERE b != 2)
	   OVER (
	         PARTITION BY a
		 ORDER BY a,b
  )
  FROM test;
                               QUERY PLAN
------------------------------------------------------------------------
 WindowAgg (actual time=0.045..0.064 rows=7 loops=1)
   ->  Sort (actual time=0.027..0.028 rows=7 loops=1)
         Sort Key: a, b
         Sort Method: quicksort  Memory: 25kB
         ->  Seq Scan on test (actual time=0.014..0.015 rows=7 loops=1)
 Planning Time: 0.085 ms
 Execution Time: 0.114 ms
(7 rows)
```

* WHERE句で`b != 2`

```sql
=# EXPLAIN (analyze on, costs off) SELECT a, b,
   	   string_agg(b::text, ',')
	   OVER (
	   	PARTITION BY a
		ORDER BY a,b
   )
   FROM test
   WHERE b != 2;
                               QUERY PLAN
------------------------------------------------------------------------
 WindowAgg (actual time=0.053..0.069 rows=5 loops=1)
   ->  Sort (actual time=0.036..0.037 rows=5 loops=1)
         Sort Key: a, b
         Sort Method: quicksort  Memory: 25kB
         ->  Seq Scan on test (actual time=0.023..0.026 rows=5 loops=1)
               Filter: (b <> 2)
               Rows Removed by Filter: 2
 Planning Time: 0.124 ms
 Execution Time: 0.121 ms
(9 rows)
```

FILTER句の例では、`WindowAgg`ノードに7行(全ての行)が渡されいることに対し、WHERE句の例では、`Seq Scan`にてすでに絞り込みが行われているため、`WindowAgg`には5行しか渡されていません。FILTER句とWHERE句では絞り込みするタイミングが異なることがわかります。

# 余談
FILTER句はWindow関数特有のものではなく、全ての集約関数に使用可能です。例えば、以下のように使うことも可能です。

```sql
=# SELECT
     string_agg(b::text, ',')
     FILTER (WHERE b != 2)
   FROM test
   GROUP BY a;
 string_agg
------------
  3,1,4
  1,3
(2 rows)
```

# まとめ
Window関数のFILTER句について解説しました。FILTER句は入力行をフィルタするときに使用しますが、あくまでの「集約関数に値を渡すかどうか」を影響し、返却される行数等には関連しません。これは、[以前に投稿した記事]({% post_url 2018-07-04-Basics-of-Window-Function %})にも記載した以下の記載を思い出します。

> > SQL において、窓関数もしくはウィンドウ関数 (英: window function) は結果セットを部分的に切り出した領域に集約関数を適用できる、拡張された SELECT ステートメントである。
>
>一見`GROUP BY`句に似ていますが、Window関数はあくまでも関数なので返却される行数には影響しません。

「入力値をフィルタしたい」という場合に、WHERE句で行うのかFILTER句で行うのかは最初は少し悩みますが、まずはSQL全体での計算量を減らすために、WHERE句でのフィルタリングを検討するのが良いと思います。そして、Window関数にて固有の絞り込み条件が必要なときにFILTER句の利用を検討する、という感じで利用していくのはいかがでしょうか。

明日は[yancha](https://qiita.com/yancya)さんの登場です。お楽しみに！

lang: jp
---

これまでにまとめたWindow関数の記事もあわせてどうぞ。

{% assign posts_list = site.posts | sort: 'date', 'last' %}
{% for post in posts_list %}
	{% if post.title contains 'Window' and post.title != page.title %}
* [{{ post.title }} ({{post.date | date: "%Y/%m/%d"}})]({{ post.url }})
	{% endif %}
{% endfor %}

