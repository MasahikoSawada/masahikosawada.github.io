---
layout: post
title: PostgreSQL 17で新しく実装されたradix treeを使ってインメモリのキーバリューストア作ってみた
tags:
  - PostgreSQL
  - radixtree
---

これは[PostgreSQL Advent calendar 2024](https://qiita.com/advent-calendar/2024/postgresql)の18日目の記事です。

# radixtree.h

先日リリースされたPostgreSQL 17では、Vacuumの実行速度やメモリ使用量が大きく改善されています。内部的な情報なのでリリースノートでは言及されていませんが、その改善の立役者となったのはPostgreSQL 17で新しく実装されたradix treeです。以前はTIDの配列を使ってゴミタプルのTIDを管理していたのですが、PostgreSQL 17からはゴミタプルのTIDをradix treeに入れることにより、Vacuumがより早く、より省メモリで動くようになりました。radix treeの実装は[こちらの論文](https://db.in.tum.de/~leis/papers/ART.pdf)をベースにしており、いくつか最適化を入れています。ソースコードに興味がある方は[こちら]()。

インメモリでなにかのデータを保持したい場合、PostgreSQLのソースコードにはハッシュテーブルをはじめとしたいくつかのデータ構造が実装されています。

- `src/backend/utils/hash/dynahash.c`
- `src/include/lib/simplehash.h`
- `src/include/lib/radixtree.h`
- `src/backend/lib/dshash.c`
- `src/backend/lib/integerset.c`
- `src/backend/lib/rbtree.c`
- `src/backend/lib/ilist.c`

例えば、`dynahash.c`はPostgreSQL内部ではロック情報の管理など、様々なところで使われており、`dshash.c`はPostgreSQLの稼働統計情報を保持するコードで使われています。

それぞれ、データ構造としての特徴が異なることはもちろんですが、PostgreSQLでの実装という観点での特徴も異なります。例えば、`dynahash.c`はプロセスのローカルメモリ上にも共有メモリ上にもハッシュテーブルを作ることが可能ですが、ハッシュテーブルのサイズは固定です。一方で、`dshash.c`は共有メモリ上にのみハッシュテーブルを作ることができ、ハッシューテーブルは自動的に成長しますが、ハッシュテーブルの値（バリュー）は固定長ですし、ハッシューテーブルは成長はしますが小さくはなりません。これらの実装依存の特徴は将来変わる可能性があります。

`radixtree.h`の実装としての特徴は以下の通りです。

- キーは`uint64`で固定
- バリューは可変長もサポートしてる
- ローカルメモリにも共有メモリにも作成可能
- 自動的に成長、縮退する

特に、可変長のバリューを持つことができ、共有メモリ上に作成できることは（今のところ）大きな特徴だと言えます。この特徴を使ってインメモリのキーバリューストアを作ってみました。

# pg_memstore

[`pg_memstore`](https://github.com/MasahikoSawada/pg_memstore)は、PostgreSQLの拡張機能（Extension）で、共有メモリ上に作成したradix treeをベースとしたキーバリューストアです。可変長のバリューが持てる特徴を活かし、バリューにはjsonbデータが格納できます。

最初は簡単なSET、GETだけをサポートする予定だったのですが、作っていたら色々面白くなってきて、ファイルへのダンプ・リストア、WALサポートも実装してみました。

インストールはリポジトリ内の[README](https://github.com/MasahikoSawada/pg_memstore)をご参照ください。

`CREATE EXTENSION pg_memstore`を実行したら早速使ってみましょう。まずはシンプルな操作です。

```sql
=# SELECT memstore.set('key-1', '{"a": 1}'); -- return false if a new key
 set
-----
 f
(1 row)

=# SELECT memstore.get('key-1');
   get
----------
 {"a": 1}
(1 row)

=# SELECT memstore.set('key-1', '{"a": 999}'); -- update the value
 set
-----
 t
(1 row)

=# SELECT memstore.get('key-1');
    get
------------
 {"a": 999}
(1 row)

=# SELECT memstore.set('key-2', '{"b": [1, 2, 3]}');
 set
-----
 f
(1 row)

=# SELECT * from memstore.list();
        key         |      value
--------------------+------------------
 \x6b65792d317e7f7f | {"a": 999}
 \x6b65792d327e7f7f | {"b": [1, 2, 3]}
(2 rows)

=# SELECT memstore.delete('key-2');
 delete
--------
 t
(1 row)

=# SELECT * from memstore.list();
        key         |      value
--------------------+------------------
 \x6b65792d317e7f7f | {"a": 999}
(1 row)
```

共有メモリ上に作られているので、他のセッションからもアクセス可能です：

```sql
=# SELECT memstore.get('key-1');
    get
------------
 {"a": 999}
(1 row)

=# \c -
=# SELECT memstore.get('key-1');
    get
------------
 {"a": 999}
(1 row)
```

メモリ使用量を確認することもできます：

```sql
=# SELECT memstore.memory_usage();
 memory_usage
--------------
       262144
(1 row)
```

`memstore.save()`でディスク上にダンプし、`memstore.load()`でロードすることも可能です。

また、`pg_memstore.wal_logging = true`に設定すると、`memstore.set()`と`memstore.delete()`の情報がWALに書かれるので、レプリケーションのスタンバイサーバでも同じデータを持つことができます。

# 実装してみた所感

`pg_memstore`を実装したことで2つPostgreSQLのバグを見つけることができました。1つは[修正済み](https://git.postgresql.org/gitweb/?p=postgresql.git;a=commit;h=724890ffb75c703afc1e0287f5a66b94c2998799)ですが、もう一つは[議論中](https://www.postgresql.org/message-id/CAD21AoBB2U47V%3DF%2BwQRB1bERov_of5%3DBOZGaybjaV8FLQyqG3Q%40mail.gmail.com)です。READMEにも書いてありますが、PostgreSQL本体でこのバグが直るまで、`memstore.list()`と`memstore.save()`は使えません。

キーバリューの情報をシャットダウン時にディスクに保存するために「CHECKPOINT時やサーバシャットダウン時に、DSA上に作成したデータをファイルに書く」みたいな挙動をやりたかったのですが、現在のPostgreSQLではできなさそうです。最初に検討したのは、「シャットダウン時にradix treeに入っているデータを一つずつファイルに書く」ですが、これはpostmasterがやる必要があります。しかし、現在postmasterがDSA上のデータを触ることはできないようです（正確にはその内部で使っているDSMにアクセスできない）。次に、checkpointerがCHECKPOINT時にそれをやる方法を考えたのですが、現在CHECKPOINT時にhook等でコードを入れ込むことはできません、この辺りは将来改善できるかもなと思いました。





