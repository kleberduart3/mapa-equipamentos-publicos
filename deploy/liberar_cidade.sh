#!/usr/bin/env bash
# Processa um município novo na VPS (depois da compra) e o deixa pronto para liberar à prefeitura.
#
#   bash deploy/liberar_cidade.sh CÓDIGO_IBGE            # começa o processamento (segundo plano, no servidor)
#   bash deploy/liberar_cidade.sh CÓDIGO_IBGE status     # acompanha; no fim mostra a checagem dos dados
#
# Rode deste computador. O IP vem de VPS_IP (padrão: o da produção) e a chave de CHAVE.
#
# O processamento roda no servidor, desligado do SSH: pode fechar o terminal e voltar com "status".
# Ele leva ~1 h por município (a maior parte na malha a pé do OpenStreetMap). Na primeira cidade
# nova, baixa também os arquivos nacionais do IBGE, INEP e CNES (vários GB, uma vez só).
# O site continua no ar; no fim a ferramenta reinicia (alguns segundos) para enxergar o município.
#
# Depois que terminar:
#   1. leia a checagem (escolas sem coordenada precisa, UBS fora do limite) e acerte com a prefeitura;
#   2. em "Administrar contas", crie a conta da prefeitura, marque o município e envie o convite.
set -euo pipefail

COD="${1:?uso: bash deploy/liberar_cidade.sh CÓDIGO_IBGE [status]}"
ACAO="${2:-iniciar}"
IP="${VPS_IP:-187.53.111.15}"
CHAVE="${CHAVE:-$HOME/.ssh/equicidade_vps}"

[[ "$COD" =~ ^[0-9]{7}$ ]] || { echo "Código IBGE deve ter 7 dígitos (ex.: 2700300)"; exit 1; }

ssh_vps() { ssh -i "$CHAVE" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 "root@$IP" "$@"; }

case "$ACAO" in
iniciar)
  # nome e UF, só para conferência (a etapa "config" do processamento busca de novo)
  json="$(curl -fsS "https://servicodados.ibge.gov.br/api/v1/localidades/municipios/$COD" 2>/dev/null || true)"
  [ -n "$json" ] && [ "$json" != "[]" ] || { echo "Código IBGE $COD não encontrado na API do IBGE."; exit 1; }
  nome="$(printf '%s' "$json" | grep -o '"nome":"[^"]*"' | head -1 | cut -d'"' -f4)"
  uf="$(printf '%s' "$json" | grep -o '"sigla":"[A-Z][A-Z]"' | head -1 | cut -d'"' -f4)"
  echo "Município $COD: $nome/$uf"
  ssh_vps "COD=$COD bash -s" <<'REMOTO'
set -euo pipefail
cd /srv/mapa
mkdir -p logs
LOG="logs/liberar-$COD.log"
if [ -f "logs/liberar-$COD.pid" ] && kill -0 "$(cat "logs/liberar-$COD.pid")" 2>/dev/null; then
  echo "Já está processando. Acompanhe com: bash deploy/liberar_cidade.sh $COD status"
  exit 0
fi
livre=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
[ "$livre" -ge 40 ] || { echo "Pouco disco livre (${livre} GB). Precisa de pelo menos 40 GB."; exit 1; }
chown -R 10001:10001 dados config
setsid nohup bash -c '
  set -o pipefail
  echo "início: $(date "+%F %T")"
  docker compose run --rm -T pipeline python backend/scripts/processar_municipio.py "$0"
  r=$?
  chown -R 10001:10001 dados config
  if [ $r -eq 0 ]; then
    docker compose restart app >/dev/null && echo "ferramenta reiniciada"
  fi
  echo "FIM código=$r em $(date "+%F %T")"
' "$COD" > "$LOG" 2>&1 < /dev/null &
echo $! > "logs/liberar-$COD.pid"
echo "Processamento iniciado no servidor (log: /srv/mapa/$LOG)."
REMOTO
  echo
  echo "Acompanhe com:  bash deploy/liberar_cidade.sh $COD status"
  ;;

status)
  ssh_vps "COD=$COD bash -s" <<'REMOTO'
set -uo pipefail
cd /srv/mapa
LOG="logs/liberar-$COD.log"
[ -f "$LOG" ] || { echo "Nenhum processamento de $COD neste servidor."; exit 0; }
fim=$(grep '^FIM código=' "$LOG" | tail -1)
if [ -z "$fim" ]; then
  etapa=$(grep -o '^=== [a-z]* ===' "$LOG" | tail -1 | tr -d '= ')
  echo "Processando $COD: etapa atual \"${etapa:-preparando a imagem}\" (config, baixar, preparar, cobertura, rede)."
  echo "--- últimas linhas do log"
  tail -8 "$LOG"
  exit 0
fi
echo "$fim"
if [ "$fim" != "${fim#FIM código=0 }" ]; then
  grep '^=== .*: [0-9]* s$' "$LOG" | sed 's/^=== /  /'
  CHK="dados/saidas/$COD/checagem_dados.md"
  if [ -f "$CHK" ]; then
    echo; echo "--- checagem dos dados ($CHK)"; head -60 "$CHK"
  fi
  echo
  echo "Pronto para liberar: crie a conta da prefeitura em Administrar contas e marque o município $COD."
else
  echo "Falhou. Últimas linhas do log (/srv/mapa/$LOG):"
  tail -30 "$LOG"
  echo
  echo "Corrija e rode de novo: bash deploy/liberar_cidade.sh $COD (o que já foi baixado não baixa outra vez)."
fi
REMOTO
  ;;

*)
  echo "Ação desconhecida: $ACAO (use: status)"; exit 1 ;;
esac
