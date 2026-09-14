# Epilogue — container image (dashboard + Vigil)
#   docker build -t epilogue .
#   docker run -p 8000:8000 -v epilogue-data:/app/data \
#     -e EPILOGUE_MODEL_PROVIDER=openai -e OPENAI_API_KEY epilogue

FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY web ./web
RUN pip install --no-cache-dir .

ENV EPILOGUE_DATA_DIR=/app/data
EXPOSE 8000
CMD ["epilogue", "serve", "--host", "0.0.0.0", "--port", "8000"]
