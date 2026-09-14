# Epilogue — container image (dashboard + Vigil)
# Build from the repository root:
#   docker build -f deploy/Dockerfile -t epilogue .
#   docker run -p 8000:8000 -v epilogue-data:/app/data \
#     -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_REGION epilogue

FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY web ./web
RUN pip install --no-cache-dir .

ENV EPILOGUE_DATA_DIR=/app/data
EXPOSE 8000
CMD ["epilogue", "serve", "--host", "0.0.0.0", "--port", "8000"]
