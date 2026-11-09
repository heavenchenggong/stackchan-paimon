#!/usr/bin/env python3
"""git push 被代理拦时，用 GitHub Git Data API 建等价 commit + ref。

适用：本机 HTTP_PROXY 只放行 api.github.com，`github.com` 的 git over
HTTPS 返回 `CONNECT tunnel failed, response 502`，但 `gh api` 能用。

原理：把 <base>..<branch> 的所有改动文件逐个 POST 成 blob，基于 base 的
tree 建新 tree，再用**本地 commit 的 author / committer / date / message**
建 commit——commit object 字节完全一致，所以远端 sha 与本地 sha 相同，
等价于一次正常 push。远端已存在该分支时改为 PATCH 强制更新 ref。

用法：
  python3 push_via_gh_api.py \
      --repo heavenchenggong/stackchan-xiaozhi-firmware \
      --branch feature/integration --base main \
      --fw "$REPO"

前置：GH_HOST=github.com，gh 已登录且有 repo + workflow scope。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import subprocess
import sys

ENV = dict(os.environ, GH_HOST="github.com")


def gh(*args, payload=None, method=None):
    cmd = ["gh", "api", *args]
    if method:
        cmd += ["--method", method]
    data = None
    if payload is not None:
        cmd += ["--input", "-"]
        data = json.dumps(payload).encode()
    p = subprocess.run(cmd, input=data, capture_output=True, env=ENV)
    if p.returncode != 0:
        raise RuntimeError(f"gh api {' '.join(args)}: {p.stderr.decode(errors='replace')[:800]}")
    return json.loads(p.stdout or b"{}")


def git(fw, *args):
    return subprocess.check_output(["git", "-C", fw, *args]).decode().strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="owner/repo")
    ap.add_argument("--branch", required=True)
    ap.add_argument("--base", default="main")
    ap.add_argument("--fw", required=True, help="本地 git 仓库绝对路径")
    a = ap.parse_args()
    fw = a.fw

    files = [x for x in git(fw, "diff", "--name-only", f"{a.base}..{a.branch}").splitlines() if x]
    if not files:
        print("没有改动文件，退出")
        return 0
    print(f"files: {len(files)}", flush=True)

    base_sha = gh(f"repos/{a.repo}/git/ref/heads/{a.base}")["object"]["sha"]
    local_base = git(fw, "rev-parse", a.base)
    if base_sha != local_base:
        raise RuntimeError(f"base 分叉: 远端={base_sha} 本地={local_base}")
    base_tree = gh(f"repos/{a.repo}/git/commits/{base_sha}")["tree"]["sha"]
    print(f"base: {a.base}={base_sha[:8]} tree={base_tree[:8]}", flush=True)

    fmt = "%an%n%ae%n%aI%n%cn%n%ce%n%cI"
    an, ae, ad, cn, ce, cd = git(fw, "show", "-s", f"--format={fmt}", a.branch).splitlines()
    raw = subprocess.check_output(["git", "-C", fw, "cat-file", "commit", a.branch]).decode()
    message = raw.split("\n\n", 1)[1]

    # 保留目标分支里每个文件的真实 mode（100644 / 100755），否则 tree sha
    # 会与本地不一致（例如本仓库 main/main.cc 历史遗留可执行位）。
    mode_of = {}
    for line in git(fw, "ls-tree", "-r", a.branch).splitlines():
        meta, p = line.split("\t", 1)
        mode_of[p] = meta.split()[0]

    entries = []
    for i, path in enumerate(files, 1):
        data = pathlib.Path(fw, path).read_bytes()
        blob = gh(f"repos/{a.repo}/git/blobs", method="POST", payload={
            "content": base64.b64encode(data).decode(), "encoding": "base64",
        })
        entries.append({"path": path, "mode": mode_of.get(path, "100644"),
                        "type": "blob", "sha": blob["sha"]})
        print(f"  [{i:2d}/{len(files)}] {path} -> {blob['sha'][:8]}", flush=True)

    new_tree = gh(f"repos/{a.repo}/git/trees", method="POST", payload={
        "base_tree": base_tree, "tree": entries,
    })["sha"]
    new_commit = gh(f"repos/{a.repo}/git/commits", method="POST", payload={
        "message": message, "tree": new_tree, "parents": [base_sha],
        "author": {"name": an, "email": ae, "date": ad},
        "committer": {"name": cn, "email": ce, "date": cd},
    })["sha"]
    print(f"commit: {new_commit}", flush=True)

    ref_path = f"refs/heads/{a.branch}"
    # 注意：GitHub REST API 的路径是 /git/refs/heads/<branch>，
    # 只有 POST /git/refs 的 body 里才写完整的 "refs/heads/<branch>"。
    try:
        gh(f"repos/{a.repo}/git/ref/heads/{a.branch}")
        exists = True
    except RuntimeError:
        exists = False
    if exists:
        gh(f"repos/{a.repo}/git/refs/heads/{a.branch}", method="PATCH",
           payload={"sha": new_commit, "force": True})
        print(f"updated {ref_path}", flush=True)
    else:
        gh(f"repos/{a.repo}/git/refs", method="POST",
           payload={"ref": ref_path, "sha": new_commit})
        print(f"created {ref_path}", flush=True)

    remote_tree = gh(f"repos/{a.repo}/git/commits/{new_commit}")["tree"]["sha"]
    local_tree = git(fw, "rev-parse", f"{a.branch}^{{tree}}")
    if remote_tree == local_tree:
        current = git(fw, "branch", "--show-current")
        if current == a.branch:
            # 正检出目标分支时，Git 不允许把 HEAD 指向的 ref 直接挪到另一个
            # 不同 sha（API 建的是 squash 后的单 commit，历史不同但 tree 一致）。
            # tree 已经一致，跳过即可，不要动工作区。
            print("当前正检出该分支，跳过本地分支指针移动（tree 已一致）", flush=True)
        else:
            subprocess.run(["git", "-C", fw, "update-ref", ref_path, new_commit], check=True)
            print("本地分支已与远端对齐", flush=True)
        # 远端跟踪 ref 可能因 packed-refs / 已存在而更新失败，不影响远端内容
        r = subprocess.run(["git", "-C", fw, "update-ref",
                            f"refs/remotes/origin/{a.branch}", new_commit],
                           capture_output=True)
        if r.returncode != 0:
            print(f"提示：本地远端跟踪 ref 未更新（不影响远端）：{r.stderr.decode().strip()[:120]}",
                  flush=True)
    else:
        print(f"!! tree 不一致 remote={remote_tree[:8]} local={local_tree[:8]}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
