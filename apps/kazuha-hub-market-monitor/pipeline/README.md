# A 股日更任务包 · 部署说明

五套日更流程 + 一个数据源服务，跑在一台能常开的 Linux 机器上。
装完就自动跑：晚上补行情库，凌晨出情绪与选股，早上出 ETF 与融资盘，白天在浏览器里看。

```
包体积  749 MB（含 12 年日线历史，解压即用，不需要重新灌数据）
安装     3 条命令，约 5 分钟（含 pip 装依赖）
定时     systemd timer（另附 crontab 写法）
页面     nginx 静态托管，一个首页汇总四份报告
```

---

## 一、包里有什么

| 模块 | 干什么 | 原定触发 |
|---|---|---|
| `stock_server/` | 行情数据源 MCP 服务，监听 `:8091`，上游是国内行情 API | 常驻 |
| `MarketData/` | A 股日线库，5,833 个代码（含 244 只已退市）、2014-06 至今、后复权 | 交易日 21:00 |
| `workspace/panorama/` | 全策略选股（54 因子 / 六策略 / 十法估值） | 周二至周六 00:50 |
| `workspace/analysis/` + `reports/sentiment-monitor/` | 市场情绪五维监控面板 | 周二至周六 00:40 |
| `workspace/analysis/panel/` | 宽基 ETF 资金监测面板 | 周二至周六 08:00 |
| `margin_scan/` | 融资盘 · 持仓结构扫描 | 周一至周五 09:00 |

**数据流**（后一个依赖前一个，顺序不能乱）：

```
       上游行情 API (QUOTE_API，默认 https://quotes.internal.anchan.kazuhahub.com)
                    │
                    ▼
        stock_server  :8091  ←── 常驻，挂了全链条都停
                    │
                    ▼
   ┌──────── MarketData 日线库 ────────┐
   │            21:00 增量              │
   ▼                  ▼                ▼
情绪面板 00:40    Panorama 00:50    （融资盘扫描不走这里，
                                   独立抓 akshare + 东财）
                                          │
        ETF 面板 08:00（独立抓东财/腾讯）─┤
                                          ▼
                                   nginx :80 四份 HTML
```

两处独立：ETF 面板和融资盘扫描不依赖行情库，各自抓外部接口，一个挂了不影响另一个。

---

## 二、服务器要求

| 项 | 要求 | 说明 |
|---|---|---|
| 系统 | Linux + systemd | Debian 12 / Ubuntu 22.04+ / Rocky 9 均可 |
| 时区 | **必须是 Asia/Shanghai** | `timedatectl set-timezone Asia/Shanghai`。时区不对，所有 `OnCalendar` 会整体偏移，21:00 变成北京时间凌晨 5 点 |
| Python | ≥ 3.9，建议 3.11 | `python3-venv`、`python3-dev` 要装 |
| 磁盘 | ≥ 3 GB 可用 | 解压 737 MB + 每日增量约 300 MB/年 + venv |
| 内存 | ≥ 2 GB | Panorama compute 峰值约 1.2 GB |
| 网络 | 能出公网 | 需要访问 `https://quotes.internal.anchan.kazuhahub.com`（行情，可用环境变量 QUOTE_API 覆盖）、东财、腾讯、深交所 |
| 权限 | root | 要写 `/etc/systemd/system`、装用户、配 nginx |

**不需要**：不需要 GPU，不需要 WorkBuddy 客户端，不需要原来的 Mac。

---

## 三、安装

```bash
# 1. 把包传上去（本地执行，530 MB）
scp daily-tasks-20261117.tar.gz daily-tasks-20261117.tar.gz.sha256 root@<服务器IP>:/root/

# 2. 校验完整性后解压
ssh root@<服务器IP>
cd /root && sha256sum -c daily-tasks-20261117.tar.gz.sha256
tar xzf daily-tasks-20261117.tar.gz && cd daily-tasks

# 3. 一键装（含依赖、用户、systemd、nginx、自检）
bash install.sh
```

装完脚本会自己跑一次自检，输出类似：

```
== 8/9 部署自检
1. 运行环境      ✓ Python 3.11.2（/opt/daily-tasks/venv/bin/python3）
2. Python 依赖   ✓ pandas ✓ numpy ✓ pyarrow ✓ requests ✓ akshare
3. 行情库数据     ✓ date_range 2014-06-03 ~ 2026-11-16，票数 3526
4. 数据源服务     ✓ 8091 可访问（HTTP 200）  ✓ 交易日历可用，最近交易日 2026-11-16
...
结果：0 项失败，0 项警告
```

**任何一项 ✗ 都不要往下走**，先修。修完重跑 `bash /opt/daily-tasks/bin/preflight.sh`。

### 装完必须手动验证一次

定时任务是凌晨才跑的，不能等它第二天用失败来告诉你装错了。装完立刻手动跑两遍：

```bash
# ① 行情库增量（10-100 分钟，取决于欠多少天）
sudo -u daily bash /opt/daily-tasks/bin/run_marketdata.sh

# ② 情绪面板（约 1 分钟，验证"读库 → 计算 → 出 HTML → 发布"整条链）
sudo -u daily bash /opt/daily-tasks/bin/run_sentiment.sh
```

两条都退出码 0，再打开 `http://<服务器IP>/`，应该看到四张卡片。只有跑过的才会亮，其余显示"尚未生成"。

### 可选参数

```bash
bash install.sh --prefix /data/daily   # 换安装目录（会自动重写包内所有路径）
bash install.sh --skip-deps            # 依赖已装好，跳过 pip
bash install.sh --no-nginx             # 只用 systemd 出文件，不配站点
bash install.sh --index https://mirrors.aliyun.com/pypi/simple   # 换 pip 源
```

`--prefix` 之后所有命令里的 `/opt/daily-tasks` 都要换成你的目录。

### 80 端口被占用怎么办

服务器上已经有别的站点时，`nginx -t` 会报 `duplicate default server`。把配置文件里的端口改掉再装：

```bash
sed -i 's/listen       80;/listen       8080;/' config/nginx-daily-tasks.conf
bash install.sh
```

然后访问 `http://<服务器IP>:8080/`，安全组也要放行对应端口。

---

## 四、时刻表

| 时间 | 任务 | 耗时 | 说明 |
|---|---|---|---|
| 周一至周五 21:00 | 行情库增量（主跑） | 100 分钟 | 3,300+ 只票，6 线程 |
| 周一至周五 23:30 | 行情库增量（兜底） | 几分钟 | 21:00 失败或机器睡过时补；并发由 `.update.lock` 挡住 |
| 周二至周六 00:40 | 情绪监控面板 | 1-2 分钟 | 内含最多 30 分钟等库就绪 |
| 周二至周六 00:50 | Panorama 选股 | 5-15 分钟 | 内含最多 25 分钟等写锁 |
| 周二至周六 08:00 | ETF 资金面板 | 3-6 分钟 | 取上一交易日披露的份额与净值 |
| 周一至周五 09:00 | 融资盘扫描 | 8-9 分钟 | 等深交所 T+1 上午披露 |
| 周一至周五 09:50 | 融资盘兜底校验 | 0 或 9 分钟 | 今天没成功才补跑，成功则秒退 |

**为什么这么排**（这几条是踩坑换来的，不要在改排期时踩回去）：

1. **行情库必须在所有读库任务之前**。21:00 起跑、22:40 收工，留出余量给 00:40。上游偶尔会跑到 00:01（全库补跑那次用了 181 分钟），所以凌晨任务都带「等就绪」逻辑，等不到就报错退出，**不会用旧数据凑一份看起来全新的报告**。
2. **00:40 与 00:50 错开 10 分钟**。两个任务都要读同一个行情库，错开避免同时算，也让前一个的日志更好看。
3. **ETF 放 08:00、融资盘放 09:00，不挤在一起**。两个都抓外部接口，撞一起容易一起被限流。
4. **融资盘不含周六**。周六上午深交所还没披露周五数据（实测两次：沪市已有 2000 行、深市 0 行），那一跑必然空转。
5. **周二至周六跑，对应周一至周五的行情**。周末没有新数据这是正常的，不是故障。

---

## 五、日常运维

```bash
# 看下一次什么时候跑、上次跑成功没有
systemctl list-timers 'daily-*'

# 看某个任务最近一次的结果
systemctl status daily-panorama
journalctl -u daily-panorama -n 100 --no-pager

# 看当天所有任务的日志（每个任务一份）
ls -lt /opt/daily-tasks/logs/ | head
tail -50 /opt/daily-tasks/logs/panorama-$(date +%Y%m%d).log

# 行情库现在到哪天了
/opt/daily-tasks/venv/bin/python3 /opt/daily-tasks/MarketData/market_data.py status

# 手动补跑某一天（Panorama 支持指定日期）
PANORAMA_ASOF=2026-11-14 sudo -u daily -E bash /opt/daily-tasks/bin/run_panorama.sh

# 盯实时输出（调试时用，别长期挂）
journalctl -u daily-marketdata -f
```

### 日志在哪

| 位置 | 内容 |
|---|---|
| `/opt/daily-tasks/logs/<任务>-YYYYMMDD.log` | 每个任务每天的完整输出（发布脚本、报错都在这里） |
| `/opt/daily-tasks/MarketData/logs/update-YYYYMMDD.log` | 行情库增量明细：抓了多少只、失败哪些 |
| `/opt/daily-tasks/MarketData/updates.jsonl` | 每次更新的审计记录，末尾若有 `aborted:"source"` 说明源端断连 |
| `/opt/daily-tasks/margin_scan/logs/YYYY-MM-DD.log` | 融资盘抓取与计算的逐步输出 |
| `journalctl -u daily-*` | systemd 层面的启动/退出码/timeout |

---

## 六、故障排查

按症状查，都给了具体命令。

### 首页四张卡全是"尚未生成"
定时任务没跑或全失败。先看 timer 有没有加载：
```bash
systemctl list-timers 'daily-*'          # 空 → 单元没装好，重跑 install.sh
systemctl status daily-stock-server      # 数据源没起，行情库必然失败
```
最常见原因：**时区不对**导致时间偏移。`timedatectl` 确认 `Time zone: Asia/Shanghai (CST, +0800)`。

### 行情库停在几天前
```bash
tail -20 /opt/daily-tasks/logs/marketdata-$(date +%Y%m%d).log
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8091/mcp     # 期望 200
```
- `连不上 stock-server` → `systemctl restart daily-stock-server`
- `数据源不可用……本次更新已中止` → 上游行情 API 故障，等它恢复；**库里已有数据仍然完整可用**，不要手动改库
- 退出码 3 → 写锁被占用超 15 分钟，说明有另一个更新在跑或锁没清。看 `ls /opt/daily-tasks/MarketData/.mdwrite.lock/`，pid 不在了就删掉

### 情绪面板或 Panorama 报"行情库未更新"
这是**保护机制不是 bug**：读库任务发现库还停在昨天之前，拒绝出报告，避免你看到一份"日期很新、数据很旧"的东西。
```bash
# 先确认库到底到哪天
/opt/daily-tasks/venv/bin/python3 -c "import json;print(json.load(open('/opt/daily-tasks/MarketData/meta.json'))['date_range'])"
```
如果确实没更新 → 先修行情库（上一节）。如果库已经是最新但它还报错 → 时区问题导致"目标交易日"算错了，`timedatectl` 检查。

### Panorama 退出码 2 / STALE
`daily_update.sh` 拿本地最后一根 K 线和**服务端交易日历**比对，不一致就拒绝发布。这说明今天是交易日但昨晚没更成。修行情库，别绕过闸门（设 `PANORAMA_ASOF` 强行指定日期会让报告带着旧数据发出去）。

### ETF 面板数据日期不前进
正常。周六和节假日后只补数据、不产生新行情。若连续两个交易日不前进：
```bash
tail -30 /opt/daily-tasks/logs/etf-$(date +%Y%m%d).log
```
上面会写哪一步抓取失败。份额/净值抓取失败属接口临时不可用，脚本会沿用库内数据继续，可以接受；`flow.py` 或 `metrics.py` 报错才是代码问题。

### 融资盘 as_of 落后一天
深交所 T+1 上午才齐，脚本要求沪深同日齐全才落库。这是数据源时滞，不是故障，**不要重复跑**。若连续两天不齐，看 `logs/` 里抓取返回条数。

### 页面打不开 / 404
```bash
ls -l /opt/daily-tasks/web/                 # 应该有 index.html + 4 个 html
sudo nginx -t && sudo systemctl reload nginx
sudo tail -20 /var/log/nginx/daily-tasks.error.log
```
403 → nginx 用户读不到文件：`sudo chmod -R a+rX /opt/daily-tasks/web`。
云服务器还要确认安全组开了 80 端口。

### 任务跑到一半被 kill
`journalctl -u daily-marketdata` 里看到 `TimeoutStartSec`。默认给了：行情库 4 小时、其余 1.5-2 小时。全库重建那种异常情况可能不够，临时改：
```bash
sudo systemctl edit daily-marketdata.service   # 加 [Service] TimeoutStartSec=21600
sudo systemctl daemon-reload
```

---

## 七、已知限制

写在这里，免得当成故障去查。

1. **行情库是单向追加**：`update` 只补 `上次末端 + 1` 之后，已写入的 bar 不会被后续修正。早跑拿到未定稿的成交额/复权因子会永久固化。所以别在数据源不稳定时反复手动重跑。
2. **停牌日在库里有 bar**（`volume=amount=0`，OHLC 等于前收），横截面统计前要过滤 `volume>0`。脚本里已经处理，你自己写分析脚本时要记得。
3. **深市 ETF 只有最新份额快照**，不支持历史回溯，所以创业板指/创业板50/国证2000 的历史段是从部署日开始逐日累积的，前面是空。
4. **akshare 版本敏感**：融资盘抓取依赖它的东财接口封装，接口字段变了会直接报错。`requirements.txt` 没锁小版本，装好后不要随手 `pip install -U akshare`；真要升，先在测试机跑一遍 `run_margin.sh`。
5. **周六不跑融资盘**，所以周五数据的首次成报是下周一 09:00。
6. **所有时间依赖服务器时区**，且机器关机时 timer 不会跑（`Persistent=true` 会在开机后补跑一次，但补跑的是「错过的最后一次」，连错过三天只会补一天）。要保证常年无休，机器得一直开着。
7. **依赖必须装在 venv 里**。`bin/env.sh` 把 `HOME` 指到安装目录，这样脚本里的 `~/MarketData`、`~/.workbuddy` 才定位得到；副作用是 Python 的**用户级** site-packages（`~/.local/lib/pythonX/site-packages`）不再被搜索。所以 `pip install --user` 装的东西在这里看不见，一律用 `$PREFIX/venv/bin/pip`。
8. **页面没有登录**。这些是选股与持仓结论，建议只在内网访问，或在 nginx 里开 basic auth（配置文件里已有注释好的四行）。

---

## 八、迁移与回滚

### 换一台机器
```bash
# 旧机：停定时，避免边跑边拷
sudo systemctl stop 'daily-*.timer'
# 拷数据（增量快，保留属性）
rsync -a --exclude venv/ --exclude logs/ /opt/daily-tasks/ newhost:/opt/daily-tasks/
# 新机：装依赖和定时（不会覆盖已有数据）
cd /opt/daily-tasks && bash install.sh
```
`install.sh` 幂等，对已有数据目录只会补 venv、单元和权限。

### 回到旧环境（Mac 上原来的 launchd + WorkBuddy 自动化）
本包**没有改动**原来的 Mac 环境，`~/MarketData`、`~/WorkBuddy/...` 都是拷贝不是移动。想回去，Mac 上那两套定时（`com.wfeixu.marketdata-update`、`com.wfeixu.marginscan`）和 WorkBuddy 自动化都还在，不受影响。**但注意不要两台机器同时写同一个行情库**——如果服务器和 Mac 都要跑，只能保留一边的行情库更新。

### 卸载
```bash
sudo bash /opt/daily-tasks/uninstall.sh        # 停定时、删单元和 nginx 配置，数据保留
sudo rm -rf /opt/daily-tasks                   # 确认不要数据了再删
```

---

## 九、包内目录

```
daily-tasks/
├── install.sh            一键安装（幂等）
├── uninstall.sh          卸载（保留数据）
├── requirements.txt      Python 依赖
├── bin/
│   ├── env.sh            公共环境（HOME 指到安装目录是关键）
│   ├── run_marketdata.sh 1/5 行情库
│   ├── run_sentiment.sh  2/5 情绪面板
│   ├── run_panorama.sh   3/5 选股估值
│   ├── run_etf.sh        4/5 ETF 资金
│   ├── run_margin.sh     5/5 融资盘
│   ├── margin_guard.sh   融资盘兜底校验
│   ├── publish.sh        产物同步到 web/ + 重建首页
│   ├── index_gen.py      首页索引页生成
│   └── preflight.sh      部署自检（8 大项）
├── systemd/              13 个单元（7 service + 6 timer）
├── config/
│   ├── nginx-daily-tasks.conf
│   └── crontab.example   不想用 systemd 时的等价写法
├── MarketData/           行情库（bars 按年分区）
├── workspace/            三套面板的代码与数据
├── margin_scan/          融资盘扫描
├── stock_server/         数据源 MCP
├── .workbuddy/skills/html-report/   HTML 构建器（内联 echarts，离线可用）
└── web/                  对外站点目录
```

**`.workbuddy` 不是可选项**：四份报告的 HTML 构建都调 `build_report.py` 把 echarts 内联进页面。缺了它，页面能生成但图表全白。所以 `env.sh` 里把 `HOME` 指到安装目录，脚本里的 `~/.workbuddy` 才找得到。
