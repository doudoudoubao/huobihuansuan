#!/usr/bin/env bash
#
# 一键更新：拉代码 → 装依赖 → 自检 → 重启。
#
#   ./update.sh              自动判断用的是 Docker 还是 venv
#   ./update.sh --check-only 只拉代码和跑自检，不重启（想先看看再说）
#   ./update.sh --rollback   回到更新前的那个版本
#   ./update.sh -y           不交互，一路默认继续（给 AI / CI / cron 用）
#
# 你的 .env 和 data/ 都不在 git 里，全程不会被动到。

set -euo pipefail

REPO_DIR="${UPDATE_SH_ROOT:-$(cd "$(dirname "$0")" && pwd)}"

# update.sh 自己也在仓库里，git pull 会把它换掉。而 bash 是边读边执行的：
# 文件在执行途中变了长度，后面读到的就会是错位的半行。
# 所以先把自己整份复制到临时文件，从副本里跑，原文件怎么变都不影响。
if [[ "${UPDATE_SH_REEXEC:-}" != "1" ]]; then
    copy="$(mktemp "${TMPDIR:-/tmp}/huobi-update.XXXXXX")"
    cat "$0" > "$copy"
    chmod +x "$copy"
    UPDATE_SH_REEXEC=1 UPDATE_SH_ROOT="$REPO_DIR" exec bash "$copy" "$@"
fi
trap 'rm -f "$0"' EXIT

cd "$REPO_DIR"

BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; OFF=$'\033[0m'
[[ -t 1 ]] || { BOLD=""; DIM=""; GREEN=""; YELLOW=""; RED=""; OFF=""; }

say()  { echo "${BOLD}▸ $*${OFF}"; }
ok()   { echo "  ${GREEN}✓${OFF} $*"; }
warn() { echo "  ${YELLOW}!${OFF} $*"; }
die()  { echo "  ${RED}✗${OFF} $*" >&2; exit 1; }

STAMP_FILE=".update-previous"
MODE="update"
ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --check-only) MODE="check" ;;
    --rollback)   MODE="rollback" ;;
    -y|--yes)     ASSUME_YES=1 ;;
    "")           ;;
    *)            die "未知参数 $arg（可用：--check-only / --rollback / -y）" ;;
  esac
done

confirm() {
  # 非交互场景（AI、CI、cron）不要卡在 read 上：给 -y 就继续，否则明确说清为什么停。
  [[ $ASSUME_YES -eq 1 ]] && { ok "已加 -y，自动继续"; return 0; }
  if [[ ! -t 0 ]]; then
    warn "非交互运行且没加 -y，就此停下。确认没问题的话重跑一次并加上 -y"
    return 1
  fi
  read -r -p "  $1 [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]]
}

# --- 判断部署方式 -------------------------------------------------------------

uses_docker() {
  command -v docker >/dev/null 2>&1 || return 1
  docker compose ps --quiet 2>/dev/null | grep -q . || return 1
}

python_bin() {
  if [[ -x .venv/bin/python ]]; then echo ".venv/bin/python"
  elif [[ -x venv/bin/python ]]; then echo "venv/bin/python"
  else command -v python3 || command -v python; fi
}

interpret_check() {
  # $1 = run.py --check 的退出码，$2 = 中止时的附加说明
  local status="$1" note="$2"
  case "$status" in
    0) ok "自检通过"; return 0 ;;
    2)
      # 「能跑，但某类数据源只剩每日更新的备胎」——服务本身没问题，
      # 不该因此拦住重启，否则新版永远上不去。
      warn "自检报告数据源有缺口（退出码 2），服务本身能跑，继续"
      return 0
      ;;
    *)
      warn "自检没通过（退出码 $status），这通常意味着新版起不来"
      warn "可以先 ./update.sh --rollback 回退，再照自检输出排查"
      [[ "$MODE" == "check" ]] && return 1
      if confirm "仍然重启？"; then
        return 0
      fi
      echo "  ${RED}✗${OFF} 已取消${note:+，$note}" >&2
      return 1
      ;;
  esac
}

# --- 回滚 ---------------------------------------------------------------------

if [[ "$MODE" == "rollback" ]]; then
  [[ -f "$STAMP_FILE" ]] || die "没有找到上一版记录（$STAMP_FILE），无法自动回滚"
  read -r PREV_BRANCH PREVIOUS < "$STAMP_FILE"
  [[ -n "${PREVIOUS:-}" ]] || die "$STAMP_FILE 内容不完整，请手动 git checkout"
  say "回滚到 $PREVIOUS"
  # 停在这个旧提交上（detached HEAD）。分支本身不动，想回到最新版
  # 只要 git checkout 回分支即可，不会留下需要清理的痕迹。
  git -c advice.detachedHead=false checkout --quiet "$PREVIOUS"
  if uses_docker; then
    docker compose up -d --build
    ok "已回到 $PREVIOUS 并重启"
  else
    "$(python_bin)" -m pip install --quiet -r requirements.txt
    ok "已回到 $PREVIOUS"
    warn "依赖已还原，请自行重启进程（systemctl restart huobihuansuan）"
  fi
  echo "  ${DIM}想再回到最新版：git checkout $PREV_BRANCH && ./update.sh${OFF}"
  exit 0
fi

# --- 检查工作区 ---------------------------------------------------------------

say "检查工作区"
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  warn "有未提交的本地改动，git pull 可能冲突："
  git status --short --untracked-files=no | sed 's/^/      /'
  warn "想丢弃本地改动：git checkout -- .   想保留：git stash"
  confirm "仍然继续？" || die "已取消"
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$BRANCH" == "HEAD" ]]; then
  die "当前不在任何分支上（多半是刚 --rollback 过）。
      先切回分支再更新，例如：git checkout main"
fi
BEFORE="$(git rev-parse --short HEAD)"
echo "$BRANCH $BEFORE" > "$STAMP_FILE"
ok "分支 $BRANCH，当前版本 $BEFORE"

# --- 拉代码 -------------------------------------------------------------------

say "拉取更新"
for attempt in 1 2 3; do
  if git pull --quiet --ff-only origin "$BRANCH"; then break; fi
  [[ $attempt -eq 3 ]] && die "git pull 失败了 3 次，检查网络或代理"
  warn "第 $attempt 次失败，${attempt}0 秒后重试"
  sleep "${attempt}0"
done

AFTER="$(git rev-parse --short HEAD)"
if [[ "$BEFORE" == "$AFTER" ]]; then
  ok "已经是最新版本，无需更新"
  exit 0
fi
ok "$BEFORE → $AFTER"
echo "${DIM}"
git --no-pager log --oneline "$BEFORE..$AFTER" | sed 's/^/      /'
echo "${OFF}"

# --- 依赖 + 自检 + 重启 -------------------------------------------------------

if uses_docker; then
  say "重建镜像"
  docker compose build
  ok "镜像已就绪"

  say "自检"
  set +e
  docker compose run --rm bot python run.py --check
  check_status=$?
  set -e
  interpret_check "$check_status" "旧容器还在跑，服务没有中断" || exit 1

  [[ "$MODE" == "check" ]] && { ok "只做检查，未重启"; exit 0; }

  say "重启服务"
  docker compose up -d
  ok "已重启，看日志：docker compose logs -f"
else
  PY="$(python_bin)"
  say "更新依赖（$PY）"
  "$PY" -m pip install --quiet --upgrade -r requirements.txt
  ok "依赖已是最新"

  say "自检"
  set +e
  "$PY" run.py --check
  check_status=$?
  set -e
  interpret_check "$check_status" "" || exit 1

  [[ "$MODE" == "check" ]] && { ok "只做检查，未重启"; exit 0; }

  say "重启服务"
  if systemctl is-active --quiet huobihuansuan 2>/dev/null; then
    sudo systemctl restart huobihuansuan
    ok "systemd 服务已重启，看日志：journalctl -u huobihuansuan -f"
  else
    warn "没检测到 systemd 服务，请手动重启：$PY run.py"
  fi
fi

echo
echo "  ${GREEN}${BOLD}更新完成${OFF}  $BEFORE → $AFTER"
echo "  ${DIM}数据库会在启动时自动补上新增字段，data/ 和 .env 都没动过${OFF}"
echo "  ${DIM}出问题就回退：./update.sh --rollback${OFF}"
