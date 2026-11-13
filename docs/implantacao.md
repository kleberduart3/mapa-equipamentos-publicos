# Implantação no servidor (VPS + domínio próprio)

O site roda em dois containers:
- **app:** a API em Python, com os dados dos municípios em memória.
- **caddy:** recebe as conexões da internet, cuida do HTTPS e repassa para o app.

Só o Caddy fica exposto. O app não tem porta aberta para fora.

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

No painel do registro do domínio (Registro.br, Cloudflare etc.), crie:
- um registro **A**: `mapa.seudominio.com.br` → IP da VPS (e **AAAA**, se a VPS tiver IPv6);
- opcionalmente, `www.mapa…` apontando para o mesmo IP.

O Caddy só consegue emitir o certificado depois que o DNS estiver propagado. Confira com `dig +short mapa.seudominio.com.br`.

## 3. Código, configuração e dados

```bash
git clone https://github.com/kleberduart3/mapa-equipamentos-publicos.git /srv/mapa
cd /srv/mapa
cp .env.exemplo .env && nano .env        # MAPA_DOMINIO, MAPA_URL_BASE, e-mail do certificado, SMTP (opcional)
chmod 600 .env
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

| Tarefa | Comando |
|---|---|
| Atualizar o código | `git pull && docker compose up -d --build` |
| Novo município | `docker compose run --rm pipeline python backend/scripts/processar_municipio.py CÓDIGO` e depois `docker compose restart app` |
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
set -e
D=/srv/backup/$(date +%F); mkdir -p "$D"
docker compose -f /srv/mapa/docker-compose.yml exec -T app \
  python -c "import sqlite3; s=sqlite3.connect('/var/lib/mapa/app.db'); d=sqlite3.connect('/tmp/app.db'); s.backup(d); d.close()"
docker compose -f /srv/mapa/docker-compose.yml cp app:/tmp/app.db "$D/app.db"
tar czf "$D/prefeitura_config.tgz" -C /srv/mapa config .env $(cd /srv/mapa && ls -d dados/brutos/municipios/*/prefeitura 2>/dev/null)
find /srv/backup -maxdepth 1 -mtime +30 -exec rm -rf {} +
```

Copie `/srv/backup` para fora do servidor, por exemplo com o rclone para um bucket ou outro provedor.
**Teste a restauração** pelo menos uma vez.

## 6. Antes de abrir para as prefeituras

- [ ] **Versão pública desativada.** A versão do GitHub Pages e o `mapa_arapiraca.html` são públicos. Desative o
      Pages (Settings → Pages) e apague a pasta `site/` do repositório se o acesso deve ser só com login.
- [ ] **Mosaicos do mapa.** Contrate um provedor (MapTiler, Stadia…) e troque a URL dos mosaicos em
      `frontend/js/app.js` e no CSP (`backend/app/acesso/web.py`). O tile.openstreetmap.org não é para produção.
- [ ] **E-mail.** Configure o SMTP no `.env` para convites e "esqueci a senha".
- [ ] **Termo de uso e LGPD.** O sistema guarda nome, e-mail, IP e registro de atividade de cada usuário, e os dados
      que as prefeituras enviarem. Defina o responsável (controlador) e o prazo de guarda.
- [ ] **Teste de restauração** da cópia de segurança.
