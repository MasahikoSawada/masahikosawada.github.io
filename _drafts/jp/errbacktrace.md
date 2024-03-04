---
layout: post
title: PostgreSQLで関数が呼び出されたパスを確認する方法
tags:
  - PostgreSQL
---

答え:`errbacktrace()`を`ereport()`の中で利用する。

例えば、`array_exec_setup()`がどうやって呼ばているのかを確認する場合は、以下のようなデバッグログを入れる。

```diff
@@ -477,6 +480,10 @@ array_exec_setup(const SubscriptingRef *sbsref,
    bool        is_slice = (sbsrefstate->numlower != 0);
    ArraySubWorkspace *workspace;

+   ereport(LOG,
+           errmsg("test"),
+           errbacktrace());
+
```

PostgreSQLをビルド、再起動すると、このログが出るときにBacktraceも出してくれるようになる。

```
[3200111] LOG:  test
[3200111] BACKTRACE:
        postgres: masahiko postgres [local] SELECT(errbacktrace+0x4f) [0x935dcf]
        postgres: masahiko postgres [local] SELECT() [0x8477b1]
        postgres: masahiko postgres [local] SELECT() [0x67c69b]
        postgres: masahiko postgres [local] SELECT(ExecBuildProjectionInfo+0xc1) [0x67e8f1]
        postgres: masahiko postgres [local] SELECT(ExecConditionalAssignProjectionInfo+0x116) [0x694f86]
        postgres: masahiko postgres [local] SELECT(ExecInitSeqScan+0x90) [0x6b7460]
        postgres: masahiko postgres [local] SELECT(ExecInitNode+0x3c8) [0x68f368]
        postgres: masahiko postgres [local] SELECT(standard_ExecutorStart+0x32f) [0x688eaf]
        postgres: masahiko postgres [local] SELECT(PortalStart+0x17e) [0x815f1e]
        postgres: masahiko postgres [local] SELECT() [0x812d75]
        postgres: masahiko postgres [local] SELECT(PostgresMain+0x883) [0x813993]
        postgres: masahiko postgres [local] SELECT() [0x793661]
        postgres: masahiko postgres [local] SELECT(PostmasterMain+0xc12) [0x794d82]
        postgres: masahiko postgres [local] SELECT(main+0x1ee) [0x4f2e7e]
        /lib64/libc.so.6(__libc_start_main+0xf3) [0x7f2e562facf3]
        postgres: masahiko postgres [local] SELECT(_start+0x2e) [0x4f315e]
[3200111] STATEMENT:  select c[2] from a;
```

`errbacktrace()`便利！
