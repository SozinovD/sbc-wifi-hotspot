FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       hostapd dnsmasq wpasupplicant iw iproute2 isc-dhcp-client \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY hotspot ./hotspot

CMD ["python", "-m", "hotspot"]
