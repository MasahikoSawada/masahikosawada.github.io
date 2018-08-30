---
layout: post
title: DeadlockとDeadLock対策のメモ
tags:
  - Database
  - Deadlock
---

簡単に調べたのでメモ。「Deadlockとは？」は色んなところで解説されているのでここでは割愛。

# Deadlockの必要条件(Coffman conditions)
* Mutual Exclusion
  * 一度に1つのプロセスのみがリソースを使用できる
* Hold and Wait
  * なにか一つのリソースを**保持したまま**他のリソースを待つ
* No preemption
  * リソースの横取りができない
* Circular wait
  * リソースの保持待ちが循環している。あるP1がP2によって保持されているリソースを待ち、P2がP3に保持されているリソースを待ち・・・が循環する。

※Deadlockは、Circular waitが解消できない状況でのみ発生する

※Circular waitは他の3つの条件が満たされているときに「解消できなくなる」

# Deadlock対策
大きく分けて3つの対策がある。
* Deadlock Prevention
* Deadlock Avoidance
* Deadlock Detection

以下1つずつ解説。

# Deadlock Prevention
Deadlock Preventionは、Deadlockの4つの必要条件をの内少なくとも1つが真でないことを保証することでDeadLockno発生自体を防ぐ事。
* Mutual Exclusion
  * 排他制御をなくす
  * 例えば、「一方が使っている間は他方は使えない」という状況（排他制御）がなければ、そもそもロック待ちが発生しないので、Deadlockも発生しない。
* Hold and Wait
  * 「確保した状態でその他を待つ」という状況をなくす
  * 方法は2通りある。
    1. プロセスが必要とするすべてのリソースを**実行前**に確保する。
       * ただし、必要ないリソースも確保している可能性があるので、スループットは下がる傾向がある
    2. プロセスがリソースを必要とするとき**そのリソースが誰にも確保されていないとき**にだけ、要求する
       * ただし、すべてのリソースが自由に使えるわけではないので、starvation（飢餓状態）になる可能性がある。
* No preemption
  * No preemptionは、「リソースはプロセスが自分の仕事が完了した後にのみリソースを開放する」ことを意味する。
    * つまり、誰か他の取得待ちのプロセスによる横取り等が発生しない
  * 例えば、なにか優先度の高いプロセスは常にリソースを横取りできる、とすることで防ぐ
* Circular wait
  * 循環待機を避ける
  * すべてのリソースに番号を付けて、番号が昇順になる順序でしかリソースを確保できないようにする。
    * 例えば、R3を一度取得してしまったら、R1, R2を取得することはできず、R4以上でないと取得できない。

## Wait-die, Wound-wait、No-wait
Wait-dieとWound-waitは、タイムスタンプをベースに「No preemption」の条件を排除するスキーム

基本的なアイディアは、「プロセスが他のプロセスが使用しているリソースの待機をブロックしようとしているとき、より大きなタイムスタンプ（つまり若い）を持つかどうかをチェックする」

前提として、全てのプロセスはタイムスタンプはあるタイムスタンプを持っていて、低いタイムスタンプを持つプロセスのほうが優先度が高い（完了までの時間が短い可能性が高い）とする。

### Wait-Die
あるリソースを要求するプロセスPaと、すでにリソースを保持しているプロセスPbが存在したとき、
* TS(Pa) < TS(Pb) : Paのほうが古い（優先度が高い）
  * PaはPbの開放を待つ(Wait)
* TS(Pa) > TS(Pb) : Paのほうが若い（優先度が低い）
  * Paは自ら諦めて、再度要求する(Die)。ただしそのときのタイムスタンプは同じで再要求する。

※ここでTS(Px)はプロセスPxがタイムスタンプを表す

つまり、Wait-Dieではより古いプロセスのみが**待つことができる**。

### Wound-Wait
あるリソースを要求するプロセスPaと、すでにリソースを保持しているプロセスPbが存在したとき、
* TS(Pa) < TS(Pb) : Paのほうが古い（優先度が高い）
  * PaはPbを終了させ、自分がリソースを取得する(Wound)
  * 終了されたPbは再度（タイムスタンプは同じで）要求を開始するが、依然TS(Pa) < TS(Pb)であるのは変わらないのでPaの開放を待つ
* TS(Pa) > TS(Pb) : Paのほうが若い（優先度が低い）
  * PaはPbの開放を待つ(Wait)

つまり、より古いプロセスは新しいプロセスからリソースを**横取りすることができ**、新しいプロセスは古いプロセスが終了するまで待たされる。

一般にWound-Waitのほうが良いスキームだと言われているらしい。Google SpannerはWound-Waitらしい[^spanner]。

両方共、Starvationが発生しないように、再実行時に**同じタイムスタンプを使う**ところに注意。

[^spanner]:https://cloud.google.com/spanner/docs/whitepapers/life-of-reads-and-writes

### No-wait
ロックを取得した際にロックが取れなかったらアボートする。

# Deadlock Avoidance
ロックを取得する前に、Deadlockが起こらない安全な状態であるかを検査する。つまり、deadlockを**起こすかもしれない**場合は、リソースの要求を拒絶するか遅延することでDeadlockを回避する。
Banker's Algorithm[^bankers_algorithm]という有名なアルゴリズムがある。
安全な状態とは、ある順序で資源を確保すればDeadlockにならない、という状態。

アルゴリズムの詳細はあとでよく読んでおく。

[^bankers_algorithm]: https://ja.wikipedia.org/wiki/%E9%8A%80%E8%A1%8C%E5%AE%B6%E3%81%AE%E3%82%A2%E3%83%AB%E3%82%B4%E3%83%AA%E3%82%BA%E3%83%A0

# Deadlock Detection
Deadlockが発生するのは許容するがそれを検知する、という戦略。検知した後は、recovery algorithmを実行する。
PostgreSQLやMySQLはDeadlock Detectionを採用[^deadlock_detection]。

* 定期的にwait-for-graphを作り、循環があるかどうかを検査する
  * 循環があるかどうかを確認するには、O(N^2)かかる

* Recovery Algorithm
  * DeadlockのすべてのプロセスをAbortする
  * Deadlockが解消するまで一つずつプロセスをAbortする
  * いくつかのルールに基づき、Abortするプロセスを決定する
    * プロセスの優先度（どれくらい長く処理shているかなど）
    * プロセスが使ったリソース数
    * どれくらいのプロセスを終了する必要があるかどうか

[^deadlock_detection] MySQLにはWFGの作成にはコストがかかるのでtimeoutを設定できる機能もあるとのことです（おそらくPostgreSQLでも同様の設定ができる）

# 参考
全部は見切れていないのであとで勉強する。
* [System Deadlocks](https://people.cs.umass.edu/~mcorner/courses/691J/papers/TS/coffman_deadlocks/coffman_deadlocks.pdf)
* [Deadlock Prevention And Avoidance](https://www.geeksforgeeks.org/deadlock-prevention/)
* [Deadlock Detection And Recovery](https://www.geeksforgeeks.org/deadlock-detection-recovery/)
* [Deadlock Prevention, Avoidance, Detection and Recovery in Operating Systems](https://javajee.com/deadlock-prevention-avoidance-detection-and-recovery-in-operating-systems)
* [Deadlock Prevention](http://www.cs.colostate.edu/~cs551/CourseNotes/Deadlock/WaitWoundDie.html)
* [デッドロック対策](https://qiita.com/kumagi/items/1b45352160c101928d7e)

次は分散Deadlockを調べよう。

(2018-08-30) Twitter上でご指摘頂いた点（typo、MySQLのDeadlock検知）について修正しました。