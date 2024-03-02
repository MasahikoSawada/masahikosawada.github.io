---
layout: post
title: FDWを使った時の読取り異常、更新異常を見てみる
tags:
  - PostgreSQL
  - Foreign Data Wrapper
  - Transaction
lang: jp
---

Merry Christmas 🎄

この記事は[PostgreSQL Advent Calendar 2019](https://qiita.com/advent-calendar/2019/postgresql)の25日目の記事です。昨日は[@atmitani](https://qiita.com/atmitani)さんの[PostgreSQLの統計情報を可視化](https://qiita.com/atmitani/items/815606e9be30a56af47d)の話でした。

FDW（Foreign Data Wrapper）は、PostgreSQLが外部のリソースに対して、あたかもPostgreSQLにデータがあるかのようにアクセスできる機能です。oracle_fdw、mysql_fdwなど様々なFDWがありますが、PostgreSQLにはpostgres_fdwといって、外部にあるPostgreSQLサーバからデータを取ってくるためのプログラムが付属されています。PostgreSQLがPostgreSQLと連携することは一見使い道がなさそうに思えますが、例えばテーブル・パーティショニング機能と連携することでシャーディングのようなことができたり、postgres_fdwを経由して異なるバージョンのPostgreSQLからデータを取ってくることでバージョンアップにも使えたりします。

<center>
<iframe src="//www.slideshare.net/slideshow/embed_code/key/eT9SoJSdkMa2Ys?startSlide=40" width="425" height="355" frameborder="0" marginwidth="0" marginheight="0" scrolling="no" style="border:1px solid #CCC; border-width:1px; margin-bottom:5px; max-width: 100%;" allowfullscreen> </iframe> <div style="margin-bottom:5px"> <strong> <a href="//www.slideshare.net/masahikosawada98/postgresql-96-69228794" title="PostgreSQL 9.6 新機能紹介" target="_blank">PostgreSQL 9.6 新機能紹介</a> </strong> from <strong><a href="//www.slideshare.net/masahikosawada98" target="_blank">Masahiko Sawada</a></strong> </div>
</center>


FDWを使うと透過的に外部にあるリソース（サーバやサービスなど）にアクセスできるため、FDWを利用するユーザとしては**あたかも1台のPostgreSQLに接続しているかのように振る舞うことを期待します**。しかし、現在のpostgres_fdwではいくつかの（トランザクションに関連する）機能が不足しているため、思いがけない結果を取得することがあります。

実際に確認してみましょう。使用するクラスタの構成は次の通りです。クライアント（`C`）はPostgreSQLサーバ（`S`）にSQLを送ります。PostgreSQLサーバはFDW（postgres_fdw）を介して外部のサーバ（`S1`と`S2`）に繋がっています。`S1`と`S2`もPostgreSQLサーバで、それぞれが持っているテーブル`a1`とテーブル`a2`には1000行ずつ入っていています。postgres_fdwでは、実行計画からSQLを生成しそれを外部サーバに送ることでデータを取得します。

```
                         SQL
                    .---------> S1 サーバ （a1テーブル:1000行入ってる）
    SQL            /
C -------> S サーバ
                   \     SQL
                    `---------> S2 サーバ （a2テーブル:1000行入ってる）
```

## 読み取り結果の異常1

では、クライアントから以下のように2つのトランザクションを実行してみましょう。`#`列は実行順序を表し、`結果`列には`SELECT`によって得られた結果を書いています。

| #  | Session A                   | Session B                        | 結果        |
| -- | :-------------------------- | :------------------------------- | ----------- |
| 1  | `BEGIN`                     |                                  |             |
| 2  | `SELECT count(*) FROM a1`   |                                  | 1000 rows   |
| 3  |                             | `BEGIN`                          |             |
| 4  |                             | `DELETE FROM a1 WHERE i < 100`   |             |
| 5  |                             | `COMMIT`                         |             |
| 6  | `SELECT count(*) FROM a1`   |                                  | 1000 rows   |
| 7  | `COMMIT`                    |                                  |             |

上記の結果は期待通りの結果でしょうか？試しにFDWを使用せず上記の手順を実行してみてください。きっと以下のような結果（`FDWを使わないときの結果`列）になると思います。


| #  | Session A                   | Session B                        | FDWを使わないときの結果 | FDWを使ったときの結果  |
| -- | :-------------------------- | :------------------------------- | ----------------------  | ---------------------- |
| 1  | `BEGIN`                     |                                  |                         |                        |
| 2  | `SELECT count(*) FROM a1`   |                                  | 1000 rows               | 1000 rows              |
| 3  |                             | `BEGIN`                          |                         |                        |
| 4  |                             | `DELETE FROM a1 WHERE i < 100`   |                         |                        |
| 5  |                             | `COMMIT`                         |                         |                        |
| 6  | `SELECT count(*) FROM a1`   |                                  | 900 rows                | 1000 rows              |
| 7  | `COMMIT`                    |                                  |                         |                        |

実はFDWを使う時と使わない時で結果が異なります。PostgreSQLのデフォルトのトランザクション分離レベルはRead Commitedですが、FDWを使った場合、`Session B`でコミットされたデータがその後の（6での）`SELECT`で見えていません。2回の`SELECT`（2と6）では同じ結果を返しています。

postgres_fdwでは外部サーバにてSQLを実行して結果を取得するのですが、そのときにトランザクション分離レベルをRepeatable Readに設定します[^isolation]。これは、クエリが複数のテーブルスキャンを外部サーバでで行う際に、確実に全てのスキャンにおいて一貫した結果を取り出すために必要なのですが、一方で上記のようなFDWを使わなかった時（単一サーバで実行した時）きでは起こり得ない結果が起こります。

[^isolation]: ローカルトランザクション（ユーザが実行したトランザクション）がSerializableの場合は外部サーバでもSerializableでトランザクションを開始します。

## 読み取り結果の異常2

次に以下のように2つのトランザクションを実行してみましょう（`#`列は実行順序を示しています）。

| # | Session A                                           | Session B                                           | FDWを使わないときの結果 | FDWを使ったときの結果 |
|---|:----------------------------------------------------|:----------------------------------------------------|-------------------------|-----------------------|
| 1 | `BEGIN TRANSACTION ISOLATION LEVEL PEPEATABLE READ` |                                                     |                         |                       |
| 2 | `SELECT count(*) FROM a1`                           |                                                     | 1000 rows               | 1000 rows             |
| 3 |                                                     | `BEGIN TRANSACTION ISOLATION LEVEL PEPEATABLE READ` |                         |                       |
| 4 |                                                     | `DELETE FROM a2 WHERE i <= 100`                     |                         |                       |
| 5 |                                                     | `COMMIT`                                            |                         |                       |
| 6 | `SELECT count(*) FROM a2`                           |                                                     | 1000 rows               | 900 rows              |
| 7 | `COMMIT`                                            |                                                     |                         |                       |

すでに`FDWを使わないときの結果`列と`FDWを使ったときの結果`列に記載しているように、これもFDWを使った場合とそうでない場合で結果が異なります。クライアントは`Session A`のトランザクションをRepeatable Readで開始しているにも関わらず、`Session B`の更新結果が見えてしまっています。

postgres_fdwでは、SQLを受け付けたサーバが初めて外部サーバにSQLを送るときにトランザクションを開始します。つまり上記の例では、2で片方のサーバ（`S1`サーバ）でトランザクションが開始され、6でもう片方のサーバ（`S2`サーバ）でトランザクションが開始されます。`a2`では、FDW経由でトランザクションが開始される（6の時点）よりも前に、`Session B`による`DELETE`がコミットされているため、削除後の状態が見えています。

上記の例では一つのSQLで一つの外部サーバからデータを取得しているため、どのタイミングで外部サーバでトランザクションが開始されるかは比較的わかりやすいですが、結合をするクエリではユーザはFDWを介した外部サーバへの接続順序やSQL実行順序は全くわかりません。そのため、この「初めて外部サーバにSQLを送るときにトランザクションを開始する」というFDW（postgres_fdw）挙動は、期待していない結果を返す可能性があるため注意が必要です。

## 更新結果の異常

最後に以下のようなケースを考えてみます。クライアントはトランザクションを開始し2つのテーブルを更新しコミットをしましたが、片方のサーバからのコミットが完了した直後にクラッシュしてしまいました。

| #  | Session A                   | S1サーバでのトランザクション                        | S2でのトランザクション                              |
|----|:----------------------------|-----------------------------------------------------|-----------------------------------------------------|
| 1  | `BEGIN`                     |                                                     |                                                     |
| 2  | `INSERT INTO a1 VALUES (1)` |                                                     |                                                     |
| 3  |                             | `BEGIN TRANSACTION ISOLATOIN LEVEL REPEATABLE READ` |                                                     |
| 4  |                             | `INSERT INTO a1 VALUES (1)`                         |                                                     |
| 5  | `INSERT INTO a2 VALUES (1)` |                                                     |                                                     |
| 6  |                             |                                                     | `BEGIN TRANSACTION ISOLATOIN LEVEL REPEATABLE READ` |
| 7  |                             |                                                     | `INSERT INTO a1 VALUES (1)`                         |
| 8  | `COMMIT`                    |                                                     |                                                     |
| 9  |                             | `COMMIT`                                            |                                                     |
| 10 | Crash!!!                    |                                                     | ローカルサーバがクラッシュしたのでAbort             |

このような状況が起きた場合、片方の外部サーバではトランザクションが成功し、もう片方では失敗するため、2つのサーバ間でのデータの整合性が崩れてしまいます（各サーバに閉じれば整合性は保たれています）。

postgres_fdwでは複数サーバに跨るアトミックなコミットをサポートしていません、FDWを介して複数サーバ上のテーブルを更新した場合、COMMIT時に外部サーバで開いているトランザクションを一つずつコミットしていきます。しかし、ある外部サーバでのコミット中にそのサーバが故障してしまうかもしれませんし、もしくはこれからコミットする必要のある外部サーバがダウンしてしまう可能性もあります。このような場合に、postgres_fdwでは「一方のサーバではコミットされたけど、もう一方のサーバではアボートした」という状況が起こり得ます。

## まとめ

FDWを使った時にトランザクションの観点から注意するべき点について書きました。一言でいうとFDWはまだreadとwriteが混じったグローバルなトランザクションに対応していません。postgres_fdwを使った場合、外部サーバはPostgreSQLなので各サーバに閉じれば整合性は保たれていますし、一度コミットされたデータが消失することはありませんが、複数のサーバで構成された一つの大きなクラスタとして見ると、期待とは異なる挙動をしているように見えたり、データの整合性が保たれない事があります。とはいえ、read-onlyなワークロードや、そこまで結果の正確性を求めない場合など、ユースケースによってはFDWは大きな武器になるため、FDWを本格的に使っていこうという方はぜひその辺りも注意して検討してみてください。

ちなみにFDWはPostgreSQLコミュニティでも活発に開発が続けられている機能の一つです。上記の問題を解決するような機能もいくつか提案されているので今後の進化にも期待ですね[^solution]。

[^solution]: 読取り異常の方はタイムスタンプを使った一貫性のあるスナップショットを用いてデータを見に行く方法。更新異常の方は2相コミットを用いた方法
