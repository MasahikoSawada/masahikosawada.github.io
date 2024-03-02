---
layout: post
title: リリースノートからコミットログを調べる
tags:
  - PostgreSQL
lang: jp
---

先日リリースされたPostgreSQL 12のリリースノートは[こちら](https://www.postgresql.org/docs/12/release-12.html)です。

<div align="center">
<img src="/images/release-note-12.png">
</div>

リリースノートの項目から該当するコミットログを検索するにはリリースノートのソースファイル（SGMLファイル）を見ると楽です。

ソースコードが手元になくてもPostgrfeSQLのgitリポジトリを[ここから](https://git.postgresql.org/gitweb/?p=postgresql.git;a=summary)見れるので、そこから`doc/src/sgml/release-12.sgml`を探します[^github]。

[^github]: githubのほうが慣れている場合は[こちら](https://github.com/postgres/postgres)

各バージョンの安定版ブランチは`REL_XX_STABLE`(PostgreSQL 12の場合は`REL_12_STABLE`)となっているので、見たいバージョンのブランチから上記のファイルを探します。例えばPostgreSQL 12の場合は、[こちら](https://git.postgresql.org/gitweb/?p=postgresql.git;a=blob;f=doc/src/sgml/release-12.sgml;h=04f4effa8a48a32425da6d36dae81107a0344e06;hb=refs/heads/REL_12_STABLE)からソースファイルを見ることができます。

リリースノートのソースファイルには以下のように変更点の上に対応するコミットがコメントとして記載されています。

```
<!--
Author: Michael Paquier <michael@paquier.xyz>
2019-03-13 [6dd263cfa] Rename pg_verify_checksums to pg_checksums
-->

     <para>
      Rename command-line tool
      <application>pg_verify_checksums</application> to <xref
      linkend="app-pgchecksums"/> (Michaël Paquier)
      </para>
     </listitem>
```

後は、Commit ID(上記の場合は`6dd263cfa`)を元に、ソースコードが手元にある場合は`git show`等で見るか、[https://git.postgresql.org/gitweb/?p=postgresql.git;a=commit;h=6dd263cfa](https://git.postgresql.org/gitweb/?p=postgresql.git;a=commit;h=6dd263cfa)のように`h=<commit id>`をすればブラウザ上でも見れます。

**(2019-10-11追記)**

@noborusさんから以下のコメントをいただきました。

<blockquote class="twitter-tweet"><p lang="ja" dir="ltr">実はこっちだと見られるようにしてあります（コメントを表示するようにしているだけですが）。<a href="https://t.co/pNBtasoHu2">https://t.co/pNBtasoHu2</a><br><br>実は公式の日本語マニュアルでもhtmlはコメントをコメントとして残すようにしてあるので、htmlのソースを見るとコメントを見ることが出来ます。<a href="https://t.co/EQ7BwTO0oi">https://t.co/EQ7BwTO0oi</a> <a href="https://t.co/GMWJy7Etbk">https://t.co/GMWJy7Etbk</a></p>&mdash; Saito Noboru (@noborus) <a href="https://twitter.com/noborus/status/1182466688794542080?ref_src=twsrc%5Etfw">October 11, 2019</a></blockquote> <script async src="https://platform.twitter.com/widgets.js" charset="utf-8"></script>

htmlのソースからコメントを見るのもありですし、教えて頂いた[こちらのページ](https://pgsql-jp.github.io/current/html/release-12.html)では、変更点とコミットログが一緒に見れて便利です！

この方法が一番楽に確認できるかもしれませんね。
