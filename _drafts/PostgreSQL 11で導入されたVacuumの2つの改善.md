---
layout: post
title: PostgreSQL 11で導入されたVacuumの2つの改善
tag:
  - PostgreSQL
  - Vacuum
---

先日リリースされた[PostgreSQL 11](https://www.postgresql.org/about/news/1855/)でVacuum関連機能の改善がいくつかあったのでその中から2つ紹介します。

## Update the free space map during vacuum (Claudio Freire)

> Vacuum中にFree Space Map(FSM)が更新されるようになりました。

これまで、Vacuum（FULLオプションなし）では、Vacuumの実行完了後にFSMを更新していました。そのため、例えばVacuumが長時間化した場合や、Vacuumが途中でキャンセルされた場合に、FSMは更新されず、テーブルの肥大化が進んでいました(※)。

PostgreSQL 11ではこの機能により、Vacuum実行中にもFSMが更新されるようになったので、上記の心配はなくなりました。
インデックスがあるテーブルへのVacuumでは、Vacuumがmaintenance_work_memで設定されたメモリを使い切る度に、そして、インデックスがないテーブルへのVacuumでは、8GBをVacuumする度にFSMが更新されるようになります。

(※)FSMはテーブルの空き領域を管理しているマップです。INSERTやUPDATEの際は、このFSMを参照してテーブルにないので空いている箇所に新しいタプルを挿入します。なので、FSMが更新されていないと、「本当は空き領域があるのに使ってくれない」という状況になってしまいまいます。

## Allow vacuum to avoid unnecesary index scans (Masahiko Sawada, Alexander Korotkov)

> Vacuumが不必要なIndex scanを回避するようになりました。

Vacuumはテーブルとインデックス（複数）の両方をVacuumを掃除する必要があるのですが、インデックスについては**一回のVacuum実行つき、最低1回は実行する必要がありました**。
そのため、例えばテーブルに複数インデックスが付与されている場合では、テーブルが全く汚れていなくても、全てのインデックスについてVacuumは処理しないといけないのでとても時間がかかっていました（※）。この、「テーブルが汚れていなくても（テーブルにゴミがなくても）実行されるインデックスへのVacuum」はドキュメント上では`Cleanup Stage`と呼ばれており、インデックスの統計情報の更新や、インデックスにあるゴミ掃除を目的として実行されます。

（※）ちなみに、テーブルが全く変更されていない状況では、テーブルへのVacuum処理はスキップされ一瞬で終わることができます。

PostgreSQL 10以前では、以下のように1行を挿入しただけでも、cleanup stageが実行されるため、Vacuumに時間がかかっています。

```sql
=# INSERT INTO test VALUES(1);
INSERT 0 1
Time: 15.207 ms
=# VACUUM VERBOSE test;
INFO:  vacuuming "public.test"
INFO:  index "test_idx" now contains 100000001 row versions in 274194 pages
DETAIL:  0 index row versions were removed.
0 index pages have been deleted, 0 are currently reusable.
CPU: user: 0.09 s, system: 2.29 s, elapsed: 5.55 s.
INFO:  "test": found 0 removable, 199 nonremovable row versions in 1 out of 442478 pages
DETAIL:  0 dead row versions cannot be removed yet, oldest xmin: 31055
There were 0 unused item pointers.
Skipped 0 pages due to buffer pins, 0 frozen pages.
0 pages are entirely empty.
CPU: user: 0.12 s, system: 2.29 s, elapsed: 5.58 s.
VACUUM
Time: 6725.698 ms (00:06.726) -- 6秒の内のほとんど(5.5秒)がインデックスVacuum(cleanup stage)によるもの
```

そこで、「前回のVacuumからテーブルが大きく状況が変わっていなければ、cleanup　stageはスキップしてもいいよね」というアイディアのもと、[`vacuum_cleanup_index_scale_factor`](https://www.postgresql.org/docs/devel/static/runtime-config-resource.html#RUNTIME-CONFIG-INDEX-VACUUM)という新しいGUCパラメータが追加されました。

`vacuum_cleanup_index_scale_factor`には、0から100の間で値を設定する事ができ、デフォルトは0.1です。これは、「テーブルが、前回のVacuumから 0.1% 変わっていなければインデックスのVacuumをスキップする」という事を意味します。
ただし、注意点が2点あります
* テーブルに一つでもゴミがある場合は、依然インデックスのVacuumは実行されます
  * この機能でスキップできるのは、cleanup stageのみです。テーブル内にゴミがあれば、通常のインデックスVacuumが実行され、cleanup stageは実行されません。
* 対象となるインデックスはB-treeのみです

つまり、この機能は頻繁に更新されるテーブルには効果がなく、大規模であまり更新されないテーブルに効果があります。例えば、分析用途などで大量のデータが挿入されるテーブルには非常に効果を発揮する機能です。
PostgreSQL 11では以下のようになります。

```sql
=# INSERT INTO test VALUES (1);
INSERT 0 1
Time: 24.499 ms
=# VACUUM VERBOSE test;
INFO:  vacuuming "public.test"
INFO:  "test": found 0 removable, 17375 nonremovable row versions in 77 out of 442478 pages
DETAIL:  0 dead row versions cannot be removed yet, oldest xmin: 582
There were 0 unused item pointers.
Skipped 0 pages due to buffer pins, 0 frozen pages.
0 pages are entirely empty.
CPU: user: 0.02 s, system: 0.00 s, elapsed: 0.03 s.
VACUUM
Time: 182.686 ms -- インデックスVacuum(cleanup stage)が実行されていないのですぐ終わる
```
