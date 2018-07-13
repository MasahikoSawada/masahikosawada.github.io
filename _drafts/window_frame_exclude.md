---
layout: post
title: Window関数のフレームを極める(EXCLUDEオプション)
tags:
  - PostgreSQL
  - Window Function
---

[前回]()飛ばした、Window関数のEXCLUDEオプションについて解説します。

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

今回の範囲は、`frame_exclusion`の部分です。
PostgreSQLでは、`EXCLUDE`オプションはPostgreSQL 11から使えるようになります。

# EXCLUDEオプションの種類

EXCLUDESオプションは全部で4つあります。デフォルトは、`EXCLUDE NO OTHERS`です。

* `EXCLUDE NO OTHERS`
  * 何も除外しない（デフォルト）
* `EXCLUDE CURENT ROW`
  * 現在行を除外する
* `EXCLUDE GROUP`
  * 現在行が含まれるグループを除外する
* `EXCLUDE TIES`
  * 現在行が含まれれるグループの中で**現在行以外**を除外する

**行**や**グループ**の考え方は、これまでの記事を見ていただければ理解できると思います。

# EXCLUDESオプションの違いを確認する

EXCLUDESオプションを変えながら挙動の違いを見ていきます。フレームは`UNBOUNDED PRECEDING AND 1 FOLLOWING`です。テーブル全体が一つのパーティションとなり、フレームは少しずつ広がっていきます。

## `EXCLUDE NO OTHERS`

まずはデフォルトでもある、`EXCLUDE NO OTHERS`を指定します。

```sql
=# SELECT *,
	string_agg(v, ',') OVER (
		PARTITION BY color
		ORDER BY v
		GROUPS BETWEEN UNBOUNDED PRECEDING AND 1 FOLLOWING
	)
	FROM t;

 color | v |   string_agg
-------+---+-----------------
 red   | a | a,b,b
 red   | b | a,b,b,c
 red   | b | a,b,b,c
 red   | c | a,b,b,c,d,d,d
 red   | d | a,b,b,c,d,d,d,e
 red   | d | a,b,b,c,d,d,d,e
 red   | d | a,b,b,c,d,d,d,e
 red   | e | a,b,b,c,d,d,d,e
(8 rows)
```

デフォルトの動作なので、これまでと同じです。

## `EXCLUDE CURRENT ROW`

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
 red   | a | b,b
 red   | b | a,b,c
 red   | b | a,b,c
 red   | c | a,b,b,d,d,d
 red   | d | a,b,b,c,d,d,e
 red   | d | a,b,b,c,d,d,e
 red   | d | a,b,b,c,d,d,e
 red   | e | a,b,b,c,d,d,d
(8 rows)

```

`EXCLUDE CURRENT ROW`では現在行を除外するため、各集約結果で自分自身の値が入っていないことがわかります。（例えば、`v = 'a'`の行では、'a'が入っていない。）

## `EXCLUDE GROUP`

次は、`EXCLUDE GROUP`です。フレームの指定モードは`ROWS`にしている所に注意です。

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
 red   | a | b,b
 red   | b | a,c
 red   | b | a,c
 red   | c | a,b,b,d,d,d
 red   | d | a,b,b,c,e
 red   | d | a,b,b,c,e
 red   | d | a,b,b,c,e
 red   | e | a,b,b,c,d,d,d
(8 rows)

```

`EXCLUDE GROUP`では、同じグループ（同じ値の行）を除くので、各集約結果で自分の**グループ**が入っていないことがわかります。（例えば、v = 'b'では、'b'が2つとも入っていない)

## `EXCLUDE TIES`

最後は、`EXCLUDE TIES`です。

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
 red   | a | a,b,b
 red   | b | a,b,c
 red   | b | a,b,c
 red   | c | a,b,b,c,d,d,d
 red   | d | a,b,b,c,d,e
 red   | d | a,b,b,c,d,e
 red   | d | a,b,b,c,d,e
 red   | e | a,b,b,c,d,d,d,e
(8 rows)
```
