"""用腾讯行情快照修正股本/市值。

背景：PIT 财务接口的 shares_outstanding 在部分科创板/CDR 标的上量纲错乱
（中芯国际差 35 倍、华虹宏力差 0.5 倍、九号公司差 10 倍），连带 eps/bps/市值/PE/PB 全错。
腾讯 q= 接口一次可拿 60 只的总市值，用它反推真实股本：shares = 总市值 / 收盘价。

输出 data/mktcap_tx.csv: code, tx_price, tx_mktcap_yi, tx_float_yi, tx_pb, tx_shares
"""
import json
import time
import urllib.request

import pandas as pd

BASE = "http://qt.gtimg.cn/q="
UA = {"User-Agent": "Mozilla/5.0"}


def prefix(code: str) -> str:
    if code[0] == "6":
        return "sh" + code
    if code[0] in "03":
        return "sz" + code
    return "bj" + code


def fetch(codes):
    q = ",".join(prefix(c) for c in codes)
    req = urllib.request.Request(BASE + q, headers=UA)
    raw = urllib.request.urlopen(req, timeout=20).read()
    txt = raw.decode("gbk", "replace")
    out = []
    for line in txt.split(";"):
        line = line.strip()
        if not line or "=" not in line:
            continue
        body = line.split('="', 1)
        if len(body) != 2:
            continue
        f = body[1].rstrip('"').split("~")
        if len(f) < 46:
            continue
        try:
            price = float(f[3])
            mktcap = float(f[45])
            floatmv = float(f[44])
            pb = float(f[46])
        except (ValueError, IndexError):
            continue
        if price <= 0 or mktcap <= 0:
            continue
        out.append({"code": f[2].zfill(6), "tx_price": price,
                    "tx_mktcap_yi": mktcap, "tx_float_yi": floatmv,
                    "tx_pb": pb, "tx_shares": mktcap * 1e8 / price})
    return out


def main():
    m = pd.read_parquet("data/master.parquet", columns=["symbol"])
    codes = sorted(set(m["symbol"].astype(str).str.zfill(6)))
    print("codes", len(codes), flush=True)
    rows, i, n = [], 0, 60
    while i < len(codes):
        chunk = codes[i:i + n]
        for attempt in range(3):
            try:
                rows += fetch(chunk)
                break
            except Exception as e:  # noqa: BLE001
                print("retry", chunk[0], type(e).__name__, flush=True)
                time.sleep(1.5)
        i += n
        if (i // n) % 10 == 0:
            print(f"{i}/{len(codes)} rows={len(rows)}", flush=True)
        time.sleep(0.15)
    df = pd.DataFrame(rows).drop_duplicates("code")
    df.to_csv("data/mktcap_tx.csv", index=False)
    print("saved", len(df), "missing", len(codes) - len(df))
    json.dump({"n": int(len(df)), "missing": int(len(codes) - len(df))},
              open("data/mktcap_tx_meta.json", "w"))


if __name__ == "__main__":
    main()
