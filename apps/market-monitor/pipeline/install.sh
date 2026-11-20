#!/usr/bin/env bash
# 日更任务一键安装（Debian/Ubuntu/CentOS 等 systemd 发行版）
#
# 用法：
#   sudo bash install.sh                        # 装到 /opt/daily-tasks，跑任务用户 daily
#   sudo bash install.sh --prefix /data/daily   # 换安装目录
#   sudo bash install.sh --user weifei          # 换运行用户（需已存在）
#   sudo bash install.sh --skip-deps            # 依赖已装好，跳过 pip
#   sudo bash install.sh --no-nginx             # 不配 nginx
#
# 幂等：可以重复执行，已存在的用户/venv/systemd 单元不会重复创建。

set -uo pipefail

# ---------- 参数 ----------
PREFIX="/opt/daily-tasks"
RUN_USER="daily"
SKIP_DEPS=0
DO_NGINX=1
PIP_INDEX="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix)   PREFIX="$2"; shift 2 ;;
    --user)     RUN_USER="$2"; shift 2 ;;
    --skip-deps) SKIP_DEPS=1; shift ;;
    --no-nginx) DO_NGINX=0; shift ;;
    --index)    PIP_INDEX="$2"; shift 2 ;;
    -h|--help)  sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "未知参数：$1"; exit 1 ;;
  esac
done

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

C_OK=$'\033[32m'; C_BAD=$'\033[31m'; C_WARN=$'\033[33m'; C_B=$'\033[1m'; C_0=$'\033[0m'
ok()   { echo "  ${C_OK}✓${C_0} $1"; }
bad()  { echo "  ${C_BAD}✗${C_0} $1"; }
warn() { echo "  ${C_WARN}!${C_0} $1"; }
step() { echo; echo "${C_B}== $1${C_0}"; }
die()  { echo "${C_BAD}中止：$1${C_0}"; exit 1; }

# ---------- 0 前置检查 ----------
step "0/9 前置检查"
[ "$(id -u)" -eq 0 ] || die "需要 root：sudo bash install.sh"
ok "root 权限"

PYTHON_BIN="$(command -v python3 || true)"
[ -n "$PYTHON_BIN" ] || die "没装 python3。Debian/Ubuntu：apt install -y python3 python3-venv python3-dev；CentOS：dnf install -y python3 python3-devel"
ver="$("$PYTHON_BIN" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
"$PYTHON_BIN" -c 'import sys;sys.exit(0 if sys.version_info>=(3,9) else 1)' \
  || die "python3 版本 $ver 过低，需要 ≥3.9"
ok "python3 ${ver}（${PYTHON_BIN}）"
"$PYTHON_BIN" -c 'import venv' 2>/dev/null || die "缺 venv 模块：apt install -y python3-venv"

command -v rsync >/dev/null 2>&1 || die "缺 rsync：apt install -y rsync"
command -v systemctl >/dev/null 2>&1 || die "没有 systemd，本包按 systemd 设计（非 systemd 环境用 crontab.example）"

mkdir -p "$(dirname "$PREFIX")"
avail_k=$(df -Pk "$(dirname "$PREFIX")" | awk 'NR==2{print $4}')
[ "${avail_k:-0}" -gt 2000000 ] || die "可用空间不足 2GB（当前 $((${avail_k:-0}/1024))MB），行情库需要约 1GB"
ok "磁盘可用 $((avail_k/1024/1024)) GB"

# ---------- 1 落位 ----------
step "1/9 安装到 $PREFIX"
CUR_PREFIX="/opt/daily-tasks"
[ -f "$SRC_DIR/.install_prefix" ] && CUR_PREFIX="$(cat "$SRC_DIR/.install_prefix")"

if [ "$SRC_DIR" != "$PREFIX" ]; then
  mkdir -p "$PREFIX"
  rsync -a --exclude 'venv/' --exclude 'logs/*' --exclude '.DS_Store' "$SRC_DIR"/ "$PREFIX"/ \
    || die "拷贝失败"
  ok "从 $SRC_DIR 拷贝到 $PREFIX"
else
  ok "已在目标目录，跳过拷贝"
fi

# 包内所有路径是硬编码的，换目录必须整包重写
if [ "$CUR_PREFIX" != "$PREFIX" ]; then
  echo "  重写路径 $CUR_PREFIX → $PREFIX"
  grep -rIl -- "$CUR_PREFIX" "$PREFIX" 2>/dev/null | while IFS= read -r f; do
    sed -i "s|$CUR_PREFIX|$PREFIX|g" "$f"
  done
  # 运行用户也写死在 systemd 单元里
  ok "路径已重写"
fi
echo "$PREFIX" > "$PREFIX/.install_prefix"

# systemd 单元里的 User=daily 跟着参数走
if [ "$RUN_USER" != "daily" ]; then
  sed -i "s|^User=daily$|User=$RUN_USER|; s|^Group=daily$|Group=$RUN_USER|" "$PREFIX"/systemd/*.service 2>/dev/null
  ok "运行用户改为 $RUN_USER"
fi

# ---------- 2 运行用户 ----------
step "2/9 运行用户"
if id "$RUN_USER" >/dev/null 2>&1; then
  ok "用户 $RUN_USER 已存在"
else
  NOLOGIN=/usr/sbin/nologin
  [ -x "$NOLOGIN" ] || NOLOGIN=/sbin/nologin
  [ -x "$NOLOGIN" ] || NOLOGIN=/bin/false
  useradd --system --home-dir "$PREFIX" --shell "$NOLOGIN" "$RUN_USER" \
    && ok "已创建系统用户 ${RUN_USER}（shell=${NOLOGIN}）" \
    || die "创建用户失败"
fi

# ---------- 3 依赖 ----------
step "3/9 Python 虚拟环境"
if [ "$SKIP_DEPS" -eq 0 ]; then
  if [ ! -x "$PREFIX/venv/bin/python3" ]; then
    "$PYTHON_BIN" -m venv "$PREFIX/venv" || die "创建 venv 失败"
    ok "venv 已创建"
  else
    ok "venv 已存在，复用"
  fi
  "$PREFIX/venv/bin/python3" -m pip install --upgrade pip -q -i "$PIP_INDEX" 2>/dev/null || warn "pip 自升级失败，继续"
  echo "  安装依赖（首次约 2-5 分钟，akshare 依赖较多）…"
  "$PREFIX/venv/bin/python3" -m pip install -q -r "$PREFIX/requirements.txt" -i "$PIP_INDEX" \
    && ok "依赖装好" || bad "依赖安装失败，检查网络或换 --index 源（如 https://mirrors.aliyun.com/pypi/simple）"
else
  ok "--skip-deps，跳过"
fi

# ---------- 4 目录与权限 ----------
step "4/9 目录与权限"
for d in logs web; do mkdir -p "$PREFIX/$d"; done
chown -R "$RUN_USER":"$RUN_USER" "$PREFIX" 2>/dev/null
# nginx 以 www-data/nginx 身份读页面
chmod -R a+rX "$PREFIX/web"
ok "日志目录 $PREFIX/logs、站点目录 $PREFIX/web"
ok "属主 $RUN_USER"

# ---------- 5 systemd ----------
step "5/9 systemd 单元"
cp -f "$PREFIX"/systemd/*.service "$PREFIX"/systemd/*.timer /etc/systemd/system/ || die "拷贝单元失败"
systemctl daemon-reload
ok "已安装 $(ls "$PREFIX"/systemd/*.service | wc -l) 个 service / $(ls "$PREFIX"/systemd/*.timer | wc -l) 个 timer"

# 数据源常驻服务先起来，日更任务依赖它
systemctl enable --now daily-stock-server.service >/dev/null 2>&1 \
  && ok "daily-stock-server 已启用并启动" || bad "daily-stock-server 启动失败：journalctl -u daily-stock-server -n 50"

for t in marketdata sentiment panorama etf margin margin-guard; do
  systemctl enable "daily-$t.timer" >/dev/null 2>&1 && ok "daily-$t.timer 已启用" || bad "daily-$t.timer 启用失败"
done
systemctl start daily-marketdata.timer daily-sentiment.timer daily-panorama.timer daily-etf.timer \
         daily-margin.timer daily-margin-guard.timer >/dev/null 2>&1
ok "timer 已启动"

# ---------- 6 nginx ----------
step "6/9 nginx 站点"
if [ "$DO_NGINX" -eq 1 ]; then
  if command -v nginx >/dev/null 2>&1; then
    cp -f "$PREFIX/config/nginx-daily-tasks.conf" /etc/nginx/conf.d/daily-tasks.conf
    if nginx -t >/dev/null 2>&1; then
      systemctl reload nginx 2>/dev/null || systemctl restart nginx 2>/dev/null
      ok "站点已生效： http://<服务器IP>/  （首页自动生成）"
    else
      bad "nginx 配置校验失败，已回退：rm /etc/nginx/conf.d/daily-tasks.conf && nginx -t"
      nginx -t
    fi
  else
    warn "没装 nginx，跳过。要访问页面：apt install -y nginx 后重跑 install.sh，或用 python3 -m http.server 临时看"
  fi
else
  ok "--no-nginx，跳过"
fi

# ---------- 7 生成索引页 ----------
step "7/9 生成首页索引"
bash "$PREFIX/bin/publish.sh" install 2>&1 | sed 's/^/  /'

# ---------- 8 自检 ----------
step "8/9 部署自检"
bash "$PREFIX/bin/preflight.sh"
PF=$?

# ---------- 9 收尾 ----------
step "9/9 完成"
if [ "$PF" -eq 0 ]; then
  cat <<EOF
  ${C_OK}安装完成${C_0}

  下一步（建议按顺序做一遍，确认端到端通）：
    1) 手动跑一次行情库增量，确认能连上数据源：
         sudo -u $RUN_USER bash $PREFIX/bin/run_marketdata.sh
    2) 再跑一次情绪面板，确认整条链能出页面：
         sudo -u $RUN_USER bash $PREFIX/bin/run_sentiment.sh
    3) 打开 http://<服务器IP>/ 看首页四张卡是否都是今天的数据

  看排期：  systemctl list-timers 'daily-*'
  看日志：  tail -f $PREFIX/logs/$(date +%Y%m%d).log
            journalctl -u daily-marketdata -n 100
  看任务：  systemctl status daily-stock-server

  定时只在机器开机且 systemd 运行时生效。云厂商的「关机」会停掉 timer。
EOF
else
  echo "  ${C_WARN}安装完成但有 $PF 项自检未通过${C_0}，修完再依赖定时任务。"
  echo "  重新自检：bash $PREFIX/bin/preflight.sh"
fi
