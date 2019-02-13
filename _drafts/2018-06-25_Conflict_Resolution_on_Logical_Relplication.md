---
layout: post
title: Local Replicationで正確にレプリケーション衝突を解決する
tags:
  - PostgreSQL
  - Replication
  - Logical Replication
  - Conflict Resolution
---

今回解決したいのは、以下で説明されているような事象。

<iframe src="//www.slideshare.net/slideshow/embed_code/key/zvqa8VssBx2T8i?startSlide=53" width="595" height="485" frameborder="0" marginwidth="0" marginheight="0" scrolling="no" style="border:1px solid #CCC; border-width:1px; margin-bottom:5px; max-width: 100%;" allowfullscreen> </iframe> <div style="margin-bottom:5px"> <strong> <a href="//www.slideshare.net/AtsushiTorikoshi/architecture-pitfalls-of-logical-replication" title="Architecture &amp; Pitfalls of Logical Replication" target="_blank">Architecture &amp; Pitfalls of Logical Replication</a> </strong> from <strong><a href="//www.slideshare.net/AtsushiTorikoshi" target="_blank">Atsushi Torikoshi</a></strong> </div>

ざっくりまとめると。「PostgreSQLのLogical Replicationでレプリケーション衝突が起こった場合、pg_replication_origin_advance()関数を使うと解決出来るけど、他の（必要な）データもスキップしてしまうかもしれないよ」ということ。

レプリケーション衝突というのは、データの受信側（レプリケーションの下流サーバ）でのデータを適用と、テーブル内のデータや受信側で実行中の変更内容が衝突する事を指しています。

実施にやってみる。まずは、テーブルを作成して、Logical Replicationを開始。

```sql
-- 上流側（Publisher)
=# CREATE TABLE test (c int primary key);
=# CREATE PUBLICATION test_pub FOR TABLE test;
=# INSERT INTO test SELECT generate_series(1,10);
=# SELECT * FROM test;
```

```sql
-- 下流側（Subscriber)
=# CREATE TABLE test (c int primary key);
=# CREATE SUBSCRIPTION test_sub CONNECTION 'port=5550 dbname=postgres' PUBLICATION test_pub;
=# SELECT * FROM test;
```

両方のテーブルに1〜10が入っている。

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

このエラーを止める方法は３つ。

1. Logical Replicationを停止する。(DROP SUBSCRIPTIONまたは、ALTER SUBSCRIPTION SET (enable = off))
2. 衝突を手動で改称する。（DELETE FROM test WHERE col = 11; など)
3. 衝突するデータの適用をスキップする。（pg_repliation_origin_advance()を使う)

長くなりましたが、「3. 衝突するデータの適用をスキップする」が今回の本題。

pg_repliation_origin_advance()を使った衝突解消の欠点は、**LSN(Log Sequence Number)を指定して適用をスキップ**所。LSNだけだとデータの切れ目が分からないので、下手すると本来必要なデータ適用もスキップしてしまう可能性がある。


```sql
-- 上流側（Publisher)
=# SELECT * FROM pg_replication_slots ;
 slot_name |  plugin  | slot_type | datoid | database | temporary | active | active_pid | xmin | catalog_xmin | restart_lsn | confirmed_flush_lsn 
-----------+----------+-----------+--------+----------+-----------+--------+------------+------+--------------+-------------+---------------------
 test_sub  | pgoutput | logical   |  13285 | postgres | f         | f      |            |      |          571 | 0/1667E48   | 0/1667E80
(1 row)

```



そこで、ふと思いついたのがreplication slotの機能を使ってWALをデコードすればよいのでは？という案。

<blockquote class="twitter-tweet"><p lang="ja" dir="ltr">衝突解決にpg_replication_origin_advanceを使うと他のデータもスキップしてしまう可能性があると書いてあるけど、pg_logical_slot_peek_changeを使えば衝突している変更だけをスキップできるのではと思いついた。<br><br>Architecture &amp; Pitfalls of Logical Replication <a href="https://t.co/60fBd0RsMI">https://t.co/60fBd0RsMI</a></p>&mdash; Sawada Masahiko (@sawada_masahiko) <a href="https://twitter.com/sawada_masahiko/status/1002574212723298305?ref_src=twsrc%5Etfw">June 1, 2018</a></blockquote> <script async src="https://platform.twitter.com/widgets.js" charset="utf-8"></script>

# 実際にやってみる

例えば、