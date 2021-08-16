---
layout: post
title: PostgreSQL 14でのBtreeインデックスのVacuum関連の改善についての解説
tags:
  - PostgreSQL
  - Vacuum
  - Btree Indexes
---

Vacuum（とautovacuum）は、テーブルとインデックスのゴミ掃除をした後にindex cleanupと呼ばれる「インデックスVacuumの後処理」のようなものを実行します。実際の処理内容はインデックスの種類によって様々ですが、index cleanupの主な目的はインデックスの統計情報（ページ数、タプル数）を取得することです（インデックスによっては、削除済みページの回収など、他の処理を行う場合もあります）。インデックスのゴミ掃除をした場合（つまりテーブルにゴミがある状態でVacuumが実行された場合）は、インデックスの統計情報はすでに取得済みなので、index cleanupでは何もしません。逆にテーブルにゴミがない状態でVacuumが実行された場合[^insert_vacuum]は、index cleanupはVacuumにとってこれが初めてのインデックスに対する処理となります。

[^insert_vacuum]: INSERTのみが走ったテーブル（ゴミが内テーブル）にはautovacuumは実行されなかった(PG11時点)。けど、XID周回防止Vacuumはゴミがないテーブルにも定期的に走る。

PostgreSQL 13までのBtreeインデックスでは、index cleanupにていくつかの条件を満たした場合にインデックスのフルスキャンを行っていました。このあたりの動作についてPostgreSQL 14にて行われた3つの改善について解説します。

PostgreSQL 14のリリースノートは[こちら](https://www.postgresql.org/docs/14/release-14.html)です。

## vacuum_cleanup_index_scale_factorの廃止

> * Remove server variable vacuum_cleanup_index_scale_factor (Peter Geoghegan)
>
> This setting was ignored starting in PostgreSQL version 13.3.

`vacuum_cleanup_index_scale_factor`はは、テーブルにゴミがなかったとしても、前回のVacuum以降にこのパラメータで設定された割合以上のタプルがに追加されている場合は、インデックスの統計情報を更新するために、インデックススキャン（多くの場合でインデックスのフルスキャン）する、というものです。

このパラメータはPostgreSQL 11で導入されたもので、XID周回防止Vacuumが走った際に「前回のXID周回防止Vacuumから全く更新されていないテーブル」に対しては完全にテーブルとインデックスのスキャンをスキップできるもののある程度のINSERTが実行されていた場合はテーブル上にゴミはないけどインデックスの統計情報は更新したい、というニーズに対応するために導入されたものです。

ただ、PostgreSQL 13で導入された`autovacuum_vacuum_insert_scale_factor`によりINSERTのみが走ったケースでもautovacuumが頻繁に走るようになり、`vacuum_cleanup_index_scale_factor`によるインデックススキャンが性能劣化の原因になるケースがあるとの[報告もありました](https://smalldatum.blogspot.com/2021/01/insert-benchmark-postgres-is-still.html)。

PostgreSQL 14では、インデックスの統計情報はANALYZEやautoanalyzeで**インデックススキャンなしで推定**するようになり、このパラメータは廃止されました。インデックスの中身を見ないで統計情報を推定するので、正確な値が得られないケースもありますが、取得する統計情報はインデックスサイズはインデックスタプル数くらいなのでそこまで正確な情報はいらないよね、という議論がありました。

## Btreeのページリサイクルの改善

> * Allow vacuum to more eagerly add deleted btree pages to the free space map (Peter Geoghegan)
>
> Previously vacuum could only add pages to the free space map that were marked as deleted by previous vacuums.

上記で説明した「Vacuum中にインデックスの統計情報を取得する処理」は、Vacuumの中のindex cleanupと呼ばれる、テーブルやインデックス内のゴミをすべて掃除した後に実行される処理の中で行われています。

Btreeインデックスが、このindex cleanupにてインデックスをスキャンしていたのは、二つの目的がありました。一つは上記で説明した「統計情報を取得するため」で、もう一つは「Btreeインデックスのページのリサイクル」です。

PostgreSQLのBtreeインデックスは、ツリーの各ノードがPostgreSQLのページ（＝ブロック）に対応しているのですが、ページ内のすべてのインデックスタプルがゴミとして削除されても、すぐ再利用することはできません（まだそのページに訪れようとしているトランザクションがあるかもしれないため）。そのため、インデックスページを削除する際はまず、その時点で走っている最新のトランザクションIDをページ内に記録しておき、そのトランザクションが終了したことがわかったらページに「再利用可能（リサイクル可能）」というマークを付ける、というよう動きます。そのため、ページを削除してからリサイクルするまでに最低でも2回のVacuumが必要でした。

PostgreSQL 14では、インデックスVacuumの後に「削除済みだけどリサイクル可能なマークを付けていないページ」がリサイクル可能になれるかどうかを確認するようになりました。これにより、多くの場合で1回のVacuumだけでページをリサイクル可能にします。多くのトランザクションは長期間滞在する事は少なく、インデックスのゴミ掃除は時間がかかる傾向があるので、インデックスのゴミ掃除をしている間にページ内に記載したトランザクションは完了している、という経験則に基づいた動作になっています。それでもそのようなページが溜まってしまった場合（インデックス全体の20%以上）にのみ、これまで通りindex cleanupにてインデックススキャンが行われるようになりました。

## ページ内に記録するトランザクションIDを64-bit トランザクションIDに変更

上記の変更により、Btreeインデックスのindex cleanupではほとんどの場合でインデックススキャンを行わないようになり、Vacuumの負荷が軽減されました。さらに、インデックススキャンが長期間行われずインデックスが肥大化してしまう、というリスクに対しても対処しています（上記の20%の条件）。しかし、実はもう一つ考慮する点があります。それはページ内に記録したトランザクションIDが放置されたままトランザクションIDが周回してしまう可能性です[^xid_wrap]。

これが発生すると、ページがリサイクル可能かどうかの判定が壊れてしまうので「本当はリサイクル可能なのにリサイクル可能とマークできない」という現象が起こってしまいます。この問題に対しては、64-bitトランザクションIDを利用することで対処しました。64-bitトランザクションIDを利用することで周回するリスクが（実質）なくなります。

[^xid_wrap]: XIDは32-bitの非負整数型
