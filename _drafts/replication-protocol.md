---
layout: post
title: ストリーミングレプリケーションプロトロルで遊んでみる
tags:
  - PostgreSQL
  - Replication
---

PostgreSQLには物理レプリケーションと論理レプリケーションの2種類のレプリケーションがありますが、どちらもサーバ間の通信にはストリーミングレプリケーションプロトロル（以下、長いのでレプリケーションプロトロルとします）を使用して、データを送っています。

```
+---------+  Replication Protocol   +---------+
| primary | ----------------------> | replica |
+---------+                         +---------+
```

# レプリケーションプロトロルで接続してみる

クライアントがPostgreSQLサーバに接続するのと同じようにPostgreSQLサーバに接続要求を出しますが、接続文字列に`replication`パラメータを使用します。例えば、`psql`を使ってレプリケーションプロトロルが使えるように接続することもできます。

```
% psql -d "dbname=postgres replication=database"
psql (16devel)
Type "help" for help.

postgres(1:1636174)=#
```

`replication=database`としている所がポイントです。これで論理レプリケーションが使えるモードに入ります。`replication=on`とすると、物理レプリケーションのモードに入ります。

`psql`で接続したままそれに対応するPostgreSQLのサーバプロセスを確認すると、walsenderが起動していることがわかります（`psql`のプロンプトに出ている1636174が接続しているPostgreSQLのサーバプロセスです）。

```
% ps x | grep 1636174
1636174 ?        Ss     0:00 postgres: walsender masahiko postgres [local] idle
```

このように、PostgreSQLではレプリケーションプロトロルを利用できるように接続すると、クライアントはwalsenderプロセスを通信することになります。

# レプリケーションプロトロルでは何ができる？

指定する`replication`パラメータによって、物理walsenderモードと論理walsenderモードに別れます。どちらもモードでもレプリケーションコマンドは使えますが、論理walsenderモードではそれに加えて通常のSQLを実行することができます。

レプリケーションプロトロルで使えるコマンドの一覧は[公式ドキュメント](https://www.postgresql.jp/document/14/html/protocol-replication.html)に載っていて、例えば物理レプリケーションを開始したいときは、`START_REPLICATION`コマンドを使用します。

```
% bin/psql -d "dbname=postgres replication=on" # 物理walsenderモード
psql (16devel)
Type "help" for help.

postgres(1:1636516)=# IDENTIFY_SYSTEM;
      systemid       | timeline |  xlogpos   | dbname
---------------------+----------+------------+--------
 7218079788637499376 |        1 | F/FE96A3E0 |
(1 row)

postgres(1:1636516)=# select version();
ERROR:  cannot execute SQL commands in WAL sender for physical replication
```

```
% psql -d "dbname=postgres replication=database" # 論理walsenderモード
psql (16devel)
Type "help" for help.

postgres(1:1636464)=# IDENTIFY_SYSTEM;
      systemid       | timeline |  xlogpos   |  dbname
---------------------+----------+------------+----------
 7218079788637499376 |        1 | F/FE96A3E0 | postgres
(1 row)

postgres(1:1636464)=# select version();
                                     version
---------------------------------------------------------------------------------
 PostgreSQL 16devel on x86_64-pc-linux-gnu, compiled by gcc (GCC) 12.2.0, 64-bit
(1 row)
```

# レプリケーションコマンドを使ってレプリケーションしてみる

ここまで紹介した内容でレプリケーションコマンドが使える様になったので、PostgreSQLの物理レプリケーションや論理レプリケーションが内部でやっていることは`psql`でもできそうです。試しに`psql`を使って論理レプリケーションをやってみたいと思います。手順は簡単で、まずレプリケーションスロットを作成し、それを使ってレプリケーションを開始するだけです。

```
% psql -d "dbname=postgres replication=database" # 論理walsenderモードで接続
psql (16devel)
Type "help" for help.

postgres(1:1636464)=# CREATE_REPLICATION_SLOT myslot LOGICAL test_decoding; -- test_decodingというプラグインを使ってスロットを作成
 slot_name | consistent_point |    snapshot_name    | output_plugin
-----------+------------------+---------------------+---------------
 myslot    | F/FE96C5A8       | 00000003-00000002-1 | test_decoding
(1 row)

postgres(1:1636464)=# START_REPLICATION SLOT myslot LOGICAL 0/0; -- レプリケーションを開始
unexpected PQresultStatus: 8
```

`START_REPLICATION`コマンドを使ってレプリケーションを開始しようとしたのですが、`unexpected PQresultStatus: 8`というメッセージが出て止まってしまいました。これは、`psql`がレプリケーションプロトロルに対応していないことが原因で出た、`psql`のエラーです。

# レプリケーションコマンドを使ってレプリケーションしてみる（リベンジ）

せっかくなので、簡単なクライアントプログラムを使って論理レプリケーションのデータを受信してみます。

論理walsenderモードを使ってPostgreSQLサーバに接続し、`CREATE_REPLICATION_SLOT`コマンドでレプリケーションスロットを作成した後、`START_REPLICATION`コマンドで受信を開始します。`START_REPLICATION`コマンドが成功すると結果は`PGRES_COPY_BOTH`となり、これはレプリケーションプロトロルでのみ利用されます（サーバからもクライアントからもデータを贈り合う、という意味）。`psql`はこれに対応していないため、`unexpected PQresultStatus: 8`を出していました(`PGRES_COPY_BOTH`は8です[コードはこちら](https://github.com/postgres/postgres/blob/master/src/interfaces/libpq/libpq-fe.h#L109))。

レプリケーションプロトロルは、libpq的には`COPY ... TO stdin`のような感じで動くので、データの受信には`PQgetCopyData()`が利用できます。受信したデータのヘッダを覗いて出力します。

```c
#include "libpq-fe.h"
#include <stdlib.h>
#include <stdio.h>

int main()
{
    PGresult *res;
    PGconn *conn;
    char *buf = NULL;

    conn = PQconnectdb("dbname=postgres replication=database");
    if (PQstatus(conn) != CONNECTION_OK)
    {
        fprintf(stderr, "connection error: %s", PQerrorMessage(conn));
        exit(1);
    }

    res = PQexec(conn, "CREATE_REPLICATION_SLOT myslot LOGICAL test_decoding");
    if (PQresultStatus(res) != PGRES_TUPLES_OK)
    {
        fprintf(stderr, "could not create logical replication slot: %s",
                PQresultErrorMessage(res));
        exit(1);
    }

    res = PQexec(conn, "START_REPLICATION SLOT myslot LOGICAL 0/0");
    if (PQresultStatus(res) != PGRES_COPY_BOTH)
    {
        fprintf(stderr, "could not start replication: %s",
                PQresultErrorMessage(res));
        exit(1);
    }
    PQclear(res);

    for (;;)
    {
        int r;

        if (buf != NULL)
        {
            PQfreemem(buf);
            buf = NULL;
        }

        r = PQgetCopyData(conn, &buf, 0);
        if (r <= 0)
            break;

        /* ignore other than decoded WAL data */
        if (buf[0] != 'w')
            continue;

        /* the message header is 24 bytes */
        printf("%s\n", &(buf[25]));
    }

    if (buf != NULL)
        PQfreemem(buf);

    PQfinish(conn);
    return 0;
}
```

これをコンパイルして実行します（libpqライブラリのパスは調整してください）。

```zsh
% gcc -o test test.c -L/usr/local/pgsql/lib -lpq
% ./test

```

プログラム実行直後は何も出力されませんが、サーバ側でなにかテーブルを変更すると、そのWALをデコードしたデータがサーバから送信され、それが表示されます。

```
% psql
postgres(1:1709135)=# create table test (c int);
CREATE TABLE
postgres(1:1709135)=# insert into test values (1);
INSERT 0 1
postgres(1:1709135)=# insert into test values (2);
INSERT 0 1
```

出力されるデータの形式はデコーディング・プラグインによって変わります。今回は、PostgreSQLに同梱されている`test_decoding`を使っています。この他にも[wal2json](https://github.com/eulerto/wal2json)を使うと、JSON形式でデータを取得できます。

```
% gcc -o test test.c -L/usr/local/pgsql/lib -lpq
% ./test
BEGIN 766
COMMIT 766
BEGIN 767
table public.test: INSERT: c[integer]:1
COMMIT 767
BEGIN 768
table public.test: INSERT: c[integer]:2
COMMIT 768
```

サンプルプログラムはCtl-cで終了できます。

# まとめ

ストリーミングレプリケーションプロトロルで遊んでみました。

PostgreSQLには`pg_recvlogical`という論理レプリケーションをするクライアントプログラムが同梱されています。最後に作ったサンプルプログラムは、`pg_recvlogical`をかなり単純化したものと言えます。
