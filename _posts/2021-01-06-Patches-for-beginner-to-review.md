---
layout: post
title: 今年はPostgreSQL開発に参画してみたいという人のためにレビューしやすいパッチを選びました
tags:
  - PostgreSQL
  - Commitfest
---

昨年9月にPostgreSQL 13がリリースされましたが、PostgreSQL開発コミュニティでは現在PostgreSQL 14の開発を行っています。PostgreSQLの開発は[Commitfest](https://commitfest.postgresql.org/)と呼ばれるWebページにパッチを登録し、みんなで1ヶ月間レビューする、という形で行われます。PostgreSQL 14に向けたCommitfestはすでに3回行われていて、2021年1月1日から第4回が始まりました（3月から始まる第5回が最後）。

Commitfestには現在260個のパッチが登録されているのですが、それぞれパッチの大きさ、難しさも違いますし、中には何年も議論が続いているパッチがあるので、それらの中からレビューするパッチを選ぶのは一苦労です。

今回のCommitfestでCommit Fest Manager[^cfm]をやらせてもらっているということもあり、一通り全てのパッチを確認したので、PostgreSQL開発に貢献したい、パッチレビューが初めて、という人に向けて簡単そうなパッチをリストアップしてみました。

[^cfm]: Commitfestに登録されたパッチの状況を確認してレビューが円滑に進むようにする役割。

以下の観点で選びました。

* パッチが小さく、難易度が高くなさそう
  * 機能が単純で、パッチが小さいものを選びました
  * クライアントツールや拡張機能(Extension)のパッチは比較的レビューしやすいと思います
* 議論が短い
  * 議論が長いと全部読むのも大変ですし、英語の議論をかいつまんで読むのも大変なので、議論がまだあまりされていないものを選びました

# パッチレビューの仕方
パッチレビューのやり方はこの辺が参考になるかと思います。

* [PostgreSQLコミュニティに飛び込もう](https://www2.slideshare.net/hadoopxnttdata/patch-review-postgresql-community-nttdata)
* [PostgreSQL開発の基本動作まとめ](https://qiita.com/sawada_masahiko/items/2fa99e422ec0eb35245c)

# 必要なもの
* メールアドレス
  * pgsql-hackersメーリングリストへの登録が必要
* PostgreSQLをビルドし動かせる環境
* C言語のソースコードが読める
* (余力があれば)PostgreSQLの公式サイトでアカウントを作成する
  * Commitfestでパッチのステータスを操作できるようになります

# レビューで貢献するともれなく・・・

* PostgreSQL開発の一通りの流れを経験できます
* コミットログに名前が残ります
* PostgreSQL 14のリリースノートに名前が載ります（[こんな感じ](https://www.postgresql.org/docs/13/release-13.html#RELEASE-13-ACKNOWLEDGEMENTS)）

# おすすめパッチ

## Clients

* [list of extended statistics on psql](https://commitfest.postgresql.org/31/2801/)
* [Improve \e, \ef and \ev if the editor is quit](https://commitfest.postgresql.org/31/2879/)
* [Add table access method as an option to pgbench](https://commitfest.postgresql.org/31/2884/)
* [psql - possibility to specify where status row should be displayed](https://commitfest.postgresql.org/31/2536/)
* [allow to set a pager for psql's watch command](https://commitfest.postgresql.org/31/2539/)
* [Improve pg_dump dumping publication tables](https://commitfest.postgresql.org/31/2728/)
* [psql \df choose functions by their arguments](https://commitfest.postgresql.org/31/2788/)

## Documentation

* [Further note require activity aspect of automatic checkpoint and archiving](https://commitfest.postgresql.org/31/2774/)
* [document the hook system](https://commitfest.postgresql.org/31/2915/)
* [Clarify that CREATEROLE roles can GRANT default roles](https://commitfest.postgresql.org/31/2921/)

## Miscellaneous

* [Add OID allocation retry log to GetNewOidWithIndex()](https://commitfest.postgresql.org/31/2899/)
* [Pageinspect functions for GiST](https://commitfest.postgresql.org/31/2825/)

## Monitoring & Control

* [pg_stat_statements and "IN" conditions](https://commitfest.postgresql.org/31/2837/)
* [About to add WAL write/fsync statistics to pg_stat_wal view](https://commitfest.postgresql.org/31/2859/)
* [Add wait_start column to pg_locks](https://commitfest.postgresql.org/31/2883/)
* [Simple progress reporting for COPY command](https://commitfest.postgresql.org/31/2923/)

## Performance

* [Consider parallel for LATERAL subqueries having LIMIT/OFFSET](https://commitfest.postgresql.org/31/2851/)
* [Make popcount available to SQL](https://commitfest.postgresql.org/31/2917/)

## Replication & Recovery

* [Improve standby connection denied error message](https://commitfest.postgresql.org/31/2509/)

## SQL Commands

* [DROP INDEX CONCURRENTLY on partitioned index](https://commitfest.postgresql.org/31/2805/)

## System Administration

* [New default role allowing to change per-role/database settings](https://commitfest.postgresql.org/31/2918/)
* [Add is_toplevel flag in pg_stat_statements](https://commitfest.postgresql.org/31/2896/)

# 注意点

* レビューしたパッチはコミットされないかもしれない
  * 議論の末Rejectされる、という可能性があります
* パッチのステータス(Commitfest上で確認できる)が`Waiting on Author`のものはパッチ作者待ち。`Needs review`を優先的にレビューするべし
* すでにコミット済みかもしれない
  * 比較的簡単そうなパッチをリストアップしたのですでにコミット済みになっているかもしれません。
  * コミットされている場合はステータスが`Committed`になっているはずです。

# 最後に

やってみたけどここがわからない、途中で詰まってしまった、という場合はいつでも[@masahiko_sawada](https://twitter.com/masahiko_sawada)に、もしくは日本PostgreSQLユーザ会が運営している[slack](https://www.postgresql.jp/node/188)にて相談してください！
