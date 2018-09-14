---
layout: post
title: Window関数のフレームを極める(EXCLUDEオプション編)
description: Window関数のフレームのEXCLUDEオプションを徹底解説
tags:
  - PostgreSQL
  - Window Function
---

[前回の記事]({% post_url 2018-07-07-Window-Frame %})では飛ばした、Window関数のEXCLUDEオプションについて解説します。

Window関数のシンタックスを改めて確認します。[^syntax] [^syntax2]

[^syntax]: PostgreSQLのシンタックスです。MySQLでも大体同じですが、`ORDER BY`句の指定は異なります。
[^syntax2]: MySQLでは、frame_endを省略した文法はありません

```
window_function:
[ existing_window_name ]
[ PARTITION BY expression [, ...] ]
[ ORDER BY expression [ ASC | DESC | USING operator ] [ NULLS { FIRST | LAST } ] [, ...] ]
[ frame_clause ]

frame_clause:
{ RANGE | ROWS | GROUPS } frame_start [ frame_exclusion ]
{ RANGE | ROWS | GROUPS } BETWEEN frame_start AND frame_end [ frame_exclusion ]

frame_start and frame_end:
{
	UNBOUNDED PRECEDING |
	offset PRECEDING |
	CURRENT ROW |
	offset FOLLOWING |
	UNBOUNDED FOLLOWING
}

frame_exclusion:
{
	EXCLUDE CURRENT ROW |
	EXCLUDE GROUP |
	EXCLUDE TIES |
	EXCLUDE NO OTHERS
}
```

今回の範囲は、`frame_exclusion`の部分です。PostgreSQLでは、`EXCLUDE`オプションはPostgreSQL 11から使えるようになります。

# EXCLUDEオプションの種類

EXCLUDESオプションは全部で4つあります。デフォルトは、`EXCLUDE NO OTHERS`です。

* `EXCLUDE NO OTHERS`
  * 何も除外しない（デフォルト）
* `EXCLUDE CURENT ROW`
  * 現在行を除外する
* `EXCLUDE GROUP`
  * 現在行が含まれるグループを除外する
* `EXCLUDE TIES`
  * 現在行が含まれるグループの中で**現在行以外**を除外する

**行**や**グループ**の考え方は、これまでの記事を見ていただければ理解できると思います。

# EXCLUDESオプションの違いを確認する

EXCLUDESオプションを変えながら挙動の違いを見ていきます。以下の例では、フレームは`GROUPS`モードで`UNBOUNDED PRECEDING AND CURRENT ROW`です。テーブル全体が一つのパーティションとなり、フレームは少しずつ広がっていくように動作します。

## `EXCLUDE NO OTHERS`

まずは`EXCLUDE NO OTHERS`を指定します。

```sql
=# SELECT *,
	string_agg(v, ',') OVER (
		PARTITION BY color
		ORDER BY v
		GROUPS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
		EXCLUDE NO OTHERS
	)
	FROM t;

 color | v |   string_agg
-------+---+-----------------
 red   | a | a
 red   | b | a,b,b
 red   | b | a,b,b
 red   | c | a,b,b,c
 red   | d | a,b,b,c,d,d,d
 red   | d | a,b,b,c,d,d,d
 red   | d | a,b,b,c,d,d,d
 red   | e | a,b,b,c,d,d,d,e
(8 rows)
```

デフォルトの動作なのでこれまでと同じです。

## `EXCLUDE CURRENT ROW`

次は`EXCLUDE CURRENT ROW`を指定します。このオプションは、現在行を除外します。

```sql
=# SELECT *,
	string_agg(v, ',') OVER (
		PARTITION BY color
		ORDER BY v
		GROUPS BETWEEN UNBOUNDED PRECEDING AND 1 FOLLOWING
		EXCLUDE CURRENT ROW
	)
	FROM t;

 color | v |  string_agg
-------+---+---------------
 red   | a |
 red   | b | a,b
 red   | b | a,b
 red   | c | a,b,b
 red   | d | a,b,b,c,d,d
 red   | d | a,b,b,c,d,d
 red   | d | a,b,b,c,d,d
 red   | e | a,b,b,c,d,d,d
(8 rows)
```

`EXCLUDE CURRENT ROW`では現在行を除外するため、各集約結果で自分自身の値が入っていないことがわかります。（例えば、`v = 'a'`の行では、`'a'`が入っていない。）

## `EXCLUDE GROUP`

次は、`EXCLUDE GROUP`です。このオプションでは、現在行を含むグループ（同じ行の集まり）が除外されます。

```sql
=# SELECT *,
	string_agg(v, ',') OVER (
		PARTITION BY color
		ORDER BY v
		GROUPS BETWEEN UNBOUNDED PRECEDING AND 1 FOLLOWING
		EXCLUDE GROUP
	)
	FROM t;

 color | v |  string_agg
-------+---+---------------
 red   | a |
 red   | b | a
 red   | b | a
 red   | c | a,b,b
 red   | d | a,b,b,c
 red   | d | a,b,b,c
 red   | d | a,b,b,c
 red   | e | a,b,b,c,d,d,d
(8 rows)

```

`EXCLUDE GROUP`では、同じグループ（同じ値の行）を除くので、各集約結果で自分の**グループ**が入っていないことがわかります。（例えば、`v = 'b'`では、`'b'`が2つとも入っていない)

## `EXCLUDE TIES`

最後は、`EXCLUDE TIES`です。このオプションでは、`EXCLUDE GROUP`に似ていますが、除外するのは**現在の行以外のグループ中の行**です。

```sql
=# SELECT *,
	string_agg(v, ',') OVER (
		PARTITION BY color
		ORDER BY v
		GROUPS BETWEEN UNBOUNDED PRECEDING AND 1 FOLLOWING
		EXCLUDE TIES
	)
	FROM t;

 color | v |   string_agg
-------+---+-----------------
 red   | a | a
 red   | b | a,b
 red   | b | a,b
 red   | c | a,b,b,c
 red   | d | a,b,b,c,d
 red   | d | a,b,b,c,d
 red   | d | a,b,b,c,d
 red   | e | a,b,b,c,d,d,d,e
(8 rows)
```

ちょっとわかりにくいですが、例えば`v = 'd'`の時、フレームには`'b'`が3つ入りますが、現在行以外の2つの`'b'`が除外されているため、`'b'`が1つしかありません。

# まとめ
今回はEXCLUDEオプションについて解説しました。これまでの記事等でフレームが理解できていれば、簡単に理解できると思います。これでフレームに関するオプションは全部解説したので、マスターできれば自由自在にWindow関数を使うことができるようになるはずです。

---

これまでにまとめた記事もあわせてどうぞ。

{% assign posts_list = site.posts | sort: 'date', 'last' %}
{% for post in posts_list %}
	{% if post.title contains 'Window' and post.title != page.title %}
* [{{ post.title }} ({{post.date | date: "%Y/%m/%d"}})]({{ post.url }})
	{% endif %}
{% endfor %}

