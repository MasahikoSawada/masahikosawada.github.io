---
layout: post
title: PostgreSQLのソースコードの構造
tags:
  - PostgreSQL
  - Source Code Reading
---

先日の[PostgreSQLアンカンファレンス](https://pgunconf.connpass.com/event/194291/)でPostgreSQLのソースコードのディレクトリ構成や読み方について簡単に紹介しました。

ソースコードのディレクトリ構成は今後変わる予定があるので、ブログにまとめて今後も適宜アップデートしていこうと思います。

以下の説明は**PostgreSQL 13をベースとしています。**

# どこで手に入るの？

* 公式のgitリポジトリ
  * [git://git.postgresql.org/git/postgresql.git]()
* githubのミラーリポジトリ
  * [https://github.com/postgres/postgres]()
* バージョン毎のソースコード
  * [https://www.postgresql.org/ftp/source/]()

# 何がはいってるの？

大まかには以下のコードが入っています。

* サーバのソースコード（バックエンドと呼んでます）
  * `src/backend`の下
* クライアントのソースコード（フロントエンドを呼んでいます）
  * `src/bin`の下
  * psql、pgbench、pg_dumpなど
* Contribのソースコード
  * `contrib`の下
  * PostgreSQLサーバのコードとは別に管理されているコード
  * rpmだと`postgresql-contrib`パッケージに相当します
* ドキュメント
  * `doc`の下
* リグレッションテスト
  * `src/test`の下

# `src`ディレクトリを見てみる

| パス           | 内容                                         |
|:---------------|:---------------------------------------------|
| src/backend    | PostgreSQLサーバのコード                     |
| src/bin        | クライアントツールのコード                   |
| src/common     | バックエンド、フロントエンド共通で使うコード |
| src/fe_utils   | フロント円でで使う便利なコード(feはFrontEnd) |
| src/include    | ヘッダファイル                               |
| src/interfaces | lipqとecpg                                   |
| src/pl         | plperl, plpgsql, plpythonなど                |
| src/port       | バックエンド、フロント共通の環境依存のコード |
| src/test       | リグレッションテスト                         |
| src/timezone   | タイムゾーン                                 |
| src/tools      | 開発者のためのツール                         |

「Backend = PostgreSQLサーバ」、「Frontend = クライアントツール」がわかればそこまで迷うことはなくなりそう。

# `src/backend`ディレクトリにあるサーバ側のコードを見てみる

| パス                     | 内容                                                                                                                                                                                         |
|:-------------------------|:---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| src/backend/access       | テーブル、インデックスなどのDBデータにアクセスするコード（PostgreSQLではアクセスメソッドを呼んでいるので多分`access`なんだと思う）。WALや2相コミットなどのトランザクション周りのコードもここ |
| src/backend/bootstrap    | データベースクラスタ作成時（`initdb`コマンド実行時）に使われる                                                                                                                               |
| src/backend/catalog      | システムカタログ                                                                                                                                                                             |
| src/backend/commands     | `CREATE TABLE`、`COPY`などのDDLやSQLコマンド                                                                                                                                                 |
| src/backend/executor     | エグゼキュータ。プランナが作成した実行計画を実行する                                                                                                                                       |
| src/backend/foreign      | 外部テーブル（Foreign Data Wrapper）の基盤となるコード                                                                                                                                     |
| src/backend/jit          | JITコンパイル                                                                                                                                                                              |
| src/backend/lib          | バックエンドで使えるライブラリ                                                                                                                                                               |
| src/backend/libpq        | lipqのサーバ側のコード                                                                                                                                                                       |
| src/backend/main         | postgresプロセスのmain関数                                                                                                                                                                   |
| src/backend/nodes        | ノードを扱う関数（比較、コピーなど）                                                                                                                                                       |
| src/backend/optimizer    | オプティマイザ（プランナ）。実行計画を作る                                                                                                                                                 |
| src/backend/parser       | パーサ。SQLを構文解析する                                                                                                                                                                  |
| src/backend/partitioning | テーブル・パーティショニング                                                                                                                                                                 |
| src/backend/po           | ログメッセージの多言語対応                                                                                                                                                                   |
| src/backend/port         | サーバ側の環境依存コード                                                                                                                                                                     |
| src/backend/postmaster   | サーバプロセス（checkpointerやautovacuum launcher/worker、bg writerなど）                                                                                                                    |
| src/backend/regex        | 正規表現                                                                                                                                                                                     |
| src/backend/replication  | 物理、論理レプリケーションやレプリケーションスロット                                                                                                                                         |
| src/backend/rewrite      | リライタ。RULEやROW LEVEL SECURITYなど                                                                                                                                                       |
| src/backend/snowball     | ステミングのためのsnowballライブラリ                                                                                                                                                         |
| src/backend/statistics   | 拡張統計情報（CREATE STATISTICSコマンド）                                                                                                                                                    |
| src/backend/tcop         | Traffic Copの略。SQL処理の起点となる所                                                                                                                                                       |
| src/backend/tsearch      | 全文検索用のライブラリ                                                                                                                                                                       |
| src/backend/utils        | その他色々なコード（設定パラメータ、カタログキャッシュ、メモリ管理、各データ型の実装など）                                                                                                                                                                                             |

# ソースコードを読む際に知っておくと便利な関数

* SQLを受け取り、処理する所
  * `src/backend/tcop/postgres.c`の`exec_simple_query()`
* COPYやALTER TABLE等のDDLやSQLコマンドを実行する所
  * `src/backend/tcop/utility.c`の`standard_ProcessUtility()`

`exec_simple_query()`を見ると、SQLを受信して、構文解析して、実行計画を作成して実行する、という一連の流れを見ることができます。構文解析後にそのSQLがSELECT、UPDATE、INSERT、DELETEの場合はExecutorに処理を渡し、それ以外のDDLやSQLコマンドである場合は、（最終的には）`standard_ProcesUtility()`に処理を引き渡します。
