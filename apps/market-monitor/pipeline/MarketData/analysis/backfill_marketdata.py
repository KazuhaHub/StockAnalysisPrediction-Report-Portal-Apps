"""补齐 ~/MarketData 的缺失标的（进程内调用，避开 shell 参数传递的坑）。

为什么不用 `xargs ... market_data.py add`：实测那条路径会把多个代码合成一个字符串
传给 argparse，数据源直接报"无效的股票代码"，而且日志里 n_ok=0 / n_fail=1 看着像
"个别标的失败"，很容易被当成正常损耗。这里直接在进程内分批调用 add()。
"""
import json
import sys

sys.path.insert(0, "/opt/daily-tasks/MarketData")
import market_data as md  # noqa: E402

LIST = sys.argv[1] if len(sys.argv) > 1 else "/tmp/missing_lc.txt"
BATCH = int(sys.argv[2]) if len(sys.argv) > 2 else 60
WORKERS = int(sys.argv[3]) if len(sys.argv) > 3 else 12

codes = [x.strip() for x in open(LIST, encoding="utf-8") if x.strip()]
lib = set(json.load(open("/opt/daily-tasks/MarketData/meta.json", encoding="utf-8"))["stocks"])
todo = [c for c in codes if c not in lib]
print(f"待补 {len(todo)} / 名单 {len(codes)}（已在库 {len(codes) - len(todo)}）", flush=True)

ok = fail = 0
for i in range(0, len(todo), BATCH):
    chunk = todo[i:i + BATCH]
    print(f"[{i + 1}-{i + len(chunk)}] …", flush=True)
    r = md.add(chunk, workers=WORKERS, quiet=True)
    ok += r["n_ok"]
    fail += r["n_fail"]
    print(f"[{i + 1}-{i + len(chunk)}] 新增 {r['n_ok']} 失败 {r['n_fail']}"
          + (f" 例：{r['fail'][0]}" if r["fail"] else ""), flush=True)

print(f"总计：新增 {ok} 只、失败 {fail} 只", flush=True)
