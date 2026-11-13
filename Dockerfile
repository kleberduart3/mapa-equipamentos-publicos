# Mapa de Equipamentos Públicos – imagem do servidor
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    MPLCONFIGDIR=/tmp/matplotlib \
    XDG_CACHE_HOME=/tmp/cache


WORKDIR /app

# Dependências primeiro (camada reaproveitada enquanto requirements.txt não muda)
COPY requirements.txt .
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && pip install -r requirements.txt \
 && python -m playwright install --with-deps chromium \
 && apt-get purge -y build-essential && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* /root/.cache

# Código (os dados ficam fora da imagem, num volume)
COPY backend ./backend
COPY config ./config
COPY frontend ./frontend

# Roda sem privilégios
RUN useradd --create-home --uid 10001 mapa \
 && mkdir -p /app/dados /var/lib/mapa \
 && chown -R mapa:mapa /app/dados /var/lib/mapa
USER mapa

ENV MAPA_AMBIENTE=producao \
    MAPA_DB_URL=sqlite:////var/lib/mapa/app.db \
    MAPA_COOKIE_SEGURO=true

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/saude', timeout=4).status == 200 else 1)"

# Um processo só: os dados de cada município ficam em memória (e os limites de
# login/PDF são por processo). --proxy-headers: o IP real vem do Caddy; a porta
# 8000 não é publicada, então só o Caddy fala com o servidor.
CMD ["uvicorn", "backend.app.api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header", "--timeout-keep-alive", "30"]
