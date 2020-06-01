---
layout: post
title: VACUUMのログの読み方(VACUUM VERBOSE)
tags:
  - PostgreSQL
  - Vacuum
---

Vacuumとうまく付き合っていくために`VACUUM VERBOSE`ログの読み方を簡単に紹介します。また、`log_autovacuum_min_duration`で出力されるautovacuumのログも大体同じです。バージョンは12.2を使います。`VACUUM VERBOSE`の出力内容はバージョンによって異なる可能性があるのでご注意ください。

# Vacuumのフェーズ

Vacuumは細かく分けると[7個のフェーズに分かれています](https://www.postgresql.jp/document/9.6/html/progress-reporting.html)が、ざっくり3つのフェーズに分けて考えることができます。

1. Scan phase
   * テーブルを先頭から読んでいきゴミタプルのID（タプルID）を記録します。
   * テーブルを最後まで読み切る or 貯めたゴミタプルの量が`maintenance_work_mem`を超えたら次のフェーズへ。
2. Vacuum phase
   * インデックス（複数個ある可能性がある）、テーブルの順で実際にゴミタプルを回収（Vacuum）します。
   * Vacuum後、Scan phaseでテーブルの全体をスキャンしていなければもう一度1へ。
3. Cleanup phase
   * インデックスのCleanupや、テーブル末尾の切り詰めとかをします。

インデックスがないテーブルのVacuumは少し手順が異なります。テーブルを1ページずつ見ながらVacuumをします。`maintenance_work_mem`は使いません。

# `VACUUM VERBOSE`

2つのインデックス（`idx1`、`idx2`）を持つテーブル`tbl`を更新した後Vacuumをしたときのログです。

```
=# VACUUM VERBOSE tbl;
INFO:  vacuuming "public.tbl"
INFO:  scanned index "idx1" to remove 698942 row versions
DETAIL:  CPU: user: 0.55 s, system: 0.01 s, elapsed: 0.57 s
INFO:  scanned index "idx2" to remove 698942 row versions
DETAIL:  CPU: user: 1.00 s, system: 0.07 s, elapsed: 1.12 s
INFO:  "tbl": removed 698942 row versions in 3093 pages
DETAIL:  CPU: user: 0.01 s, system: 0.00 s, elapsed: 0.01 s
INFO:  scanned index "idx1" to remove 301058 row versions
DETAIL:  CPU: user: 0.40 s, system: 0.01 s, elapsed: 0.42 s
INFO:  scanned index "idx2" to remove 301058 row versions
DETAIL:  CPU: user: 0.80 s, system: 0.07 s, elapsed: 0.92 s
INFO:  "tbl": removed 301058 row versions in 1333 pages
DETAIL:  CPU: user: 0.00 s, system: 0.00 s, elapsed: 0.00 s
INFO:  index "idx1" now contains 3000000 row versions in 10970 pages
DETAIL:  1000000 index row versions were removed.
2736 index pages have been deleted, 0 are currently reusable.
CPU: user: 0.00 s, system: 0.00 s, elapsed: 0.01 s.
INFO:  index "idx2" now contains 3000000 row versions in 10985 pages
DETAIL:  1000000 index row versions were removed.
0 index pages have been deleted, 0 are currently reusable.
CPU: user: 0.00 s, system: 0.00 s, elapsed: 0.00 s.
INFO:  "tbl": found 1000000 removable, 3000000 nonremovable row versions in 17700 out of 17700 pages
DETAIL:  0 dead row versions cannot be removed yet, oldest xmin: 562
There were 0 unused item identifiers.
Skipped 0 pages due to buffer pins, 0 frozen pages.
0 pages are entirely empty.
CPU: user: 3.29 s, system: 0.22 s, elapsed: 3.64 s.
INFO:  "tbl": truncated 17700 to 13275 pages
DETAIL:  CPU: user: 0.00 s, system: 0.00 s, elapsed: 0.01 s
VACUUM
```

# `VACUUM VERBOSE`ログの読み方

各ログの読み方を紹介します。

```
=# VACUUM VERBOSE tbl;
INFO:  vacuuming "public.tbl"
```

これはVacuum開始時に出るログ。このログの直後からScan phaseに入ってます。
次のログが出るまでずっとScan phaseです。

```
INFO:  scanned index "idx1" to remove 698942 row versions
DETAIL:  CPU: user: 0.55 s, system: 0.01 s, elapsed: 0.57 s

INFO:  scanned index "idx2" to remove 698942 row versions
DETAIL:  CPU: user: 1.00 s, system: 0.07 s, elapsed: 1.12 s
```

Vacuum phaseでインデックスのVacuumが完了した時に出るログで、インデックス個数分でます。
削除したインデックスのタプル数、かかった時間が出ています。

インデックスのVacuumは（インデックスの種類によりますが）フルスキャンするので注意が必要です。テーブルのVacuumに比べてインデックスのVacuumがとても時間がかかります。いかにVacuum phaseの回数を減らすかがVacuum時間の短縮に重要です。メモリに余裕があれば`maintenance_work_mem`を増やして、最大でも1回に収めるようにするのがおすすめです（ただし1GBが上限）。

```
INFO:  "tbl": removed 698942 row versions in 3093 pages
DETAIL:  CPU: user: 0.01 s, system: 0.00 s, elapsed: 0.01 s
```

Vacuum phaseでテーブルのVacuumが完了した時に出るログです。
これも`removed XXXXX row version`は削除したテーブルのゴミタプルの数です。
このログが出た後、Scan phaseに戻るか、Cleanup phaseに進みます。

次のログを見てみましょう。

```
INFO:  scanned index "idx1" to remove 301058 row versions
DETAIL:  CPU: user: 0.40 s, system: 0.01 s, elapsed: 0.42 s

INFO:  scanned index "idx2" to remove 301058 row versions
DETAIL:  CPU: user: 0.80 s, system: 0.07 s, elapsed: 0.92 s
```

もう一度インデックスをVacuumしたログが出ています。
なので、`maintenance_work_mem`が足りておらず（698942行分しか貯めれなかった）、 Scan phase -> Vacuum phase がもう一度実行されたという事がわかります。

Vacuum phaseの合計回数はautovacuumのログだと`index scans: XX`みたいな感じで表示されます。(VACUUM VERBOSEでも表示するようにしても良いかも?）

```
INFO:  "tbl": removed 301058 row versions in 1333 pages
DETAIL:  CPU: user: 0.00 s, system: 0.00 s, elapsed: 0.00 s
```

インデックスのVacuumの後なので、テーブルのVacuumが実行されました。内容は先程と同じです。

次のログを見てみます。

```
INFO:  index "idx1" now contains 3000000 row versions in 10970 pages
DETAIL:  1000000 index row versions were removed.
2736 index pages have been deleted, 0 are currently reusable.
CPU: user: 0.00 s, system: 0.00 s, elapsed: 0.01 s.

INFO:  index "idx2" now contains 3000000 row versions in 10985 pages
DETAIL:  1000000 index row versions were removed.
0 index pages have been deleted, 0 are currently reusable.
CPU: user: 0.00 s, system: 0.00 s, elapsed: 0.00 s.
```

Cleanup phaseに入り、これはインデックスのCleanupが完了したログです。各インデックスについてVacuumのサマリ情報が出力されます。Btreeインデックスの場合、一度インデックスのVacuumをしていれば、このCleanupは一瞬で終わります。

`INFO:  index "idx1" now contains 3000000 row versions in 10970 pages`はVacuum後にインデックスにある有効なタプル数とそのページ数です。

`DETAIL:  1000000 index row versions were removed.`の`1000000`はこれまでのインデックスVacuumで削除したタプル数の合計になります。

`2736 index pages have been deleted, 0 are currently reusable.`は2736ページ削除したけどまだ再利用にはなっていない、という意味になります。Btreeインデックスではページが再利用されるまでには最低2回Vacuumが必要になる[^btreevacuum]ので、次にVacuumをした時には`2736 are currently reusable`と表示されるはずです[^btreevacuum2]。

[^btreevacuum]: (インデックスタプルはXIDを持たないので)BtreeのVacuumではページを削除する際にその時点での最小のXIDをページに記録しておき、次ページを見たときにそのXIDを過ぎていたら（誰もそのページを見ていないことがわかるので）再利用可能にする、という感じで2フェーズで実行されています。
[^btreevacuum2]: 再利用可能なページ数のカウント方法が最近のバージョンで[修正された](https://www.postgresql.org/docs/12/release-12-3.html)ので、バージョンによっては数字が一致しない可能性あります。

ここからはテーブルVacuumのサマリとなる情報が表示されます。

```
INFO:  "tbl": found 1000000 removable, 3000000 nonremovable row versions in 17700 out of 17700 pages
```

テーブルの削除したタプル、残ったタプル、ページ数の合計です。

```
DETAIL:  0 dead row versions cannot be removed yet, oldest xmin: 562
```

`0 dead row versions cannot be removed yet`の数には注意が必要です。この数は「Vacuumしようとしたけど他に参照する可能性のあるトランザクションがいるのでVacuumできなかった」ということなので、この数が大きいとVacuumをしたのにも関わらずあまり領域を回収できなかったという事になります。

Vacuumで使ったしきい値となるトランザクションIDは`oldest xmin: 562`の`562`です。何度VacuumをしてもこのXIDの値が変わらず、それが原因で残っているタプルが多い場合は、この値は`pg_stat_activity`の`backend_xmin`か`backend_xid`、もしくは`pg_prepared_xacts`の`xid`にいるはずですので、チェックしましょう。

```
There were 0 unused item identifiers.
```

これはVacuum中に見つけた利用可能なItemID（Line Pointerとも呼びます）の数です。個人的にはあまり注目して見ない値ではありますが、テーブルが大きいように見えてもこの値が大きい場合はまだテーブルに隙間があるという場合もありますし、逆に必要ないItemIDがページの中でスペースを奪ってしまっている場合もあります。少ない数の方が健全な状態ではあると思います。

```
Skipped 0 pages due to buffer pins, 0 frozen pages.
```

前半の`Skipped 0 pages due to buffer pins`は「バッファロックが競合してVacuumしようとしたけどできなかったページ数」なので少ない方が良いです。（あまり見たことはありませんが）この数が大きい場合は、そのテーブルがあまりアクセスされていない時間帯にもう一度Vacuumを試すのがおすすめです。

一方後半の`0 frozen pages`は「Visibility Mapにより処理をしなくて済んだページ数」なので多い方が良いです。Vacuumの高速化に直結する値なので、いつもこの値が少ない、かつVacuumをもっと早くしたい、という場合はVacuum（またはautovacuum）の頻度を上げる、または遅延を抑える（遅延時間を短くする）ことをおすすめします。

```
0 pages are entirely empty.
CPU: user: 3.29 s, system: 0.22 s, elapsed: 3.64 s.
```

これはVacuum中に発見した空ページの数です。この値も個人的にはあまり注目して見ることはないですが、おおまかなテーブルの肥大化率の計算には役に立ちそうです。
また、この時間はVacuumが始まってからここまでの処理に合計時間です。

```
INFO:  "tbl": truncated 17700 to 13275 pages
DETAIL:  CPU: user: 0.00 s, system: 0.00 s, elapsed: 0.01 s
```

これは最後にテーブルに末尾を切り詰める処理のレポートです。Vacuumでは基本的には物理的なテーブルサイズを小さくすることはしませんが、テーブルの（物理的な）末尾に空ページが続いている場合、テーブルの物理ファイルを切り詰めて物理的に小さくします。

この例では、元々17700ページあったのが、13275ページまで切り詰められたことがわかります。Vacuum中のテーブルの切り詰めは一長一短があります。テーブルやインデックスのVacuum中は`ShareUpdateExclusiveLock`という、SELECT/INSERT/UPDATE/DELETEとは競合しない[ロック](https://www.postgresql.jp/document/12/html/explicit-locking.html)を取得しますが、切り詰める時には一時的に`AccessExclusiveLock`というすべてのロックに競合するロック（排他ロック）取得します。これが同時実行中のプロセスやホットスタンバイに影響を与えることもあるので、それを避けるためにPostgreSQL 12以降では`TRUNCATE [on|off]`オプションで制御することが可能です。

# 終わりに

他にもこんな読み方があるよ、という場合はぜひコメントください。
