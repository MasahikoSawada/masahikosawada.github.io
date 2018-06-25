---
layout: post
title: Deadlock
tags:
  - Database
  - Deadlock
---

# Deadlock Prevention
Deadlock Preventionは、以下の条件(Coffman Condition)の内少なくとも1つが真でないことを保証することでDeadLockの発生を防ぐこと。
* Mutual Exclusion
  * 排他制御をなくす
  * 「一方が使っている間は他方は使えない」という状況（排他制御）がなければ、そもそもロック待ちが発生しないので、Deadlockも発生しない。
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
* Circular wait
  * 循環待機を避ける
  * すべてのリソースに番号を付けて、番号が昇順になる順序でしかリソースを確保できないようにする。
    * 例えば、R3を一度取得してしまったら、R1, R2を取得することはできず、R4以上でないと取得できない。

* Deadlockは、Circular waitが解消できない状況でのみ発生する
* Circular waitは他の3つの条件が満たされているときに「解消できなくなる」

## Wait-die, Wound-wait
これは、タイムスタンプをベースに「No preemption」の条件を排除するスキーム

基本的なアイディアは、「プロセウスが他のプロセスが使用しているリソースの待機をブロックしようとしているとき、より大きなタイムスタンプ（つまり若い）を持つかどうかをチェックする」

前提として、全てのプロセスはタイムスタンプはあるタイムスタンプを持っていて、低いタイムスタンプを持つプロセスのほうが（完了までの）優先度が高いとする。

### Wait-Die
要求するプロセスPaと、すでにリソースを保持しているプロセスPbが存在したとき、
* TS(Pa) < TS(Pb) : Paのほうが古い（優先度が高い）
  * PaはPbの開放を待つ(Wait)
* TS(Pa) > TS(Pb) : Paのほうが若い（優先度が低い）
  * Paは自ら諦めて、再度要求する(Die)。ただしそのときのタイムスタンプは同じで再要求する。

つまり、より古いプロセスのみが待つことができる。

### Wound-Wait
要求するプロセスPaと、すでにリソースを保持しているプロセスPbが存在したとき、
* TS(Pa) < TS(Pb) : Paのほうが古い（優先度が高い）
  * PaはPbを終了させ、自分がリソースを取得する(Wound)
  * 終了されたPbは再度（タイムスタンプは同じで）要求を開始するが、依然TS(Pa) < TS(Pb)であるのは変わらないのでPaの開放を待つ
* TS(Pa) > TS(Pb) : Paのほうが若い（優先度が低い）
  * PaはPbの開放を待つ(Wait)

つまり、より古いプロセスは新しいプロセスからリソースを横取りすることができ、新しいプロセスは古いプロセスが終了するまで待たされる。

一般に、Wound-Waitのほうが良いスキームだと言われている。

Stravationが発生しないように、再実行時に**同じタイムスタンプを使う**ところに注意。

## アルゴリズム
* Banker's algorithm
* Preventiong recursive locks

# Deadlock Avoidance
deadlockを**起こすかもしれない**要求をしない。

## Banker&s Algorithm

# Deadlock Detection
Deadlockが発生するのは許容するが、それを検知する戦略。検知した後は、recovery algorithmを実行する。

* 定期的にWFGを作り、循環があるかどうかを検査する
  * 循環があるかどうかを確認するには、O(N^2)かかる

* Recovery Algorithm
  * DeadlockのすべてのプロセスをAbortする
  * Deadlockが解消するまで一つずつプロセスをAbortする
  * いくつかのルールに基づき、Abortするプロセスを決定する
    * プロセスの優先度（どれくらい長く処理shているかなど）
    * プロセスが使ったリソース数
    * どれくらいのプロセスを終了する必要があるかどうか

# 参考
* [System Deadlocks](https://people.cs.umass.edu/~mcorner/courses/691J/papers/TS/coffman_deadlocks/coffman_deadlocks.pdf)
  * Coffman Condition
* [Deadlock Prevention And Avoidance](https://www.geeksforgeeks.org/deadlock-prevention/)
* [Deadlock Prevention, Avoidance, Detection and Recovery in Operating Systems](https://javajee.com/deadlock-prevention-avoidance-detection-and-recovery-in-operating-systems)
* [Concurrency Control in Distributed Database Systems](https://people.eecs.berkeley.edu/~kubitron/cs262/handouts/papers/concurrency-distributed-databases.pdf)
* [Deadlock Prevention](http://www.cs.colostate.edu/~cs551/CourseNotes/Deadlock/WaitWoundDie.html)