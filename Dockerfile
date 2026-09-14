# Epilogue — container image (dashboard + Vigil)
#   docker build -t epilogue .
#   docker run -p 8000:8000 -v epilogue-data:/app/data \
#     -e EPILOGUE_MODEL_PROVIDER=openai -e OPENAI_API_KEY epilogue

FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY web ./web
RUN pip install --no-cache-dir '.[hosting]'

ENV EPILOGUE_DATA_DIR=/app/data
EXPOSE 8000
# Cloud Run (and most PaaS hosts) inject the serving port as $PORT — honor it.
CMD exec epilogue serve --host 0.0.0.0 --port "${PORT:-8000}"
