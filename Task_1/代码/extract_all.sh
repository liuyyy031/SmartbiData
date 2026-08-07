#!/bin/bash
# 逐个解压 -> 校验 tiff 可读 -> 删除压缩包释放空间
set -e
cd /d/SmartAI/data
RAW=raw
EX=extracted

extract_one () {  # $1=archive path  $2=target dir
    mkdir -p "$EX/$2"
    tar -xzf "$1" -C "$EX/$2"
    echo "EXTRACTED $2"
}

verify_dir () {  # 校验目录里所有 tiff 可被 rasterio 打开
    python - "$EX/$1" <<'EOF'
import sys, glob, rasterio
d = sys.argv[1]
tiffs = glob.glob(d + "/**/*.tif*", recursive=True)
ok = True
for t in tiffs:
    try:
        with rasterio.open(t) as ds:
            print(f"  OK {t.split('/')[-1]} {ds.width}x{ds.height} bands={ds.count} {ds.dtypes[0]}")
    except Exception as e:
        print(f"  BAD {t}: {e}"); ok = False
sys.exit(0 if ok and tiffs else 1)
EOF
}

run () {  # $1=glob pattern for archive  $2=target dir
    for f in $1; do
        [ -f "$f" ] || continue
        extract_one "$f" "$2"
    done
    if verify_dir "$2"; then
        for f in $1; do rm -f "$f"; done
        echo "CLEANED $2"
        df -h /d | tail -1
    else
        echo "VERIFY FAILED for $2, archives kept"
    fi
}

run "raw/2026年5月11日*/*/*.tar.gz" 0511_LT1B
run "raw/2026年7月6日*/*/*.tar.gz" 0706_LT1B
run "raw/2026年6月3日*/*/*_L2_*.tar.gz" 0603_GF3B
run "raw/2026年7月7日*/*/*.tar.gz" 0707_GF3B
run "raw/2026年7月9日*/*/*E109.3*_L2_*.tar.gz" 0709_GF3B_south
run "raw/2026年7月8日*/*/*.tar.gz" 0708_GF1B
echo "ALL EXTRACTION DONE"
