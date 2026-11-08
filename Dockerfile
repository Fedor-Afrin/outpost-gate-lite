# Один образ для всех режимов: dev / gns3 / host.
# Режим определяется НЕ здесь, а способом запуска (compose / GNS3).
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        iproute2 nftables iputils-ping traceroute tcpdump procps busybox \
        dnsmasq-base ieee-data wireguard-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/ubuntu-router

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY web/ web/
COPY config/router.yaml /etc/ubuntu-router/router.yaml
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh app/scripts/*.sh && mkdir -p /var/lib/ubuntu-router

ENV ROUTER_MODE=dev \
    API_HOST=0.0.0.0 \
    API_PORT=8000

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
