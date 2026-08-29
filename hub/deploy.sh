#!/usr/bin/env bash
# deploy.sh -- board-side deploy for ~/multinode_aq/hub (run as user arduino).
#
#   ./deploy.sh           dry-run: show commits/files that would arrive and which
#                         services would need a restart. Changes nothing.
#   ./deploy.sh --apply   git pull --ff-only, uv sync --frozen, import check.
#                         Restart commands need sudo, so they are PRINTED, not run.
#
# Never edits files, never restarts anything, never touches sensor_data.db.
set -euo pipefail
cd "$(dirname "$0")"
UV="${UV:-$HOME/.local/bin/uv}"
BRANCH="${BRANCH:-main}"
PY=".venv/bin/python"

git fetch -q origin "$BRANCH"
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")
CHANGED=$(git diff --name-only "$LOCAL" "$REMOTE" -- . | sed 's#^hub/##')

need_hub=0; need_dash=0
while IFS= read -r f; do
  [ -z "$f" ] && continue
  case "$f" in
    hub.py|pyproject.toml|uv.lock|systemd/multinode_aq_hub.service) need_hub=1 ;;
  esac
  case "$f" in
    dashboard.py|nodes.json|pyproject.toml|uv.lock|aq/*|pages/*|.streamlit/*|systemd/multinode_aq_dashboard.service) need_dash=1 ;;
  esac
done <<< "$CHANGED"

echo "branch   : $BRANCH"
echo "local    : $(git rev-parse --short "$LOCAL")   remote: $(git rev-parse --short "$REMOTE")"
if [ "$LOCAL" = "$REMOTE" ]; then
  echo "status   : up to date"
else
  echo "commits  :"; git log --oneline "$LOCAL..$REMOTE" | sed 's/^/  /'
  echo "files    :"; printf '  %s\n' $CHANGED
fi
restart=()
[ $need_hub  = 1 ] && restart+=(multinode_aq_hub)
[ $need_dash = 1 ] && restart+=(multinode_aq_dashboard)
echo "restart  : ${restart[*]:-none}"

if [ "${1:-}" != "--apply" ]; then
  echo "(dry-run; pass --apply to pull and sync)"
  exit 0
fi

if [ -n "$(git status --porcelain)" ]; then
  echo "ERROR: working tree not clean - the board must never be edited directly" >&2
  git status --short >&2
  exit 1
fi

git pull -q --ff-only origin "$BRANCH"
"$UV" sync --frozen
"$PY" -m py_compile hub.py
"$PY" -c "import aq, dashboard" >/dev/null 2>&1 && echo "import   : aq, dashboard OK" || {
  echo "ERROR: import check failed - NOT safe to restart" >&2; "$PY" -c "import aq, dashboard"; exit 1; }
echo "deployed : $(git rev-parse --short HEAD)"
if [ ${#restart[@]} -gt 0 ]; then
  echo
  echo "Run as the user (sudo needs a password):"
  echo "  sudo systemctl restart ${restart[*]}"
  echo "  systemctl is-active ${restart[*]}"
fi
