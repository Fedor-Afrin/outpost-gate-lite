# Один образ для всех режимов: dev / gns3 / host.
# Режим определяется НЕ здесь, а способом запуска (compose / GNS3).

# --- AmneziaWG: userspace-реализация (модуль ядра не нужен) ---------------------
FROM golang:1-bookworm AS awg-go
RUN git clone --depth 1 https://github.com/amnezia-vpn/amneziawg-go /src \
    && cd /src && CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o /out/amneziawg-go .

# --- AmneziaWG: утилита awg (собирается на той же базе, что и итоговый образ) ---
FROM python:3.12-slim AS awg-tools
RUN apt-get update && apt-get install -y --no-install-recommends build-essential git ca-certificates \
    && git clone --depth 1 https://github.com/amnezia-vpn/amneziawg-tools /src \
    && make -C /src/src \
    && mkdir -p /out \
    && (cp /src/src/awg /out/awg 2>/dev/null || cp /src/src/wg /out/awg)

# --- итоговый образ -------------------------------------------------------------
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        iproute2 nftables iputils-ping traceroute tcpdump procps busybox \
        dnsmasq-base ieee-data wireguard-tools \
        strongswan-charon strongswan-swanctl xl2tpd ppp \
    && rm -rf /var/lib/apt/lists/*

COPY --from=awg-go /out/amneziawg-go /usr/local/bin/amneziawg-go
COPY --from=awg-tools /out/awg /usr/local/bin/awg

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
