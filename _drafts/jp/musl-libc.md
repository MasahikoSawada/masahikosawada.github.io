---
layout: post
title: PostgreSQLでmusl libcを使う方法
tags:
  - PostgreSQL
---

有名な標準Cライブラリの実装はglibc。[musl libc](https://www.musl-libc.org/)(マッスル)は別の標準Cライブラリの実装。ライセンスはMITライセンスで、シンプルな実装、小さいバイナリ、が特徴らしい。Alpine Linuxでも使われているとの事。

glibcとの比較は[こちら](https://www.etalabs.net/compare_libcs.html)。

このmusl libcを使うPostgreSQLをビルドする方法のメモ。

# musl libcの準備

ソースコードは[ここ](https://musl.libc.org/)から取得可能。[musl.cc](https://musl.cc/)というビルド済みのバイナリをダウンロード出来る所もあるらしいが、今回はソースコードをビルドした。


```bash
$ wget https://musl.libc.org/releases/musl-1.2.5.tar.gz
$ tar zxf musl-1.2.5.tar.gz
$ cd musl-1.2.5
$ ./configure --prefix=/home/masahiko/musl --syslibdir=/home/masahiko/musl-lib/
$ make
$ make install
```

`--prefix`と`--syslibdir`オプションで、musl libcがインストールされるディレクトリとダイナミックリンカがインストールされるディレクトリを指定する。ビルドは20秒程度で終わった。

インストール先の`bin`ディレクトリに`musl-gcc`というプログラムがあればOK。

```bash
$ ls /home/masahiko/musl/bin
musl-gcc
```

これはgccのラッパーで、これを使ってプログラムをコンパイルするとmusl libcにリンクするようになるらしい。

# PostgreSQLのビルド

開発版のHEADを使ってビルドする。


## 下準備

下準備として、先程インストールした`musl-gcc`をPATHに含めておく。

```bash
$ export PATH=/home/masahiko/musl/bin:$PATH
```

また、`/usr/include/linux`、`/usr/include/asm`、`/usr/include/asm-generic`をディレクトリごと、musl libcをインストールしたところにコピーする。

```bash
$ cd /home/masahiko/musl/include
$ cp -rs /usr/include/linux linux/
$ cp -rs /usr/include/asm asm/
$ cp -rs /usr/include/asm-generic asm-generic/
```

これをする理由は後ほど。

## ビルド

PostgreSQLのソースコードをダウンロードして、ビルドする。

```bash
$ git clone git://git.postgresql.org/git/postgresql.git
$ cd postgresql
$ ./configure --prefix=/home/masahiko/pgsql CC=musl-cc --without-readline --without-icu --witout-zlib
$ make
$ make install
```

## `CC=musl-cc`について

CCには使用するコンパイラを指定できる。

## `--without-XXX`の指定について

PostgreSQLがデフォルトでreadline, zlib, icuを有効にしてビルドする（configureの場合）。例えば、readlineのヘッダファイルは`/usr/include/readline`にあるけど、`/usr/include`にはglibcのヘッダファイルもある。なので`/usr/include`を探しに行くように設定するとmusl libcを使ったビルドができなかった。なので、これらのライブラリは無効にした状態でビルドする。今回はお試しなのでこれでOK。

下準備として`/usr/include/linux`等をディレクトリごとコピーしたのはこれに対応するため。これは[推奨された方法ではない](https://www.openwall.com/lists/musl/2017/11/23/1)らしいけど今回はこれでOKとした。おそらく、readline等も同じようにすればビルド出来るのだと思う。

readline等はなくてもPostgreSQLのビルドは出来るけど、`/usr/include/linux`等はPostgreSQLのビルドに必須だったので今回はこの方法を使った。これがないと、自分の環境は以下のエラーが出た。

```bash
musl-gcc -Wall -Wmissing-prototypes -Wpointer-arith -Wdeclaration-after-statement -Werror=vla -Wendif-labels -Wmissing-format-attribute -Wimplicit-fallthrough=3 -Wcast-function-type -Wshadow=compatible-
local -Wformat-security -fno-strict-aliasing -fwrapv -fexcess-precision=standard -Wno-format-truncation -Wno-stringop-truncation -O2 -I../../../src/interfaces/libpq -I../../../src/include  -D_GNU_SOURCE
   -c -o pg_combinebackup.o pg_combinebackup.c
pg_combinebackup.c:24:10: fatal error: linux/fs.h: No such file or directory
   24 | #include <linux/fs.h>
      |          ^~~~~~~~~~~~
```

## ビルド中のWARNING

自分の環境では、以下のようなWARNINGが出た。ビルド自体はできたので問題なし。

```
pg_get_line.c: In function _pg_get_line_append_:
pg_get_line.c:129:27: warning: _({anonymous})_ may be used uninitialized [-Wmaybe-uninitialized]
  129 |         if (prompt_ctx && sigsetjmp(*((sigjmp_buf *) prompt_ctx->jmpbuf), 1) != 0)
      |                           ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
```

# 確認

PostgreSQLがビルドできたら、ちゃんとmusl libcにリンクするようになっているかを確認する。

```bash
$ ldd bin/postgres
        linux-vdso.so.1 (0x00007ffd0bdf6000)
        libc.so => /home/masahiko/musl/lib/libc.so (0x00007f21be639000)
```

`make check-world`も通って一安心。
