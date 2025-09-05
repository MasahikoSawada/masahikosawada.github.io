---
layout: post
title: PostgreSQLがUUIDv7をサポート
tags:
  - PostgreSQL
  - UUID
---

UUIDv7は[RFC 9562](https://www.rfc-editor.org/rfc/rfc9562.html)で定義されました。UUIDには8つのバージョンがあり、どれもサイズは128ビットですが、格納するデータがそれぞれバージョンで異なります。私もUUIDv7を知るまでは、UUIDといえばランダムデータのイメージでしたが、それはバージョン4のUUIDで、本記事で紹介するバージョン7のUUID（UUIDv7）はタイムスタンプをデータの先頭に持つためソート可能であるのが大きな特徴です。

実際に比較してみると違いは一目瞭然です:

```sql
=# select uuidv4(), uuidv7() from generate_series(1, 5);
                uuidv4                |                uuidv7
--------------------------------------+--------------------------------------
 216aae4c-6b02-4bea-bd84-7fea9617e0cc | 01991632-e3a0-7468-ac42-26afbc51df65
 55372a64-0351-40a1-a32c-318e581f4561 | 01991632-e3a0-748a-bb4c-9882ddaf0721
 e154c7a7-4a6b-4446-96be-6a1cb84b773e | 01991632-e3a0-749f-b429-d2ef56b9683e
 59adba82-8a88-4f4f-b859-036430d09045 | 01991632-e3a0-74b5-9a86-8107f1851200
 be096cb4-ee48-4bf8-ae30-3ca6d09af786 | 01991632-e3a0-74c9-a08a-1ec588e5a60d
(5 rows)
```

UUIDv7は、例えばデータベースの主キーとして使用した時に多くのメリットがあります。PostgreSQLでは主キーインデックスにはBtreeインデックスが使われます。そのため、大量にデータをロードした場合でも挿入されるUUIDのデータは常に昇順になるので、インデックス更新の局所性が高く、性能的に有利です。また、PostgreSQLではFull Page Writes（FPW）を抑える効果もあります。

SERIAL型（シーケンス）とUUID型（UUIDv4とUUIDv7）に主キーをつけた状態で500万件INSERTした結果は以下のとおりです(PostgreSQL 18 Betaで検証):

|          | SERIAL  | UUIDv4  | UUIDv7   |
|----------|---------|---------|----------|
| Druation | 8.452 s | 42.24 s | 16.922 s |

# PostgreSQLとUUID

PostgreSQLはSQLのデータ型として[`uuid`型](https://www.postgresql.jp/document/17/html/datatype-uuid.html)を持っていて、（PostgreSQL 17現在）UUIDを生成する方法は大きく2つあります。

一つは、組み込みの[`gen_random_uuid()`SQL関数](https://www.postgresql.jp/document/17/html/functions-uuid.html)を利用する方法です。これはバージョン4のUUIDを生成します（バージョンの詳細については後述）。PostgreSQL独自の実装を利用しています。

もう一つは、[uuid-ossp contribモジュール](https://www.postgresql.jp/document/17/html/uuid-ossp.html)を使う方法です。UUID生成を外部ライブラリによって行うのですが、プラットフォームによって利用するライブラリはことなります。LinuxやmacOSではlibuuidを利用します。バージョン1 ~ 5まで生成可能です。

上記の通り、PostgreSQL 17現在、UUIDv7の生成をサポートしていないので、UUIDv7を利用したい場合は、公開されているextensionを利用する、もしくは自分で実装する必要があります。githubで探すと以下のextensionが見つかりました:

- [pg_uuidv7](https://github.com/fboulnois/pg_uuidv7)
  - C言語で実装
- [postgres-uuidv7-sql](https://github.com/dverite/postgres-uuidv7-sql)
  - SQLで実装。なので、Extensionとして登録しなくても`CREATE FUNCTION`を使えば利用可能

pg_tle + PL/RustでUUIDv7を生成する関数を作るブロクもあります：

[https://aws.amazon.com/blogs/database/implement-uuidv7-in-amazon-rds-for-postgresql-using-trusted-language-extensions/](https://aws.amazon.com/blogs/database/implement-uuidv7-in-amazon-rds-for-postgresql-using-trusted-language-extensions/)

PL/Rustは利用できるcrateが限られているためRustのuuid crateは利用できません。自作ExtensionでUUIDv7を生成する関数を作りたい場合は、おそらくpgrx[^pgrx]を利用するのが一番簡単だと思います。UUIDv7の生成だけであれば以下のコードだけで可能です:

[^pgrx]: RustでPostgreSQLのExtensionを作成するためのフレームワーク

```rust
use pgrx::prelude::*;
use uuid::Uuid;

::pgrx::pg_module_magic!(name, version);

#[pg_extern]
fn pgrx_uuidv7() -> pgrx::Uuid {
    let uuid = Uuid::now_v7();

    pgrx::Uuid::from_bytes(uuid.into_bytes())
}
```

PostgreSQL 18では[`uuidv7()`SQL関数](https://www.postgresql.org/docs/devel/functions-uuid.html)が導入されるため、すべてのPostgreSQLがユーザがUUIDv7を利用できるようになります([コミットログ](https://github.com/postgres/postgres/commit/78c5e141e9c139fc2ff36a220334e4aa25e1b0eb))！

後方互換性のため`gen_random_uuid()`はこれまで通りUUIDv4を生成する関数として存在します。`uuidv7()`にあわせて`uuidv4()`も追加されましたが`gen_random_uuid()`のエイリアスです。

# UUIDv7のフォーマット

UUIDv7のフォーマットはRFCに以下のように記載されています:

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                           unix_ts_ms                          |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|          unix_ts_ms           |  ver  |       rand_a          |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|var|                        rand_b                             |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                            rand_b                             |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

すべてのUUIDにはデータ自体にそのバージョンが記載されています（`ver`の部分）。

```
           Version
              |
              v
01937a3a-3d34-74d0-a1b7-e1f1b53064d8
```

UUIDv7では、バージョンの前にミリ秒制度のタイムスタンプを入れ、バージョンの後にランダムデータ(正確には+variant)を入れる、というのがざっくりとしたフォーマットです。

```
  timestamp      random data(+var)
|-----------|  |-------------------|
01937a3a-3d34-74d0-a1b7-e1f1b53064d8

```

## UUIDv7の単調増加性

ミリ秒精度のタイムスタンプでは精度が足りないというユースケースのために、RFCでは、`rand_a`の部分を（またはそれに加えて`rand_b`も)生成されたデータの単調増加性を維持すための追加データとして利用することを許可しています。そして、どのように使うことができるかの方法もいくつかRFCで[紹介されています](https://www.rfc-editor.org/rfc/rfc9562.html#name-monotonicity-and-counters)。

UUIDv7生成関数の実装毎に異なる使い方をしていますが、高頻度なUUID生成が行われる環境でもデータの単調増加性を維持すためにどのように`rand_a`と`rand_b`を使うかはとても重要です。例えば、「ミリ秒精度のタイムスタンプ＋あとは全部ランダムデータ」といった一番単純フォーマットを利用したUUIDv7では、1秒間に1000個以上のUUIDが生成された場合、先頭のタイムスタンプはすべて同じ値になるので、生成されたUUIDv7のデータの単調増加性は保証されません。つまり、秒間1000個以上のUUIDのを生成する可能性あるシステムでは、そのようなUUIDv7生成関数を利用すると、UUIDv7の利点を活かしきることができません。ユースケースに応じて利用するUUIDv7生成関数を見極める必要があります[^pg_uuidv7_analysis]。

[^pg_uuidv7_analysis]: 例えば[pg_uuidv7の実装](https://github.com/fboulnois/pg_uuidv7/blob/main/pg_uuidv7.c#L35)を見ると「ミリ秒精度のタイムスタンプ＋ランダムデータ」ということがわかります

# PostgreSQLのUUIDv7の実装

PostgreSQLのUUIDv7実装では、RFCで記載されている[Method 3(Replace Leftmost Random Bits with Increased Clock Precision)](https://www.rfc-editor.org/rfc/rfc9562.html#name-monotonicity-and-counters)の方法を取り入れました。具体的には、`rand_a`の部分にミリ秒以下のタイムスタンプを入れ、全体で60(=48+12)ビットをタイムスタンプに使っています。これにより、秒間約400万個のUUID生成に耐えることが可能です。さらに、同一プロセス内ではUUID生成事に`rand_a`の部分が必ず増加するように調整しているので、それ以上の高頻度でのUUID生成でも**単一プロセスから生成されるUUIDv7のデータは単調増加していることが保証**されています。

また、引数に`interval`値を入れることができ、UUIDデータに格納されるタイムスタンプを指定した期間だけずらすことも可能です。

ソースコードは[ここ](https://github.com/postgres/postgres/blob/master/src/backend/utils/adt/uuid.c#L601)です。

