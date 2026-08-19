---
layout: post
title: PostgreSQLのWALを対話的に読むTUIツール(pg_walview)を作ってみた
description: >-
  PostgreSQLのWALファイルを対話的に読むためのTUIツール pg_walview を作りました。
  同じXIDのレコードをグラフ線で繋いで表示するので、絞り込まずに特定のトランザクションを
  目で追えます。画面の構成と使い方を紹介します。
lang: ja
image: /assets/images/og/ja/pg-walview-ed6e5f59.png
translated: true
tags:
  - PostgreSQL
  - WAL
  - Rust
---

以前、[pg_walview](https://github.com/MasahikoSawada/pg_walview)という、PostgreSQLのWAL（Write-Ahead Log）ファイルを対話的に読むためのTUIツールを作りました。`pg_waldump`のように出力を一度に吐き出すのではなく、ターミナル上でカーソルを動かしながらWALレコードを1つずつ眺めていくツールです。Rustで書いています。

<video src="/images/2026-08-18/pg_walview-demo.mp4" poster="/images/2026-08-18/pg_walview-demo-poster.jpg"
       width="1200" height="600" autoplay muted loop playsinline preload="none"
       style="max-width:100%;height:auto"
       aria-label="pg_walviewでWALファイルを開き、カーソルを動かしながらWALレコードの詳細とHEXダンプを表示している様子">
</video>

`pg_waldump`は`-x`でXID、`-r`でリソースマネージャ、`-R`や`-B`でリレーションやブロック、という具合に絞り込みは一通りできます。ですが、絞り込むと今度はその前後で何が起きていたかが見えなくなります。`-x`を付けて実行して、やっぱり周りが気になって`-x`を外して実行して、というのを何度も繰り返していました。だったら全部読み込んでおいて、その場で視点だけ切り替えられればいいのでは、と思ったのがきっかけです。

## 画面の構成

画面は3つのペインに分かれていて、`Tab`でフォーカスを移動します。

### WAL records（左）

LSN、XID、レコード長、FPIの有無、リソースマネージャ、説明の一覧です。

一番やりたかったのが左端のグラフ線です。カーソルを合わせたレコードと同じXIDを持つレコードが、線で繋がって表示されます。

```
    0/100 13840   171  Heap      UPDATE
 ┏━ 0/100 13841  8135  Heap      LOCK        ← このXIDの最初のレコード
 ┃  0/100 13839  8135  Heap      LOCK
 ┣━ 0/100 13841   171  Heap      UPDATE      ← カーソル位置
 ┃  0/100 13840  8135  Heap      LOCK
 ┃  0/100 13839   171  Heap      UPDATE
 ┣━ 0/100 13841    64  Btree     INSERT_LEAF
 ┗━ 0/100 13841    34  Transact  COMMIT      ← このXIDの最後のレコード
```

他のトランザクションのレコードは間に挟まったまま残ります。なので、絞り込まずに特定のトランザクションだけを目で追えます。`s`と`r`で同じXIDの次／前のレコードにジャンプすることもできます[^xid]。

[^xid]: ただしXIDが0、1、2のときはジャンプを無効にしています。それぞれ`InvalidTransactionId`、`BootstrapTransactionId`、`FrozenTransactionId`ですが、XIDを持たないレコードは大量にあるので、繋いでも意味がないためです。

線の色は、そのXIDの最後のレコードを見て決めています。要はそのトランザクションがどう終わったかです。

| 状態         | 判定条件                                                            |
|--------------|---------------------------------------------------------------------|
| コミット済み | `COMMIT` または `COMMIT_PREPARED` で終わっている                    |
| アボート     | `ABORT` または `ABORT_PREPARED` で終わっている                      |
| 保留中       | `PREPARE` など、コミットでもアボートでもないTransactionレコードで終わっている |
| 未完結       | Transactionレコードで終わっていない                                 |

最後の「未完結」が地味に便利です。そのトランザクションがこのWALファイル内では完結していない、つまり続きが次のセグメントにあるということなので、次のファイルを開くべきかどうかがわかります。

ちなみに使っているのはANSIの16色だけです。実際にどう見えるかは端末のテーマ次第。`NO_COLOR`を設定すれば色は落ちます。

### DETAILS（右上）

選択中のレコードの詳細です。`XLogRecord`のヘッダ、ブロック参照（`RelFileLocator`、フォーク、ブロック番号、フラグ）、そしてリソースマネージャごとにデコードした構造体のフィールドが並びます。

アコーディオンになっていて、`Enter`でブロックごとの詳細を開閉できます。Heapの`UPDATE`なら`xl_heap_header`の`t_infomask`や`t_infomask2`をフラグ名に展開して表示します。`HEAP_XMAX_INVALID`が立っているかどうか、みたいな確認をその場でできるので便利です。

### HEX DUMP（右下）

WALセグメント全体のバイト列です。各行はLSNとファイルオフセットの両方で位置を示すので、レコードがどのページのどこに載っているかを見ながら読めます。

色が付くのは選択中のレコードのバイトだけです。しかも`XLogRecord`のヘッダ、ディスクリプタ、FPI、ブロックデータ、メインデータ、と構造ごとに色が分かれます。ページ境界をまたぐレコードは、実際にファイル上で占めている複数の断片として色が付きます。間に挟まるページヘッダはレコードの一部ではないので、そこには色を付けていません。

DETAILSでカーソルを合わせている項目は、ダンプ側でも強調されます。なのでアコーディオンがそのままバイト列のナビゲータになります。デコード結果と生バイトを並べて見られるのは、`*desc.c`相当の実装[^desc]を書いているときのデバッグにも効きました。

[^desc]: リソースマネージャごとのデコード部分は、PostgreSQL本体の`src/backend/access/rmgrdesc/`にある`*desc.c`と同じ役割です。本体の構造に寄せておいたほうが、あとで追従しやすいはず、という判断でそうしています。

## 使い方

`pg_config`にパスが通っていればそのままビルドできます。ビルド時にPostgreSQL本体のヘッダから`XLogRecord`などの定義を取り込んでいるので、ヘッダが必要です[^version]。

[^version]: なので、ビルドしたヘッダのバージョンのWALしか読めません。別バージョンのセグメントを開いた場合は、誤読せずにページマジックの不一致としてエラーになります。`--version`を付けると、そのバイナリがどのPostgreSQL向けにビルドされたものかを表示します。

```bash
git clone https://github.com/MasahikoSawada/pg_walview.git
cd pg_walview
cargo build --release

# PostgreSQLを独自の場所にインストールしている場合
PG_INCLUDE_DIR=/path/to/pgsql/include/server cargo build --release
```

あとはWALファイルのパスを渡すだけです。サーバに接続するわけではないので、稼働中のインスタンスでなくても、コピーしてきたWALファイルさえあれば読めます。

```bash
pg_walview /path/to/pg_wal/000000010000000000000001
```

主なキーバインドはこちら。

| キー          | 動作                                |
|---------------|-------------------------------------|
| `j` / `k`     | 次／前のレコードへ移動              |
| `g` / `G`     | 最初／最後のレコードへ移動          |
| `s` / `r`     | 同じXIDの次／前のレコードへジャンプ |
| `Space` / `-` | ページ送り／ページ戻し              |
| `Tab`         | ペインの切り替え                    |
| `q`           | 終了                                |

## 制限

- 一度に1つのセグメントファイルしか開けません。トランザクションがセグメントをまたぐと追いきれません。グラフ線が「未完結」になるのは、この制限の裏返しでもあります
- ファイル内の全レコードをメモリに読み込みます。セグメントは既定で16MBなので今のところ困っていませんが、`--wal-segsize`を大きくしている環境では効いてくるかもしれません。なおセグメントサイズ自体はロングページヘッダから読むので、非デフォルトでも読めます
- リソースマネージャごとのデコーダが揃っていません。Heap、Heap2、Btree、Transaction、XLOGあたりは書きましたが、GiST、GIN、SP-GiSTなどはまだmain dataのバイト数を表示するだけです
- 圧縮されたFPI（Full Page Image）を展開できません。圧縮方式の表示まではしますが、中身までは見られません

## おわりに

WALの中身を見る手段としては`pg_waldump`も[pg_walinspect](https://www.postgresql.org/docs/18/pgwalinspect.html)もありますし、機能面では当然そちらのほうが揃っています。pg_walviewは「対話的に動き回れる」という一点だけに絞ったツールです。

自分の場合、ロジカルレプリケーション関連のデバッグで、このトランザクションはどこでコミットされたのか、このレコードとこのレコードの間に何が挟まっているのか、といったことを追う機会が多くあります。その用途では作ってよかったと思っています。

ソースは[GitHub](https://github.com/MasahikoSawada/pg_walview)に置いてあります。MITライセンスです。ContributionもWelcomeです！
