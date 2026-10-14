# Install the design-studio starter skill for Claude Code (user level, all projects).
#   git clone --depth 1 https://github.com/tutleblue/claude-code-designtool "$env:USERPROFILE\.claude\design-studio\tool"
#   powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.claude\design-studio\tool\install.ps1"
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$base = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $env:USERPROFILE ".claude" }
$dest = Join-Path $base "skills\design-studio"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item -Force (Join-Path $here "skill\design-studio\SKILL.md") (Join-Path $dest "SKILL.md")
Write-Host "installed: $dest\SKILL.md"
Write-Host "tool: $here"
