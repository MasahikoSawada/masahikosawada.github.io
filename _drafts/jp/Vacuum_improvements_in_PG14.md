---
layout: post
title: PostgreSQL 14で行われたVacuum改善の解説
tags:
  - PostgreSQL
  - Vacuum
---

PostgreSQL 14で導入されたVacuumに関する改善についていくつか紹介・解説します。

# テーブル上のゴミがある程度集中していたらインデックスVacuumをスキップする

> * Allow vacuum to skip index vacuuming when the number of removable index entries is insignificant (Masahiko Sawada, Peter Geoghegan)
>
> The vacuum parameter INDEX_CLEANUP has a new default of auto that enables this optimization.

これまでは、テーブル上に1つでもゴミがある場合、そのテーブルについている全てのインデックスに対してVacuumを行う必要がありました。[以前にも少し解説した]()ように、インデックスのVacuumはインデックス全体をスキャンしなければいけないものが多く、非常に時間がかかります。通常、テーブルにちょっとしかゴミがある場合は自動Vacuumは起動しませんが、Vacuumはゴミ回収以外にもタプルのFreeze処理を行うために、ゴミの溜まり具合に関係なくVacuumを行います。そういうときに、たまたまテーブル上に少量のゴミがあると、そのゴミのためだけにインデックスVacuumが必要となっていました。

この改善によりVacuumは、テーブル上に多少ゴミがあってもインデックスVacuumをスキップするようになりました。「多少ゴミがある」というのは、テーブル全体の2%以下のブロックのみがゴミを持っている場合です。つまり、ゴミがテーブルに局所的に固まっている場合はインデックスVacuumをスキップします。

インデックスVacuumをスキップした場合、もちろんインデックス上のゴミは回収されないまま（テーブル上のゴミは回収済み）ですが、これは大きな問題にはならないと思います。Vacuumがゴミ掃除と同時に行うVisibility Mapの更新にも、そこまで大きな悪影響は与えないと思います（更新できたとしても全体の2%以下のブロックしか更新できないため）。多くの場合で、これらの可能性のある副作用よりも、インデックスVacuumをスキップできるメリットの方が大きいと思います。

# Failsafe modeの導入

> * Cause vacuum operations to be more aggressive if the table is near xid or multixact wraparound (Masahiko Sawada, Peter Geoghegan)
>
> This is controlled by vacuum_failsafe_age and vacuum_multixact_failsafe_age.

Vacuumはゴミ掃除以外にもFreeze処理をテーブルに行う必要があります。Freeze処理はデータベース全体で使われているトランザクションIDの消費に伴い必要なってくるもので、最大でも約20億トランザクション消費する前に行う必要があります。

もしFreeze処理を行わず20億トランザクション以上経過した場合は、データベース全体でトランザクションIDの払い出しが停止されます。つまり、データベースが読み込み専用になってしまいます。そこから復旧するには、データベースを特殊なモード（シングルユーザモード）で起動し、Vacuumをする必要があります。

データベースが壊れるようなことはないものの、これはPostgreSQLにとって最悪の状況の一つです。PostgreSQL 14では、このような状態に陥る前にFail Safeモードと呼ばれるモードになります。Fail Safeモードでは、自動VacuumがFreeze処理を可能な限り早く完了させることに注力します。通常自動Vacuumは、同時実行中のトランザクション処理への影響を少なくするためにわざとスリープを入れながら行っているのですが、Fail Safeモードではこれらの遅延を無効化し全力でVacuumするようになります。

Fail Safeモードで無効になる処理や機能は以下のとおりです。

* コストベースの遅延(cost-based vacuum delay)
* インデックスVacuum
* テーブルの切り詰め

いつFail Safeモードに入るのかは、`vacuum_failsafe_age`や`vacuum_multixact_failsafe_age`で調整可能です。デフォルトは16億で、16億トランザクションの間Freezeができていなかった場合にFail Safeモードに入ります。

# vacuum_cost_page_missのデフォルト値を小さくした

> Reduce the default value of vacuum_cost_page_miss to better reflect current hardware capabilities (Peter Geoghegan)

# VACUUM VERBOSEの改善

# autovacuum logの改善

> * Add per-index information to autovacuum logging output (Masahiko Sawada)

# lazy vacuumのリファクタリング

