# Implantação no servidor (VPS + domínio próprio)

O site roda em dois containers:
- **app:** a API em Python, com os dados dos municípios em memória.
- **caddy:** recebe as conexões da internet, cuida do HTTPS e repassa para o app.

Só o Caddy fica exposto. O app não tem porta aberta para fora.

## Caminho rápido: um comando

Com a VPS criada (Ubuntu 24.04, chave `~/.ssh/equicidade_vps.pub` cadastrada para o root) e o registro DNS `mapa`
apontando para o IP, rode **neste computador** (Git Bash):

```bash
bash deploy/instalar_vps.sh IP_DA_VPS seu@email "Seu Nome"
```

O script faz tudo:
- a segurança do servidor: firewall, SSH só por chave, fail2ban, atualizações automáticas e swap;
- instala o Docker;
- clona o código e envia os dados dos municípios;
- cria o `.env`;
- sobe a aplicação com HTTPS;
- instala a cópia de segurança diária;
- cria o administrador e mostra o link de senha.

Pode rodar de novo para atualizar. As seções abaixo explicam cada passo, para quem preferir fazer à mão.

Provedor recomendado (13/11/2026): **Hostinger VPS KVM 2** (2 vCPU, 8 GB, 100 GB NVMe, datacenter no Brasil). Custa
R$ 42,99/mês no plano de 24 meses e renova a R$ 77,99/mês.

## 1. Servidor

**Máquina.** Uma VPS com **Ubuntu 24.04**, 4 vCPU e **8 GB de RAM**. Cada município carregado ocupa cerca de 1 GB
com a malha a pé, e o servidor mantém até 3 em memória. O disco precisa de **≥ 60 GB**: os arquivos nacionais do
IBGE, INEP e CNES somam ~25 GB.

Opções comuns: Hetzner (CPX31), DigitalOcean, Contabo, Magalu Cloud.

**Primeiros passos de segurança (como root, uma vez):**

```bash
adduser mapa && usermod -aG sudo mapa
# copie sua chave SSH para /home/mapa/.ssh/authorized_keys e teste o login com ela ANTES do próximo passo
sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/; s/^#\?PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl restart ssh
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw enable
apt update && apt install -y unattended-upgrades fail2ban && dpkg-reconfigure -plow unattended-upgrades
curl -fsSL https://get.docker.com | sh && usermod -aG docker mapa
```

## 2. Domínio

O produto usa **equicidade.com.br** para a landing page e **mapa.equicidade.com.br** para a ferramenta
(detalhes em `docs/equicidade.md`). No painel do Registro.br (ou do DNS que você usar), crie registros **A**
apontando para o IP da VPS (e **AAAA**, se ela tiver IPv6) para:
- `equicidade.com.br`
- `www.equicidade.com.br` (o Caddy redireciona para o endereço sem www)
- `mapa.equicidade.com.br`

O Caddy só consegue emitir os certificados depois que o DNS estiver propagado. Confira com
`dig +short equicidade.com.br` e `dig +short mapa.equicidade.com.br`.

## 3. Código, configuração e dados

```bash
git clone https://github.com/kleberduart3/mapa-equipamentos-publicos.git /srv/mapa
cd /srv/mapa
cp .env.exemplo .env && nano .env        # MAPA_DOMINIO, MAPA_URL_BASE, e-mail do certificado, SMTP (opcional)
chmod 600 .env
mkdir -p dados
```

Para os dados há dois caminhos:

- **Copiar do seu computador** (mais rápido). Precisa só de `processados/` e `saidas/` de cada município:
  ```bash
  rsync -av --relative "dados/./processados" "dados/./saidas" mapa@IP:/srv/mapa/dados/
  ```
- **Processar no servidor** (baixa tudo de novo; ~1 h por município, quase todo o tempo na malha do OSM):
  ```bash
  docker compose build
  docker compose run --rm pipeline python backend/scripts/processar_municipio.py 2700300
  ```

Arapiraca tem o Catálogo do INEP versionado no git, então reprocessar dá os mesmos números.

**Dono das pastas.** O container roda como o usuário 10001, sem root. Ele precisa poder gravar em `dados/`
(uploads das prefeituras, processamento) e em `config/` (o processamento cria o YAML do município).
Rode isto depois de copiar ou processar os dados, e de novo se copiar arquivos como outro usuário:

```bash
sudo chown -R 10001:10001 dados config
```

## 4. Subir

```bash
docker compose up -d --build
docker compose logs -f caddy          # espere "certificate obtained successfully"
docker compose exec app python -m backend.app.acesso.cli criar-admin voce@seudominio.com.br "Seu Nome"
```

Abra o link que o último comando mostrar e defina a sua senha. Depois, em **Administrar contas**:
- crie as contas das prefeituras e marque o(s) município(s) de cada uma;
- copie o link de convite e envie por um canal seguro (ou configure o SMTP para enviar por e-mail).

## 5. Operação

### Liberar uma cidade (depois da compra)

A Equicidade vende **uma cidade por compra**: o município só é processado e liberado depois que a compra é
efetuada. Deste computador:

```bash
bash deploy/liberar_cidade.sh 2704302          # começa (roda no servidor, em segundo plano)
bash deploy/liberar_cidade.sh 2704302 status   # acompanha; no fim mostra a checagem dos dados
```

- Leva ~1 h por cidade. Na primeira cidade nova, baixa também os arquivos nacionais do IBGE, INEP e CNES (uma vez só).
- O site continua no ar. No fim, a ferramenta reinicia em poucos segundos para enxergar o município novo.
- Quando o `status` disser "Pronto para liberar":
  1. leia a checagem (escolas sem coordenada precisa, UBS fora do limite) e acerte com a prefeitura;
  2. em **Administrar contas**, crie a conta da prefeitura, marque o município e envie o convite.

| Tarefa | Comando |
|---|---|
| Atualizar o código | `git pull && docker compose up -d --build` |
| Novo município (à mão, no servidor) | `docker compose run --rm pipeline python backend/scripts/processar_municipio.py CÓDIGO` e depois `docker compose restart app` |
| Mudou `config/parametros.yaml` | `docker compose run --rm pipeline python backend/scripts/calcular_cobertura.py -m CÓDIGO` e depois `docker compose restart app` |
| Link de senha (alguém esqueceu) | painel de contas, ou `docker compose exec app python -m backend.app.acesso.cli link email@x` |
| Ver logs | `docker compose logs --tail 200 app` |
| Listar contas | `docker compose exec app python -m backend.app.acesso.cli listar` |

### Cópia de segurança (diária)

O que não se recupera baixando de novo:
- **o banco de contas;**
- `dados/brutos/municipios/*/prefeitura/` (o que as prefeituras enviaram);
- `config/` e o `.env`.

```bash
# /etc/cron.daily/mapa-backup  (chmod +x)
#!/bin/sh
set -eu
C="docker compose -f /srv/mapa/docker-compose.yml"
D=/srv/backup/$(date +%F); mkdir -p "$D"; chmod 700 /srv/backup
# cópia consistente do SQLite (mesmo com o site em uso), gravada no volume e depois lida para fora
$C exec -T app python -c "import sqlite3; s=sqlite3.connect('/var/lib/mapa/app.db'); d=sqlite3.connect('/var/lib/mapa/backup.db'); s.backup(d); d.close(); s.close()"
$C exec -T app cat /var/lib/mapa/backup.db > "$D/app.db"
test -s "$D/app.db"
tar czf "$D/prefeitura_config.tgz" -C /srv/mapa config .env $(cd /srv/mapa && ls -d dados/brutos/municipios/*/prefeitura 2>/dev/null)
find /srv/backup -mindepth 1 -maxdepth 1 -mtime +30 -exec rm -rf {} +

```

Copie `/srv/backup` para fora do servidor, por exemplo com o rclone para um bucket ou outro provedor.
**Teste a restauração** pelo menos uma vez.

## 6. Antes de abrir para as prefeituras

- [x] **Versão pública desativada** (13/11/2026): GitHub Pages desligado; `site/` e o HTML único saíram do
      repositório e não são mais versionados. Eles continuam no histórico do git: para apagar de vez, torne o
      repositório privado.
- [ ] **Mosaicos do mapa.** Contrate um provedor (MapTiler, Stadia…) e preencha `MAPA_MOSAICOS_URL` e
      `MAPA_MOSAICOS_ATRIBUICAO` no `.env`; o mapa, o relatório e a política de segurança passam a usá-lo.
      O tile.openstreetmap.org não é para produção.
- [ ] **E-mail.** Configure o SMTP no `.env` para convites e "esqueci a senha".
- [ ] **Termo de uso e LGPD.** O sistema guarda nome, e-mail, IP e registro de atividade de cada usuário, e os dados
      que as prefeituras enviarem. Defina o responsável (controlador) e o prazo de guarda.
- [ ] **Teste de restauração** da cópia de segurança.
