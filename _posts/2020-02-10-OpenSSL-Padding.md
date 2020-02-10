---
layout: post
title: OpenSSLでAES暗号したときのPadding
tags:
  - AES
  - OpenSSL
---

OpenSSLのPaddingではまったので覚書。

# TL;DR
* 入力サイズがAESのブロックサイズ（16バイト）の倍数でない可能性があるのなら、`EVP_{En|De}cryptFinal_ex`が必要
* PaddingにはPKCS#7 Paddingを使っており、入力サイズがブロックサイズの倍数の場合でも、1ブロック分Paddingされる
* PKCS#7 Paddingを使った際の暗号化データサイズは、`data_size + (block_size - data_size % block_size)`で計算できる

# 実験

OpenSSLを使うソースは以下の通り。

```c
#include <stdlib.h>
#include <stdio.h>
#include <openssl/conf.h>
#include <openssl/evp.h>
#include <openssl/err.h>

#define KEY	"12345678901234567890123456789012"
#define IV	"1234567890123456"
#define BUFSIZE 128

void dump(char *msg, uint8_t *d, int len)
{
	fprintf(stderr, "%s (%2d) : ", msg, len);
	for (int i = 0; i < len; i++)
	{
		if (i % 10 == 0 && i != 0)
			fprintf(stderr, "| ");
		fprintf(stderr, "%02X ", d[i]);
	}
	fprintf(stderr, "\n");
}

void dec(uint8_t *in, int inlen)
{
	int olen, len;
	uint8_t out[BUFSIZE];
	EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();

	EVP_DecryptInit_ex(ctx, EVP_aes_256_cbc(), NULL, NULL, NULL);
	EVP_CIPHER_CTX_set_key_length(ctx, 32);
	EVP_DecryptInit_ex(ctx, NULL, NULL, KEY, IV);
	EVP_DecryptUpdate(ctx, out, &len, in, inlen);
	olen = len;
	EVP_DecryptFinal_ex(ctx, out + olen, &len);
	olen += len;
	dump("dec", out, olen);
	EVP_CIPHER_CTX_free(ctx);
}

void enc(uint8_t *data, int datalen)
{
	int olen, len;
	uint8_t out[BUFSIZE];
	EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();

	dump("in ", data, datalen);
	EVP_EncryptInit_ex(ctx, EVP_aes_256_cbc(), NULL, NULL, NULL);
	EVP_CIPHER_CTX_set_key_length(ctx, 32);
	EVP_EncryptInit_ex(ctx, NULL, NULL, KEY, IV);
	EVP_EncryptUpdate(ctx, out, &len, data, datalen);
	olen = len;
	EVP_EncryptFinal_ex(ctx, out + olen, &len);
	olen += len;
	dump("enc", out, olen);

	dec(out, olen);
	EVP_CIPHER_CTX_free(ctx);
}


int main()
{
	uint8_t in[16] = {
		0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x10,
		0x11, 0x12, 0x13, 0x14, 0x15, 0x16
	};
	enc(in, 16);

	return 0;
}
```

これをコンパイル（以下はOS Xの環境の例）して、

```
$ gcc -o test test.c -L /usr/local/Cellar/openssl/1.0.2t/lib/ -lcrypto -I /usr/local/Cellar/openssl/1.0.2t/include/
```

実行すると、

```
$ ./test
in  (16) : 01 02 03 04 05 06 07 08 09 10 | 11 12 13 14 15 16
enc (32) : 4A 86 AA B0 F5 53 4B A1 AC 8F | E3 10 94 80 53 40 44 FB FE 41 | 15 1E DA 04 80 93 07 87 42 8E | EB 02
dec (16) : 01 02 03 04 05 06 07 08 09 10 | 11 12 13 14 15 16
```

となる。（`in`は入力、`enc`は暗号化後のデータ、`dec`は復号したデータ）

AESは16バイトを1ブロックとして暗号化するブロック暗号なので、入力が16バイトの場合はちょうど1回AES暗号を行えばOKのはず。だけど、実際にやってみると出力は32バイトになっている。

これは、OpenSSLは[PKCS#7 Padding](https://en.wikipedia.org/wiki/Padding_(cryptography)#PKCS%235_and_PKCS%237)を使っており、デフォルトで有効になっているのが原因。PCKS#7 Paddingでは、Paddingがあることが前提なので、暗号化対象データがちょうどブロックサイズの倍数の場合でも、1ブロック分Paddingが追加される。実際に、コードを以下のように変更してPaddingを無効にしてみると、暗号化後も16バイトになる。

```diff
@@ -29,6 +29,7 @@

        EVP_DecryptInit_ex(ctx, EVP_aes_256_cbc(), NULL, NULL, NULL);
        EVP_CIPHER_CTX_set_key_length(ctx, 32);
+       EVP_CIPHER_CTX_set_padding(ctx, 0);
        EVP_DecryptInit_ex(ctx, NULL, NULL, KEY, IV);
        EVP_DecryptUpdate(ctx, out, &len, in, inlen);
        olen = len;
@@ -47,6 +48,7 @@
        dump("in ", data, datalen);
        EVP_EncryptInit_ex(ctx, EVP_aes_256_cbc(), NULL, NULL, NULL);
        EVP_CIPHER_CTX_set_key_length(ctx, 32);
+       EVP_CIPHER_CTX_set_padding(ctx, 0);
        EVP_EncryptInit_ex(ctx, NULL, NULL, KEY, IV);
        EVP_EncryptUpdate(ctx, out, &len, data, datalen);
        olen = len;
```

```
$ ./test
in  (16) : 01 02 03 04 05 06 07 08 09 10 | 11 12 13 14 15 16
enc (16) : 4A 86 AA B0 F5 53 4B A1 AC 8F | E3 10 94 80 53 40
dec (16) : 01 02 03 04 05 06 07 08 09 10 | 11 12 13 14 15 16
```

だからといって、入力サイズがブロックサイズの倍数かどうかでPaddingの有効／無効を切り替えるのは良くない、というか実現は難しい。例えば、Paddingが必要の時にのみPaddingを有効にした場合、生のデータサイズがブロックサイズの倍数であってもそうでなくても、暗号化後は（Paddingされているので）必ずブロックサイズの倍数になる。そうすると、復号時には元のデータサイズはわからず、Paddingを有効／無効にする判断ができない（またはどこかでそのような情報を持っておくことも考えられるが多分それは間違ってる）。

逆にPaddingを常に有効にすると、暗号化時に暗号化後のデータサイズが幾つになるのかを計算する必要がでてくる。けど、PKCS#7 Paddingを使う場合、暗号化後のデータサイズは、`data_size + (block_size - dta_size % block_size)`で計算できるので、それを元に出力用のメモリを確保することで対応可能。

まとめると、

* 暗号化後のデータサイズを求めてバッファを確保
* Paddingは常に有効（デフォルト）する
* `EVP_{En|De}cryptFinal_ex`は常に実行する
* `EVP_{En|De}cryptUpdate`、`EVP_{En|De}cryptFinal_ex`の出力データサイズ(`olen`)の合計が実際の暗号化／復号したデータ。特に復号時は、復号してみないと元データの大きさがわからないので、復号処理の中で余分なデータを削除したりする必要がある（もしくは復号後のサイズも一緒に返す）。

というやり方が正しいそうな感じ。

# おまけ1

`openssl`コマンドでも`-nopad`をつけることで同じ事ができる。

```
$ echo 123456789012345 | openssl enc -aes-256-cbc -nosalt  -e | wc
enter aes-256-cbc encryption password:
Verifying - enter aes-256-cbc encryption password:
      0       1      32
$ echo 123456789012345 | openssl enc -aes-256-cbc -nosalt -nopad -e | wc
enter aes-256-cbc encryption password:
Verifying - enter aes-256-cbc encryption password:
      0       1      16
```

# おまけ2

PKCS#7 PaddingがどのようにPaddingをしているのかを確認してみる。

```diff
@@ -9,8 +9,8 @@

 void dump(char *msg, uint8_t *d, int len)
 {
-       fprintf(stderr, "%s (%d) : ", msg, len);
-       for (int i = 0; i < len; i++)
+       fprintf(stderr, "%s (%2d) : ", msg, len);
+       for (int i = 0; i < 32; i++)
        {
                if (i % 10 == 0 && i != 0)
<                        fprintf(stderr, "| ");
@@ -65,6 +65,12 @@
                0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x10,
                0x11, 0x12, 0x13, 0x14, 0x15, 0x16
        };
-       enc(in, 16);
+
+       for (int i = 1; i <= 16; i++)
+               enc(in, i);

        return 0;
```

```
$ ./test 2>&1 | grep dec
dec ( 1) : 01 0F 0F 0F 0F 0F 0F 0F 0F 0F | 0F 0F 0F 0F 0F 0F 00 00 00 00 | 00 00 00 00 00 00 00 00 00 00 | 00 00
dec ( 2) : 01 02 0E 0E 0E 0E 0E 0E 0E 0E | 0E 0E 0E 0E 0E 0E 00 00 00 00 | 00 00 00 00 00 00 00 00 00 00 | 00 00
dec ( 3) : 01 02 03 0D 0D 0D 0D 0D 0D 0D | 0D 0D 0D 0D 0D 0D 00 00 00 00 | 00 00 00 00 00 00 00 00 00 00 | 00 00
dec ( 4) : 01 02 03 04 0C 0C 0C 0C 0C 0C | 0C 0C 0C 0C 0C 0C 00 00 00 00 | 00 00 00 00 00 00 00 00 00 00 | 00 00
dec ( 5) : 01 02 03 04 05 0B 0B 0B 0B 0B | 0B 0B 0B 0B 0B 0B 00 00 00 00 | 00 00 00 00 00 00 00 00 00 00 | 00 00
dec ( 6) : 01 02 03 04 05 06 0A 0A 0A 0A | 0A 0A 0A 0A 0A 0A 00 00 00 00 | 00 00 00 00 00 00 00 00 00 00 | 00 00
dec ( 7) : 01 02 03 04 05 06 07 09 09 09 | 09 09 09 09 09 09 00 00 00 00 | 00 00 00 00 00 00 00 00 00 00 | 00 00
dec ( 8) : 01 02 03 04 05 06 07 08 08 08 | 08 08 08 08 08 08 00 00 00 00 | 00 00 00 00 00 00 00 00 00 00 | 00 00
dec ( 9) : 01 02 03 04 05 06 07 08 09 07 | 07 07 07 07 07 07 00 00 00 00 | 00 00 00 00 00 00 00 00 00 00 | 00 00
dec (10) : 01 02 03 04 05 06 07 08 09 10 | 06 06 06 06 06 06 00 00 00 00 | 00 00 00 00 00 00 00 00 00 00 | 00 00
dec (11) : 01 02 03 04 05 06 07 08 09 10 | 11 05 05 05 05 05 00 00 00 00 | 00 00 00 00 00 00 00 00 00 00 | 00 00
dec (12) : 01 02 03 04 05 06 07 08 09 10 | 11 12 04 04 04 04 00 00 00 00 | 00 00 00 00 00 00 00 00 00 00 | 00 00
dec (13) : 01 02 03 04 05 06 07 08 09 10 | 11 12 13 03 03 03 00 00 00 00 | 00 00 00 00 00 00 00 00 00 00 | 00 00
dec (14) : 01 02 03 04 05 06 07 08 09 10 | 11 12 13 14 02 02 00 00 00 00 | 00 00 00 00 00 00 00 00 00 00 | 00 00
dec (15) : 01 02 03 04 05 06 07 08 09 10 | 11 12 13 14 15 01 00 00 00 00 | 00 00 00 00 00 00 00 00 00 00 | 00 00
dec (16) : 01 02 03 04 05 06 07 08 09 10 | 11 12 13 14 15 16 10 10 10 10 | 10 10 10 10 10 10 10 10 10 10 | 10 10
```
