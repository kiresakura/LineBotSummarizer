#!/bin/bash
# 一鍵環境建置腳本 — 從 1Password 自動拉取所有 secrets
set -e

echo "=== LINE Bot Summarizer 環境建置 ==="

# 1. 檢查必要工具
for cmd in python3 pip op; do
  if ! command -v $cmd &> /dev/null; then
    echo "錯誤: 找不到 $cmd，請先安裝"
    [[ $cmd == "op" ]] && echo "  brew install 1password-cli"
    [[ $cmd == "python3" ]] && echo "  brew install python@3.11"
    exit 1
  fi
done

# 2. 確認 1Password 已登入
if ! op account list &> /dev/null; then
  echo "請先登入 1Password CLI: eval \$(op signin)"
  exit 1
fi

echo "[1/4] 從 1Password 拉取 secrets..."

LINE_SECRET=$(op item get "繆思精工LINE Channel Secret" --fields credential --reveal)
LINE_TOKEN=$(op item get "繆思精工LINE Access Token" --fields credential --reveal)
NOTION_KEY=$(op item get "繆思精工Notion API Key" --fields credential --reveal)
NOTION_DB=$(op item get "繆思精工Notion Main DB ID" --fields credential --reveal)
NOTION_DIGEST_DB=$(op item get "繆思精工Notion Digest DB ID" --fields credential --reveal)
OPENROUTER_KEY=$(op item get "繆思精工OpenRouter API Key" --fields credential --reveal)

echo "[2/4] 產生 .env..."

cat > .env << EOF
# === LINE ===
LINE_CHANNEL_SECRET=${LINE_SECRET}
LINE_CHANNEL_ACCESS_TOKEN=${LINE_TOKEN}

# === Notion ===
NOTION_API_KEY=${NOTION_KEY}
NOTION_DATABASE_ID=${NOTION_DB}
NOTION_DIGEST_DATABASE_ID=${NOTION_DIGEST_DB}

# === AI (OpenRouter) ===
OPENROUTER_API_KEY=${OPENROUTER_KEY}

# === Processing ===
AGGREGATION_WINDOW_SECONDS=300
MIN_BATCH_SIZE=3
MAX_BATCH_SIZE=20
NOISE_FILTER_ENABLED=true
EOF

echo "[3/4] 安裝 Python 依賴..."
pip install -q .

echo "[4/4] 驗證..."
python3 -c "from app.config import get_settings; s = get_settings(); print(f'  Models: text={s.ai_model_text}, vision={s.ai_model_vision}')"

echo ""
echo "=== 建置完成！==="
echo "啟動方式："
echo "  uvicorn app.main:app --reload --port 8000"
echo "  docker build -t linebot-summarizer . && docker run -p 8000:8000 --env-file .env linebot-summarizer"
