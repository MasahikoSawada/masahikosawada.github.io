---
layout: post
tags:
  - PostgreSQL
  - zheap
  - MVCC
---

# 全般
* 現時点ではpluggable storage engineのパッチを当てている訳ではなく、毎回リレーションのオプショを見て、zheapかheapかを判断してコードを切り替えている
* ただし、インターフェースはPSEと同じ。
  * insert, update, delete, lock_tuple, multi_insert, prone, scan(beginscan, endscan, etc), MVCCなど
# ストレージフォーマット
* タプルヘッダも小さい

```c
struct HeapTupleHeaderData
{
    union
    {
        HeapTupleFields t_heap;
        DatumTupleFields t_datum;
    }           t_choice;

    ItemPointerData t_ctid;     /* current TID of this or newer tuple (or a
                                 * speculative insertion token) */

    /* Fields below here must match MinimalTupleData! */

    uint16      t_infomask2;    /* number of attributes + various flags */

    uint16      t_infomask;     /* various flag bits, see below */

    uint8       t_hoff;         /* sizeof header incl. bitmap, padding */

    /* ^ - 23 bytes - ^ */

    bits8       t_bits[FLEXIBLE_ARRAY_MEMBER];  /* bitmap of NULLs */

    /* MORE DATA FOLLOWS AT END OF STRUCT */
};
```

```c
typedef struct ZHeapTupleHeaderData
{
    uint16      t_infomask2;    /* number of attributes + translot info + various flags */

    uint16      t_infomask; /* various flag bits, see below */

    uint8       t_hoff;     /* sizeof header incl. bitmap, padding */

    /* ^ - 4 bytes - ^ */

    bits8       t_bits[FLEXIBLE_ARRAY_MEMBER];  /* bitmap of NULLs */

    /* MORE DATA FOLLOWS AT END OF STRUCT */
} ZHeapTupleHeaderData;
```

* ZHeapPageOpaqueData
  * UNDOログへのポイントに必要な情報を格納している。
    * xid_epoch, xid, urec_ptr
    * xid_epochはxidの周回を判断するために必要。
* 上記は`Transaction Slot`と呼ばれ、UNDO領域を使う前には必ず確保している必要がある。
* 上記の情報を、要素4の配列で持っている。
  * 1スロット＝1トランザクションに対応している
  * スロットを使い切っている場合は、少し(10ms)待って再度挑戦
* ページごとにUNDOへのポインタがあるということは、一つのページにアクセス（変更できる）Txの上限があるということ
  * 例えば、ロングトランザクションが複数いて、transaction slotを使い切っている場合は、他のトランザクションはINSERTできない
  * そういう場合は、別のページを探しに行く。（上記の通り10ms待ってから）
    * つまり、このような場合にテーブルが肥大化する。ただし、ロングトランザクションが解決されれば一括して削除される。

```c
#define MAX_PAGE_TRANS_INFO_SLOTS   4

/*
 * We need tansactionid and undo pointer to retrieve the undo information
 * for a particular transaction.  Xid's epoch is primarily required to check
 * if the xid is from current epoch.
 */
typedef struct TransInfo
{
    uint32      xid_epoch;
    TransactionId   xid;
    UndoRecPtr  urec_ptr;
} TransInfo;

typedef struct ZHeapPageOpaqueData
{
    TransInfo   transinfo[MAX_PAGE_TRANS_INFO_SLOTS];
} ZHeapPageOpaqueData;
```

# UNDO
## 基本的な方針
**COMMIT時には何もしない** ように、UNDOの中身を書くようになっている。
* INSERT: テーブルに新しいレコードを書く。UNDOログにINSERTと記録して、ABORTの場合はLPにDEADと付ける。COMMITの場合はそのまま
* DELETE: テーブルのレコードには削除フラグ（ZHEAP_DELETED)を付ける。削除前のレコードをUNDOログに記録する。ABORTの場合の場合は、UNDOログからmemcpyでもってくる。
* INPLACE-UPDATE: 同ページ内で「置き換えUPDATE」ができる場合は、新しいレコードをテーブルに書く。古いレコードはUNDOに入れて、ABORTの時にUNDOログから取ってくる
* UPDATE: UPDATEでタプルが動く場合は、UNDO_UPDATE＋UNDO_INSERTみたいになる。つまり、テーブル内の旧タプルを削除して削除したレコードをUNDOに入れる＋新しいレコードを別ページに追加して対応する（そのタプルを削除する）UNDOを入れる。ABORT時は、旧タプルをUNDOから復元し、新タプルをUNDOによって削除する。

## 具体的なコード
例えばINSERTの時・・・
* `PageGetUNDO(page, trans_slot_id)`をして、現時点でページからポイントしているUNDOページのアドレスを保持しておく（これはUNDOレコードをたどるために必要）
* UNDOログを作成
* `PrepareUndoInsert(&undorecord, UNDO_PERSISTENT, InvalidTransactionId)`をして、メモリ上にUNDOログを挿入する
* `InsertPreparedUNDO()`で、上記のUNDOログを実際に書く

# MVCC
* 入力は、ZheapTuple, Snapshot, Buffer, ItemPointerの4つ。出力はZHeapTupleまたはNULL
* 対応する関数は、`ZHeapTupleSatisfiesMVCC`
1. テーブル内のタプルが削除済み、または更新済み
   1. 自分自身によるもの＆タプルのコマンドIDがスナップショット内のもの以下
      * UNDOログからタプルを返却（`GetTupleFromUndo`)
   1. 削除したTxが現在も実行中（スナップショット内にある）
      * UNDOログからタプルを返却（`GetTupleFromUndo`)
   1. 削除したTxがCOMMIT済み
      * return NULL; /* 見えない、という意味 */
   1. 削除したTxがABORT済み
      * UNDOログからタプルを返却（`GetTupleFromUndo`)
1. テーブル内のタプルが、in-place更新済み、またはロック済み
