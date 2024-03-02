---
layout: post
title: OS Xで開発中のコードに対してpgindentを実行する
tags:
  - PostgreSQL
  - pgindent
  - OS X
lang: jp
---

外部ツールや開発中のコードについてpgindentを走らせたい時のメモ[^pgindent]。

[^pgindent]:すでにコミットされているコードに対してpgindentを走らせる方法は`src/tools/pgindent/README`に書いてある通り。

基本的なやり方は[ここ](https://wiki.postgresql.org/wiki/Running_pgindent_on_non-core_code_or_development_code)に書いてある方法と同じで、変更済みのソースコードをコンパイルしてできた`postgres`実行ファイルからデバッグ情報を取得して、そこから構造体や変数定義の情報を抽出します。ですが、gccで（デバッグ情報つきで）コンパイルすると実行ファイルにデバッグ情報が入りますが、OS Xで使われているLLVMではデバッグ情報は実行ファイルとは別にあります[^linker]。

[^linker]: LLVMのリンカ(lld)では、デバッグ情報は[リンクしないようです](https://stackoverflow.com/questions/10044697/where-how-does-apples-gcc-store-dwarf-inside-an-executable)。だからOS XでコンパイルしたPostgreSQLのバイナリはgccでコンパイルしたものよりもサイズが小さいんですね

pgindentの実行に必要な手順は以下の通りです。

# 1. `-gdwarf-2`フラグをつける

コンパイル時にはgccのオプションとして`-gdwarf-2`フラグをつけます。なので、`configure`のときに`CFLAGS="-O0 -gdwarf-2"`のような感じで指定します。

# 2. DWARF情報からtypedefsファイルを生成する

OS Xでは以下のように、`dsymutil`を使ってデバッグ情報（DWARF情報）を取り出して、そこから構造体のや変数の定義情報を取得します（`postgres.dwarfファイル`）。`pgindent`コマンドでは`--typedefs`オプションで任意のtypedefsファイルを指定できるので、作成したtypedefsファイルを指定します。

```bash
$ dsymutil -flat src/backend/postgres
$ vim /tmp/conv.pl
while (<>) {
    chomp; @flds = split;next unless (1 < @flds);
    next if $flds[0]  ne "DW_AT_name" && $flds[1] ne "DW_AT_name";
    next if $flds[-1] =~ /^DW_FORM_str/;
    $flds[1] =~ /([\w_-]+)/;
    print "$1\n";
}
$ dwarfdump src/backend/postgres.dwarf | egrep -A3 DW_TAG_typedef | perl /tmp/conv.pl | sort | uniq > /tmp/my.typedefs
$ ./src/tools/pgindent/pgindent --typedefs=/tmp/my.typedefs src/backend/access/heap/heapam.c
$ rm src/backend/postgres.dwarf
```

上記の方法を使えば多くの場合で上手くいきますが、たまにgcc+objdumpで作ったtypedefsを使った場合と異なる結果になるので念の為チェックが必要です。あとコンパイル環境によっても当然バイナリが変わり、それによっても抽出できる定義情報は異なるので要注意です。
