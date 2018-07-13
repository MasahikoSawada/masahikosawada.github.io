---
layout: post
title: Window関数のフレームを極める
tags:
  - PostgreSQL
  - Window Function
---

Window関数のパーティションは`PARTITION BY`句で指定するだけなのですが、フレームについては色々モードやオプションがあり細かく指定できます。
フレーム指定は一見難しそうに見えますが、一回理解すると自由自在にWindow関数が使えるようになると思います。MySQL 8.0でもWindow関数が導入されてますます需要が利用頻度が増えた今、少し時間はかかるかもしれませんがちゃんと理解しておくと便利です。

Window関数のシンタックスは以下のようになっています。[^syntax] [^syntax2]

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

フレームの指定は、`RANGE`、`ROWS`、`GROUPS`の中から一つモードを選び、その後にフレームの境界を指定します。*frame_start*だけを指定した場合は、*frame_end*は`CURRENT ROW`になります。
今回は、*frame_clause*と*frame_start*、*frame_end*について説明し、*frame_exclusion*についてはまた別途解説しようと思います。

# モードの種類

今年リリース予定のPostgreSQL 11では、フレーム指定のモードが3種類使えます。

* `ROWS`モード
  * SQL:2003の新機能
  * PostgreSQL 11以前でも使える
  * MySQL 8.0でも使える
* `RANGE`モード
  * SQL:2003の新機能
  * PostgreSQL 11以前でも使える
  * MySQL 8.0でも使える
* `GROUPS`モード
  * SQL:2011の新機能[^sql2011]
  * PostgreSQL 11で導入された新入り
  * `GROUPS`モードを実装しているのは今の所PostgreSQL 11だけのよう[^groups]

[^groups]: https://modern-sql.com/blog/2018-04/mysql-8.0
[^sql2011]: https://sigmodrecord.org/publications/sigmodRecord/1203/pdfs/10.industry.zemke.pdf

各フレームオプションの意味や、モードによってどのように挙動が異なるかを解説します。

# UBOUNDED PRECEDING, UNBOUNDED FOLLOWING
この2つのフレームオプションはモードに関係なく動作します。

`UNBOUNDED PRECEDING`を指定すると、フレーム開始とパーティション開始が一致し、`UNBOUNDED FOLLOWING`を指定するとフレーム終了とパーティション終了が一致します。

```
=# SELECT *,
	string_agg(c, ',') OVER (
		PARTITION BY color
		ORDER BY c
		ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
		)
	FROM w;

 color | c |  string_agg
-------+---+---------------
 red   | a | a,b,b,c,c,d,e
 red   | b | a,b,b,c,c,d,e
 red   | b | a,b,b,c,c,d,e
 red   | c | a,b,b,c,c,d,e
 red   | c | a,b,b,c,c,d,e
 red   | d | a,b,b,c,c,d,e
 red   | e | a,b,b,c,c,d,e
(7 rows)
```

上記のように指定すると、フレームは常に(`color`列で分割している)パーティションと一致します。そのため、`string_agg()`関数の処理対象は常にパーティション全体となるので、パーティション内での結果が同じになります。これは簡単。
上記の例では`ROWS`モードにしましたが、他のモードでもを変えても結果は同じです。

# CURRNET ROW
`CURRENT ROW`はその意味の通り、「現在の行」をフレーム開始またはフレーム終了に指定しますが、`RANGE`、`GROUPS`、`ROWS`のそれぞれのモードで"現在の行"の判定が変わります。

## ROWSモード
ROWSモードでの`CURRENT ROW`の考え方は非常に単純で、その名の通り「現在の行」がCURRENT ROWになります。

**※わかりやすくするためにcolor列の'red'を'red(1)','red(2)'...に分けています。**

```
=# SELECT *,
	sum(value) OVER (
		PARTITION BY color
		ORDER BY value
		ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
		)
	FROM w;

---------------------------
 color | c |  string_agg
-------+---+---------------  =    =    =    =     <---- フレームの始まり(UNBOUNDED PRECEDING)
 red(1)| a | a,              |(1) |    |    |
-------+---+---------------  =    |(2) |    |     <---- 現在の行='red(1)'の時のフレームの終わり(CURRENT ROW)
 red(2)| b | a,b                  |    |(3) |
-------+---+---------------       =    |    |(4)  <---- 現在の行='red(2)'の時のフレームの終わり(CURRENT ROW)
 red(3)| b | a,b,b                     |    |
-------+---+---------------            =    |     <---- 現在の行='red(3)'の時のフレームの終わり(CURRENT ROW)
 red(4)| c | a,b,b,c                        |
-------+---+---------------                 =     <---- 現在の行='red(4)'の時のフレームの終わり(CURRENT ROW)
 red(5)| c | a,b,b,c,c
-------+---+---------------                         :
 red(6)| d | a,b,b,c,c,d                            : 以下の同じように続く
-------+---+---------------                         :
 red(7)| e | a,b,b,c,c,d,e
---------------------------
(7 rows)
```

全ての行がフレーム境界になるので、上記のように、現在行が進むに連れてフレームは行が進む毎に広がっていき、`string_agg()`の処理対象も広がっていきます。

## RANGE, GROUPSモード
この2つのモードは、`CURRENT ROW`を使う上では実質同じ挙動をするので、まとめて解説します。

`RANGE`、`GROUPS`モードでは、フレーム開始に`CURRENT ROW`を指定した場合は**一致する行のグループの先頭**、フレーム終了に`CURRENT ROW`を指定した場合は**一致するグループの末尾**になります。

```
=# SELECT *,
	sum(value) OVER (
		PARTITION BY color
		ORDER BY value
		GROUPS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
		)
	FROM w;
---------------------------
 color | c |  string_agg
-------+---+---------------  =    =    =    =     <---- フレームの始まり(UNBOUNDED PRECEDING)
 red(1)| a | a,              |    |    |    |
-------+---+---------------  |    |    |    |
 red(2)| b | a,b,b           |(1) |(2) |    |
-------+---+---------------  |    |    |(3) |(4)
 red(3)| b | a,b,b           |    |    |    |
-------+---+---------------  =    =    |    |    <---- 現在の行='red(1), red(2)'の時のフレームの終わり(CURRENT ROW)
 red(4)| c | a,b,b,c,c                 |    |
-------+---+---------------            |    |
 red(5)| c | a,b,b,c,c                 |    |
-------+---+---------------            =    =    <---- 現在の行='red(3), red(4)'の時のフレームの終わり(CURRENT ROW)
 red(6)| d | a,b,b,c,c,d
-------+---+---------------                         : 以下の同じように続く
 red(7)| e | a,b,b,c,c,d,e                          :
---------------------------
(7 rows)
```

`RANGE`、`GROUPS`モードでの`CURRENT ROW`は、同じ値も含めたグループが`CURRENT ROW`としてみなされます。上記の例では、`blue(1)`と`blue(2)`は共にvalue = 130で、フレーム終点に`CURRENT_ROW`を指定しているので、`blue(1)`、`blue(2)`の時のフレーム(1)と(2)は同じフレームになります。

# offset PRECEDING and offset FOLLOWING
`offset PRECEDING/FOLLOWING`は、フレーム境界を現在の行の**位置や値**を基準に`offset`分だけ後ろ、または前のデータをフレームに加えます。各モードでの基本的な考え方はこれまで解説したものとにています。

* ROWSモード
  - 現在の行の**位置**を基準に、offset分だけ後ろ/前をフレームに含める
* GROUPSモード
  - **同一の行をひとまとまりにしたグループ**を基準に、offset分だけ後ろ/前をフレームに含める
* RANGEモード
  - 現在の行の**値**を基準に、offset分だけ後ろ/前をフレームに含める

## ROWSモード

ROWSモードはその名の通り、行をベースにしてオフセットを指定します。

```
=# SELECT *,
	string_agg(c, ',') OVER (
		PARTITION BY color
		ORDER BY c
		ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING
		)
	FROM w;

--------------------------
 color | c |  string_agg    1  2
-------+---+--------------  =  =
 red(1)| a | a,b            |  |  3
-------+---+--------------  -  -  =
 red(2)| b | a,b,b          |  |  |  4
-------+---+--------------  =  -  -  =
 red(3)| b | b,b,c             |  |  |  5
-------+---+--------------     =  -  -  =
 red(4)| c | b,c,c                |  |  |  6
-------+---+--------------        =  -  -  =
 red(5)| c | c.c,d                   |  |  |  7
 -------+---+-------------           =  -  -  =
 red(6)| d | c,d,e                      |  |  |
-------+---+--------------              =  -  -
 red(7)| e | d,e                           |  |
--------------------------                 =  =
(7 rows)
```
※フレーム境界を簡易的に表しています。`-`がグループの境界で、`=`がフレームの境界です。上に付いている番号は同じ番号の行に対応するフレームを表しています。

フレームオプションが、`ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING`なので、「1つ前の行～1つ後ろの行」までをフレームに含めます。

## GROUPSモード
`GROUPS`モードでは、同一行を一つのグループとみなして、オフセットの指定も「1つ前のグループ」「2つ後のグループ」の用にグループが境界となります。

```
=# SELECT *,
	string_agg(c, ',') OVER (
		PARTITION BY color
		ORDER BY c
		GROUPS BETWEEN 1 PRECEDING AND 1 FOLLOWING
		)
	FROM w;

--------------------------
 color | c |  string_agg    1  2  3
-------+---+--------------  =  =  =
 red(1)| a | a,b,b          |  |  |  4  5
-------+---+--------------  -  -  -  =  =
 red(2)| b | a,b,b,c,c      |  |  |  |  |
-------+---+--------------  |  |  |  |  |
 red(3)| b | a,b,b,c,c      |  |  |  |  |  6
-------+---+--------------  =  -  -  -  -  =
 red(4)| c | b,b,c,c,d         |  |  |  |  |
-------+---+--------------     |  |  |  |  |
 red(5)| c | b,b,c.c,d         |  |  |  |  |  7
 -------+---+-------------     =  =  -  -  -  =
 red(6)| d | c,c,d,e                 |  |  |  |
-------+---+--------------           =  =  -  -
 red(7)| e | d,e                           |  |
--------------------------                 =  =
(7 rows)
```
※フレーム境界を簡易的に表しています。`-`がグループの境界で、`=`がフレームの境界です。上に付いている番号は同じ番号の行に対応するフレームを表しています。

一見複雑でわかりにくいですが、どのフレームも3つのグループ（一つ前、現在、一つ後）を含んでいることがわかります。

## RANGEモード
`RANGE`モードでは、**行の値**をオフセットとして指定します。ここまではTEXT型の列で解説しましたが、ここではDate型の列で解説します。(TEXT型列ではオフセットを指定できません)

`RANGE`モードでのオフセット指定はSQL:2003の新機能ですが、PostgreSQL 10以前ではサポートされていません。PostgreSQL 11からはサポートされています。

```
=# SELECT *,
	string_agg(c::text, ',') OVER (
		PARTITION BY color
		ORDER BY c
		RANGE BETWEEN '5 day' PRECEDING AND '5 day' FOLLOWING
		)
	FROM ww;

 color |     c      |                 string_agg
-------+------------+---------------------------------------------
 red   | 2018-07-01 | 2018-07-01,2018-07-02,2018-07-05
 red   | 2018-07-02 | 2018-07-01,2018-07-02,2018-07-05
 red   | 2018-07-05 | 2018-07-01,2018-07-02,2018-07-05,2018-07-10
 red   | 2018-07-10 | 2018-07-05,2018-07-10,2018-07-15
 red   | 2018-07-15 | 2018-07-10,2018-07-15
 red   | 2018-07-30 | 2018-07-30
(6 rows)
```
上記の例では、`c`列をDate型にしたので、オフセットの指定を` '5 day' PRECEDING AND '5 day' FOLLOWING`にしました。これは、フレーム境界を「現在の５日前〜現在の５日後」に指定しています。`string_agg`関数の結果を見てみると、そのようになっていることがわかります。

# まとめ
フレームの指定、モードについて解説しました。今回解説した内容で、Window関数を使うほとんどの用途はカバーできると思います。この他にも`frame_exclusion`と呼ばれるオプションもあるので、それはまた別途解説しようと思います。

---

これまでにまとめた記事もあわせてどうぞ。

{% assign posts_list = site.posts | sort: 'date', 'last' %}
{% for post in posts_list %}
	{% if post.title contains 'Window' and post.title != page.title %}
* [{{ post.title }} ({{post.date | date: "%Y/%m/%d"}})]({{ post.url }})
	{% endif %}
{% endfor %}
