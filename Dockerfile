FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .
CMD ["app-store-connect-mcp", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8080"]
