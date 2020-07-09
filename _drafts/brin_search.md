---
layout: post
title: BRINソースコードリーディング（検索）
tags:
  - PostgreSQL
  - BRIN
  - Source Code Reading
---

BRINは一つのインデックスタプルが複数のブロックの束（ブロックのレンジ）に対応しているので、IndexScanには対応しておらず、BitmapIndexScanのみが可能。BRINを使って検索をして、スキャンする必要のあるブロックに対応するBitを立て、それを元にテーブルを検索（BitmapHeapScan）していくイメージ。

# bringetbitmap()

検索時のエントリポイントなる関数。

大きく以下のような処理になっている。Revmapを一つずつ見ながら、検索条件に合致するレンジのブロックをbitmapに入れていく。

```
	 for each ranges
	 {
	 	get BrinTuple from regular page;

	 	if not exist
	 		add this range to the result bitmap;
	 	else
	 	{
	 		deform BrinTuple;
	 		add this range to the result bitmap if this range includes the scan key values;
	 	}
	 }
```

revmapを一つずつ見ていく所。テーブルのブロック数を元にして全revmapを見ていくので、まだrevmapが作られていない可能性がある（INSERT,UPDATE時は新しいrevmapエントリはつくられない)。そのようなときは、`tup == NULL`になり、そのレンジはbitmapに追加する。

```c
    /*
     * Now scan the revmap.  We start by querying for heap page 0,
     * incrementing by the number of pages per range; this gives us a full
     * view of the table.
     */
    for (heapBlk = 0; heapBlk < nblocks; heapBlk += opaque->bo_pagesPerRange)
    {
        bool        addrange;
        bool        gottuple = false;
        BrinTuple  *tup;
        OffsetNumber off;
        Size        size;

        CHECK_FOR_INTERRUPTS();

        MemoryContextResetAndDeleteChildren(perRangeCxt);

        tup = brinGetTupleForHeapBlock(opaque->bo_rmAccess, heapBlk, &buf,
                                       &off, &size, BUFFER_LOCK_SHARE,
                                       scan->xs_snapshot);
        if (tup)
        {
            gottuple = true;
            btup = brin_copy_tuple(tup, size, btup, &btupsz);
            LockBuffer(buf, BUFFER_LOCK_UNLOCK);
        }

        /*
         * For page ranges with no indexed tuple, we must return the whole
         * range; otherwise, compare it to the scan keys.
         */
        if (!gottuple)
        {
            addrange = true;
        }
```

revmapに対応するインデックスタプルがあり、scan keyがmin, maxに合うかどうかを確かめる所。

* `dtup`はBRINインデックスのタプルで、`bval`にはそのインデックスタプルが持つmin, maxの値が入っている
* `consistentFn[]`には検索条件（ScanKey)にあるインデックス列毎に合わせた`consistentFn()`が入っている（例えば`brin_minmax_consistent()`など)。
  * 一つのインデックス列に対して複数の検索条件がある可能性がある(`a = 100 and a = 110`とか)。
  * なので、前処理としてそれらをインデックス列毎にまとめていて、`keys[][]`にはインデックス列に対して指定された条件が設定され（`keys[1][0]`には1番目のインデックス列に対する0番目の条件）、`nkeys[]`は`keys[][]`の各インデックス列における検索条件の数。
  * `keys[N][M]`としたとき、Nはインデックス列数になるが、Mはそのインデックス列に対して指定された検索条件の数になる。それは可変長なので`nkeys[N] = M`というようにデータを持っている。
* consistentFnには複数の検索条件を一度に渡せる。(`if consistentFn[attno - 1].fn_nargs >= 4`の所）
* consistentFnがtrueを返せば、そのレンジをBitmapに追加する。
* 一つずつキー（検索条件）を見ていく場合、一つのキーチェックでもfalseを返せばそのレンジは検索条件に合わないので途中でチェックを打ち切ってfalseとなる。

```c

                /*
                 * Compare scan keys with summary values stored for the range.
                 * If scan keys are matched, the page range must be added to
                 * the bitmap.  We initially assume the range needs to be
                 * added; in particular this serves the case where there are
                 * no keys.
                 */
                addrange = true;
                for (attno = 1; attno <= bdesc->bd_tupdesc->natts; attno++)
                {
                    BrinValues *bval;
                    Datum       add;

                    /* skip attributes without any san keys */
                    if (!nkeys[attno - 1])
                        continue;

                    bval = &dtup->bt_columns[attno - 1];

                    Assert((nkeys[attno - 1] > 0) &&
                           (nkeys[attno - 1] <= scan->numberOfKeys));

                    /*
                     * Check whether the scan key is consistent with the page
                     * range values; if so, have the pages in the range added
                     * to the output bitmap.
                     *
                     * When there are multiple scan keys, failure to meet the
                     * criteria for a single one of them is enough to discard
                     * the range as a whole, so break out of the loop as soon
                     * as a false return value is obtained.
                     */
                    if (consistentFn[attno - 1].fn_nargs >= 4)
                    {
                        Oid         collation;

                        /*
                         * Collation from the first key (has to be the same for
                         * all keys for the same attribue).
                         */
                        collation = keys[attno - 1][0]->sk_collation;

                        /* Check all keys at once */
                        add = FunctionCall4Coll(&consistentFn[attno - 1],
                                                collation,
                                                PointerGetDatum(bdesc),
                                                PointerGetDatum(bval),
                                                PointerGetDatum(keys[attno - 1]),
                                                Int32GetDatum(nkeys[attno - 1]));
                        addrange = DatumGetBool(add);
                    }
                    else
                    {
                        /* Check keys one by one */
                        int         keyno;

                        for (keyno = 0; keyno < nkeys[attno - 1]; keyno++)
                        {
                            add = FunctionCall3Coll(&consistentFn[attno - 1],
                                                    keys[attno - 1][keyno]->sk_collation,
                                                    PointerGetDatum(bdesc),
                                                    PointerGetDatum(bval),
                                                    PointerGetDatum(keys[attno - 1][keyno]));
                            addrange = DatumGetBool(add);
                            if (!addrange)
                                break;
                        }
                    }

                    if (!addrange)
                        break;
                }
```

該当のレンジをスキャンする必要があるとわかった場合(`addrange == true`)、以下のコートで追加する。今の所、Bitmap(`tbm`)にはページ単位かタプル単位でしかページを登録する方法がないので、該当のレンジ内のブロックを一つずつ入れていく。

ここはまとめて入れれるようにできそう。毎回`MemoryContextSwitchTo()`を読んでいるのも気になる。


```c
        /* add the pages in the range to the output bitmap, if needed */
        if (addrange)
        {
            BlockNumber pageno;

            for (pageno = heapBlk;
                 pageno <= heapBlk + opaque->bo_pagesPerRange - 1;
                 pageno++)
            {
                MemoryContextSwitchTo(oldcxt);
                tbm_add_page(tbm, pageno);
                totalpages++;
                MemoryContextSwitchTo(perRangeCxt);
            }
        }
```

次にconsistentFnの一例として、`brin_minmax_consistent()`を見ていく。

# brin_minmax_consistent()

最初に検索条件が`IS NULL`かどうかのチェックをする。このあたりはあとでチェックする。

```c
    /*
     * First check if there are any IS NULL scan keys, and if we're
     * violating them. In that case we can terminate early, without
     * inspecting the ranges.
     */
    for (keyno = 0; keyno < nkeys; keyno++)
    {
        ScanKey key = keys[keyno];

        Assert(key->sk_attno == column->bv_attno);

        /* handle IS NULL/IS NOT NULL tests */
        if (key->sk_flags & SK_ISNULL)
        {
            if (key->sk_flags & SK_SEARCHNULL)
            {
                if (column->bv_allnulls || column->bv_hasnulls)
                    continue;   /* this key is fine, continue */

                PG_RETURN_BOOL(false);
            }

            /*
             * For IS NOT NULL, we can only skip ranges that are known to have
             * only nulls.
             */
            if (key->sk_flags & SK_SEARCHNOTNULL)
            {
                if (column->bv_allnulls)
                    PG_RETURN_BOOL(false);

                continue;
            }

            /*
             * Neither IS NULL nor IS NOT NULL was used; assume all indexable
             * operators are strict and return false.
             */
            PG_RETURN_BOOL(false);
        }
        else
            /* note we have regular (non-NULL) scan keys */
            regular_keys = true;
    }
```

メインとなるチェック処理はここ。ただ実際の処理は`minmax_consistent_key()`で行っている。

```c
    for (keyno = 0; keyno < nkeys; keyno++)
    {
        ScanKey key = keys[keyno];

        /* ignore IS NULL/IS NOT NULL tests handled above */
        if (key->sk_flags & SK_ISNULL)
            continue;

        matches = minmax_consistent_key(bdesc, column, key, colloid);

        /* found non-matching key */
        if (!matches)
            break;
    }
```

# minmax_consistent_key()

大きくない関数だったので全体を載せてみた。この関数で確認することは、あるレンジのmin, max(`column`)が検索条件(`key`)を満たすかどうか。`column->bv_values[0]`には最小値、`column->bv_values[1]`には最大値が入っている。

例えば、検索条件が`a < 100`の場合（`key->sk_stratgy`は`BTLessStrategyNumber`になる）、そのレンジの最小値が100以下(つまり、`min < 100`)でであればそのレンジを選択する必要がある。

次に、検索条件が`a = 100`の場合（`key->sk_stratgy`は`BTEqualStrategyNumber`になる）、その値が`min < x <= max`になっている必要があるので、`min < x`の部分と`x <= max`の部分をそれぞれ計算する。

`bv_values[0]`が最小値(min)、`bv_values[1]`が最大値(max)であることがわかると非常に読みやすい。


```c
static bool
minmax_consistent_key(BrinDesc *bdesc, BrinValues *column, ScanKey key,
                      Oid colloid)
{
    FmgrInfo   *finfo;
    AttrNumber  attno = key->sk_attno;
    Oid         subtype = key->sk_subtype;
    Datum       value = key->sk_argument;
    Datum       matches;

    switch (key->sk_strategy)
    {
        case BTLessStrategyNumber:
        case BTLessEqualStrategyNumber:
            finfo = minmax_get_strategy_procinfo(bdesc, attno, subtype,
                                                 key->sk_strategy);
            matches = FunctionCall2Coll(finfo, colloid, column->bv_values[0],
                                        value);
            break;
        case BTEqualStrategyNumber:

            /*
             * In the equality case (WHERE col = someval), we want to return
             * the current page range if the minimum value in the range <=
             * scan key, and the maximum value >= scan key.
             */
            finfo = minmax_get_strategy_procinfo(bdesc, attno, subtype,
                                                 BTLessEqualStrategyNumber);
            matches = FunctionCall2Coll(finfo, colloid, column->bv_values[0],
                                        value);
            if (!DatumGetBool(matches))
                break;
            /* max() >= scankey */
            finfo = minmax_get_strategy_procinfo(bdesc, attno, subtype,
                                                 BTGreaterEqualStrategyNumber);
            matches = FunctionCall2Coll(finfo, colloid, column->bv_values[1],
                                        value);
            break;
        case BTGreaterEqualStrategyNumber:
        case BTGreaterStrategyNumber:
            finfo = minmax_get_strategy_procinfo(bdesc, attno, subtype,
                                                 key->sk_strategy);
            matches = FunctionCall2Coll(finfo, colloid, column->bv_values[1],
                                        value);
            break;
        default:
            /* shouldn't happen */
            elog(ERROR, "invalid strategy number %d", key->sk_strategy);
            matches = 0;
            break;
    }

    return DatumGetBool(matches);
}
```

# 気になる点（調べならが埋めていく予定）

* NULLの扱い
  * レンジはNULLをどう扱う？
  * NOT NULLなインデックスは作れる？
  * 検索条件がIS NULLのときの挙動は？
* もっと効率良くBitmapを作れそう？
  * 個々のブロックではなく、ブロックの範囲を記録するようにすればサイズを圧縮できる
* `if (consistentFn[attno - 1].fn_nargs >= 4)`じゃないときはどういう時？
