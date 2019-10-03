---
layout: post
title: PostgreSQLのリカバリ周りのバグを修正してみた - 問題発見編 -
tags:
  - PostgreSQL
  - Bug fixes
---

私自身PostgreSQL本体の開発やバグ修正を何度か行っているのですが、最近リカバリ機能周りで面白いバグを修正したので、バグの発見から原因の特定、修正まで実際に行ったことを紹介しようと思います。これからPostgreSQLに貢献していきたい、開発を始めたいという方に参考になると嬉しいです。

**本バグはすでに[修正されている](https://git.postgresql.org/gitweb/?p=postgresql.git;a=commitdiff;h=df86e52cace2c4134db51de6665682fb985f3195)ため、再現したい方は9.5.19以前、9.6.15以前、10.10以前、11.5以前のどれかを使うか、開発用ブランチを使う場合は、コミット`df86e52cace2c413`よりも古いコードを利用してください**

本記事ではPostgreSQLの開発用ブランチ(materブランチ)を使用しています。PostgreSQLのソースコードのダウンロードやビルドについては[こちら](https://qiita.com/sawada_masahiko/items/2fa99e422ec0eb35245c#%E3%82%BD%E3%83%BC%E3%82%B9%E3%82%B3%E3%83%BC%E3%83%89%E5%85%A5%E6%89%8B%E3%81%8B%E3%82%89%E8%B5%B7%E5%8B%95%E3%81%BE%E3%81%A7)の記事をご参照ください。

# バグの発見

Single Page Recovery[^pagerecovery]という技術をPostgreSQLに組み込むために開発していた所、PostgreSQLの[タイムラインID](https://www.postgresql.jp/document/11/html/continuous-archiving.html#BACKUP-TIMELINES)について理解を深めるために、色々な動作確認や実験をしていました。

[^pagerecovery]: おもしろい技術なのでまた今度解説します。

実際に行った動作確認は以下のステップです。ざっくりいうと、PITRしたデータベースから更にバックアップを取得してPITRをしています。

```bash
# データベースの作成
ninitdb -D base -E UTF8 --no-locale

# 設定ファイルの編集
cat << EOF >> base/postgresql.conf
archive_mode = on
archive_command = 'cp %p /path/to/archive/%f'
EOF

# 起動
pg_ctl start -D base
psql -c "create table a (i int primary key)"
psql -c "insert into a select generate_series(1,100)"
psql -c "checkpoint"

# 物理バックアップを取得
pg_basebackup -D bkp1 -P

# リカバリ設定
echo "restore_command = 'cp /path/to/archive/%f %p'" >> bkp1/postgresql.conf
touch bkp1/recovery.signal

# リカバリ開始(1回目)
pg_ctl stop -D base
pg_ctl start -D bkp1

# 物理バックアップを取得
pg_basebackup -D bkp2 -P

# リカバリ設定
echo "restore_command = 'cp /path/to/archive/%f %p'" >> bkp2/postgresql.conf
touch bkp2/recovery.signal

# リカバリ開始(2回目)
pg_ctl stop -D bkp1
pg_ctl start -D bkp2
```
(バグの再現手順はこのようにスクリプト化しておくと、修正後にバグが治っているかの確認もできるので楽です。)

上記のスクリプト実行後、2回目のリカバリ後のWAL(`bkp2/pg_wal`)を見てみると以下のようなファイルがあります。

```bash
00000002.history          000000030000000000000006  archive_status
000000030000000000000005  00000003.history          RECOVERYHISTORY
```

ここで注目するのは`RECOVERYHISTORY`ファイルです。このファイルはドキュメントを見てもなにも説明は載っておらず、中身を見てみると`00000002.history`と全く同じなので必要なさそうです。なのになぜかこのファイルが残っている、これが今回解決したい問題です。

# 原因解析 - RECOVERYHISTORYファイルとはなにか？-

なぜか`pg_wal`ディレクトリに存在している`RECOVERYHISTORY`ファイルはどのようなファイルなのでしょうか？まずは、ソースコードで`RECOVERYHISTORY`ファイルを操作している箇所を見てみます。

```bash
$ git grep RECOVERYHISTORY
src/backend/access/transam/timeline.c:          if (RestoreArchivedFile(path, histfname, "RECOVERYHISTORY", 0, false))
src/backend/access/transam/timeline.c:                  RestoreArchivedFile(path, histfname, "RECOVERYHISTORY", 0, false);
src/backend/access/transam/timeline.c:          RestoreArchivedFile(path, histfname, "RECOVERYHISTORY", 0, false);
src/backend/access/transam/timeline.c:          RestoreArchivedFile(path, histfname, "RECOVERYHISTORY", 0, false);
src/backend/access/transam/xlog.c:      snprintf(recoveryPath, MAXPGPATH, XLOGDIR "/RECOVERYHISTORY");
```

`RestoreArchivedFile関数`が関係していることがわかります。

この関数は`src/backend/access/transam/timeline.c`に定義されているので見てみます。

```c
/
 * Attempt to retrieve the specified file from off-line archival storage.
 * If successful, fill "path" with its complete path (note that this will be
 * a temp file name that doesn't follow the normal naming convention), and
 * return true.
 *
 * If not successful, fill "path" with the name of the normal on-line file
 * (which may or may not actually exist, but we'll try to use it), and return
 * false.
 *
 * For fixed-size files, the caller may pass the expected size as an
 * additional crosscheck on successful recovery.  If the file size is not
 * known, set expectedSize = 0.
 *
 * When 'cleanupEnabled' is false, refrain from deleting any old WAL segments
 * in the archive. This is used when fetching the initial checkpoint record,
 * when we are not yet sure how far back we need the WAL.
 */
bool
RestoreArchivedFile(char *path, const char *xlogfname,
                    const char *recovername, off_t expectedSize,
                    bool cleanupEnabled)
{
```

300行程ある関数ですが随所にコメントが残されているため、比較的簡単に内容は理解できると思います。関数を読んでみるとこのコマンドは、以下のような動作をすることがわかります。

* `restore_command`パラメータに設定されたコマンドを実行し、アーカイブからファイル（WALなど）をリストアする
* リストアが成功した場合、引数`path`には`pg_wal`と`recovername変数の値`を組み合わせた文字列が設定（コード上では`xlogpath変数`）され`true`が返される
* リストアが失敗した場合は、引数`path`には`xlogfname`が設定され`false`が返される

`RestoreArchivedFile(path, histfname, "RECOVERYHISTORY", 0, false);`のようにこの関数を使っていることから、**`restore_command`によってhistoryファイルがリストアされ、リストアされたファイルが`RECOVERYHISTORY`という名前になっている、ことがわかります**

## RECOVERYHITORYファイルのその後は？

`RECOVERYHISTORY`ファイルはその後どうなるのでしょうか？答えは`RestoreArchivedFile関数`が使われている周辺を見るとわかります。

`src/backend/access/transam/timeline.c`に定義されている`restoreTimeLineHistoryFiles関数`は以下のようになっています。

```c
void
restoreTimeLineHistoryFiles(TimeLineID begin, TimeLineID end)
{
    char        path[MAXPGPATH];
    char        histfname[MAXFNAMELEN];
    TimeLineID  tli;

    for (tli = begin; tli < end; tli++)
    {
        if (tli == 1)
            continue;

        TLHistoryFileName(histfname, tli);
        if (RestoreArchivedFile(path, histfname, "RECOVERYHISTORY", 0, false))
            KeepFileRestoredFromArchive(path, histfname);
    }
}
```

`RestoreArchivedFile関数`を実行していて、さらにその後に`KeepFileRestoredFromArchive関数`を実行しています。`KeepFileRestoredFromArchive関数`のコメントを読むとわかりますが、この関数は`path`に指定されたファイル名を`histfname`に変換します。つまり、ここで`RECOVERYHISTORY`は一時的なファイル名であり、後のコードで適切な名前に変更されることがわかります。

さらに、`RECOVERYHISTORY`をキーワードにもう少しコードを見てみると以下のように、アーカイブリカバリ終了時にこれらのファイルを削除しているコードも見つかります。

```c
static void
exitArchiveRecovery(TimeLineID endTLI, XLogRecPtr endOfLog)
{
	:
	:

    /*
     * Since there might be a partial WAL segment named RECOVERYXLOG, get rid
     * of it.
     */
    snprintf(recoveryPath, MAXPGPATH, XLOGDIR "/RECOVERYXLOG");
    unlink(recoveryPath);       /* ignore any error */

    /* Get rid of any remaining recovered timeline-history file, too */
    snprintf(recoveryPath, MAXPGPATH, XLOGDIR "/RECOVERYHISTORY");
    unlink(recoveryPath);       /* ignore any error */
```

やはり`RECOVERYHISTORY`(や`RECOVERYXLOG`)は不必要なファイルなようです。

# まとめ

今回はバグの発見、問題の理解まで書いてみました。もしPostgreSQLのバグを見つけた場合は、自分で修正しなくても、この時点で再現手順を添えてPostgreSQLコミュニティに[報告](https://www.postgresql.org/account/submitbug/)しても良いと思います。コミュニティ上での議論を見たり、自分なりの調査を行うことでPostgreSQLの動作にソースコードレベルで詳しくなることができます。

次回は原因究明、解決を紹介しようと思います。興味がある方はこれらの情報を元に、ぜひ自分で何が原因になっているのかを探してみてください！

## 本バグの影響は？

本バグの修正は次回にリリースされるバージョンに取り込まれる予定ですので、PostgreSQLコミュニティによる公式な見解はまだですが、個人的には本バグによる影響は大きくないと考えています。`RECOVERYHISTORY`ファイルは不必要なファイルではありますが、存在していてもPostgreSQLの動作に悪影響を及ぼすものではありません。ただし、お使いのバックアップ管理ツール等では`pg_wal`ディレクトリ内になにか不要なファイルがあることで問題を引き起こす可能性もあるかもしれないので、念の為確認することを推奨します。

