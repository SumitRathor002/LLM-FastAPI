FROM python:3.12-slim

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies into system Python (no venv needed in Docker)
RUN uv pip install --system -r pyproject.toml

# Copy project
COPY . .

EXPOSE 8000

CMD ["uv" , "run" ,"python", "-m", "src.app.main"]