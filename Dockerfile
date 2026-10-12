FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.lock ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -f /run/secrets/build_ca ]; then \
      PIP_CERT=/run/secrets/build_ca pip install --no-cache-dir -r requirements.lock; \
    else pip install --no-cache-dir -r requirements.lock; fi
COPY --chown=10001:10001 studio ./studio
COPY --chown=10001:10001 web ./web
COPY --chown=10001:10001 scripts ./scripts
RUN useradd --create-home --uid 10001 studio && mkdir /data && chown studio:studio /data
ENV STUDIO_DATA_DIR=/data HF_HOME=/data/huggingface HF_HUB_DISABLE_XET=1
USER studio
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "studio.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*"]
