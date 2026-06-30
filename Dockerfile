FROM python:3.11-slim

# 以非 root 使用者執行（最小權限原則）
RUN useradd --create-home --uid 10001 appuser

WORKDIR /app

# 先複製專案再安裝。
# .dockerignore 已排除 .env / .git 等機密與雜物，不會被烤進 image layer。
COPY . .
RUN pip install --no-cache-dir .

USER appuser

EXPOSE 8000

CMD ["uvicorn", "lorekeeper.app:app", "--host", "0.0.0.0", "--port", "8000"]
