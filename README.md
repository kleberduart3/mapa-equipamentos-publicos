# Equicidade – Mapa de Déficit de Equipamentos Públicos

> **Equicidade** é o nome do produto: landing em `equicidade.com.br` ([`landing/`](landing/)), ferramenta em
> `mapa.equicidade.com.br`. Marca, cores e logos em [`marca/`](marca/); resumo, domínios e pendências em
> [`docs/equicidade.md`](docs/equicidade.md).

Ferramenta web para prefeituras que mapeia creches, escolas e unidades básicas de saúde
de responsabilidade municipal, cruza com a população por setor censitário e mostra no
mapa onde há gente sem atendimento. Municípios processados: **Arapiraca/AL** (piloto) e
**Palmeira dos Índios/AL**. Qualquer município brasileiro entra com um comando.

> **Status.** Etapas 1 a 5 e fase 2 concluídas, além de:
> - vários municípios ao mesmo tempo;
> - login com contas por prefeitura;
> - painel de administração;
> - empacotamento Docker para o servidor com HTTPS.
>
> Deploy: [`docs/implantacao.md`](docs/implantacao.md). Segurança: [`docs/seguranca.md`](docs/seguranca.md).

## Como usar

- **No servidor:** acesse o endereço do site e entre com e-mail e senha.
- **Contas:** quem cria as contas é o administrador. Ele escolhe quais municípios cada pessoa vê:
  - **consulta:** vê o mapa e gera relatórios;
  - **gestor:** também envia dados da prefeitura.
- **Senhas:** cada pessoa define a própria senha por um link de uso único. Ninguém digita a senha de outra pessoa.

### O que o mapa mostra
- **Fundo e seletor:** fundo OpenStreetMap e seletor de município (só os liberados para a conta).
- **Pins por tipo:** cor e ícone por tipo, com popup de matrículas/equipes, rede, bairro e raio. Contorno vermelho
  tracejado indica localização a confirmar.
- **Círculo de raio:** um por equipamento, na cor do tipo, com anéis concêntricos tipo radar (zona rural: raio × 3).
- **Déficit:** hexágonos vermelhos por tipo, ou **prioridade geral** (todos os tipos).
- **Radar pulsante:** marca as áreas sugeridas para novos equipamentos, na cor do tipo, numeradas por ordem.
- **Linha reta × A pé pelas ruas:** no modo a pé, o círculo vira a **mancha das ruas alcançáveis** dentro do raio.
  Indicadores, déficits, sugestões e prioridade passam a usar a distância caminhada.
- **Raio por tipo:** cada tipo tem seu controle de raio, e cobertura, déficit e sugestões são recalculados na hora.
- **Painel e legenda:** população, gente sem cobertura e % coberta por tipo; a legenda mostra o raio atual de cada tipo.
- **Relatório PDF:** usa os raios da tela e leva cerca de 40 s; um de cada vez no servidor.
- **Ranking de bairros:** os bairros com mais gente fora do raio, com o tempo médio a pé até a unidade mais próxima.
  Clicar num bairro aproxima o mapa; a lista sai em planilha CSV.
- **Setores do IBGE:** o déficit pode ser visto por setor censitário em vez de hexágonos. Clicar numa área mostra os
  números dela.
- **Simulador de nova unidade:** marque um ponto no mapa e veja quantas pessoas da faixa passariam a ter o equipamento
  no raio e como a cobertura do município muda. Arraste o marcador para comparar terrenos.
- **Tempo a pé:** cada raio aparece também em minutos (80 m por minuto, ajustável em `velocidade_caminhada_m_min`).
- **Upload do IPTU** (só gestor): aceita CSV com lat/long, GeoPackage, GeoJSON ou shapefile. Hoje só recebe e valida.

> Os mosaicos de tile.openstreetmap.org servem para desenvolvimento e demonstração. Para uso em produção
> com várias prefeituras, a [política de uso do OSM](https://operations.osmfoundation.org/policies/tiles/)
> pede um provedor de mosaicos próprio ou contratado (ex.: MapTiler, Stadia, Thunderforest).
> Basta preencher `MAPA_MOSAICOS_URL` no `.env`.

## Incluir um município

```
python backend/scripts/processar_municipio.py CÓDIGO_IBGE        # ex.: 2706307
```

O comando faz tudo, nesta ordem:
1. Cria `config/municipios/{código}.yaml`, com nome e UF tirados da API do IBGE.
2. Baixa as fontes.
3. Prepara os dados:
   - zona UTM estimada automaticamente;
   - escolas geocodificadas pelo CNEFE;
   - relatório de conferência.
4. Calcula a cobertura.
5. Baixa a malha a pé do OpenStreetMap.

Depois:
1. Leia `dados/saidas/{código}/checagem_dados.md`. Escolas e UBS com localização aproximada precisam ser
   conferidas com a prefeitura.
2. Libere o município para as contas no painel **Administrar contas**.

Parâmetros: [`config/parametros.yaml`](config/parametros.yaml) vale para todos os municípios. Qualquer chave pode
ser trocada para um município só, dentro de `parametros:` no YAML dele.

**Coordenadas das escolas.** Se existir `dados/brutos/municipios/{código}/inep_catalogo.tsv` (exportação manual do
Catálogo de Escolas do INEP, como em Arapiraca), ele tem prioridade. Sem ele, o endereço dos microdados do Censo
Escolar é localizado no CNEFE:
- pelo nome do estabelecimento de ensino no mesmo CEP;
- pelo nome muito parecido no município;
- pelo número de porta;
- pelo centro do CEP.

Contra o Catálogo de Arapiraca, essa geocodificação acerta a posição em 100 m em 57% das escolas, e a mediana do
erro é 42 m. Só o casamento de nome no mesmo CEP é tratado como preciso. Os demais vão para a lista de conferência:
em Arapiraca e em Palmeira dos Índios, mais da metade das escolas. **Sem o Catálogo, peça à prefeitura as coordenadas
das escolas** (ou exporte o Catálogo do INEP) antes de usar os números.

## 1. Stack

| Camada | Escolha | Por quê |
|---|---|---|
| Análise | **Python 3.12 + GeoPandas, Shapely 2, pyogrio, pyproj** | Padrão para dados geográficos em Python; lê shapefile, GeoPackage e CSV da prefeitura sem complicação. |
| Unidade de prioridade | **Hexágonos H3** | Grade regular, independente do desenho dos setores; boa para “onde pôr o próximo equipamento”. |
| Dados geográficos | **GeoParquet em arquivo**, por município | Sem servidor de banco para instalar; cada município em `dados/processados/{código}/`. |
| Contas e sessões | **SQLite** (SQLAlchemy) | Um arquivo, cópia de segurança simples; troca por PostgreSQL mudando `MAPA_DB_URL`. |
| API | **FastAPI** | Leve, com upload de arquivos e validação de entrada. |
| Senhas | **Argon2id** (argon2-cffi) | Algoritmo recomendado pela OWASP para guardar senhas. |
| Mapa | **MapLibre GL JS** (servido pelo próprio site) | Renderização vetorial em GPU, sem custo de licença e sem script de terceiros. |
| Distância caminhável | **OSMnx + SciPy (Dijkstra)** sobre a malha do OpenStreetMap | OSMnx baixa a malha de pedestres; o menor caminho sai do SciPy. |
| Relatório PDF | **HTML + Playwright (Chromium)** | Gera o PDF a partir de uma página HTML com o próprio mapa. |
| Servidor | **Docker + Caddy** | HTTPS automático (Let's Encrypt) no domínio; um comando para subir. |

## 2. Estrutura de pastas

```
Equipamentos Publicos/
├── config/
│   ├── parametros.yaml          # raios, faixas etárias, metas — padrão de todos os municípios
│   └── municipios/{código}.yaml # nome, UF e substituições de cada município
├── dados/                       # fora do git (exceto os .tsv do Catálogo do INEP)
│   ├── brutos/
│   │   ├── ibge/ inep/ cnes/    # arquivos nacionais, compartilhados
│   │   ├── uf/{UF}/             # malha de setores e equipes do CNES do estado
│   │   └── municipios/{código}/ # CNEFE, SIDRA, malha OSM e prefeitura/ (uploads)
│   ├── processados/{código}/    # dados limpos em GeoParquet
│   └── saidas/{código}/         # cobertura, conferência e relatórios
├── backend/
│   ├── app/
│   │   ├── acesso/              # login, sessões, contas, CSRF, cabeçalhos de segurança
│   │   ├── analise/             # cobertura, demanda × capacidade, prioridade, malha a pé
│   │   ├── ingestao/            # leitura e limpeza de cada fonte
│   │   ├── relatorio/           # template HTML e geração do PDF
│   │   ├── api/                 # rotas FastAPI
│   │   ├── servicos.py          # respostas do mapa por município (com cache)
│   │   └── config.py            # município, parâmetros e pastas
│   └── scripts/                 # processar_municipio.py e etapas avulsas
├── frontend/                    # mapa, login, definir senha e administração
├── tests/                       # pytest: acesso e regressão de Arapiraca
├── deploy/Caddyfile             # proxy HTTPS
├── Dockerfile  docker-compose.yml  .env.exemplo
├── docs/                        # fontes, implantação, segurança e equicidade.md
├── landing/                     # landing page estática (equicidade.com.br)
└── marca/                       # manual da marca, tokens.json e logos SVG
```

## 3. Fontes de dados

| Dado | Fonte | Observação |
|---|---|---|
| População por setor | IBGE – Censo 2022, agregados por setor + malha de setores | Faixas 0–3, 4–5, 6–10 e 11–14 estimadas a partir das quinquenais × idade simples do município (SIDRA 9514). |
| Endereços/domicílios | IBGE – **CNEFE 2022** (pontos com coordenadas) | Distribui a população *dentro* do setor e localiza escolas. |
| Escolas e creches | INEP – Censo Escolar (microdados) | Matrículas e endereço; coordenadas pelo Catálogo (se houver) ou CNEFE. |
| UBS e equipes | DATASUS – CNES | Estabelecimentos (nacional) e equipes (arquivo EP do estado, mais recente). |
| Cadastro imobiliário (opcional) | Prefeitura – IPTU em CSV ou shapefile | Upload pela ferramenta; refina densidade e aponta áreas em expansão. |
| Malha viária | OpenStreetMap | Distância caminhável. |

Detalhes e decisões: [`docs/fontes.md`](docs/fontes.md).

**Escopo municipal:** creche, pré-escola e ensino fundamental da rede municipal, e UBS.
O ensino médio (rede estadual) aparece só como camada de contexto, fora dos indicadores.

## 4. Etapas

1. **Plano e estrutura** ✅
2. **Coleta e limpeza** – fontes, recorte do município, GeoParquet em UTM, relatório de checagem. ✅
3. **Cálculo de cobertura** – população atendida e não atendida, demanda × capacidade, índice de prioridade. ✅
4. **Mapa** interativo. ✅
5. **Relatório PDF**. ✅
6. *(Fase 2)* **Distância caminhável** pela malha do OSM. ✅
   - **Malha:** pedestres do OpenStreetMap (OSMnx, vias `walk`), limite do município + 2 km.
   - **Ligação à malha:** cada endereço, equipamento e centro de hexágono é ligado à via mais próxima.
   - **Menor caminho:** Dijkstra (SciPy) entre as pontas das vias.
   - **Conferência:** nenhuma distância a pé pode ser menor que a linha reta.
7. **Vários municípios, login e servidor** ✅. Ver [`docs/implantacao.md`](docs/implantacao.md).

## 5. Cuidados de método

- **População uniforme no setor + raio simples distorce o resultado**, principalmente em
  setores rurais grandes. Refinamento adotado:
  1. distribuir a população do setor pelos pontos de endereço residencial do **CNEFE**
     (método dasimétrico) e, quando houver, pelo cadastro do IPTU;
  2. tratar setores rurais à parte (fator de raio, e depois tempo de deslocamento).
- **Distância a pé depende da qualidade do OpenStreetMap**:
  - rua ou atalho que falta no mapa aumenta a distância;
  - via mapeada mas intransitável a diminui;
  - não considera relevo, calçadas nem travessias perigosas.
- **Escolas geocodificadas pelo CNEFE** (municípios sem o Catálogo do INEP): confira a lista do relatório de
  checagem com a Secretaria de Educação antes de usar os números em processo oficial.
- Os raios e metas em `config/parametros.yaml` são **padrões iniciais a revisar**; cada valor
  tem um campo `fonte` para registrar a referência adotada.
- Capacidade escolar usa **matrículas** como aproximação até haver dado de vagas.

## 6. Desenvolvimento (Windows)

1. Instale o **Miniforge** (<https://github.com/conda-forge/miniforge>) e, nesta pasta:
   ```
   conda env create -f environment.yml
   conda activate equipamentos
   playwright install chromium

   ```
2. Crie o administrador local e abra o link que aparecer:
   ```
   python -m backend.app.acesso.cli criar-admin voce@exemplo.com "Seu Nome"
   uvicorn backend.app.api.main:app --port 8000
   ```
   O banco de contas fica em `%USERPROFILE%\.mapa-equipamentos\app.db`, fora do Google Drive: a sincronização
   corrompe SQLite.
3. Testes:
   ```
   python -m pytest -m "not lento"   # acesso, CSRF, sessões (segundos)
   python -m pytest -m lento         # regressão: números de Arapiraca (minutos; precisa dos dados)
   ```

Neste computador o Miniforge está em `C:\Users\Public\miniforge3`, porque o nome de usuário tem acento e isso quebra
o conda. **Sempre ative o ambiente** antes de rodar: chamar o `python.exe` do ambiente direto faz o Windows carregar
DLLs de outros programas.

**Projeto dentro do Google Drive.** O ambiente conda e o banco de contas ficam fora da pasta. Os dados brutos são
grandes: o ideal é marcar `dados/brutos` para não sincronizar.

### Versão estática (sem login)

Os scripts abaixo geram uma cópia do mapa de **um** município que funciona sem servidor:
- `backend/scripts/exportar_estatico.py --municipio CÓDIGO` gera a pasta `site/`;
- `exportar_html_unico.py` gera um único arquivo HTML.

**Essas cópias não têm login.** Quem tiver os arquivos vê tudo. Use só com autorização da prefeitura.
