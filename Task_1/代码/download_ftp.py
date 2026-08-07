# -*- coding: utf-8 -*-
"""FTP 递归下载脚本：支持断点续传、大小校验、多数据集目录映射。

用法:
    python download_ftp.py --host 112.6.51.208 --user xxx --pwd xxx --dest D:/SmartAI/data/raw
"""
import argparse
import os
import sys
import time
from ftplib import FTP, error_perm


def connect(host, user, pwd, retries=5):
    for i in range(retries):
        try:
            ftp = FTP(host, timeout=60)
            ftp.login(user, pwd)
            ftp.encoding = "utf-8"
            ftp.set_pasv(True)
            return ftp
        except Exception as e:
            print(f"  connect attempt {i+1}/{retries} failed: {e}", flush=True)
            time.sleep(10)
    raise RuntimeError(f"cannot connect to {host}")


def is_dir(ftp, name):
    cur = ftp.pwd()
    try:
        ftp.cwd(name)
        ftp.cwd(cur)
        return True
    except error_perm:
        return False


def download_file(ftp, remote, local, remote_size):
    """断点续传下载单个文件。"""
    os.makedirs(os.path.dirname(local), exist_ok=True)
    local_size = os.path.getsize(local) if os.path.exists(local) else 0
    if local_size == remote_size and remote_size > 0:
        print(f"  SKIP (complete) {os.path.basename(local)}", flush=True)
        return
    mode = "ab" if local_size > 0 else "wb"
    with open(local, mode) as f:
        def callback(chunk):
            f.write(chunk)
        ftp.voidcmd("TYPE I")
        try:
            ftp.retrbinary(f"RETR {remote}", callback, blocksize=1024 * 256, rest=local_size or None)
        except Exception:
            # 服务器不支持断点续传则重新下载
            f.close()
            with open(local, "wb") as f2:
                ftp.retrbinary(f"RETR {remote}", f2.write, blocksize=1024 * 256)
    got = os.path.getsize(local)
    if remote_size and got != remote_size:
        raise RuntimeError(f"size mismatch {remote}: {got} != {remote_size}")
    print(f"  OK {os.path.basename(local)} ({got/1e6:.1f} MB)", flush=True)


def walk_and_download(host, user, pwd, remote_root, local_root):
    """递归下载 remote_root 下所有文件，保持目录结构。"""
    ftp = connect(host, user, pwd)
    pending = [(remote_root, local_root)]
    while pending:
        rdir, ldir = pending.pop()
        try:
            ftp.cwd(rdir)
        except Exception:
            ftp = connect(host, user, pwd)
            ftp.cwd(rdir)
        try:
            entries = ftp.nlst()
        except Exception:
            ftp = connect(host, user, pwd)
            ftp.cwd(rdir)
            entries = ftp.nlst()
        for name in entries:
            base = os.path.basename(name)
            if base in (".", ".."):
                continue
            rpath = f"{rdir}/{base}"
            lpath = os.path.join(ldir, base)
            if is_dir(ftp, base):  # ftp 当前已在 rdir，用相对名判断
                pending.append((rpath, lpath))
                continue
            for attempt in range(5):
                try:
                    size = ftp.size(base) or 0
                    download_file(ftp, base, lpath, size)
                    break
                except Exception as e:
                    print(f"  retry {attempt+1} {base}: {e}", flush=True)
                    ftp = connect(host, user, pwd)
                    ftp.cwd(rdir)
            else:
                print(f"  FAILED {rpath}", flush=True)
    try:
        ftp.quit()
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--user", required=True)
    ap.add_argument("--pwd", required=True)
    ap.add_argument("--dest", required=True)
    args = ap.parse_args()

    ftp = connect(args.host, args.user, args.pwd)
    roots = [n for n in ftp.nlst() if os.path.basename(n) not in (".", "..")]
    ftp.quit()
    print(f"datasets on {args.host}: {len(roots)}", flush=True)
    for r in roots:
        print(f"== downloading {r}", flush=True)
        walk_and_download(args.host, args.user, args.pwd, r, os.path.join(args.dest, os.path.basename(r)))
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    sys.exit(main())
