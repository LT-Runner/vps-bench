FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg python3 python3-venv iperf3 jq dnsutils \
    && curl -fsSL https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh -o /tmp/ookla-repo.sh \
    && bash /tmp/ookla-repo.sh \
    && apt-get update && apt-get install -y --no-install-recommends speedtest \
    && python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir speedtest-cli \
    && ln -s /opt/venv/bin/speedtest-cli /usr/local/bin/speedtest-cli \
    && rm -rf /var/lib/apt/lists/* /tmp/ookla-repo.sh

WORKDIR /app
COPY benchmark.py /app/benchmark.py
RUN mkdir -p /results
VOLUME ["/results"]
ENTRYPOINT ["python3", "/app/benchmark.py"]
