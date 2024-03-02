---
layout: post
title: "Replication Originとは"
tags:
  - PostgreSQL
  - Replication
lang: jp
---

PostgreSQLのLogical Replicationはいくつかのコンポーネントから実現されていており、その一つが **Replication Origin** です。PostgreSQLの日本語マニュアルだとReplication Originは「レプリケーション起点」と訳されていますが、名前だけみてもあまりぱっとイメージが付かなくて気になったので、少し調べた結果をまとめます。

# Replicaiton Originの目的は？
Replication OriginはPostgreSQLのLogical Replicationでのみ使用される機能です。PostgreSQL 9.0から利用できるStreaming Replicationとの関連性は全くありません。Replication Originの目的は2つあります。

1. Logical Replicationの時に、レプリケーションの進捗を追跡する
   * Replication Origin、途中でレプリケーションが止まった時に、どこから再開すればよいかがわからない
   * ※SRのときは、マスタとスタンバイのLSNが同じなので、スタンバイの最新のLSNから開始すればよかった
2. レプリケーションされた情報がローカルから発生したのか、リモートから発生したのかを区別する印を付ける
   * これを使うことで、「ローカルで発生した変更」のみを適用し、「レプリケーションで来た変更で出力される変更情報」は無視する、のような動作が可能

以下、それぞれの目的について簡単に解説します。

## 「1. Logical Replicationの時に、レプリケーションの進捗を追跡する」について

こちらについては、比較的イメージしやすいかと思います。

Logical Replicationでは、「受信側がどこまで変更を受信したか」をLSN(Log Sequence Number)で管理します。Streaming Replicationでは、マスタとスタンバイのLSNは一致しているため、スタンバイは常に自分の最新のLSNからレプリケーションを再開すればよいのですが、Logical Replicationでは、

* 送信側(Publisher)と受信側(Subscriber)のLSNは異なる
* Subscriberは複数のPublisherから変更を受信出来る

ため、各レプリケーション毎にLSNを管理する必要があります。その機能を実現するのがReplication Originです。

## 「2. レプリケーションされた情報がローカル発生したのか、リモートから発生したのかを区別する」について

こっちは少しわかりにくいかもです。使い道としては、Logical Replicationを循環するような形（リング型）でLogical Replicationを利用した場合（マルチマスターなど）に、 **Logical Replication経由で伝搬されてきた変更については、下流に伝搬しない**というのがあります。PostgreSQL 10ではこの機能がまだ（恐らくPostgreSQL 11でもまだ）使われていませんが、もし実装されれば、レプリケーションが無限に伝搬し続ける、といったことを防ぐことや、特定の上流から来た変更だけを下流に流す、といったこともプラグインの書き方次第で可能になると思います。

一つのReplication Originは、一つのLogical Replicationの流れ、つまり一組のPublicationとSubscriptionに対応します。例えば、以下のようにLogical Replicationをカスケード形式で組んだ場合、`ORIGIN-A`と`ORIGIN-B`の二つのReplication Originができており、それぞれ異るReplication Origin IDを持つことが可能です。

```
  Srv-X                          Srv-Y                           Srv-Z
+--------+                 +---------------+                 +---------+
| (PubA) | -- ORIGIN-A --> | (SubB : PubB) | -- ORIGIN-B --> |  (SubC) |
+--------+                 +---------------+                 +---------+
```

Logical Decodingには、`filter_by_origin_cb`コールバックがあり、PublisherはWALをデコードするときに、WALに書かれているReplication Origin IDを用いてフィルターすることが可能です。例えば、上記のような構成で、`Srv-X`に更新が発生した場合、各Publicationは以下のようなReplication Origin IDを受け取ることになります。

* PubA: SQLからの変更なので、ID=0
* PubB: `ORIGIN-A`からの変更なので、ID=`ORIGIN-AのID`
* PubC: `ORIGIN-B`からの変更なので、ID=`ORIGIN-BのID`

このように変更元を区別することができるので、下流のサーバに流す、流さないをLogical Decodingのプラグインが決めることができます。なかなか考えられて作られていて素晴らしいですね。

Replication Originの作成や確認、Replication Origin IDの設定なども色々あるのですが、その辺りはまた時間がある時にまとめたいと思います。
