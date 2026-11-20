"""日更收尾摘要：一行结论，避免去翻日志。"""
import json

m = json.load(open("data/site_payload.json"))["meta"]
mk = json.load(open("data/market.json"))
d = json.load(open("data/diff.json"))
print("股票 %d · 估值池 %d · 有结论 %d · 中位 PE %.1f / PB %.2f"
      % (m["n_universe"], m["n_pool"], m["n_valid"], mk["median_pe"], mk["median_pb"]))
if d.get("first"):
    print("首日快照已固化（%s），下一交易日起有 diff" % d.get("cur"))
else:
    mv = d["moves"]
    print("对比 %s → %s：可比 %d 只，上涨空间上移 %d / 下移 %d，中位位移 %+.1f%%"
          % (d["prev"], d["cur"], d.get("n_comp") or d["n_overlap"],
             mv["up"], mv["down"], (mv["med_d"] or 0) * 100))
