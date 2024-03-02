---
layout: post
title: シーケンシャル・スキャンだからといってデータがテーブルの先頭から返ってくるとは限らない、という話
tags:
  - PostgreSQL
lang: jp
---

この記事は[PostgreSQL Advent Calendar 2020](https://qiita.com/advent-calendar/2020/postgresql)の23日目の記事です。昨日は、[@hiro5963](https://qiita.com/hiro5963)さんによる「[pg_repackについて調べてみた](https://qiita.com/hiro5963/items/79e1f9c7db0362411793)」でした。

シーケンシャルスキャン（逐次スキャン、Seq Scan）は「テーブルを先頭からスキャンしていきデータ（行）を返す）」というイメージがありますが、PostgreSQLでは必ずしもそうとは限りません。本記事ではそれを実験してみます。

まずはテーブルを作成します。

```sql
create table test as select generate_serires(1, 10000000) id;
```

`test`テーブルには1000万件のデータが入りました。この時、これらのデータはテーブルの先頭から順番に1~10,000,000のデータが格納されています。


# 返ってくるデータの順番を確認するための準備

`select * from test`で返ってきた行を見れば、どのような順番でSeq Scanが行を取り出したのかがわかるのですが、返ってくる行が大量で確認しづらいので、以下のような集約関数を作成します。

```sql
create or replace function int4streamchk_accum(s text[], i int) returns text[] as
$$
declare cur int;
begin
        if s is null then
           return array[i::text, i::text];
        end if;

        cur := s[2]::int;
        if i = (cur + 1) then
           s[2] := (cur + 1)::int;
        else
           s[1] := s[1] || '-' || cur::text || ' ' || i::text;
           s[2] := i::text;
        end if;
        return s;
end;
$$ language plpgsql;

create or replace function int4streamchk_final(s text[]) returns text as
$$
declare ret text;
begin
        ret := s[1] || '-' || s[2];
        return ret;
end;
$$ language plpgsql;

create or replace aggregate streamchk (int)
	(sfunc = int4streamchk_accum,
	finalfunc = int4streamchk_final,
	stype = text[],
	parallel = safe);
```

上記で作成した`streamchk()`関数を使用すると、どのような順番でデータが処理されたかを簡単に確認できます。少し試してみます。

連続する数値を処理した場合は`1-6`のように、最小値と最大値だけを残した形で出力されます：

```sql
=# with vals(v) as (values (1), (2), (3), (4), (5), (6))
-# select streamchk(v) from vals;
 streamchk
-----------
 1-6
(1 row)
```

連続していない数値を処理した場合は、`5-7 1-3`のように省略した形がスペース区切りで繋がって出力されます：

```sql
=# with vals(v) as (values (5), (6), (7), (1), (2), (3), (10), (11))
-# select streamchk(v) from vals;
   streamchk
---------------
 5-7 1-3 10-11
(1 row)
```

# 格納順で行が返ってくるケース

早速、先程作成したテーブルに使ってみます。

```sql
=# select streamchk(id) from test;
 streamchk
------------
 1-10000000
(1 row)

```

結果が`1-100000`ということは、1から100000まで順番にデータを処理したということになります。これは予想通りですね。では、Seq Scanをしているのに順番に返ってこない場合を見てみます。

# パラレルクエリが使われた場合は返ってくる行の順番はランダム

`Parallel Seq Scan`が使われた場合、各パラレルワーカーが並列にスキャンし、行を返却するので、格納順に行は返ってきません。

```sql
=# set parallel_tuple_cost to 0;
SET
=# select streamchk(id) from test;
                       streamchk
--------------------------------------------------------
 1-1394 7233-14464 21697-10000000 14465-21696 1395-7232
(1 row)
```

行がバラバラに返ってきてたことがわかります。

最後に、パラレルクエリを使わなくても行がテーブルの先頭から返ってこないケースを見てみます。

# Seq Scanはテーブルの途中からスキャンを開始する

PostgreSQLでは、Seq Scan開始時にすでに同じテーブルに対するSeq Scanが走っている場合、テーブルの途中からSeq Scanを開始します。これは、すでに走っているSeq Scanが読んでいるデータはメモリ上にある可能性が高く、再度テーブルの先頭からスキャンを始めていくよりも効率的になるからです。2つのSeq Scanを時間差で開始し、結果を見てみます。

```bash
$ psql -d postgres -c "select '1st seq scan', streamchk(id) from test;" &
$ sleep 5
$ psql -d postgres -c "select '2nd seq scan', streamchk(id) from test;"

   ?column?   | streamchk
--------------+------------
 1st seq scan | 1-10000000
(1 row)

   ?column?   |         streamchk
--------------+----------------------------
 2nd seq scan | 1569345-10000000 1-1569344
(1 row)

```

最初のSeq Scanはテーブルの先頭からスキャンを開始し、その5秒後に開始した2つ目のSeq Scanはテーブルの途中からSeq Scanを始めたことがわかります。

このように、（テーブルが全く変更されておらず）Seq Scanをする場合でも、スキャンがテーブルの途中から始まる可能性があるので、`ORDER BY`をつけないクエリが返す行の順序は基本的に予測できません。必ず`ORDER BY`をつけるようにしましょう。

# おまけ

この機能は**synchronize seq scan**と呼ばれていて、`SET synchronize_seqscans = off`とすることで無効にすることが可能です。

このオプションはバージョン8.3以前の動作との互換性を保つためにあるものなので、実際にoffにすることはないと思います。
