#!/bin/sh
# 디자인 스튜디오 시작 스킬을 이 컴퓨터의 Claude Code 에 설치한다 (모든 프로젝트에서 /design-studio 로 부를 수 있게).
#   git clone --depth 1 https://github.com/tutleblue/claude-code-designtool ~/.claude/design-studio/tool
#   sh ~/.claude/design-studio/tool/install.sh
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
DEST="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/design-studio"
mkdir -p "$DEST"
cp "$HERE/skill/design-studio/SKILL.md" "$DEST/SKILL.md"
echo "installed: $DEST/SKILL.md"
echo "tool: $HERE"
