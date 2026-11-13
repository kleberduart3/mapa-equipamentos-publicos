#!/usr/bin/env bash
# Instala (ou atualiza) a Equicidade numa VPS Ubuntu 24.04 recém-criada, a partir deste computador.
#
#   bash deploy/instalar_vps.sh IP_DA_VPS [email-do-admin] ["Nome do admin"]
#
# Pré-requisitos:
#   - VPS com Ubuntu 24.04 e a chave pública ~/.ssh/equicidade_vps.pub cadastrada para o root;
#   - registro DNS "mapa" (tipo A) apontando para o IP (o HTTPS só sai depois disso; o script avisa).
#
# O que faz, nesta ordem (pode rodar de novo: cada passo confere o que já existe):
#   1. confere acesso SSH e DNS;
#   2. segurança: atualizações, firewall (22/80/443), fail2ban, atualizações automáticas,
#      SSH só por chave, swap de 2 GB;
#   3. instala o Docker;
#   4. clona (ou atualiza) o repositório em /srv/mapa;
#   5. envia os dados processados dos municípios (dados/processados e dados/saidas) e os
#      microdados do Censo Escolar (o relatório PDF soma as matrículas por rede a partir deles);
#   6. cria o .env de produção (só na primeira vez);
#   7. sobe app + Caddy (HTTPS automático) e espera ficar saudável;
#   8. instala a cópia de segurança diária;
#   9. cria a conta de administrador e mostra o link para definir a senha.
set -euo pipefail

IP="${1:?uso: bash deploy/instalar_vps.sh IP_DA_VPS [email] [nome]}"
ADMIN_EMAIL="${2:-}"
ADMIN_NOME="${3:-Administrador}"
DOMINIO="${MAPA_DOMINIO:-mapa.equicidade.com.br}"
REPO="https://github.com/kleberduart3/mapa-equipamentos-publicos.git"
CHAVE="${CHAVE:-$HOME/.ssh/equicidade_vps}"
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"

ssh_vps() { ssh -i "$CHAVE" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 "root@$IP" "$@"; }
passo() { printf '\n=== %s\n' "$*"; }

passo "1/9 Conferindo acesso e DNS"
ssh_vps 'grep -q "24.04" /etc/os-release && echo "Ubuntu 24.04 ok" || { echo "AVISO: não é Ubuntu 24.04"; cat /etc/os-release | head -3; }'
resolvido="$(nslookup "$DOMINIO" 8.8.8.8 2>/dev/null | awk '/^Address/ && !/8\.8\.8\.8/ {print $2}' | head -1 || true)"
if [ "$resolvido" = "$IP" ]; then
  echo "DNS ok: $DOMINIO -> $IP"
else
  echo "AVISO: $DOMINIO aponta para '${resolvido:-nada}', não para $IP."
  echo "       Crie no Registro.br o registro 'mapa' tipo A = $IP. O site sobe, mas o HTTPS só sai depois do DNS."
fi

passo "2/9 Segurança do servidor"
ssh_vps 'bash -s' <<'REMOTO'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get -y -q -o Dpkg::Options::=--force-confold upgrade
apt-get install -y -q ufw fail2ban unattended-upgrades git curl ca-certificates
# firewall: só SSH e web
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw allow 443/udp >/dev/null
ufw --force enable >/dev/null
# atualizações de segurança automáticas
dpkg-reconfigure -f noninteractive -plow unattended-upgrades
# SSH só por chave (a chave de implantação já funciona: foi por ela que chegamos aqui)
cat > /etc/ssh/sshd_config.d/10-equicidade.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
X11Forwarding no
EOF
sshd -t && systemctl reload ssh
systemctl enable --now fail2ban >/dev/null
# swap de 2 GB (folga para o relatório PDF e o cálculo a pé)
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
timedatectl set-timezone America/Maceio || true
echo "segurança ok"
REMOTO

passo "3/9 Docker"
ssh_vps 'command -v docker >/dev/null && docker --version || (curl -fsSL https://get.docker.com | sh >/dev/null && docker --version)'

passo "4/9 Código"
ssh_vps "if [ -d /srv/mapa/.git ]; then git -C /srv/mapa pull --ff-only; else git clone -q '$REPO' /srv/mapa; fi; git -C /srv/mapa log --oneline -1"

passo "5/9 Dados dos municípios"
pacote="$(mktemp -t equicidade-dados.XXXXXX).tgz"
tar czf "$pacote" -C "$RAIZ" dados/processados dados/saidas $(cd "$RAIZ" && ls dados/brutos/inep/microdados_censo_escolar_*.zip 2>/dev/null)
echo "pacote: $(du -h "$pacote" | cut -f1)"
scp -i "$CHAVE" -o StrictHostKeyChecking=accept-new -q "$pacote" "root@$IP:/root/equicidade-dados.tgz"
rm -f "$pacote"
ssh_vps 'tar xzf /root/equicidade-dados.tgz -C /srv/mapa && rm /root/equicidade-dados.tgz && ls /srv/mapa/dados/processados'

passo "6/9 Configuração de produção (.env)"
ssh_vps "cd /srv/mapa && if [ -f .env ]; then echo '.env já existe (mantido)'; else
cat > .env <<EOF
MAPA_DOMINIO=$DOMINIO
MAPA_URL_BASE=https://$DOMINIO
EOF
chmod 600 .env; echo '.env criado'; fi
chown -R 10001:10001 dados config"

passo "7/9 Subindo a aplicação (a primeira montagem da imagem leva alguns minutos)"
ssh_vps 'cd /srv/mapa && docker compose up -d --build 2>&1 | tail -5
for i in $(seq 1 60); do
  s=$(docker inspect -f "{{.State.Health.Status}}" "$(docker compose ps -q app)" 2>/dev/null || echo "?")
  [ "$s" = healthy ] && { echo "app saudável"; break; }
  sleep 5
done
docker compose ps'

passo "8/9 Cópia de segurança diária"
ssh_vps 'bash -s' <<'REMOTO'
set -euo pipefail
cat > /etc/cron.daily/equicidade-backup <<'EOF'
#!/bin/sh
set -eu
C="docker compose -f /srv/mapa/docker-compose.yml"
D=/srv/backup/$(date +%F); mkdir -p "$D"; chmod 700 /srv/backup
$C exec -T app python -c "import sqlite3; s=sqlite3.connect('/var/lib/mapa/app.db'); d=sqlite3.connect('/var/lib/mapa/backup.db'); s.backup(d); d.close(); s.close()"
$C exec -T app cat /var/lib/mapa/backup.db > "$D/app.db"
test -s "$D/app.db"
tar czf "$D/prefeitura_config.tgz" -C /srv/mapa config .env $(cd /srv/mapa && ls -d dados/brutos/municipios/*/prefeitura 2>/dev/null)
find /srv/backup -mindepth 1 -maxdepth 1 -mtime +30 -exec rm -rf {} +
EOF
chmod 755 /etc/cron.daily/equicidade-backup
echo "backup diário instalado em /etc/cron.daily/equicidade-backup (cópias em /srv/backup, 30 dias)"
REMOTO

passo "9/9 Conta de administrador"
if [ -n "$ADMIN_EMAIL" ]; then
  ssh_vps "cd /srv/mapa && docker compose exec -T app python -m backend.app.acesso.cli criar-admin '$ADMIN_EMAIL' '$ADMIN_NOME' || docker compose exec -T app python -m backend.app.acesso.cli link '$ADMIN_EMAIL'"
else
  echo "Sem e-mail informado: crie depois com"
  echo "  ssh -i $CHAVE root@$IP 'cd /srv/mapa && docker compose exec app python -m backend.app.acesso.cli criar-admin EMAIL \"NOME\"'"
fi

passo "Pronto"
echo "Ferramenta: https://$DOMINIO  (HTTPS assim que o DNS de $DOMINIO apontar para $IP)"
echo "Conferir:   curl -sI https://$DOMINIO/saude"
