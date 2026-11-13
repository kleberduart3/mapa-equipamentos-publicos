# Segurança – o que está implementado e por quê

## Acesso

- **Tudo exige login.**
  - Sem sessão válida, as páginas redirecionam para `/entrar` e a API responde 401.
  - A documentação automática da API (`/docs`) está desligada.
- **Contas só por convite.** Não há cadastro aberto. O administrador cria a conta, e a pessoa define a própria
  senha por um link de uso único:
  - o link vale 72 h;
  - fica no fragmento `#`, então não aparece em logs nem no cabeçalho Referer.
- **Acesso por município.** Cada conta tem a lista de municípios que pode ver, com papel `consulta` ou `gestor`;
  o administrador vê todos.
  - A checagem é uma dependência única em todas as rotas `/api/{código}/…`.
  - Município sem acesso e município inexistente dão a **mesma** resposta (404), para não revelar quais
    prefeituras usam o sistema.
- **Papéis:**
  - `consulta` vê o mapa e gera relatórios;
  - `gestor` também envia dados da prefeitura;
  - `admin` gerencia contas e vê o registro de atividade.

## Senhas e sessões

- **Senhas:**
  - guardadas com **Argon2id**, refeitas automaticamente se os parâmetros recomendados mudarem;
  - mínimo de 12 caracteres, recusando as óbvias e as que contêm o e-mail;
  - a verificação leva o mesmo tempo para e-mail existente e inexistente.
- **Sessão no servidor:**
  - o cookie leva um token aleatório de 256 bits, e o banco guarda só o hash dele;
  - cookie `HttpOnly`, `SameSite=Lax`, `Secure` e prefixo `__Host-` em produção;
  - expira com 12 h sem uso ou 7 dias no máximo;
  - trocar a senha, desativar a conta ou o admin clicar em "Desconectar" derruba todas as sessões.
- **Força bruta:**
  - 5 senhas erradas seguidas bloqueiam a conta por 15 min;
  - limite de 10 tentativas por minuto por IP;
  - a mensagem de erro é a mesma para e-mail inexistente e senha errada.

## Requisições forjadas e navegador

- **CSRF:** toda requisição que altera algo precisa do cabeçalho `X-CSRF: 1` **e** de `Origin` igual ao endereço do
  site. Formulários de outros sites não conseguem cumprir os dois.
- **Cabeçalhos:**
  - `Content-Security-Policy` restrita: só scripts do próprio site, já que o MapLibre é servido localmente, e mosaicos
    do OSM;
  - `frame-ancestors 'none'` e `X-Frame-Options: DENY` contra clickjacking;
  - `nosniff`, `Referrer-Policy`, `Permissions-Policy` e HSTS em produção;
  - `Cache-Control: no-store` nas respostas da API.
- **Saída escapada:** nomes de escolas, bairros e e-mails são escapados antes de entrar no HTML do mapa e do painel.

## Entradas pesadas ou não confiáveis

- **Upload do IPTU** (só gestor):
  - extensões e nomes de arquivo validados;
  - limite de tamanho (`MAPA_UPLOAD_MAX_MB`, padrão 200 MB), lido em blocos;
  - pasta temporária e, se o arquivo for válido, cópia para a pasta do município;
  - erros de leitura vão para o log do servidor, nunca para o navegador;
  - registrado na auditoria.
- **Relatório PDF:** uma geração por vez no servidor (`MAPA_PDF_SIMULTANEOS`), 10 por usuário por hora, tempo-limite
  no Chromium; o arquivo temporário é apagado depois do download.
- **Códigos de município:** validados como 7 dígitos antes de virar caminho de pasta (sem `../`).
- **Erros internos:** resposta genérica; o detalhe fica só no log.

## Servidor

- **Container sem root:** usuário 10001, sistema de arquivos **somente leitura** (exceto dados, banco e /tmp) e
  `no-new-privileges`.
- **Exposição:** o app não publica porta. Só o Caddy (80/443) fica exposto, com HTTPS automático e redirecionamento.
- **Arranque em produção:** o servidor se recusa a subir sem `https://` em `MAPA_URL_BASE`, sem cookie seguro ou com
  o banco numa pasta sincronizada.
- **Segredos:** só no `.env`, fora do git. O repositório tem `.gitignore` para `.env`, `*.db` e
  `dados/brutos/municipios/*/prefeitura/`.
- **Auditoria:** tabela `eventos` com:
  - logins, falhas e bloqueios;
  - contas criadas e editadas;
  - links gerados;
  - uploads;
  - relatórios.

  O admin vê o registro na tela de contas.
- **Testes automáticos:** `tests/test_acesso.py` cobre:
  - login, bloqueio e limite por IP;
  - CSRF e cabeçalhos;
  - convite de uso único;
  - isolamento entre municípios;
  - permissões de admin.

  O GitHub Actions roda os testes e sobe a imagem Docker a cada push.

## Limites conhecidos (decisões conscientes)

- **Um processo só:** os limites de taxa ficam em memória. Para escalar para vários processos, mova-os para o
  Redis ou o banco.
- **Banco sem migrações:** `create_all` cria as tabelas. Na primeira mudança de esquema, adote o Alembic.
- **Sem 2FA:** o segundo fator (TOTP) é o próximo passo natural se houver contas de administrador de várias
  prefeituras.
- **SMTP opcional:** sem ele, "esqueci a senha" orienta a pedir um link ao administrador.
