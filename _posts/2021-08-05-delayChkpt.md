---
layout: post
title: `MyProc->delayChkpt`についての理解と覚書
tags:
  - PostgreSQL
  - Source Code Reading
---

PostgreSQLのコードを読んでいるとたまに`MyProc->delayChkpt`と一旦`true`にして、いくつか処理をしたあとに再び`false`に戻す、という処理を見ることがあります。

例えば、PostgreSQLのトランザクションのコミットのコードを（かなり省略して書くと）以下のような流れになっていて、コミットのWALレコードを書く（`XactLogCommitRecord()`）の処理と、それのディスクへのFlush（`XLogFlush()`）、pg_xact（以前はpg_clogと呼ばれていたもの）を更新する処理（`TransactionIdCommitTree()`）の一連の処理の間`MyProc->delayChkpt`を`true`にしています。

```c
    MyProc->delayChkpt = true;

    XactLogCommitRecord(xactStopTimestamp,
                        nchildren, children, nrels, rels,
                        nmsgs, invalMessages,
                        RelcacheInitFileInval,
                        MyXactFlags,
                        InvalidTransactionId, NULL /* plain commit */ );

    XLogFlush(XactLastRecEnd);

    TransactionIdCommitTree(xid, nchildren, children);

    MyProc->delayChkpt = false;
```

`MyProc->delayChkpt = true`をすると、実行中のCHECKPOINTを止めることができます。CHECKPOINTを実行するコード（`CreateCheckPoint()`）には、以下のようなコードが入っていて、バッファやpg_xactなどをFlushする処理（`CheckPointGuts()`）の前で`MyProc->delayChkpt = true`となっているプロセスを探してそれらがすべて`false`にするまで待つ、という挙動になっていることがわかります。

```c
    vxids = GetVirtualXIDsDelayingChkpt(&nvxids);
    if (nvxids > 0)
    {
        do
        {
            pg_usleep(10000L);	/* wait for 10 msec */
        } while (HaveVirtualXIDsDelayingChkpt(vxids, nvxids));
    }
    pfree(vxids);

    CheckPointGuts(checkPoint.redo, flags);
```

では、なぜトランザクションのコミットは、コミットのWALレコードをディスクに書いて、pg_xactログを更新するまでCHECKPOINTの動作を止める必要があるのか？それについての覚書です。

# PostgreSQLにおけるトランザクションのコミット
PostgreSQLでは、トランザクションのコミット時に「XID=100のトランザクションはコミットされた」という情報をpg_xactログに書きます。

pg_xactログは各トランザクションのステータス（コミットされたのか実行中なのかなど）を保持しているモジュールで、テーブルやインデックスと同様に共有バッファにバッファされ、バッファから追い出される時やCHECKPOINT時にディスクに書かれます。PostgreSQLでは各トランザクションの状態をトランザクションにつき2 bitsで表している[^clog]ため、トランザクションのコミット時はそのbitを更新するだけです（bitの更新はAtomicになる）。つまり、PostgreSQLではトランザクション内でどれだけデータを更新しても、そのトランザクションがコミットされたという記録は、pg_xactログ内のそのトランザクションに対応する2 bitsを更新すれば良いだけということになります。

[^clog]: `0x00` = 進行中、`0x01` = コミット済み、のような感じ

ただ、pg_xactログ自体はメモリ上にありCHECKPOINTのタイミングでディスクに書き出されます。なので、ディスクに書き出される前にサーバがクラッシュすると、トランザクションをコミットしたという情報を失ってしまうことになります。

そのため、PostgreSQLはトランザクションのコミットWALを書きます。コミットのWALレコードにはXIDが記載されているので、クラッシュした場合でもそのWALレコードを再生すれば「XID=100のトランザクションがコミットされた」という状況をリカバリ（回復）できます。

# PostgreSQLのCHECKPOINT

CHECKPOINTでは、共有バッファに乗っているテーブルやインデックスのデータや前述したpg_xactのデータをディスクに書き出して永続化します。PostgreSQLでは、CHECKPOINTはcheckpointerと呼ばれる専用のプロセスが定期的に実行するようになっています（手動てももちろんできます）。

CHECKPOINTがあることで、サーバがクラッシュした後のリカバリ時間を短縮することができます。CHECKPOINTがなかったら（例えば月次で取っている）バックアップからリカバリするしかありません。しかし、例えば30分毎にCHECKPOINTが走った場合、サーバがクラッシュしてもサーバは前回のCHECKPOINT時点からリカバリを開始できるので、30分間の間に変更されたトランザクションだけをリカバリすれば良いです。

# CHECKPOINTとWALとpg_xactの競合

ここからが本題ですが、これまで説明した「pg_xactのbitを更新する処理」、「コミットWALをディスクに書き出す処理」、「CHECKPOINTがpg_xactのデータをディスクに書き出す処理」は、実行する順序がとても大切です。

必ず、

1. コミットWALをディスクに書き出す
2. pg_xactログのbitを更新
3. CHECKPOINTが走る

または、

1. CHECKPOINTが走る
2. コミットWALをディスクに書き出す
3. pg_xactログのbitを更新

の順序で起こらなくてはいけません。つまり、「pg_xactのbitを更新する処理」→「コミットWALをディスクに書き出す処理」の順序で行う必要があり、かつ、その間にCHECKPOINTによる処理が入り込んではいけません。「pg_xactのbit更新処理」と「コミットWALの書き出し処理」は同じプロセスが行うので、そのような順序にコードを書くだけで良いですが、CHECKPOINTはcheckpointerプロセスがバックグラウンドで走るので、タイミングによっては間に入ってしまう可能性があります。

冒頭で紹介した`MyProc->delayChkpt`はまさにこのためにある変数で、トランザクションを処理する各プロセスはコミット時に、コミットWALを書く処理とpg_xactを更新する処理の間にCHECKPOINTが入り込まないようにこの変数を`true`にします。

これらの処理の順序が守られないとどういう状況が起こるかを考えてみます。

## WALを書く前にpg_xactログを更新する場合

1. pg_xactログのbitを更新
2. コミットWALをディスクに書き出す
3. CHECKPOINTが走る

例えば、上記のように、コミットWALを書く前にpg_xactログのbitを更新したケースの場合、1の直後から他のトランザクションは「そのトランザクションがコミットされた」と知ることができますが、2の前にサーバがクラッシュするとトランザクションがコミットされた情報は消える（リカバリできない）ので、先程コミットされていたトランザクションはアボートされている、という状況になってしまいます。さらに、1の直後にpg_xactログがバッファから追い出されて変更が永続化される可能性もあり、その直後（コミットWALを書く前）にサーバがクラッシュすると、ディスク上のpg_xactだけが更新されているけどWALに情報は残っていない、という状況になってしまいます。そのため、バックアップからリカバリする際にはその情報は失われます。

## CHECKPOINTが間に入る場合

1. コミットWALをディスクに書き出す
2. CHECKPOINTが走る
3. pg_xactログのbitを更新

CHECKPOINT実行時にはpg_xactの内容は更新されていないので、この時点では更新前のpg_xactログの内容をディスクに書き出します。その直後（3の前）にサーバがクラッシュすると、サーバは2で実行したCHECKPOINTからリカバリを開始します。そうすると、1で書いたコミットWALは**CHECKPOINTより前**なので適用されません。なので、トランザクションはアボートされたことになります。しかし、もし昔に取ったバックアップを持っていてそこからデータベースをリカバリすると、1で書いたコミットWALは再生されるので「トランザクションはコミットされた」ことになります。リカバリ開始時点によってリカバリ後のデータベースの状況が変わってしまいます。

# 最後に

`MyProc->delayChkpt`がなぜあるのかについての覚書でした。この変数を使ったやり方は、「pg_xactログの更新＋コミットWALの書き出し」以外の箇所にも使われています。例えば、2相コミットでトランザクションをPREPAREDした際には、「2相コミットの情報が記載されたファイル」と「トランザクションをPREPAREするWAL」も同じような関係になるため、`MyProc->delayChkpt`が使われています。
