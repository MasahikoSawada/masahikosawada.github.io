---
layout: post
title: Building PostgreSQL with musl libc
lang: en
tags:
  - PostgreSQL
---

The well-known implementation of the standard C library is glibc. [musl libc](https://www.musl-libc.org) is another implementation of the standard C library. It uses the MIT License, and it is known for its simple implementation and small binary size. It is also used in Alpine Linux.

A comparison with glibc can be found [here](https://www.musl-libc.org).

This post is a note on how to build PostgreSQL using musl libc.

# Preparing musl libc

The source code of musl libc can be downloaded [here](https://musl.libc.org/releases.html). It seems that there is also a place called [musl.cc](https://musl.cc/) where you can download pre-built binaries, but this time I built it from source code:

```bash
$ wget https://musl.libc.org/releases/musl-1.2.5.tar.gz
$ tar zxf musl-1.2.5.tar.gz
$ cd musl-1.2.5
$ ./configure --prefix=/home/masahiko/musl --syslibdir=/home/masahiko/musl-lib/
$ make
$ make install
```

By specifying `--prefix` and `--syslibdir` options, you can specify the directories where musl libc and the dynamic linker will be installed, respectively. The build completed in about 20 seconds in my environment.

You can find a program called `musl-gcc` in the `bin` directory of the installation destination:

```bash
$ ls /home/masahiko/musl/bin
musl-gcc
```

`musl-gcc` is a wrapper program (it's actually a shell script), and it seems that when you compile programs using this, they will be linked against musl libc.

# Building PostgreSQL from source code

## Preparation

As preparation, include the `musl-gcc` installed above in the `PATH`:

```bash
$ export PATH=/home/masahiko/musl/bin:$PATH
```

Then, copy the directories `/usr/include/linux`, `/usr/include/asm`, and `/usr/include/asm-generic` to the location where musl libc was installed:

```bash
$ cd /home/masahiko/musl/include
$ cp -rs /usr/include/linux linux/
$ cp -rs /usr/include/asm asm/
$ cp -rs /usr/include/asm-generic asm-generic/
```

The reason for doing this will be explained later.

## Build

Download the PostgreSQL source code and built it:

```bash
$ git clone git://git.postgresql.org/git/postgresql.git
$ cd postgresql
$ ./configure --prefix=/home/masahiko/pgsql CC=musl-cc --without-readline --without-icu --witout-zlib
$ make
$ make install
```

## About `CC=musl-cc`

You can specify the compiler to use with `CC`.

## About specifying `--without-XXX`

By default, PostgreSQL builds with readline, zlib, and icu enabled (in the case of using `configure` script). While the readline header files are in `usr/include/readline`, `/usr/include` also contains the header files of glibc. Therefore, if it's configured to search `/usr/include` directory when compiling programs, the build using `musl-gcc` wouldn't work. So I disabled these libraries for the build.

The reason I copied `/usr/include/linux` etc. directories in the preparation step was to deal with this problem. [This seems to be the recommended way](https://www.openwall.com/lists/musl/2017/11/23/1), but I went with it for now. I think readline etc. could also be built in a similar way. Not sure.

While PostgreSQL can be built without readline etc. `/usr/include/linux` etc. are essential for building PostgreSQL as PostgreSQL's built-in programs are using it. For instance, `pg_combinebackup` requires `/usr/include/linux`. Without these steps, I got the following error in my environment:

```bash
musl-gcc -Wall -Wmissing-prototypes -Wpointer-arith -Wdeclaration-after-statement -Werror=vla -Wendif-labels -Wmissing-format-attribute -Wimplicit-fallthrough=3 -Wcast-function-type -Wshadow=compatible-
local -Wformat-security -fno-strict-aliasing -fwrapv -fexcess-precision=standard -Wno-format-truncation -Wno-stringop-truncation -O2 -I../../../src/interfaces/libpq -I../../../src/include  -D_GNU_SOURCE
   -c -o pg_combinebackup.o pg_combinebackup.c
pg_combinebackup.c:24:10: fatal error: linux/fs.h: No such file or directory
   24 | #include <linux/fs.h>
      |          ^~~~~~~~~~~~
```

## WARNINGs during build

In my environment, I got the following WARNING during the build, but the build itself succeeded, so no problem:

```bash
pg_get_line.c: In function _pg_get_line_append_:
pg_get_line.c:129:27: warning: _({anonymous})_ may be used uninitialized [-Wmaybe-uninitialized]
  129 |         if (prompt_ctx && sigsetjmp(*((sigjmp_buf *) prompt_ctx->jmpbuf), 1) != 0)
      |                           ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
```

# Veficiation

After building PostgreSQL from source code, verify that it is indeed linked against musl libc:


```bash
$ ldd bin/postgres
        linux-vdso.so.1 (0x00007ffd0bdf6000)
        libc.so => /home/masahiko/musl/lib/libc.so (0x00007f21be639000)
```

musl libc is not completely compatible with glibc, and there are [some behavioral differences](https://wiki.musl-libc.org/functional-differences-from-glibc.html), `make check-world` also passed.

While musl libc is smaller as a library than glibc, glibc is faster in terms of performance, so I'd also like to compare the performance as the next step.
