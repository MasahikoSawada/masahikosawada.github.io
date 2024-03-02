---
layout: post
title: PostgreSQLのリカバリ周りのバグを修正してみた - 原因究明編 -
tags:
  - PostgreSQL
  - Bug fixes
lang: jp
---

PostgreSQLのリカバリ周りにあったバグ修正について、発見から修正までに実際に行ったことを紹介しています。今回は原因究明編です。前回をまだ読んでいない方は[前回の記事]({% post_url 2019-10-03-Fix-Recovery-Bug-01 %})を先に読むことをおすすめします。

# 前回おさらい

前回は`RECOVERYHISTORY`ファイルがなぜ作られるのか、そして作られた後どうなるのか？について調査しました。

そしてソースコードを確認した所、`RECOVERYHISTORY`ファイルは作られた後、`KeepFileRestoredFromArchive関数`にて名前が変えられたり、`exitArchiveRecovery関数`で削除(unlink)されていました。

# 仮説１ - 削除失敗? -

`exitArchiveRecovery関数`をよく見ると、`unlink関数`が失敗した場合でもエラーを無視するようなコードになっています。

```c
    :
    /* Get rid of any remaining recovered timeline-history file, too */
    snprintf(recoveryPath, MAXPGPATH, XLOGDIR "/RECOVERYHISTORY");
    unlink(recoveryPath);       /* ignore any error */
    :
```

このことから、**「`unlink関数`が何かしらの原因で失敗したために`RECOVERYHISTORY`ファイルが残ってしまったのではないか」**という仮説が生まれます。

# 仮説1の検証

この仮説を検証するために実際にコードを変更して、`unlink関数`が成功したのか、失敗したのか、また、失敗したのであればなにがエラーの原因だったのかを見てましょう。


`src/backend/access/transam/xlog.c`にある`exitArchiveRecovery関数`を以下のように変更します。

```diff
diff --git a/src/backend/access/transam/xlog.c b/src/backend/access/transam/xlog.c
index 61ba6b852e..24fd8ea689 100644
--- a/src/backend/access/transam/xlog.c
+++ b/src/backend/access/transam/xlog.c
@@ -5550,7 +5550,10 @@ exitArchiveRecovery(TimeLineID endTLI, XLogRecPtr endOfLog)
 
        /* Get rid of any remaining recovered timeline-history file, too */
        snprintf(recoveryPath, MAXPGPATH, XLOGDIR "/RECOVERYHISTORY");
-       unlink(recoveryPath);           /* ignore any error */
+       int r;
+       r = unlink(recoveryPath);               /* ignore any error */
+       if (r < 0)
+               elog(WARNING, "unlink error!! %m");
 
        /*
         * Remove the signal files out of the way, so that we don't accidentally
```

ここではいわゆるprintfデバッグをして、`unlink関数`が失敗した場合にエラーメッセージを表示するようにしています。PostgreSQLでは`elog関数`を使ってprintfデバッグをすることが多いです。`elog関数`の第一引数にはエラーレベルを指定するのですが、私はいつも（面倒くさいので）WARNINGを指定しています。第二引数以降はprintfと同じです。

上記の変更を加えたPostgreSQLをビルドし、インストールします(ビルド時にwarningが出るかもしれませんが無視します)。そして、再度リカバリ手順を行うと以下のようなログが出力されます。

```
WARNING:  unlink error!! No such file or directory
```

上記のエラーメッセージ(`No such file or directy`)から、`RECOVERYHISTORY`ファイルをunlinkをする時点(`exitArchiveRecovery関数`の時点)には当該ファイルは存在していない、ということがわかります。つまり、**残念ながら仮説1（unlinkが失敗してファイルが残ってしまった説）は間違っていた**ということになります。

# 仮説2 - 削除後に再度作られた？-

仮説1は間違っていましたが、検証したことにより`exitArchiveRecovery関数`が呼ばれる時には`RECOVERYHISTORY`ファイルが存在していないことがわかりました。このことから、**「`exitArchiveRecovery関数`後に`RECOVERYHISTORY`ファイルが作られたために消されずに残った」**という次の仮説が生まれます。

では、どこで`RECOVERYHISTORY`ファイルは作られたのでしょうか？ソースコードから該当の箇所を探すことも可能ですが、この仮説が間違っていたら探しても見つからない可能性がありますし、今回は再現可能な事象でもありますので、コードを修正して実際に動かしてみながら探していきます。

## `exitArchiveRecovery関数`の後、いつ`RestoreArchivedFile関数`が呼ばれるのか？

前回の調査により、`RECOVERYHISTORY`ファイルは`RestoreArchivedFile関数`で作成されています。今回の調査では、**`exitArchiveRecovery関数`の後に呼ばれた`RestoreArchivedFile関数`でプロセスにデバッガでアタッチし、バックトレースを見ることで、いつどこで`RECOVERYHISTORY`ファイルが作られたのかを確認する**、という方針で調査します。

ただ一つ問題なのが`RestoreArchivedFile関数`はhistoryファイルだけでなく、リカバリに必要なWALのリストアも行う関数であるため、様々な所から呼ばることです。

`RestoreArchivedFile関数`の先頭にsleepを入れてその間にアタッチする、としたかったのですが、そうすると何度もsleepしてしまい時間がかかってしまいそうなので、以下のように少し工夫してsleepするコードを追加します。

```diff
diff --git a/src/backend/access/transam/xlogarchive.c b/src/backend/access/transam/xlogarchive.c
index 9a21f006d1..ad28f4cb2a 100644
--- a/src/backend/access/transam/xlogarchive.c
+++ b/src/backend/access/transam/xlogarchive.c
@@ -213,6 +213,12 @@ RestoreArchivedFile(char *path, const char *xlogfname,
 
        if (rc == 0)
        {
+               if (!InArchiveRecovery)
+               {
+                       elog(WARNING, "restoring %s!! %d", xlogfname, MyProcPid);
+                       pg_usleep(20 * 1000000L);
+               }
+
                /*
                 * command apparently succeeded, but let's make sure the file is
                 * really there now and has the correct size.
```

リストアが成功した場合(`rc == 0`)かつ、アーカイブリカバリが終了している(`!InArchiveRecovery`)時のみsleepするようにしています。`InArchiveRecovery`は`restoreArchivedFile関数`で`false`に設定されます。これにより、今回調査したい状況でのみ20秒間sleepさせることができます。

私はsleepする時はよく`pg_usleep関数`を使いますが、通常の`sleep関数`でも問題ありません。アタッチするプロセスのPIDを出力するために`MyProcPid`を使っています。

上記の変更を加えたPostgreSQLをビルドし、インストールします。そして、再度リカバリ手順を行うと、追加したデバッグログの出力とともに動作がストップします。そして、ストップしてる間に該当プロセスのバックトレースを見ます[^debug]。psコマンドで見るとわかるのですが、アタッチする対象のプロセスは`startup`プロセスです。

[^debug]: バックトレースを見るためにはconfigure時に`--enable-debug`を指定する必要があります。詳細は[こちら](https://qiita.com/sawada_masahiko/items/2fa99e422ec0eb35245c#%E3%82%BD%E3%83%BC%E3%82%B9%E3%82%B3%E3%83%BC%E3%83%89%E5%85%A5%E6%89%8B%E3%81%8B%E3%82%89%E8%B5%B7%E5%8B%95%E3%81%BE%E3%81%A7)をご参照ください。

```bash
:
WARNING:  restoring 00000002.history!! 20097
$ gdb -p 20097
GNU gdb (GDB) 8.3
Copyright (C) 2019 Free Software Foundation, Inc.
:
(gdb) bt
#0  0x00007f5d2c590e0b in select () from /usr/lib/libc.so.6
#1  0x00005634aea20918 in pg_usleep (microsec=20000000) at pgsleep.c:56
#2  0x00005634ae44b55e in RestoreArchivedFile (path=0x7ffcf05e52c0 "", xlogfname=0x7ffcf05e5280 "00000002.history",
    recovername=0x5634aea53d1d "RECOVERYHISTORY", expectedSize=0, cleanupEnabled=false) at xlogarchive.c:219
#3  0x00005634ae42881f in writeTimeLineHistory (newTLI=3, parentTLI=2, switchpoint=83886080,
    reason=0x7ffcf05e81c0 "no recovery target specified") at timeline.c:322
#4  0x00005634ae442337 in StartupXLOG () at xlog.c:7493
#5  0x00005634ae76dcc5 in StartupProcessMain () at startup.c:207
#6  0x00005634ae458b67 in AuxiliaryProcessMain (argc=2, argv=0x7ffcf05e8690) at bootstrap.c:451
#7  0x00005634ae76cac3 in StartChildProcess (type=StartupProcess) at postmaster.c:5414
#8  0x00005634ae7672a1 in PostmasterMain (argc=3, argv=0x5634b03a19a0) at postmaster.c:1383
#9  0x00005634ae66e472 in main (argc=3, argv=0x5634b03a19a0) at main.c:210
(gdb)
```

仮説2は正しかったようです！`exitArchiveRecovery関数`の直後に呼ばれる`writeTimeLineHistory関数`からの呼び出しで`RECOVERYHISTORY`ファイルが作成されていました(バックトレースの#3の所)。**`exitArchiveRecovery関数`で不要（一時）ファイルの掃除がされていましたが、その後に作られたため最後まで残ってしまったのですね。**

```c
       /*
        * We are now done reading the old WAL.  Turn off archive fetching if
        * it was active, and make a writable copy of the last WAL segment.
        * (Note that we also have a copy of the last block of the old WAL in
        * readBuf; we will use that below.)
        */
       exitArchiveRecovery(EndOfLogTLI, EndOfLog);

       /*
        * Write the timeline history file, and have it archived. After this
        * point (or rather, as soon as the file is archived), the timeline
        * will appear as "taken" in the WAL archive and to any standby
        * servers.  If we crash before actually switching to the new
        * timeline, standby servers will nevertheless think that we switched
        * to the new timeline, and will try to connect to the new timeline.
        * To minimize the window for that, try to do as little as possible
        * between here and writing the end-of-recovery record.
        */
       writeTimeLineHistory(ThisTimeLineID, recoveryTargetTLI,
                            EndRecPtr, reason);

```

# まとめ

仮説→検証を繰り返すことでバグの原因をコードレベルで突き止める事ができました！ここまで来たら後は修正するだけです。修正する際には、コードの修正だけでなくいつこのバグが作り込まれたのか、、どのバージョンが影響を受けるのか、も見るようにしています。

次回はもう少し問題となったコードを調べ、修正してみます。
