---
layout: post
title: BRINソースコードリーディング（構築）
tags:
  - PostgreSQL
  - BRIN
  - Source Code Reading
---

# struct BrinBuildState


BRINを構築するときに使う構造体。

```c
typedef struct BrinBuildState
{
    Relation    bs_irel;			// 対象のインデックス
    int         bs_numtuples;		// 今のレンジに何個タプルがあるか
    Buffer      bs_currentInsertBuf;  // 現在INSERTしているインデックスのバッファ
    BlockNumber bs_pagesPerRange;	// レンジ毎のブロック数
    BlockNumber bs_currRangeStart;	// 今のレンジの開始ブロック番号
    BrinRevmap *bs_rmAccess;	// revmap
    BrinDesc   *bs_bdesc;
    BrinMemTuple *bs_dtuple;
} BrinBuildState;
```

# brinbuild()

meta pageを初期化して、`XLOG_BRIN_CREATE_INDEX`をWALに書く。

実際にテーブルをスキャンしながらインデックスを構築するのは、`table_index_build_scan()`の部分。`brinbuildCallback()`をコールバック関数として渡している。この関数は一行テーブルから行を取得する度に呼ばれる。テーブル、インデックスのレイヤがともに抽象化されているのでこのような形になっている。`table_index_build_scan()`はテーブルアクセスメソッド（TableAM）の`index_build_range_scan()`を呼ぶ（Heapの場合、最終的には`heapam_index_build_range_scan()`)。"range_scan"とはなっているけど、全ブロックをスキャンするようになっている。



```c
    /*
     * Critical section not required, because on error the creation of the
     * whole relation will be rolled back.
     */

    meta = ReadBuffer(index, P_NEW);
    Assert(BufferGetBlockNumber(meta) == BRIN_METAPAGE_BLKNO);
    LockBuffer(meta, BUFFER_LOCK_EXCLUSIVE);

    brin_metapage_init(BufferGetPage(meta), BrinGetPagesPerRange(index),
                       BRIN_CURRENT_VERSION);
    MarkBufferDirty(meta);

    if (RelationNeedsWAL(index))
    {
	:
        // WALを書く準備をする
	:
	recptr = XLogInsert(RM_BRIN_ID, XLOG_BRIN_CREATE_INDEX);
    }

    UnlockReleaseBuffer(meta);

    /*
     * Initialize our state, including the deformed tuple state.
     */
    revmap = brinRevmapInitialize(index, &pagesPerRange, NULL);

    state = initialize_brin_buildstate(index, revmap, pagesPerRange);

    /*
     * Now scan the relation.  No syncscan allowed here because we want the
     * heap blocks in physical order.
     */
    reltuples = table_index_build_scan(heap, index, indexInfo, false, true,
                                       brinbuildCallback, (void *) state, NULL);

    /* process the final batch */
    form_and_insert_tuple(state);

```

# brinbuildCallback()

ビルドのメインはここ。`while`の所では、ブロックのレンジが設定値（デフォルトでは128ブロック）を超えたら、そこまでに貯めたタプルのサマリを新しい、Brinインデックスタプルとして書き出す(`form_and_insert_tuple()`)。その後に、`state->bs_currRangeStart`に次のレンジの最初のブロック番号を設定している。

```c
static void
brinbuildCallback(Relation index,
                  ItemPointer tid,
                  Datum *values,
                  bool *isnull,
                  bool tupleIsAlive,
                  void *brstate)
{
    BrinBuildState *state = (BrinBuildState *) brstate;
    BlockNumber thisblock;
    int         i;

    thisblock = ItemPointerGetBlockNumber(tid);

    /*
     * If we're in a block that belongs to a future range, summarize what
     * we've got and start afresh.  Note the scan might have skipped many
     * pages, if they were devoid of live tuples; make sure to insert index
     * tuples for those too.
     */
    while (thisblock > state->bs_currRangeStart + state->bs_pagesPerRange - 1)
    {

        BRIN_elog((DEBUG2,
                   "brinbuildCallback: completed a range: %u--%u",
                   state->bs_currRangeStart,
                   state->bs_currRangeStart + state->bs_pagesPerRange));

        /* create the index tuple and insert it */
        form_and_insert_tuple(state);

        /* set state to correspond to the next range */
        state->bs_currRangeStart += state->bs_pagesPerRange;

        /* re-initialize state for it */
        brin_memtuple_initialize(state->bs_dtuple, state->bs_bdesc);
    }

```

`index_getprocinfo(..., BRIN_PROCNUM_ADDVALUE)`では、データタイプによって異なる関数を呼び出すが、BRINの場合は`brin_minmax_add_value()`か`brin_inclusion_add_value()`になる。

各HeapTupleを取得するたびに、`brin_minmax_add_value()`もしくは、`brin_inclusion_add_value()`を呼び出す。処理内容を見るとわかる通り、どのデータ型でも比較することができればOKなので、データ型毎にこの`xxx_add_values()`があるわけではない。すべての（比較できる）データ型は`brin_minmax_add_value()`で対応できるし、範囲型やネットワークアドレス型のような包含関係があるものは、`brin_inclusion_add_values()`を使うことができる。

この関数は、BrinDesc, BrinValues, newval, isnullが引数で与えられる。`BrinValues`は、一つのレンジ毎に一つある構造体で、現在持っているminとmaxの値（`bv_values[0]`がminで`[1]`がmaxとなる）。

```c
    /* Accumulate the current tuple into the running state */
    for (i = 0; i < state->bs_bdesc->bd_tupdesc->natts; i++)
    {
        FmgrInfo   *addValue;
        BrinValues *col;
        Form_pg_attribute attr = TupleDescAttr(state->bs_bdesc->bd_tupdesc, i);

        col = &state->bs_dtuple->bt_columns[i];
        addValue = index_getprocinfo(index, i + 1,
                                     BRIN_PROCNUM_ADDVALUE);

        /*
         * Update dtuple state, if and as necessary.
         */
        FunctionCall4Coll(addValue,
                          attr->attcollation,
                          PointerGetDatum(state->bs_bdesc),
                          PointerGetDatum(col),
                          values[i], isnull[i]);
    }
}
```

# brin_minmax_add_value()



まずは、新しい値(`newval`)に対して、既存のminより値が小さいかどうかを書くにする。そのために、比較用の関数を探す（BTLessStrategyNumber(つまり`<`)）。既存のminよりも小さい場合は、minを更新する必要があるので、`bv_values[0]`に新しいminを代入する。

```c
    BrinDesc   *bdesc = (BrinDesc *) PG_GETARG_POINTER(0);
	BrinValues *column = (BrinValues *) PG_GETARG_POINTER(1);
	Datum       newval = PG_GETARG_DATUM(2);
	bool        isnull = PG_GETARG_DATUM(3);
	Oid         colloid = PG_GET_COLLATION();

	:

    cmpFn = minmax_get_strategy_procinfo(bdesc, attno, attr->atttypid,
                                         BTLessStrategyNumber);
    compar = FunctionCall2Coll(cmpFn, colloid, newval, column->bv_values[0]);
    if (DatumGetBool(compar))
    {
        if (!attr->attbyval)
            pfree(DatumGetPointer(column->bv_values[0]));
        column->bv_values[0] = datumCopy(newval, attr->attbyval, attr->attlen);
        updated = true;
    }
```

同様に、次の新しい値が既存のmaxよりも大きいかを確認する。

```c
    /*
     * And now compare it to the existing maximum.
     */
    cmpFn = minmax_get_strategy_procinfo(bdesc, attno, attr->atttypid,
                                         BTGreaterStrategyNumber);
    compar = FunctionCall2Coll(cmpFn, colloid, newval, column->bv_values[1]);
    if (DatumGetBool(compar))
    {
        if (!attr->attbyval)
            pfree(DatumGetPointer(column->bv_values[1]));
        column->bv_values[1] = datumCopy(newval, attr->attbyval, attr->attlen)
        updated = true;
    }
```


# brin_doinsert()

`BrinTuple`を実際にディスク上に書く関数。

heapBlkは現在のレンジの最初のHeapのブロック。例えば、デフォルトだとpagesPerRange = 128なので、128とか256という値が入る。`tup`は挿入したいインデックスタプルで、`itemsz`はそのサイズ。

```c
|OffsetNumber
|brin_doinsert(Relation idxrel, BlockNumber pagesPerRange,
|              BrinRevmap *revmap, Buffer *buffer, BlockNumber heapBlk,
|              BrinTuple *tup, Size itemsz)
```

この関数でやることは大きく2つ。

* インデックス（のディスク）に`BrinTuple tup`を入れる
* revmapを更新する。

まずは、`brinRevmapExtend()`で十分にインデックスのページが有るかを確認する。revmapに`rm_pagesPerRange`（各レンジのブロック数）があり、`heapBlk`（テーブルにINSERTされた新しいタプルが置かれたブロック番号）があるので、それらからrevmap上のどこの位置に新しいrevmapのタプルを入れる必要があるかがわかる。なので、それをもとに必要な領域があることを保証する。

詳細はINSERT周りのコードを読むときに調べていきたい。多分ここで、新しいrevmap pageが必要なときにregular pageのタプルを追い出す、という処理があると思う。


```c
    /* Make sure the revmap is long enough to contain the entry we need */
    brinRevmapExtend(revmap, heapBlk);
```


その後は、十分な空き領域があるregular pageを取得して、それにインデックスタプルを入れる。

```c
    /*
     * If we still don't have a usable buffer, have brin_getinsertbuffer
     * obtain one for us.
     */
    if (!BufferIsValid(*buffer))
    {
        do
            *buffer = brin_getinsertbuffer(idxrel, InvalidBuffer, itemsz, &extended);
        while (!BufferIsValid(*buffer));
    }
    else
        extended = false;

    /* Now obtain lock on revmap buffer */
    revmapbuf = brinLockRevmapPageForUpdate(revmap, heapBlk);

    page = BufferGetPage(*buffer);
    blk = BufferGetBlockNumber(*buffer);

    /* Execute the actual insertion */
    START_CRIT_SECTION();
    if (extended)
        brin_page_init(page, BRIN_PAGETYPE_REGULAR);
    off = PageAddItem(page, (Item) tup, itemsz, InvalidOffsetNumber,
                      false, false);
    if (off == InvalidOffsetNumber)
        elog(ERROR, "failed to add BRIN tuple to new page");
    MarkBufferDirty(*buffer);
```

そして、新しいrevmapのエントリにregular pageに追加したTID(`tid`)を設定する。

```c
    ItemPointerSet(&tid, blk, off);
    brinSetHeapBlockItemptr(revmapbuf, pagesPerRange, heapBlk, tid);
    MarkBufferDirty(revmapbuf);
```

最後はWAL関連。対応するテーブルブロック(`heapBlk`)、レンジ毎のブロック数(`pagesPerRange`)、オフセット(`offset`)の情報を書く。`xl_brin_insert`を使っているのでINSERT時と同じようにWALを書いているように見える。詳細は、INSERT周りのコードを見るときに調べていきたい。

```c
    if (RelationNeedsWAL(idxrel))
    {
        xl_brin_insert xlrec;
        XLogRecPtr  recptr;
        uint8       info;

        info = XLOG_BRIN_INSERT | (extended ? XLOG_BRIN_INIT_PAGE : 0);
        xlrec.heapBlk = heapBlk;
        xlrec.pagesPerRange = pagesPerRange;
        xlrec.offnum = off;

        XLogBeginInsert();
        XLogRegisterData((char *) &xlrec, SizeOfBrinInsert);

        XLogRegisterBuffer(0, *buffer, REGBUF_STANDARD | (extended ? REGBUF_WILL_INIT : 0));
        XLogRegisterBufData(0, (char *) tup, itemsz);

        XLogRegisterBuffer(1, revmapbuf, 0);

        recptr = XLogInsert(RM_BRIN_ID, info);

        PageSetLSN(page, recptr);
        PageSetLSN(BufferGetPage(revmapbuf), recptr);
     }
```


