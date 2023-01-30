---
layout: post
title: PostgreSQLの色んなINSERTの仕方
tags:
  - PostgreSQL
---

# 使用するテーブル

今回は`int`と`text`の列を持ったテーブルを使います。列`a`にはインデックスが付いています。INSERTするデータはどれも共通して`1'`と`'alice'`にします。

```sql
CREATE TABLE test (a int primary key, b text);
```

# SQLでINSERTを実行

これが最も簡単な方法です。PostgreSQLサーバを起動し、`psql`で接続して`INSERT`を実行します。

```sql
=# INSERT INTO test VALUES (1, 'alice');
INSERT 1
=# SELECT * FROM test;
 a |   b
---+-------
 1 | alice
(1 row)
```

# SPIでINSERTを実行

ここからはサーバ内で実行するプログラムを自分で書いて、その中で`INSERT`を実行します。

SPI(Server Programming Interface)は、C言語で書かれたユーザ定義関数からSQLを実行する機能です。PostgreSQLの内部処理でも利用されており、`REFRESH MATERIALIZED VIEW CONCURRENTLY`でマテリアライズド・ビューとテーブルの差分を取得する所や、PL/pgSQLの内部処理でも使われています。

SPIの使い方は非常に簡単で、`SPI_connect()`で接続し、`SPI_execute()`でSQLを実行します。

```c
Datum
insert_spi(PG_FUNCTION_ARGS)
{
    SPI_connect();

    SPI_execute("INSERT INTO test VALUES (1, 'alice');", false, 1);

    SPI_finish();

    PG_RETURN_VOID();
}

```

C言語で書かれたユーザ定義関数をコンパイルして、サーバにロードする方法は最後にまとめて記載します。テーブルをTRUNCATEした後、`insert_spi()`関数を実行します。

```sql
=# SELECT insert_spi();
 insert_spi
------------

(1 row)
```

「SQLでINSERTを実行」ではクライアントがSQLを送信してサーバ上で実行しているのに対し、「SPIでINSERTを実行」はサーバ上でSQLを指定してサーバ上で実行しています。SQLを実行していることに違いはないので、SQLのパース、時刻プランの作成、実行プランの実行が`SPI_execute()`の中では行われています。

# Executorを直接叩いてINSERT

次はもう少し下のレイヤーに行き、Executorを直接使ってINSERTしてみます。

```c
Datum
insert_executor(PG_FUNCTION_ARGS)
{
    Relation rel;
    Oid nspid, relid;
    EState *estate;
    ResultRelInfo *relinfo;
    RangeTblEntry *rte;
    TupleTableSlot *slot;

    /* Open table "test" */
    nspid = get_namespace_oid("public", false);
    relid = get_relname_relid("test", nspid);
    if (!OidIsValid(relid))
        elog(ERROR, "table \"%s\" does not exist", "test");
    rel = table_open(relid, RowExclusiveLock);

    /* Set up executor state */
    estate = CreateExecutorState();
    rte = makeNode(RangeTblEntry);
    rte->rtekind = RTE_RELATION;
    rte->relid = relid;
    rte->relkind = rel->rd_rel->relkind;
    rte->rellockmode = RowExclusiveLock;
    ExecInitRangeTable(estate, list_make1(rte));
    relinfo = makeNode(ResultRelInfo);
    InitResultRelInfo(relinfo, rel, 1, NULL, 0);
    estate->es_opened_result_relations =
        lappend(estate->es_opened_result_relations, relinfo);
    estate->es_output_cid = GetCurrentCommandId(false);

    /* fill input data to tuple slot */
    slot = ExecInitExtraTupleSlot(estate,
                                  RelationGetDescr(rel),
                                  &TTSOpsVirtual);
    ExecClearTuple(slot);
    slot->tts_values[0] = Int32GetDatum(1);
    slot->tts_isnull[0] = false;
    slot->tts_values[1] = CStringGetTextDatum("alice");
    slot->tts_isnull[1] = false;
    ExecStoreVirtualTuple(slot);

    /* Execute insertion */
    ExecOpenIndices(relinfo, false);
    ExecSimpleRelationInsert(relinfo, estate, slot);
    ExecCloseIndices(relinfo);

    /* Clean up */
    ExecResetTupleTable(estate->es_tupleTable, false);
    FreeExecutorState(estate);
    table_close(rel, NoLock);

    PG_RETURN_VOID();
}
```

SPIを使ったプログラムに比べるとだいぶ書く量が増えました。この関数では、パーサ、プランナをスキップしてExecutorに必要な情報を準備して、直接Executorを実行することでINSERTしています。そのため、まずテーブルのOidを探すことからはじめ、INSERTのためにテーブルをロック、そしてExecutorに渡すためのデータ（`EState`や`ResultRelInfo`）を準備しています。

通常INSERTを実行するとプランナは`ExecModifyTable()`でINSERTを実行するのですが、ここでは簡単のために`ExecSimpleRelationInsert()`でINSERTを実行しています。

準備することが多いですがExecutorを使ってINSERTしているので、それよりも下のレイヤーのことは考えなくて良くなっています。例えば、テーブルについているインデックスへのINSERT、空き領域が十分あるページを取得、そのページへの挿入、INSERTのWALを書く、あたりの動作はすべて`ExecSimpleRelationInsert()`の中でやってくれています。さらに、INSERTするタプルは`TableTupleSlot`というデータを使って作成しています。コードには一切`heap`の文字がありません。そのため、テーブルが`heap`以外のAccess Methodでも動くようになっています。

# HeapからINSERT

もう一つ下のレイヤーに降りて、Heap Access MethodのAPIを直接叩いてINSERTします。

```c
Datum
insert_heap(PG_FUNCTION_ARGS)
{
    Oid relid, nspid;
    Relation rel;
    TupleDesc tupdesc;
    Datum values[2];
    bool isnull[2];
    HeapTuple tuple;

    /* Open table "test" */
    nspid = get_namespace_oid("public", false);
    relid = get_relname_relid("test", nspid);
    if (!OidIsValid(relid))
        elog(ERROR, "table \"%s\" does not exist", "test");
    rel = table_open(relid, RowExclusiveLock);
    tupdesc = RelationGetDescr(rel);

    values[0] = Int32GetDatum(1);
    isnull[0] = false;
    values[1] = CStringGetTextDatum("alice");
    isnull[1] = false;

    tuple = heap_form_tuple(tupdesc, values, isnull);

    simple_heap_insert(rel, tuple);

    table_close(rel, NoLock);

    PG_RETURN_VOID();
}
```

先程よりは簡単に書けました。しかし、Executorから実行した時とは異なり、インデックスへのINSERTもやってくれませんし、テーブルがHeap Access Methodであるときにだけこのコードは動きます。一方、バッファアクセスやWALに関しては`simple_heap_insert()`の中でやってくれています。PostgreSQL内部でシステムカタログを変更する時なんかは、これに近い事をやっています(例えば`InsertPgClassTuple()`など)。

# 直接ページにINSERT

最後に更にもう一つ下レイヤーにいき、ページに直接タプルをINSERTしてみます。

```c
Datum
insert_page(PG_FUNCTION_ARGS)
{
    Oid relid, nspid;
    Relation rel;
    TupleDesc tupdesc;
    Datum values[2];
    bool isnull[2];
    HeapTuple tuple;
    Buffer buffer;
    Page page;
    OffsetNumber offnum;

    /* Open table "test" */
    nspid = get_namespace_oid("public", false);
    relid = get_relname_relid("test", nspid);
    if (!OidIsValid(relid))
        elog(ERROR, "table \"%s\" does not exist", "test");
    rel = table_open(relid, RowExclusiveLock);
    tupdesc = RelationGetDescr(rel);

    /* Create a heap tuple */
    values[0] = Int32GetDatum(1);
    isnull[0] = false;
    values[1] = CStringGetTextDatum("alice");
    isnull[1] = false;
    tuple = heap_form_tuple(tupdesc, values, isnull);

    /* Fill the tuple header */
    tuple->t_data->t_infomask &= ~(HEAP_XACT_MASK);
    tuple->t_data->t_infomask2 &= ~(HEAP2_XACT_MASK);
    tuple->t_data->t_infomask = HEAP_XMAX_INVALID;
    HeapTupleHeaderSetXmin(tuple->t_data, GetTopTransactionId());
    HeapTupleHeaderSetCmin(tuple->t_data, GetCurrentCommandId(true));
    tuple->t_tableOid = relid;

    /* Get the buffer to insert */
    buffer = RelationGetBufferForTuple(rel, tuple->t_len, InvalidBuffer,
                                       0, NULL, NULL, NULL);
    START_CRIT_SECTION();

    /* Put the tuple in the page */
    page = BufferGetPage(buffer);
    offnum = PageAddItm(page, (Item) tuple->t_data,
                        tuple->t_len, InvalidOffsetNumber, false, true);
    ItemPointerSet(&(tuple->t_self), BufferGetBlockNumber(buffer), offnum);

    MarkBufferDirty(buffer);

    /* Write WAL record */
    if (RelationNeedsWAL(rel))
    {
        xl_heap_insert xlrec;
        xl_heap_header xlhdr;
        XLogRecPtr recptr;
        uint8   info = XLOG_HEAP_INSERT;
        Page page = BufferGetPage(buffer);

        if (ItemPointerGetOffsetNumber(&(tuple->t_self)) == FirstOffsetNumber &&
            PageGetMaxOffsetNumber(page) == FirstOffsetNumber)
            info |= XLOG_HEAP_INIT_PAGE;

        xlrec.offnum = ItemPointerGetOffsetNumber(&tuple->t_self);
        xlrec.flags = 0;

        XLogBeginInsert();
        XLogRegisterData((char *) &xlrec, SizeOfHeapInsert);

        XLogRegisterBuffer(0, buffer, REGBUF_STANDARD);
        XLogRegisterBufData(0, (char *) &xlhdr, SizeOfHeapHeader);
        XLogRegisterBufData(0,
                           (char *) tuple->t_data + SizeofHeapTupleHeader,
                           tuple->t_len - SizeofHeapTupleHeader);

        recptr = XLogInsert(RM_HEAP_ID, info);

        PageSetLSN(page, recptr);
    }

    END_CRIT_SECTION();

    UnlockReleaseBuffer(buffer);
    table_close(rel, NoLock);

    PG_RETURN_VOID();
}
```

スキーマ（Namesapce）とテーブルの存在確認、OIDの取得から始まり、INSERTする`HeapTuple`の準備、タプルヘッダの設定、ページの取得やWAL書き込みまですべて行っています。個々まで来ると、Table Access Methodで実装している事をユーザ定義関数で実装していることになります。ただし、CLOG（コミットログ）については別モジュールで管理されているので、ここでは意識する必要はありません。Heapでは、PostgreSQLが生成したトランザクションID（この例だと`GetTopTransactionId()`で取得している部分)をタプルに書きます。Heapが用意するタプルの可視性判断関数（`HeapTupleSatisfiesXXX()`）では、そのトランザクションIDをCLOGに問い合せることで、トランザクションがCommitしたのかAbortしたのかを認識しています。

# 参考

ここで利用したソースコードは、[こちら](https://gist.github.com/MasahikoSawada/6db0e7b381fa89e3301596489437886c)に公開しています。ソースコードのビルドは他のExtensionと同じです(PG15で動作確認ずみ）。

```
$ make USE_PGXS=1
$ sudo make USE_PGXS=1 install
```

`pg_insert_test`という名前のExtensionができるので、`CREATE EXTENSION`コマンドでデータベースの登録します。

```
=# CREATE EXTENSION pg_insert_test;
CREATE EXTENSION
```
