# Sử dụng Python 3.12 slim để nhẹ và bảo mật
FROM python:3.12-slim

# Cài đặt uv từ image chính thức
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Thiết lập thư mục làm việc
WORKDIR /app

# Copy file quản lý thư viện trước để tận dụng Docker Cache
COPY pyproject.toml uv.lock ./

# Cài đặt dependencies (không cài đặt project chính ở bước này)
RUN uv sync --frozen --no-install-project

# Copy toàn bộ mã nguồn vào container
COPY . .

# Expose port 8000 cho FastAPI
EXPOSE 8000

# Chạy ứng dụng bằng uv
CMD ["uv", "run", "python", "-m", "app.main"]