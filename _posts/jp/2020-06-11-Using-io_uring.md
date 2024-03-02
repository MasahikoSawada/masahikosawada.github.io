---
layout: post
title: io_uringを使ってみた
tags:
  - Linux
  - io_uring
lang: jp
---

Liunxカーネル 5.1から入ったio_uringに興味があったので実際に使ってみました

調べていくと[liburing](https://github.com/axboe/liburing)なるものを見つけたので、今回はliburingを使ったプログラムを書いたメモです。

# liburingのビルド

liburingのREADMEに書いてあるように、Linux カーネルは5.5以上が必要なので、今回はFedora 32の環境を用意しました。

liburingのビルドは簡単でした。事前に`kernel-devel`、`kernel-modules`、`kernel-headers`のRPMパッケージをインストールしておいたけど、全部必要なのかはわかりません。

```bash
$ cd liburing
$ ./configure
$ make
$ sudo make install
```

ビルドが完了すると`src/`に共有ライブラリが作成されます。

# wcコマンドを実装してみました

io_uring(liburing)を使って`wc`コマンドを実装してみました。[io_uring-by-example](https://github.com/shuveb/io_uring-by-example)や、[liburing/examples/](https://github.com/axboe/liburing/tree/master/examples)あたりを参考にさせていただきました。

ソースはgithubに[置きました](https://github.com/MasahikoSawada/wc_aio)。

```bash
$ git clone git@github.com:MasahikoSawada/wc_aio.git
$ cd wc_aio
$ gcc -Wall -O2 -o wc_aio wc_aio.c -luring
$ ./wc_aio wc_aio.c README.md
  291  723 5082 wc_aio.c
    8   21  110 README.md
  299  744 5192 total
```

非同期I/Oのリクエストを送り、それを待っている間にすでに読んだ分の文字数をカウントしています。ちゃんと作れているかは微妙な所はありますが、io_uringの使い方を少し理解できたので良かったです。

I/Oリクエストを送る時は、こんな感じでSQE(Submission Queue Entry)にI/Oリクエストを追加する。

```c
sqe = io_uring_get_sqe(&ring);
io_uring_prep_readv(sqe, f->fd, &data->iov, 1, f->read_offset);
io_uring_sqe_set_data(sqe, data);
io_uring_submit(&ring)
```

完了したI/Oを取得する時は、こんな感じでCQE(Completion Queue Entry)から取得する。

```c
io_uring_wait_cqe(&ring, &cqe);
data = io_uring_cqe_get_data(cqe);
io_uring_cqe_seen(&ring, cqe);
```

`cqe->res`が実際に読み込んだ（もしくは書き込んだ）サイズになると思うけど、これが実際にリクエストした長さより短い時がある。これはどういうときに発生するんだろう。liburingのドキュメントが見つからなくて詳細な使い方がわからなかった。

プログラム内では、途中から読むようにI/Oリクエストを再度投げるようにしました。

# 最後に

PostgreSQLは同期I/O（かつBuffered I/O）ですが、先月開催されたPGConでio_uringを使った非同期I/Oの導入が[提案されていました](https://www.pgcon.org/events/pgcon_2020/schedule/session/152-asynchronous-io-for-postgresql/)。結構良い性能も出ているようです。パッチがでたらレビューできると良いなと思ってます。

[このあたり](https://kernel.dk/io_uring.pdf)も読んでみてもうちょっと勉強してみます。
