---
layout: post
title: Window関数のフレームを極める
tags:
  - PostgreSQL
  - Window Function
---

[前回]()は、Window関数を理解する上で大切なパーティションやフレームの概念について説明しました。

パーティションは、`PARTITION BY`句で指定するだけなのですが、フレームについては色々モードやオプションがあり細かく指定できます。
[PostgreSQLの公式マニュアル]だけでは、わかりづらいところもあるためその辺りを解説していきます。

# Window関数のシンタックス

PostgreSQLのWindow関数のシンタックスは以下のようになっています。


```
[ existing_window_name ]
[ PARTITION BY expression [, ...] ]
[ ORDER BY expression [ ASC | DESC | USING operator ] [ NULLS { FIRST | LAST } ] [, ...] ]
[ frame_clause ]
```

```
frame_clause: 
{ RANGE | ROWS | GROUPS } frame_start [ frame_exclusion ]
{ RANGE | ROWS | GROUPS } BETWEEN frame_start AND frame_end [ frame_exclusion ]
```

```
frame_start and frame_end:
{
	UNBOUNDED PRECEDING |
	offset PRECEDING |
	CURRENT ROW |
	offset FOLLOWING |
	UNBOUNDED FOLLOWING |
}
```

フレームの指定は、`RANGE`、`ROWS`、`GROUPS`の中から一つモードを選び、その後にフレームの境界を指定します。*frame_start*だけを指定した場合は、*frame_end*は`CURRENT ROW`になります。

今回は、*frame_clause*と*frame_start*、*frame_end*について説明して、*frame_exclusion*についてはまた別途解説しようと思います。

各フレームオプションの意味や、モードによってどのように挙動が異なるかを解説します。

# UBOUNDED PRECEDING, UNBOUNDED FOLLOWING
この2つのフレームオプションはモードに関係なく動作します。

`UNBOUNDED PRECEDING`を指定すると、フレーム開始とパーティション開始が一致し、`UNBOUNDED FOLLOWING`を指定するとフレーム終了とパーティション終了が一致します。

```sql
=# SELECT *,
	sum(value) OVER (
		PARTITION BY color
		ORDER BY value
		ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
		)
	FROM w;
 color | id | value | sum
-------+----+-------+-----
 blue  |  1 |   130 | 500
 blue  |  3 |   130 | 500
 blue  |  2 |   240 | 500
 red   |  3 |   120 | 660
 red   |  1 |   200 | 660
 red   |  2 |   340 | 660
(6 rows)
```

フレームは常に(`color`列で分割している)パーティションと一致します。そのため、`sum()`関数の処理対象は常にパーティション全体となるので、パーティション内での結果が同じになります。これは簡単。

上記の例では`ROWS`モードにしましたが、他のモードでもを変えても結果は同じです。
 
# CURRNET ROW
`CURRENT ROW`はその意味の通り、「現在の行」をフレーム開始またはフレーム終了に指定しますが、`RANGE`、`GROUPS`、`ROWS`のそれぞれのモードで"現在の行"の判定が変わります。
	   
## ROWSモード
ROWSモードでの`CURRENT ROW`の考え方は非常に単純で、その名の通り「現在の行」がCURRENT ROWになります。
'blue'のパーティションに注目してフレームの動きを見てみます。

**※わかりやすくするためにcolor列の'blue'を'blue(1)','blue(2)','blue(3)'に分けています。**

```sql
=# SELECT *,
	sum(value) OVER (
		PARTITION BY color
		ORDER BY value
		GROUPS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
		)
	FROM w;
---------------------------
 color  | id | value | sum
--------+----+-------+-----  =    =    =     <---- フレームの始まり(UNBOUNDED PRECEDING)
 blue(1)|  1 |  130  | 130   |(1) |    |
--------+----+-------+-----  =    |(2) |     <---- 現在の行='blue(1)'の時のフレームの終わり(CURRENT ROW)
 blue(2)|  3 |  130  | 260        |    |(3)
--------+----+-------+-----       =    |     <---- 現在の行='blue(2)'の時のフレームの終わり(CURRENT ROW)
 blue(3)|  2 |  240  | 500             |
--------+----+-------+-----            =     <---- 現在の行='blue(3)'の時のフレームの終わり(CURRENT ROW)
 red    |  3 |  120  | 120
--------+----+-------+-----
 red    |  1 |  200  | 320
--------+----+-------+-----
 red    |  2 |  340  | 660
---------------------------
(6 rows)
```

上記のように、現在行が進むに連れてフレームは行が進む毎に広がっていき、sum()の処理対象も広がっていきます。

## RANGE, GROUPSモード
この2つのモードは、`CURRENT ROW`を使う上では同じ挙動をするので、まとめて解説します。

`RANGE`、`GROUPS`モードでは、フレーム開始に`CURRENT ROW`を指定した場合は**一致する行のグループの先頭**、フレーム終了に`CURRENT ROW`を指定した場合は**一致するグループの末尾**になります。
`ROWS`モードの違いは、**同じ値の行をCURRENT ROWとして認識するかどうか**の違いです。

具体的に、'blue'のパーティションに注目してフレームの動きを見てみます。

```sql
=# SELECT *,
	sum(value) OVER (
		PARTITION BY color
		ORDER BY value
		GROUPS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
		)
	FROM w;
---------------------------
 color  | id | value | sum
--------+----+-------+-----  =    =    =     <---- フレームの始まり(UNBOUNDED PRECEDING)
 blue(1)|  1 |  130  | 260   |    |    |
--------+----+-------+-----  |(1) |(2) |
 blue(2)|  3 |  130  | 260   |    |    |(3)
--------+----+-------+-----  =    =    |     <---- 現在の行='blue(1)'と'blue(2)'の時のフレームの終わり(CURRENT ROW)
 blue(3)|  2 |  240  | 500             |
--------+----+-------+-----            =     <---- 現在の行='blue(3)'の時のフレームの終わり(CURRENT ROW)
 red    |  3 |  120  | 120
--------+----+-------+-----
 red    |  1 |  200  | 320
--------+----+-------+-----
 red    |  2 |  340  | 660
---------------------------
(6 rows)
```

`RANGE`、`GROUPS`モードでの`CURRENT ROW`は、同じ値も含めたグループが`CURRENT ROW`としてみなされます。上記の例では、`blue(1)`と`blue(2)`は共にvalue = 130で、フレーム終点に`CURRENT_ROW`を指定しているので、`blue(1)`、`blue(2)`の時のフレーム(1)と(2)は同じフレームになります。
	 
# offset PRECEDING and offset FOLLOWING
`offset PRECEDING/FOLLOWING`は、フレーム境界を現在の行の**位置や値**を基準に`offset`分だけ後ろ、または前のデータをフレームに加えます。簡単に違いをまとめると次のようになります。

* ROWSモード
  - 現在の行の**位置**を基準に、offset分だけ後ろ/前をフレームに含める
* GROUPSモード
  - ROWSモードと同様に、現在の行の**位置**を基準に、offset分だけ後ろ/前をフレームに含める。ただし、同一行がある場合はそれも含める
  - CURRENT ROWの説明したRANGE, GROUPSモードと同じような挙動
* RANGEモード
  - 現在の行の**値**を基準に、offset分だけ後ろ/前をフレームに含める
		
## ROWSモード
ROWSモードは単純でわかりやすいので例を見たほうが早いと思います。

```sql
=# SELECT *,
	sum(value) OVER (
		PARTITION BY color
		ORDER BY value
		ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING
		)
	FROM w;
---------------------------
 color  | id | value | sum
--------+----+-------+-----
 blue   |  1 |  130  | 500 
--------+----+-------+-----
 blue   |  3 |  130  | 500 
--------+----+-------+-----
 blue   |  2 |  240  | 370 
--------+----+-------+-----  =    =
 red(1) |  3 |  120  | 240   |    |
--------+----+-------+-----  |(1) |    =
 red(2) |  3 |  120  | 440   |    |(2) |
--------+----+-------+-----  =    |    |    =
 red(3) |  1 |  200  | 660        |    |(3) |
--------+----+-------+-----       =    |    | (4)
 red(4) |  2 |  340  | 540             |    |
---------------------------            =    =
(6 rows)
```
フレームオプションが、`ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING`なので、「1つ前の行～1つ後ろの行」までをフレームに含めます。

## GROUPSモード

```sql
=# SELECT *,
	sum(value) OVER (
		PARTITION BY color
		ORDER BY value
		ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING
		)
	FROM w;
---------------------------
 color  | id | value | sum
--------+----+-------+-----
 blue   |  1 |  130  | 500 
--------+----+-------+-----
 blue   |  3 |  130  | 500 
--------+----+-------+-----
 blue   |  2 |  240  | 370 
--------+----+-------+-----  =    =
 red(1) |  3 |  120  | 440   |    |
--------+----+-------+-----  |    |    =
 red(2) |  3 |  120  | 440   |(1) |(2) |
--------+----+-------+-----  |    |    |    =
 red(3) |  1 |  200  | 780   |    |    |(3) |
--------+----+-------+-----  =    =    |    | (4)
 red(4) |  2 |  340  | 540             |    |
---------------------------            =    =
(6 rows)
```

## RANGEモード
		
ORDER BYが必要
		
		
