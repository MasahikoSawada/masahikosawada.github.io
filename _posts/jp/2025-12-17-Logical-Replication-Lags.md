---
layout: post
title: 論理レプリケーションでのレプリケーションラグの原因を調べてみた
lang: jp
tags:
  - PostgreSQL
  - Logical Replication
---

これは[PostgreSQL Advent calendar 2025](https://qiita.com/advent-calendar/2025/postgresql)の17日目の記事です。

物理レプリケーションと論理レプリケーションの性能を比較するために、色々実験をしていたら少し嵌ってしまったのでその備忘録です。

実験では、トランザクションがCommitされてからそれが受信側で適用するまでの時間を計測しました。具体的には、同期レプリケーションを利用し、[`synchronous_commit`](https://www.postgresql.jp/document/17/html/runtime-config-wal.html#GUC-SYNCHRONOUS-COMMIT)を変更しながらトランザクションの完了時間を比較します。`synchronous_commit`パラメータを使うと「何を持って受信側で変更の適用が完了したとみなすか」(例えば、メモリ上に書かれた時点で完了とするなど)をトランザクション単位で制御することができますす。発生させたトランザクションは、1000行INSERTするような軽いトランザクションです。

結果はこちら:

|                      | remote_write | on         | remote_apply |
|----------------------|--------------|------------|--------------|
| 物理レプリケーション | 2.551 ms     | 3.858 ms   | 4.788 ms     |
| 論理レプリケーション | 5.744 ms     | 405.534 ms | 5.377 ms     |

物理レプリケーションの結果は想定通りでした。スタンバイで適用をより待つように`synchronous_commit`を設定する(remote_write -> on -> remote_apply)と、トランザクション完了までより長い時間がかかります。

一方、論理レプリケーションでは、実行時間が`on` > `remote_apply`であり、`on`の時にかなり長い時間がかかっている結果となり、ちょっと意外でした。

物理レプリケーション、論理レプリケーションは基本的には似たように動いているはずなので、適用完了とみなしたLSNがどのように管理されているのかを調査しました。それらは`pg_stat_replication`ビューの`sent_lsn`、`write_lsn`、`flush_lsn`、`replay_lsn`列の値に対応します。`sent_lsn`、`write_lsn`、`flush_lsn`、`replay_lsn`は、どこまでの変更を送信完了なのかやどこまでの変更が複製完了なのかを示すLSN（Log Sequence Number）です。これらは、レプリケーションのラグを計測するのにとても便利で、例えば、`pg_current_wal_lsn() - sent_lsn`を計算することで、どれくらい変更の送信が遅れているのかがわかります。`

それぞれの列の値はどのようにこうしんされるのでしょうか。

# 物理レプリケーションの場合

物理レプリケーションの場合は、プライマリはWALが書かれた順番通りに送り、スタンバイはそれを適用するので単純です。

1. プライマリがWALを読み送る（`sent_lsn`を更新）
2. スタンバイが受信しWALを書く（`write_lsn`を更新）
3. スタンバイがWALをFlushする（`flush_lsn`を更新）
4. スタンバイでWALが適用される（`replay_lsn`を更新）

プライマリに通知する各LSNは以下の通りになります:

- write_lsn: スタンバイが書いた最新のLSN
- flush_lsn: スタンバイがFlushした最新のLSN
- replay_lsn: スタンバイが適用した最新のLSN

`pg_stat_replicationビュー`でのそれぞれの列値は、`sent_lsn` -> `write_lsn` -> `flush_lsn` -> `replay_lsn`の順に増えていきます。

# 論理レプリケーションの場合

論理レプリケーションでは、パブリッシャ（送信側）はWALをデコードし、コミット順に並び替えてからトランザクション単位で送り、サブスクライバ（受信側）ではトランザクション単位で適用するので多少複雑です。サブスクライバでは、「パブリッシャで発生したトランザクションのCommit LSN[^commit_LSN]」と「それをローカルで適用して得られたCommit LSN」をペアで管理します。例えば、パブリッシャで3つのトランザクションが発生し、それぞれのCommit LSNが100, 120, 200だった場合、それぞれのトランザクションをサブスクライバで適用して、以下のようにCommit LSNのペアを管理します：

[^commit_LSN]: トランザクションのCommit WALレコードのLSN

```
{remote commit-lsn = 100, local commit-lsn = 123}
{remote commit-lsn = 120, local commit-lsn = 1234}
{remote commit-lsn = 200, local commit-lsn = 2345}
```

サブスクライバがどこまでのWALを適用したのかをパブリッシャへ通知する際は、上記の情報を元に「どのトランザクションまでをCommitしたのか」、「どのトランザクションまでをCommitしそのWALをFlushしたのか」を計算します。例えば、サブスクライバでの最新のFlush済みLSNが2000だった場合、remote commit-lsn = 120まではCommitが完了しており、remote commit-lsn = 200はCommit済みだけどまだFlushされていない、という事になります。パブリッシャに通知するLSNは、

- write_lsn: 最新の受信済みLSN
- flush_lsn: 最新のCommit済みかつFlush済みの(remote)トランザクションのCommit LSN
- replay_lsn: 最新のCommit済み（かつ未Flush）の(remote)トランザクションのCommit LSN

つまり、物理レプリケーションとは違い、データを受信(write)→それを適用(replay)→適用したWALをFlushという流れて処理するので、`pg_stat_replicationビュー`でのそれぞれの列値は、`sent_lsn` -> `write_lsn` -> `replay_lsn` -> `flush_lsn`の順に増えていきます。

# サブスクライバではデフォルトで非同期コミットを利用している

ソースコードやドキュメントを確認していると、サブスクライバでパブリッシャからの変更を受け取り適用するワーカー（Apply Worker）はデフォルトでは非同期コミットを利用していることがわかりました。つまり、先程の実験でサブスクライバでは、Apply Workerが変更を適用することで発生したWALレコードを、WAL WriterプロセスがFlushするまで待つ必要があった訳です。その遅延は最大で`wal_writer_delay`の3倍で、`wal_writer_delay`はデフォルトで200msです。

実際に`wal_writer_delay = 10ms`に変更すると`synchronous_commit = on`での結果が変わりました:

|                                                | remote_write | on         | remote_apply |
|------------------------------------------------|--------------|------------|--------------|
| 論理レプリケーション(wal_writer_delay = 200ms) | 5.744 ms     | 405.534 ms | 5.377 ms     |
| 論理レプリケーション(wal_writer_delay = 10ms)  | 5.352 ms     | 26.813 ms  | 5.289 ms     |

`wal_writer_delay`を変更してより早くWALをFlushすることで待ち時間を少なくする代わりに、`CREATE SUBSCRIPTION`に用意されている`synchronous_commit`オプションを利用することも可能です。[ドキュメント](https://www.postgresql.jp/document/17/html/sql-createsubscription.html#SQL-CREATESUBSCRIPTION-PARAMS-WITH-SYNCHRONOUS-COM)にもしっかり書かれています:


> 同期論理レプリケーションを行う場合は別の設定が適切かもしれません。 論理レプリケーションのワーカーは書き込みおよび吐き出しの位置をパブリッシャーに報告しますが、同期レプリケーションを行っているときは、パブリッシャーは実際に吐き出しがされるのを待ちます。 これはつまり、サブスクリプションが同期レプリケーションで使われている時に、サブスクライバーのsynchronous_commitをoffに設定すると、パブリッシャーでのCOMMITの遅延が増大するかもしれない、ということを意味します。 この場合、synchronous_commitをlocalまたはそれ以上に設定することが有利になりえます。

試してみると:

|                                                          | remote_write | on         | remote_apply |
|----------------------------------------------------------|--------------|------------|--------------|
| 論理レプリケーション(synchronous_commitオプション = off) | 5.744 ms     | 405.534 ms | 5.377 ms     |
| 論理レプリケーション(synchronous_commitオプション = on)  | 5.829 ms     | 5.851 ms   | 5.874 ms     |

という感じで納得行く結果を得ることができました。`wal_writer_delay`はインスタンス全体に影響を与えてしまうので、`synchronous_commit`オプションで調整するの方が推奨です。

# まとめ

最初からドキュメントを読んでいればよかったですが、調査を通して論理レプリケーションのflush_lsnとreplay_lsn更新の仕方の違いなども知ることができたので良かったです。次回は、本来やりたかった物理レプリケーションと論理レプリケーションの性能比較をやっていきます。

