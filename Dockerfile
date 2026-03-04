FROM python:3.11-slim

WORKDIR /app

# 安裝依賴
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# 複製程式碼
COPY . .

# 啟動
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
