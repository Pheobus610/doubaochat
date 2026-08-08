#!/usr/bin/env bash
# 简易密钥扫描钩子：阻止疑似密钥进入版本库。
# 这是轻量级检查；如需更强能力推荐搭配 gitleaks 或 AWS git-secrets（见 SECURITY.md）。
set -euo pipefail

staged=$(git diff --cached --name-only --diff-filter=ACM || true)
# 排除二进制资源、示例文件与许可证
staged=$(printf '%s\n' "$staged" \
  | grep -vE '\.(png|jpe?g|gif|svg|webp|woff2?|ico|lock)$|^\.env(\.example)?$|^LICENSE$' || true)

[ -z "$staged" ] && exit 0

# 形如  API_KEY="ak..." / token: xxxxxxxx  （>=24 位的字母数字/+/=/_-）
pattern='(api[_-]?key|secret|token|password|passwd|private[_-]?key).{0,6}[=:]["'"'"']?[A-Za-z0-9/+_=-]{24,}'

found=0
while IFS= read -r f; do
  [ -z "$f" ] && continue
  [ -f "$f" ] || continue
  if grep -nIE "$pattern" "$f" 2>/dev/null; then
    found=1
  fi
done <<< "$staged"

if [ "$found" -eq 1 ]; then
  echo "❌ 疑似密钥泄露（见上方匹配行）。提交前请改为环境变量，或确认仅为占位示例。" >&2
  echo "   如确认为占位，可在 scripts/check-secrets.sh 的排除清单中补充该文件。" >&2
  exit 1
fi

exit 0
