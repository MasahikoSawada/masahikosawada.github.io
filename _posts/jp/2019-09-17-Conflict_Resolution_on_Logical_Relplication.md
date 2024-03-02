---
layout: post
title: ロジカルレプリケーションのレプリケーション衝突を解決する
tags:
  - PostgreSQL
  - Replication
  - Logical Replication
  - Conflict Resolution
lang: jp
---

今回解決したいのは、以下で説明されているような事象。

<iframe src="//www.slideshare.net/slideshow/embed_code/key/zvqa8VssBx2T8i?startSlide=53" width="595" height="485" frameborder="0" marginwidth="0" marginheight="0" scrolling="no" style="border:1px solid #CCC; border-width:1px; margin-bottom:5px; max-width: 100%;" allowfullscreen> </iframe> <div style="margin-bottom:5px"> <strong> <a href="//www.slideshare.net/AtsushiTorikoshi/architecture-pitfalls-of-logical-replication" title="Architecture &amp; Pitfalls of Logical Replication" target="_blank">Architecture &amp; Pitfalls of Logical Replication</a> </strong> from <strong><a href="//www.slideshare.net/AtsushiTorikoshi" target="_blank">Atsushi Torikoshi</a></strong> </div>

ざっくりまとめると、

* PostgreSQLのロジカルレプリケーションでレプリケーション衝突が起こった場合、衝突が（手動で）回避されるまでスタンバイでの反映が止まる
* 衝突を回避するための一つの方法として、pg_replication_origin_advance()関数を使って衝突の原因となるWAL（を送信する事）をスキップできるけど、スキップ先のLSNを指定するので他の必要なデータもスキップしてしまうかもしれないよ

ということ。

レプリケーション衝突というのは、データの受信側（Subscriber）でのデータを適用と、テーブル内のデータや受信側で実行中の変更内容が衝突する事を指しています。

# 試してみる

実施にやってみる。まずは、テーブルを作成して、ロジカルレプリケーションを開始。

```sql
-- 上流側（Publisher)
=# CREATE TABLE test (c int primary key);
=# CREATE PUBLICATION test_pub FOR TABLE test;
=# INSERT INTO test SELECT generate_series(1,10);
=# SELECT * FROM test;
  c
----
  1
  2
  3
  4
  5
  6
  7
  8
  9
 10
(10 rows)
```

```sql
-- 下流側（Subscriber)
=# CREATE TABLE test (c int primary key);
=# CREATE SUBSCRIPTION test_sub CONNECTION 'port=5550 dbname=postgres' PUBLICATION test_pub;
=# SELECT * FROM test;
  c
----
  1
  2
  3
  4
  5
  6
  7
  8
  9
 10
(10 rows)
```

両方のテーブルに1〜10が入っています。

ここで、**Publisherでc = 11をINSERTする前に**、Subscriberでc = 11をINSERT。

```sql
-- 下流側（Subscriber)
=# INSERT INTO test VALUES (11);
```

```sql
-- 上流側（Publisher)
=# INSERT INTO test VALUES (11);
```

すると、Subscriberでは、複製されたデータ（c = 11）を追加する時に、一意製薬に違反するのでエラーが発生。
```
ERROR:  duplicate key value violates unique constraint "test_pkey"
DETAIL:  Key (c)=(11) already exists.
```

# 解決策

このエラーを止める方法は主に2つ。

1. 衝突を手動で解消する。（`DELETE FROM test WHERE col = 11;`)
2. 衝突するデータの適用をスキップする。（`pg_repliation_origin_advance関数`を使う)

今回は「2. 衝突するデータの適用をスキップする」を試します。

## 衝突するデータの適用をスキップする

`pg_repliation_origin_advance関数`を使うと、Subscriberが指定するレプリケーションの開始位置を先に進めることができます。**衝突を引き起すデータの後**からレプリケーションを開始できるので衝突が解消できるのですが、これの欠点は、**LSN(Log Sequence Number)を指定して適用をスキップする所**です。LSNだけだとWALレコードの切れ目が分からないので、下手すると本来必要なデータ適用もスキップしてしまう可能性があります。

そこで、ふと思いついたのがレプリケーションスロットの機能を使ってWALをデコードすればよいのでは？という案。

<blockquote class="twitter-tweet"><p lang="ja" dir="ltr">衝突解決にpg_replication_origin_advanceを使うと他のデータもスキップしてしまう可能性があると書いてあるけど、pg_logical_slot_peek_changeを使えば衝突している変更だけをスキップできるのではと思いついた。<br><br>Architecture &amp; Pitfalls of Logical Replication <a href="https://t.co/60fBd0RsMI">https://t.co/60fBd0RsMI</a></p>&mdash; Sawada Masahiko (@sawada_masahiko) <a href="https://twitter.com/sawada_masahiko/status/1002574212723298305?ref_src=twsrc%5Etfw">June 1, 2018</a></blockquote> <script async src="https://platform.twitter.com/widgets.js" charset="utf-8"></script>

つまり、ロジカルレプリケーションを使ってどのLSNにどのWALのデータが記録されているのかを確かめることで、衝突を起こすWALのデータのみをスキップできます。これには「衝突を起こしているレプリケーションスロットと同じまたはそれより前のLSNからデコードできる別のレプリケーションスロット」が必要です。[^slot]

[^slot]: `pg_waldump`を使ってWALを見てみるのもありです。


## レプリケーションスロットのコピー

PostgreSQL 12ではレプリケーションスロットをコピーする機能が導入される予定[^slotcopy]なので、簡単に「衝突を起こしているレプリケーションスロットと同じまたはそれより前のLSNからデコードできる別のレプリケーションスロット」を用意することができます。

[^slotcopy]:PostgreSQL 12は現在Beta3

```sql
-- 上流側（Publisher)
=# SELECT * FROM pg_replication_slots;
 slot_name |  plugin  | slot_type | datoid | database | temporary | active | active_pid | xmin | catalog_xmin | restart_lsn | confirmed_flush_lsn
-----------+----------+-----------+--------+----------+-----------+--------+------------+------+--------------+-------------+---------------------
 test_sub  | pgoutput | logical   |  13544 | postgres | f         | f      |            |      |          494 | 0/16516D0   | 0/1651708
(1 row)

=# SELECT pg_copy_logical_replication_slot('test_sub', 'test_sub_copy', true, 'test_decoding');
 pg_copy_logical_replication_slot
----------------------------------
 (test_sub_copy,0/1651708)
(1 row)
```

コピー完了。コピーしたレプリケーションスロットで、WALの中身を見てみます。

```sql
-- 上流側（Publisher)
=# SELECT * from pg_logical_slot_peek_changes('test_sub_copy', NULL, NULL);
    lsn    | xid |                   data
-----------+-----+------------------------------------------
 0/1651708 | 494 | BEGIN 494
 0/1651708 | 494 | table public.test: INSERT: c[integer]:11
 0/16517B8 | 494 | COMMIT 494
 0/16517F0 | 495 | BEGIN 495
 0/16517F0 | 495 | table public.test: INSERT: c[integer]:12
 0/1651870 | 495 | table public.test: INSERT: c[integer]:13
 0/1651920 | 495 | COMMIT 495
(7 rows)
```

どうやら衝突しているレコード(c = 11)は `0/16517B8` でCOMMITされている模様。

今度は、Subscriber側で`pg_replication_origin_advance関数`を使って、問題となっている変更をスキップします。

```sql
-- 下流側（Subscriber)
=# SELECT * FROM pg_replication_origin;
 roident |  roname
---------+----------
       1 | pg_16389
(1 row)

=# SELECT pg_replication_origin_advance ('pg_16389', '0/16517F0'::pg_lsn);
 pg_replication_origin_advance
-------------------------------
 
 (1 row)
```

`pg_replication_origin_advance関数`を実行した後、レプリケーション衝突が解決されSubscriberでは`c = 12`のデータから反映されているはずです。

```sql
=# SELECT * FROM test;
  c
----
  1
  2
  3
  4
  5
  6
  7
  8
  9
 10
 11
 12
 13
(13 rows)
```

# まとめ

PostgreSQL 12で導入予定のレプリケーションスロットのコピー機能を使って、レプリケーション中のWALをサーバ側で確認することが可能です。今回はそれを使ってレプリケーション衝突の回避をやってみました。今回の例は単純だったので比較的簡単に衝突回避ができましたが、~~より複雑なケースには対応できないか、かなり難しい可能性がありますので、あくまでも参考として見ていただければと。~~

(2021/06/14 追記)
スキップしたいトランザクションのCOMMITの次のLSNを指定すれば、「本来必要なデータ適用もスキップしてしまう」という現象は起こらないようです。
