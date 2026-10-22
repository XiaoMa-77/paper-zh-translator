FROM python:3.11-slim

# Chromium 内核 + 中文字体。
# 注意：服务器上不能用 SimSun（微软授权仅限 Windows 客户端），
# 只能用 OFL 授权的 Noto CJK，否则产出不可分发。
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium fonts-noto-cjk ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PAPERTRANS_BROWSER=/usr/bin/chromium
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

WORKDIR /data
ENTRYPOINT ["papertrans"]
CMD ["doctor"]
