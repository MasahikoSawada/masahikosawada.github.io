---
layout: post
title: FreeBSDソースコードリーディング（psコマンド）
tags:
  - FreeBSD
  - Source Code Reading
---

気になったので読んでみた。`bin/ps`にあるコードが対象。

大まかな流れはこんな感じ。

1. オプション処理
2. プロセスリストの取得(`kvm_getprocs()`)
3. プロセスリストのフィルタリング(オプション引数を使う)
4. 必要に応じてソート
5. 出力(`libxo`の利用)

プロセスデータを扱う構造体として、`struct kinfo`(`kinfo_proc`へのポインタを含む)や、リスト構造として`STAILQ_XXX`を使っていることがわかった。

それでは読んでみる。

最初の方はオプションの処理。

`kvm_openfiles`の使い道はよくわかってない。

```c
	kd = kvm_openfiles(nlistf, memf, NULL, O_RDONLY, errbuf);
	if (kd == NULL)
		xo_errx(1, "%s", errbuf);
```

プロセスのリストを取得する所。`kvm_getprocs()`で取得している。それにフラグを与えることで、希望のプロセスのリストを要求できるような感じ。


```c
	/*
	 * Get process list.  If the user requested just one selector-
	 * option, then kvm_getprocs can be asked to return just those
	 * processes.  Otherwise, have it return all processes, and
	 * then this routine will search that full list and select the
	 * processes which match any of the user's selector-options.
	 */
	what = showthreads != 0 ? KERN_PROC_ALL : KERN_PROC_PROC;
	flag = 0;
	if (nselectors == 1) {
		if (gidlist.count == 1) {
			what = KERN_PROC_RGID | showthreads;
			flag = *gidlist.l.gids;
			nselectors = 0;
		} else if (pgrplist.count == 1) {
			what = KERN_PROC_PGRP | showthreads;
			flag = *pgrplist.l.pids;
			nselectors = 0;
		} else if (pidlist.count == 1 && !descendancy) {
			what = KERN_PROC_PID | showthreads;
			flag = *pidlist.l.pids;
			nselectors = 0;
		} else if (ruidlist.count == 1) {
			what = KERN_PROC_RUID | showthreads;
			flag = *ruidlist.l.uids;
			nselectors = 0;
		} else if (sesslist.count == 1) {
			what = KERN_PROC_SESSION | showthreads;
			flag = *sesslist.l.pids;
			nselectors = 0;
		} else if (ttylist.count == 1) {
			what = KERN_PROC_TTY | showthreads;
			flag = *ttylist.l.ttys;
			nselectors = 0;
		} else if (uidlist.count == 1) {
			what = KERN_PROC_UID | showthreads;
			flag = *uidlist.l.uids;
			nselectors = 0;
		} else if (all) {
			/* No need for this routine to select processes. */
			nselectors = 0;
		}
	}

	/*
	 * select procs
	 */
	nentries = -1;
	kp = kvm_getprocs(kd, what, flag, &nentries);
```

`flag`の部分は、例えば`-p`でPIDが一つだけ指定されている場合とかに使われる。（`-p`が複数指定されている場合はどうなる？）

そして、`what`の部分は`sys/sys/sysctl.h`に定義がある。

```c
/*
 * KERN_PROC subtypes
 */
#define KERN_PROC_ALL       0   /* everything */
#define KERN_PROC_PID       1   /* by process id */
#define KERN_PROC_PGRP      2   /* by process group id */
#define KERN_PROC_SESSION   3   /* by session of pid */
#define KERN_PROC_TTY       4   /* by controlling tty */
#define KERN_PROC_UID       5   /* by effective uid */
#define KERN_PROC_RUID      6   /* by real uid */
#define KERN_PROC_ARGS      7   /* get/set arguments/proctitle */
#define KERN_PROC_PROC      8   /* only return procs */
#define KERN_PROC_SV_NAME   9   /* get syscall vector name */
#define KERN_PROC_RGID      10  /* by real group id */
#define KERN_PROC_GID       11  /* by effective group id */
#define KERN_PROC_PATHNAME  12  /* path to executable */
#define KERN_PROC_OVMMAP    13  /* Old VM map entries for process */
#define KERN_PROC_OFILEDESC 14  /* Old file descriptors for process */
#define KERN_PROC_KSTACK    15  /* Kernel stacks for process */
#define KERN_PROC_INC_THREAD    0x10    /*
                     * modifier for pid, pgrp, tty,
                     * uid, ruid, gid, rgid and proc
                     * This effectively uses 16-31
```

ちなみに、`kvm_getprocs()`は`lib/libkvm/kvm_proc.c`に定義されている。このファイルはProcの情報を検索する時に使える関数が色々定義されている(`ps`とか`w`とか）。

次に`-p`が複数」指定された時等、検索条件みたいなのが指定されている場合に、必要ないものを取り除く処理。

```c
	if (nentries > 0) {
		if ((kinfo = malloc(nentries * sizeof(*kinfo))) == NULL)
			xo_errx(1, "malloc failed");
		for (i = nentries; --i >= 0; ++kp) {
			/*
			 * If the user specified multiple selection-criteria,
			 * then keep any process matched by the inclusive OR
			 * of all the selection-criteria given.
			 */
			if (pidlist.count > 0) {
				for (elem = 0; elem < pidlist.count; elem++)
					if (kp->ki_pid == pidlist.l.pids[elem])
						goto keepit;
			}
			/*
			 * Note that we had to process pidlist before
			 * filtering out processes which do not have
			 * a controlling terminal.
			 */
			if (xkeep == 0) {
				if ((kp->ki_tdev == NODEV ||
				    (kp->ki_flag & P_CONTROLT) == 0))
					continue;
			}
			if (nselectors == 0)
				goto keepit;
			if (gidlist.count > 0) {
				for (elem = 0; elem < gidlist.count; elem++)
					if (kp->ki_rgid == gidlist.l.gids[elem])
						goto keepit;
			}
			if (jidlist.count > 0) {
				for (elem = 0; elem < jidlist.count; elem++)
					if (kp->ki_jid == jidlist.l.jids[elem])
						goto keepit;
			}
			if (pgrplist.count > 0) {
				for (elem = 0; elem < pgrplist.count; elem++)
					if (kp->ki_pgid ==
					    pgrplist.l.pids[elem])
						goto keepit;
			}
...(という感じの処理が続く)...
```

選択したプロセスは`struct kinfo`構造体に格納していく。

```c
typedef struct kinfo {
	struct kinfo_proc *ki_p;	/* kinfo_proc structure */
	const char *ki_args;	/* exec args */
	const char *ki_env;	/* environment */
	int ki_valid;		/* 1 => uarea stuff valid */
	double	 ki_pcpu;	/* calculated in main() */
	segsz_t	 ki_memsize;	/* calculated in main() */
	union {
		int level;	/* used in decendant_sort() */
		char *prefix;	/* calculated in decendant_sort() */
	} ki_d;
	STAILQ_HEAD(, kinfo_str) ki_ks;
} KINFO;
```

ソートする。`pscomp()`は、`sortby`オプションによって、comparatorの振る舞いが変わる。

```c
	/*
	 * sort proc list
	 */
	qsort(kinfo, nkept, sizeof(KINFO), pscomp);
```

最後にフォーマットを準備して、Headerを書いて、一つずつエントリを出力していく。

* `STAILQ_FOREACH()`はSlighly-linked Tail queueの略で、`sys/sys/queue.h`に定義してある
* `struct kinfo`に`STAILQ_HEAD()`が定義されており、これがリストのHeadになる。そして、そこからつながっている要素は、`struct varent`で、そこには`STAILQ_ENTRY(varent) next_ve`と、次の要素へのリンクが定義されている。このリストをたどる時に使うのが`STALW_FOREACH()`。
* 出力には、`xo_open_instance()` -> `xo_emit()` * N -> `xo_close_instance()`と、[libxo](https://www.freebsd.org/cgi/man.cgi?query=libxo&sektion=3)を使っている。
  * libxoは、textやXML、JSON形式で値を出力するためのライブラリ。

```c
	/*
	 * Prepare formatted output.
	 */
	for (i = 0; i < nkept; i++)
		format_output(&kinfo[i]);

	/*
	 * Print header.
	 */
	xo_open_container("process-information");
	printheader();
	if (xo_get_style(NULL) != XO_STYLE_TEXT)
		termwidth = UNLIMITED;

	/*
	 * Output formatted lines.
	 */
	xo_open_list("process");
	for (i = lineno = 0; i < nkept; i++) {
		linelen = 0;
		xo_open_instance("process");
		STAILQ_FOREACH(vent, &varlist, next_ve) {
			ks = STAILQ_FIRST(&kinfo[i].ki_ks);
			STAILQ_REMOVE_HEAD(&kinfo[i].ki_ks, ks_next);
			/* Truncate rightmost column if necessary.  */
			fwidthmax = _POSIX2_LINE_MAX;
			if (STAILQ_NEXT(vent, next_ve) == NULL &&
			   termwidth != UNLIMITED && ks->ks_str != NULL) {
				left = termwidth - linelen;
				if (left > 0 && left < (int)strlen(ks->ks_str))
					fwidthmax = left;
			}

			str = ks->ks_str;
			if (str == NULL)
				str = "-";
			/* No padding for the last column, if it's LJUST. */
			fwidthmin = (xo_get_style(NULL) != XO_STYLE_TEXT ||
			    (STAILQ_NEXT(vent, next_ve) == NULL &&
			    (vent->var->flag & LJUST))) ? 0 : vent->var->width;
			snprintf(fmtbuf, sizeof(fmtbuf), "{:%s/%%%s%d..%dhs}",
			    vent->var->field ? vent->var->field : vent->var->name,
			    (vent->var->flag & LJUST) ? "-" : "",
			    fwidthmin, fwidthmax);
			xo_emit(fmtbuf, str);
			linelen += fwidthmin;

			if (ks->ks_str != NULL) {
				free(ks->ks_str);
				ks->ks_str = NULL;
			}
			free(ks);
			ks = NULL;

			if (STAILQ_NEXT(vent, next_ve) != NULL) {
				xo_emit("{P: }");
				linelen++;
			}
		}
	        xo_emit("\n");
		xo_close_instance("process");
		if (prtheader && lineno++ == prtheader - 4) {
			xo_emit("\n");
			printheader();
			lineno = 0;
		}
	}

```

# おわりに

* libxo便利そう
* ユーザランドのコードなら読めそう
* 流れと雰囲気は掴んだのでちょっと細かく読んでいきたい
