FROM python:3.12-slim

# 1. Cài đặt uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# 2. Copy file quản lý thư viện từ GỐC (Context là .)
COPY pyproject.toml uv.lock ./

# 3. Cài đặt thư viện (Streamlit sẽ nằm trong .venv)
RUN uv sync --frozen --no-install-project

# 4. COPY NỘI DUNG THƯ MỤC FRONTEND VÀO /APP
# Vì Huy đứng ở Gốc dự án để build, nên phải trỏ vào folder frontend
COPY frontend/ .

# 5. Cập nhật PATH để dùng streamlit trực tiếp
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8501

# Chạy streamlit (lúc này streamlit_app.py đã nằm ngay tại /app/)
CMD ["streamlit", "run", "streamlit_app.py", "--server.port", "8501", "--server.address", "0.0.0.0"]