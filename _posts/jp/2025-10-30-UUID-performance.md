---
layout: post
title: UUIDの生成速度を上げる取り組み
lang: jp
tags:
  - PostgreSQL
  - UUID
---

以前PostgreSQL 18でUUIDv7がサポートされたという[記事](https://masahikosawada.github.io/2025/09/04/UUIDv7-in-PostgreSQL/)を書きました。今回は現在取り組んでいるUUIDv7の生成を早くするための改善について、その背景や検証内容についてです。

# 背景

UUIDの生成速度が気になったきっかけは、PostgreSQLで色々なUUIDv7生成方法を比較していた時に、PostgreSQL 18で導入される予定の`uuidv7()`関数とpgrxで自前で作ったUUIDv7生成関数の性能比較をしていたときでした。

PostgreSQL 18の`uuidv7()`関数はC言語で実装されていて、自作のpgrxのUUIDv7（便宜上`pgrx_uuiv7()`と呼びます）はRustのuuid createを利用して実装しています[^pgrx-uuidv7]。

[^pgrx-uuidv7]: 前回のポストにコードを乗せています

UUIDv7を100万件生成するのにかかった時間は以下のとおりです:

|              | `uuidv7()` | `pgrx_uuidv7()` |
|--------------|------------|-----------------|
| 実行時間(ms) | 2203.124   | 264.688         |

`uuidv7()`でも秒間約45万個のUUIDv7が生成できていてる一方で、`pgrx_uuidv7()`は約10倍近く速い結果となりました。この生成速度の違いを調べた所、ランダムデータ生成が実行時間の大半を占めていて、それぞれの方式で異なるランダムデータ生成方法が使用されていることがわかりました。

# PostgreSQLのランダムデータ生成方法

PostgreSQLは以下の2つ種類のランダムデータ生成方法をサポートしています（Linuxの場合）：

1. OpenSSLの`RAND_bytes()`関数を使う
2. /dev/urandomを読む

PostgreSQLではビルド時にどちらの方法を利用するか決めていて、OpenSSLを利用してビルドした場合(`--with-openssl`を指定)は常に1を選択することになります。2はFallBackとして用意されています。

先程の性能測定では、OpenSSLを利用しないでビルドしたPostgreSQLを利用したので2の方法を利用していました。2は[コード](https://github.com/postgres/postgres/blob/master/src/port/pg_strong_random.c#L150)を見ると分かる通り、`/dev/urandom`を`open()`して`read()`し、最後に`close()`するという、移植性の高い方法ではありますが性能的には良くありません。

一方、OpenSSLを利用すると[`RAND_bytes()`関数を使用](https://github.com/postgres/postgres/blob/master/src/port/pg_strong_random.c#L90)してランダムデータを生成します。PostgreSQLをOpenSSLを有効にしてビルドし直してもう一度UUIDv7の生成速度を測定してます。


|              | `uuidv7() (/dev/urandomを利用)` | `uuidv7() (OpenSSLのRAND_bytes()を利用)` | `pgrx_uuidv7()` |
|--------------|---------------------------------|------------------------------------------|-----------------|
| 実行時間(ms) | 2203.124                        | 759.296                                  | 264.688         |

OpenSSLは`/dev/urandom`よりはかなり速いが、`pgrx_uuidv7()`よりは遅いという結果になりました。世の中のほぼすべてのPostgreSQLはOpenSSLを有効にしてビルドされたものだと思うので、UUIDの生成速度で困ることはほとんどないでしょう。

しかし、`pgrx_uuidv7()`とはまだ3倍近くの差があります。一度検証を始めたからには、この差を埋める方法が見つかるまでさらに検証を進めていきます。

# uuid createでは`getrandom()`を使っていた

`pgrx_uuidv()`の元になっている`Uuid::now_v7()`を調べた所、おそらく最終的には(Linuxでは)`getrandom()`関数を使ってランダムデータを生成しているようです[^source]。[`getrandom()`](https://man7.org/linux/man-pages/man2/getrandom.2.html)はランダムデータを生成するglibcの関数であり、同名のシステムコールを呼びます。

[^source]: https://github.com/rust-lang/rust/blob/master/library/std/src/random.rs

`getrandom()`関数の`flags`に`GRND_NONBLOCK`を指定することで`/dev/urandom`と同じソースからランダムデータを生成することができるようです。`/dev/urandom`を`open()`したり`read()`する必要がないので高速に動きます。古いLinuxではサポートされていないシステムコールなので注意が必要です。

# 実際どれくらい違うのか？

簡単なCプログラムを書いて、それぞれ方式でののランダムデータ生成速度を測定してみました。各方式では、以下のようにランダムデータを生成しています。

1. urandom: `/dev/urandom`を直接読む
2. `getrandom()`関数を呼ぶ
3. OpenSSLの`RAND_bytes()`関数を呼ぶ

生成するデータサイズを変えながら、データ生成にかかった時間を計測しました（単位はナノ秒）:

```
$ ./bench
        len    urandom  getrandom   openssl
         16       1932         61      1505
         64       2067        160       427
        256       2507        505       492
       1024       4346       1807       592
```

生成データが小さい場合(len<=64)はgetrandomの方が圧倒的に性能が良く、生成するデータが大きくなっていくとOpenSSLの方が良くなる、という結果でした。PostgreSQLのUUIDv7実装では62 bitsのランダムデータを格納しているので、`getrandom()`を利用していた`pgrx_uuidv7()`が一番早かったのは納得です。

# PostgreSQLでも`getrandom()`が使えるのか？

より速いUUID生成性能を得るために、開発コミュニティに提案したのが[こちら](https://www.postgresql.org/message-id/CAD21AoAjb2TP%2BUj-fOr7s1cjv2Eq65BaUYi8xNMumcAXiYFM9Q%40mail.gmail.com)です。

セキュリティ、性能、互換性などを中心に議論し、以下のような方針で進めようと思っています。

- Packagerがビルドオプションで使用するランダムデータ生成方法を選択できるようにする。
  - OpenSSLを有効にするけどランダムデータ生成だけは`getrandom()`を使う、みたいなことが可能になる。
  - 実際のシステムでこれを使うユースケースはおそらくほぼないけど、OpenSSLを無効にしてビルドされたPostgreSQLに対するテストの高速化が期待できる
  - とはいえ、セキュリティ面（特にFIPS準拠など[^fips]）を考えるとOpenSSLのRAND_bytes()を使うのがもっとも望ましいというのは変わらない。
  - これまでとの互換性を保つためにも、「OpenSSLが有効ならランダムデータ生成にはRAND_bytes()を使う」という動作をデフォルトにする。
- `getrandom()`が生成するランダムデータでもセキュリティ的な要件を満たせるケースはあるので、UUID生成のレイヤにてユーザが使用するランダムデータ生成方法を選択できるようにする

議論のポイントとしては「セキュリティ＞速度」なので、OpenSSLを有効にしたビルドではこれまでの動作とは変えないようにしながら、ユースケースに応じてユーザが設定できるようにする、という点です。

[^fips]: getrandom()はCSPRNGでRAND_bytes()はDRPRNG

特に最後の点は、`getrandom()`のvDSO実装によりさらなる性能的なメリットが得られることが議論を後押ししました。

# getrandom()のvDSO実装でUUID生成を比べてみる

詳しいことはわかりませんが、新し目のLinuxカーネルではvDSO(Virtual Dynamic Shared Object)という仕組みを利用して、ユーザ空間で`getrandom`システムコール相当の処理ができるようなったようです。コンテキストスイッチも不要かつ、カーネル空間→ユーザ空間へのコピーも不要なのでとても高速化されているとのことです。これは、Linux 6.11以降 + glibc 2.40以降で利用可能で、特に数百バイト程度のランダムデータ生成時にこの方式が利用されます。

実は先程の性能検証結果で使ったマシンにはRed Hat Enterprise Linux 10.0がインストールをされていて、vDSOのgetrandomを利用していました[^rhel10]。なので少量のランダムデータ生成では圧倒的に早かったということです。一応、getrandomシステムコールとの差を比べてみると、以下のような結果になりました。

[^rhel10]: Linux kernel 6.12.0 + glibc-2.39-43ですが、Red Hat Engerprise LinuxではvDSO対応パッチをバックポートしているようです。

```
./bench
            len        urandom      getrandom  getrandom_sys        openssl
             16           1921             61            366           1536
             64           2063            160            501            430
            256           2506            506            953            490
           1024           4351           1801           2780            593
```

# vDSO実装のgetrandomを使ってUUIDを生成してみる

最後にgetrandomを使ってPostgreSQLでUUIDv7を生成すると、どれくらい高速になるかを検証してみます。

この検証には、先程紹介したPostgreSQLコミュニティに提案中のパッチが必要となります。

|              | `uuidv7() (/dev/urandomを利用)` | `uuidv7() (OpenSSLのRAND_bytes()を利用)` | `uuidv7() (getrandom)を利用` | `pgrx_uuidv7() (参考)` |
|--------------|---------------------------------|------------------------------------------|------------------------------|------------------------|
| 実行時間(ms) | 2183.191                        | 766.671                                  | 196.876                      | 260.512                |

ついにPostgreSQLの`uuidv7()`が最も早くなりました！秒間約500万件のUUIDv7が生成できています。ちなみに、同環境では、シーケンスの値を`nextval()`関数で100万回取得するのに352.519msかかったので、シーケンスの払い出しよりも高速になったと言えます[^sequence]。

[^sequence]: シーケンスの払い出しはシーケンス自体の更新＋WALもあるので

# 参考資料

- A vDSO implementation of getrandom() : https://lwn.net/Articles/919008/
- GNU C Library Merges Support for getrandom vDSO : https://www.phoronix.com/news/glibc-getrandom-vDSO-Merged
- implement getrandom() in vDSO : https://lwn.net/Articles/978601/

