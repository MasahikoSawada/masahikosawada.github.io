---
layout: post
title: 最速でVacuumを完了させる方法とその副作用
tags:
  - PostgreSQL
  - Vacuum
---

これは[PostgreSQL Advavent Calendar 2022](https://qiita.com/advent-calendar/2022/postgresql)の21日目のエントリです。昨日は、[@tom-sato](https://qiita.com/tom-sato)さんによる[PostgreSQL でページの中身を視覚的に表示してみる](https://qiita.com/tom-sato/items/e91c7cd816bf3464a417)でした。

通常Vacuumはautovacuumによってテーブルの削除済みの行数や、新しく追加された行数をベースに自動的に実行されます。autovacuumによって行われるVacuumで問題なくテーブルのメンテナンスが行われる状況が理想的ではありますが、特にXID周回問題が絡んでくると、Vacuumを実行にできるだけ早く完了させたくなることがよくあります。

XID周回問題についてはネット上に色々な解説があるのでここでは詳しく説明しませんが、端的に言うとPostgreSQLの内部構造の都合で定期的にVacuum（特にFreezeと呼ばれる処理）を**テーブルの利用状況に関わらず**各テーブルに対して行う必要があります。全テーブルをFreezeするまでの猶予期間は最大でも「約20億トランザクション消費するまで」です[^xid]。

このFreezeが長時間行われなかった場合は、PostgreSQLは新しいXIDの払い出しを停止します。そのため、SELECTはできるけどINSERT、UPDATE、DELETEはできない状態になり、実質読み取り専用になってしまいます。

[^xid]: PostgreSQLは内部でトランザクションID（以下、XID）と呼ばれる単調増加な32bit非負整数を持っています。このXIDは各タプルに記載され（つまりディスクにも書かれる）、この値を元に行の可視性判断(ACIDのI)を行っています。ただ、XIDは32bitですので最大は約40億で、その半分を未来XID、もう半分を過去のXIDとして扱っているので約20億。

# Vacuumはなぜ時間がかかる？

最近のVacuumは高速化されていますが、数百GBや数TBレベルの大きいテーブルにはどうしても時間がかかります。特に時間がかかるインデックスのVacuumです。インデックスVacuumでは、基本的にインデックスを全スキャンしてゴミを探しますが、以下のようにmaintenance_work_memに達した場合は、インデックスVacuumが複数回実行されます。

1. テーブルをスキャンしてゴミを集める
  * 集めたゴミがmaintenance_work_memに達するか、テーブルをスキャンし終わったら次へ。
2. インデックスをVacuumする
3. テーブルをVacuumする
  * テーブルを最後までスキャンしていなければ(つまり、maintenance_work_memに達していた場合は）再度1へ。
4. テーブルを切り詰める

そして、「XIDをFreezeする」という観点では、実はインデックスをVacuumする必要はありません。XIDはテーブル内のタプルには書かれますが、インデックスのタプルに書かれないためです。

それでは、Freeze処理の必要性の迫られた時、大きいテーブルのVacuumを早く完了させる方法について考えていきます。

# そのテーブル本当に必要ですか？

結構忘れがちですがまず検討したいのは、このデータは本当に必要か？ということです。実はなくても問題ない（すでにバックアップを取っていて必要な時に戻せば良いなど）、ということであればテーブルをDROPもしくはTRUNCATEでき、Vacuumする必要もなくなるのでこれが最速の方法です。

# テーブル構造を変える

とはいえ、実際にテーブルを削除できるケースは少ないと思いますので、次に検討するのはテーブル・パーティショニングを利用したテーブルの分割です。現在のVacuumは、テーブルに張ってあるインデックスに対しては並列に処理することが可能ですが、テーブル自体のVacuumはまだ単一プロセスで行います。テーブルを分割すれば、テーブルサイズも小さくなりますし、分割したテーブルを同時にVacuumすることができるので、とても効果が大きいです。これはVacuumの完了を急いでいないときでも有効な手段です。ただし、テーブル・パーティショニングを利用することによる副作用（実行プランの変更）には注意が必要です。

あとは、不要なインデックスを削除することも効果があります。ただ、Freeze処理に迫られているときはそもそもインデックスへのVacuumをスキップすることがおすすめです。

# パラメータを調整する

適切にパラメータを調整することも大切です。最速でFreezeしたい場合は、

* vacuum_cost_delay = 0
  * 遅延を無効にする。autovacuumはデフォルトで遅延がかかっていますが、手動Vacuumはデフォルトでは遅延がかかっていません。
* maintenance_work_mem = 1GB
  * Vacuum中に使う最大のメモリ量。1GBが以上に設定しても意味無し(1GB使うと最大で約3800万タプルを一度の回収できる）[^maintenance_work_mem]。この値が低いとインデックスのVacuumを何度も行うことになるので非常に遅くなります。
* max_parallel_maintenance_workers = (最低でも、対象のテーブルのインデックス数 - 1。複数テーブルを同時にVacuumする場合は増やす）
  * Parallel Vacuumを使った場合の最大のワーカー数。

[^maintenance_work_mem]: この制限をなくす＋高速化する[パッチ](https://www.postgresql.org/message-id/CAD21AoAfOZvmfR0j8VmZorZjL7RhTiQdVttNuC4W-Shdc2a-AA%40mail.gmail.com)に取り組んでいるので上手く行けばPG16で改善するかもしれません。

また、VACUUMコマンドのオプションは以下のように設定します。

* INDEX_CLEANUP off
  * インデックスVacuumをスキップする
* TRUNCATE off
  * Vacuumの最後に可能であればテーブルを切り詰める

これにより、VacuumはテーブルのVacuum＋Freezeのみを行い、Freezeに不必要なインデックスVacuumやテーブルの切り詰めはスキップします。

# `INDEX_CLEANUP off`の副作用

インデックスもテーブルと同じようにゴミが溜まります。インデックスのVacuumをスキップしているので、当然インデックスの肥大化につながる可能性があります。ただ、通常、インデックスは一部の列のデータしか入っていないのでインデックスのタプルは、テーブルのタプルに比べて小さいことが多いです。そのため、テーブルよりは肥大化の影響は少ないと思います。

`INDEX_CLEANUP off`によって溜まるゴミは実はインデックスだけではありません。削除されていないインデックスの（ゴミ）タプルが参照するテーブル内タプルは消せるのですが、そのインデックスが指すテーブル内のタプル（正確にはタプルの[ItemID](https://www.postgresql.jp/document/14/html/storage-page-layout.html#STORAGE-PAGE-LAYOUT-FIGURE)）が再利用されないようするためにDead状態で残ります。

```
postgres=# create table test (a int primary key);
CREATE TABLE
postgres=# insert into test select generate_series(1, 100000);
INSERT 0 100000
postgres=# delete from test where a % 10 = 0;
DELETE 10000
postgres=# vacuum (index_cleanup off, verbose) test;
INFO:  vacuuming "postgres.public.test"
INFO:  finished vacuuming "postgres.public.test": index scans: 0
pages: 0 removed, 443 remain, 443 scanned (100.00% of total)
tuples: 10000 removed, 90000 remain, 0 are dead but not yet removable
removable cutoff: 728, which was 0 XIDs old when operation ended
new relfrozenxid: 726, which is 2 XIDs ahead of previous value
index scan bypassed: 443 pages from table (100.00% of total) have 10000 dead item identifiers
avg read rate: 1.633 MB/s, avg write rate: 2.449 MB/s
buffer usage: 890 hits, 2 misses, 3 dirtied
WAL usage: 447 records, 3 full page images, 68882 bytes
system usage: CPU: user: 0.00 s, system: 0.00 s, elapsed: 0.00 s
VACUUM
```

`443 pages from table (100.00% of total) have 10000 dead item identifiers`とログに書いてあるように、10000個の死んだItemId (dead item identifiers)が残っています。`INDEX_CLEANUP on`でVacuumすると、これらは削除されます。

```
postgres=# vacuum (index_cleanup on, verbose) test;
INFO:  vacuuming "postgres.public.test"
INFO:  finished vacuuming "postgres.public.test": index scans: 1
pages: 0 removed, 443 remain, 443 scanned (100.00% of total)
tuples: 0 removed, 90000 remain, 0 are dead but not yet removable
removable cutoff: 739, which was 0 XIDs old when operation ended
index scan needed: 443 pages from table (100.00% of total) had 10000 dead item identifiers removed
index "test_pkey": pages: 276 in total, 0 newly deleted, 0 currently deleted, 0 reusable
avg read rate: 0.000 MB/s, avg write rate: 0.378 MB/s
buffer usage: 1618 hits, 0 misses, 1 dirtied
WAL usage: 1162 records, 1 full page images, 109723 bytes
system usage: CPU: user: 0.02 s, system: 0.00 s, elapsed: 0.02 s
VACUUM
```

PostgreSQLの1ページ(8kB)には最大で格納できるItemIdの数が決まっているので、死んだItemIdが増えすぎると、ページに空き領域はあるけど空いているItemIdがないので新しいタプルを格納できない（なので新しいページを探す・作る）、ということが起きます。

`INDEX_CLEANUP off`を使った後、テーブルの肥大化が心配な場合は、余裕のある時に`INDEX_CLEANUP on`でVacuumをすることをおすすめします。

# まとめ

* 「やらない」ことが最速。できるだけVacuumをしなくても良い状況を検討する。
* どうしてもVacuumが必要な状況では、高速化を検討する前に処理量の削減を検討する。
  * その上で、できるだけ早く完了するようにパラメータを設定する。
* `INDEX_CLEANUP off`を使った後は、余裕のある時に`INDEX_CLEANUP on`でも実行する。

