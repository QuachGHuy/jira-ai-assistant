FROM python:3.12-slim

# 1. Cài đặt uv từ image chính thức
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Tối ưu hóa uv cho Docker: Không tạo file bytecode thừa và dùng chế độ copy
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

# 2. Copy file quản lý thư viện từ thư mục GỐC
COPY pyproject.toml uv.lock ./

# 3. Cài đặt dependencies (Bỏ qua dev dependencies để image nhẹ hơn)
RUN uv sync --frozen --no-install-project --no-dev

# 4. Copy mã nguồn backend vào container
# Đảm bảo context trong docker-compose.yml là dấu chấm (.)
COPY backend/ .

# 5. Tự động kích hoạt môi trường ảo của uv
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# Giờ Huy có thể dùng trực tiếp uvicorn vì đã có ENV PATH ở trên
# Hoặc dùng 'uv run' như cũ đều được, nhưng dùng trực tiếp sẽ nhanh hơn 1 chút
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]