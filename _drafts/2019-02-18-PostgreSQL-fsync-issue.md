---
layout: post
title: PostgreSQLは20年間どのようにfsyncを間違って使っていたか - 聴講メモ -
description: PostgreSQLで修正されたfsync周りのバグ修正について解説された動画の聴講メモ。
tags:
  - PostgreSQL
  - Bugs
---

先日PostgreSQLの新しいマイナーバージョンが[リリースされました](https://www.postgresql.org/about/news/1920/)。このマイナーリリースでメインとなる修正は「fsync周りのバグ修正」で、このバグは**間違ったfsyncに対する間違った認識から約20年間存在してたバグ**ということで注目されていました。

このバグについてPostgreSQLのコミッタ(Tomas Vondra氏)が解説しているセッションが、先々週開催されたFOSDEM 2019でありました。私もFOSDEM 2019に参加していたのですがその際は裏セッションに参加していて聞けず、資料が公開されないかなーと思っていたら、[講演動画](https://fosdem.org/2019/schedule/event/postgresql_fsync/)が公開されていたので観てみました。

以下は、その時の聴講メモです。より詳しく知りたい方は、是非動画の方も観て下さい。

# TL;DR

* PostgreSQLはずっとfsyncについて一部間違った認識をしており(具体的には、fsyncがエラーした後の動作)を間違っており、稀なケースではあるけどユーザの知らない所でデータが破損するリスクがあった
* PostgreSQL 11以下の最近リリースされた全てのバージョンで、fsyncに失敗したらpanic(データベースのクラッシュ）になるような変更をいれることでこの修正されている

# 聴講メモ

## Intro into durability

WALはDirect I/Oを使っているけど、テーブルやインデックスなどのデータベースデータについては、page cache(kernelが管理している)の上にある共有バッファをつかって、Buffered I/Oを使っている。

INSERT/UPDATE/DELETEが発生すると、

1. WALそして共有バッファ上のデータを更新する。
2. WALの変更をflushして永続化する
3. 完了

この時にデータベースが落ちた場合、共有バッファ上の更新データは無くなる。けど、WALはディスク上に書かれているため、WALを再生することで落ちた直前の状態に回復することが出来る。

ここで一つ問題なのは、運用を続けているとWALはとても大きいサイズになる可能性があり、リカバリ時にWALを先頭から再生すると、とても時間がかかる。そのため、CHECKPOINTを使ってリカバリ時間を短縮する。

## PostgreSQLのCHECKPIONT
PostgreSQLのCHECKPOINTは以下のように動く

1. CHECKPOINT開始のLSNを記録する
2. 共有バッファ上にある変更されたデータをpage cacheに書き出す(write)
3. page cacheのデータをディスクに書き出す(fsync)
4. 不要になったWALを消す

## CHECKPOINT中にエラーが発生したら？

CHECKPOINTは完了してはいけないし、WALも削除されてはいけない。

* writeの失敗
  * 原理的には可能性はあるけど稀
  * writeするべきデータはPostgreSQLが持っているのでりリトライできる
* fsyncの失敗
  * SAN、NFSとか使っていると簡単に発生する
  * fsyncするべきデータは**kernelが持っている**

## fsyncへの2つの間違った期待

>1: fsyncが失敗した場合、次のfsyncのタイミングで失敗したdirty pageは再度書き込まれる

実際には・・・最初のfsyncに失敗したらデータはpage cacheから削除される。なので、次のfsyncはリトライしない。
さらに、これは、ファイルシステムによって挙動は変わる。ext4は、dirty dataをpage cacheに**clean**として残すし、xfsは捨てる。

>2: 複数のファイルディスクリプタがある場合（例えばマルチプロセスの時）、一つのプロセスでfsyncが失敗したら、他のプロセスでも同じようにエラーとなる

実際には・・最初のプロセスだけがエラーとなる。その際、ファイルはcloseされopenされる。さらに、これはkernel versionによって挙動は異なる。

BSDでも同じように発生するけど、FreeBSD、illumosでは起きない。

## なぜ今になって問題が明らかになってきた？

* SAN、EBS、NFSとか使うようになってきた
* thin provisioning
  * ENOSPCとかよくある

つまり、fsyncが失敗しやすい条件を持つユースケースが増えてきた

## そもそもなぜBufferd I/Oなのか？

Postgresはもともとresearch projectで、当時その辺を頑張る研究者がいなかった。また、複雑さをなくすため。

## どうやって直すかか
1. カーネルを修正する
  * カーネル開発者たちに受け入れられたとしても数年単位で時間がかかる
2. PostgresでCEHCKPOINTのfsyncが失敗したらpanicを起こすようにする
  * panicしてWALからcrash recoveryする

Direct I/Oのアプローチもありだしパッチもでている、だけどこれも数年かかるだろう。

## 参考リンク

* pgsql-hackers
  * 開発者MLでの議論
  * https://goo.gl/Y47xFs
  * https://goo.gl/dk4F3n

* PostgreSQL fsync() surprise
  * https://lwn.net/Articles/752063/

* Improved block-layer error handling
  * https://lwn.net/Articles/724307

* PGCon 2018 fsyncgate : Matthew Wilcox
  * 昨年のPGConでKernel開発者が発表したlinux kernelのfsyncについての話
  * 個人的にもこれはおススメ
  * https://goo.gl/Qst2Lf

## 質疑

いくつか抜粋。

* Q. どうやって修正パッチをテストした？
  * A. エラーを再現するスクリプトを作ってそれでテストした。テストはすでに公開されている。

* Q. どのようにこの問題は明らかになった？
  * A. 実環境でデータ破損が起きて、インデックスが壊れているとか色々色々探した結果、この問題を発見した

   現在のFSを使うにあたってなにかおすすめは？
    thin provisioningをつかっている場合は容量のモニタリングが重要
	 multi path?
		 使っているシステムでfsyncのエラーが出ているどうやってデバッグするのか？
		  ちょっとわからない
		  freebsdはzfsでは起こらない
	  どのバージョン？
		  すべてのバージョン
* Q. zfs on freebsdではこの問題は起きない、と言っていたけど、zfs on linuxではどう？
  * A. zfs on linuxもセーフだと思う。page cacheではなくarcを使っているから

# 最後に
対応する修正コミットは[これ](https://git.postgresql.org/gitweb/?p=postgresql.git;a=commit;h=9ccdd7f66e3324d2b6d3dec282cfa9ff084083f1)と[これ](https://git.postgresql.org/gitweb/?p=postgresql.git;a=commit;h=1556cb2fc5c774c3f7390dd6fb19190ee0c73f8b)。
`data_sync_retry`という新しいパラメータが導入されて、デフォルトではfsync()の失敗でPANICになるようになった。fsyncの失敗は稀なケースではあるけれど、NFSとかEBSとかthin provisioningを使っている場合は気を付けたい。
