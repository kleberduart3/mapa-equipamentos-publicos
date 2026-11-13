# Mapa de Déficit de Equipamentos Públicos

Ferramenta web para prefeituras que mapeia creches, escolas e unidades básicas de saúde
de responsabilidade municipal, cruza com a população por setor censitário e mostra no
mapa onde há gente sem atendimento. Município piloto: **Arapiraca/AL**.

> Status: **Etapas 1 a 5 e fase 2 concluídas** para Arapiraca (mapa interativo, relatório PDF e distância a pé pelas ruas).
> Relatório: botão **Exportar relatório PDF** no mapa (usa os raios da tela) ou
> `python backend/scripts/gerar_relatorio.py [--creche 600 ...]` → `dados/saidas/relatorio_<municipio>_<data>.pdf`.
> O relatório tem resumo com achados e mapa de prioridade, uma página por equipamento (mapa sobre
> OpenStreetMap, raios, déficit, áreas sugeridas), metodologia, sensibilidade ao raio e dados a confirmar.
> Requer `playwright install chromium` uma vez. `--modo rede` gera o relatório com distância a pé (`..._a_pe.pdf`).
>
> Fase 2 – distância a pé: `python backend/scripts/preparar_rede.py` (baixa a malha de pedestres do OSM, uma vez) e
> `python backend/scripts/comparar_distancias.py` → `dados/saidas/comparacao_distancias.md` (linha reta × a pé).
>
> Etapa 4 – mapa interativo:
> Abrir o mapa (ambiente ativado, na raiz do projeto):
> `uvicorn backend.app.api.main:app --port 8000` e acessar <http://localhost:8000>.
> Cobertura: `dados/saidas/resumo_cobertura.md` · dados: `dados/saidas/checagem_dados.md`, `docs/fontes.md`.

### Versão online (GitHub Pages)

<https://kleberduart3.github.io/mapa-equipamentos-publicos/> — versão estática, sem servidor Python: os resultados
foram pré-calculados para raios de 200 a 3.000 m em passos de 100 m, em linha reta e a pé. O PDF baixado é o
relatório pronto com os raios padrão; o upload do IPTU só funciona na versão local.

Para atualizar depois de mudar dados ou parâmetros:
```
python backend/scripts/exportar_estatico.py   # gera a pasta site/ (~15 min)
git add site && git commit -m "Atualiza site" && git push
```
O GitHub Actions (`.github/workflows/pages.yml`) publica a pasta `site/` a cada push.

### O que o mapa mostra
- Fundo **OpenStreetMap**; seletor de município (hoje só Arapiraca).
- **Pins** por tipo (cor e ícone), com popup de matrículas/equipes, rede, bairro e raio. Contorno vermelho
  tracejado = localização a confirmar.
- **Círculo de raio** de cada equipamento na cor do tipo, com anéis concêntricos tipo radar (zona rural: raio × 3).
- **Déficit** em hexágonos vermelhos (por tipo) ou **prioridade geral** (todos os tipos).
- **Radar pulsante** nas áreas sugeridas para novos equipamentos, na cor do tipo, numerado por ordem.
- Seletor **Linha reta × A pé pelas ruas**: no modo a pé, o círculo vira a **mancha das ruas alcançáveis** dentro do raio
  e todos os indicadores, déficits, sugestões e a prioridade passam a usar a distância caminhada.
- Controles de **raio** por tipo: recalculam cobertura, déficit e sugestões na hora.
- Painel com população, gente sem cobertura e % coberta por tipo; legenda com o raio atual de cada tipo.
- Upload do cadastro do IPTU (CSV com lat/long, GeoPackage, GeoJSON ou shapefile): hoje só recebe e valida.

> Os mosaicos de tile.openstreetmap.org servem para desenvolvimento e demonstração. Para uso em produção
> com várias prefeituras, a política de uso do OSM exige um provedor de mosaicos próprio ou contratado.

---

## 1. Stack

| Camada | Escolha | Por quê |
|---|---|---|
| Análise | **Python 3.12 + GeoPandas, Shapely 2, pyogrio, pyproj** | Padrão para dados geográficos em Python; lê shapefile, GeoPackage e CSV da prefeitura sem complicação. |
| Unidade de prioridade | **Hexágonos H3** | Grade regular, independente do desenho dos setores; boa para “onde pôr o próximo equipamento”. |
| Armazenamento (piloto) | **GeoParquet / GeoPackage em arquivo** | Sem servidor de banco para instalar. **PostGIS** entra quando houver vários municípios e usuários. |
| API | **FastAPI** | Leve, com upload de arquivos e documentação automática. |
| Mapa | **MapLibre GL JS** | Renderização vetorial em GPU: coroplético, hexágonos e calor mais fluidos que no Leaflet, e sem custo de licença. Leaflet seria mais simples, mas sofre com milhares de polígonos. |
| Distância caminhável (fase 2) | **OSMnx + SciPy (Dijkstra)** sobre a malha do OpenStreetMap | OSMnx baixa a malha de pedestres; o menor caminho sai do SciPy, que já está no ambiente (o pandana não foi necessário). |
| Relatório PDF | **HTML + Playwright (Chromium)** | Gera o PDF a partir de uma página HTML com o próprio mapa; funciona no Windows sem as dependências GTK que o WeasyPrint exige. |

## 2. Estrutura de pastas

```
Equipamentos Publicos/
├── README.md
├── environment.yml          # ambiente conda (conda-forge)
├── config/
│   └── parametros.yaml      # raios, faixas etárias, metas — EDITÁVEL, "a revisar"
├── dados/
│   ├── brutos/              # arquivos como baixados, sem alteração
│   │   ├── ibge/            # malha de setores + agregados do Censo 2022, CNEFE
│   │   ├── inep/            # Censo Escolar (microdados / catálogo de escolas)
│   │   ├── cnes/            # estabelecimentos e equipes de saúde
│   │   ├── prefeitura/      # uploads: cadastro do IPTU (CSV/shapefile)
│   │   └── osm/             # malha viária (fase 2)
│   ├── processados/         # dados limpos, recortados para o município, em GeoParquet
│   └── saidas/              # resultados de cobertura, déficit e relatórios PDF
├── backend/
│   ├── app/
│   │   ├── ingestao/        # download, leitura e limpeza de cada fonte
│   │   ├── analise/         # cobertura, demanda × capacidade, prioridade
│   │   ├── relatorio/       # template HTML e geração do PDF
│   │   └── api/             # endpoints FastAPI (camadas, indicadores, upload)
│   ├── scripts/             # rotinas de linha de comando (ex.: preparar_arapiraca.py)
│   └── tests/
├── frontend/                # página do mapa (MapLibre) — HTML/JS/CSS estático
│   ├── js/  css/  assets/
├── notebooks/               # explorações e conferência dos dados
└── docs/                    # metodologia, fontes e decisões
```

## 3. Fontes de dados

| Dado | Fonte | Observação (conferir na Etapa 2) |
|---|---|---|
| População por setor | IBGE – Censo 2022, agregados por setor + malha de setores | Confirmar se as **faixas etárias** (0–3, 4–5, 6–10, 11–14) estão publicadas no nível de setor ou se será preciso estimar. |
| Endereços/domicílios | IBGE – **CNEFE 2022** (pontos com coordenadas) | Usado para distribuir a população *dentro* do setor (ver §5). |
| Escolas e creches | INEP – Censo Escolar | Confirmar se as coordenadas vêm nos microdados ou no Catálogo de Escolas; geocodificar o que faltar. Filtrar **dependência municipal**. |
| UBS e equipes | DATASUS – CNES | Lat/long do CNES costuma ter falhas; prever conferência e geocodificação. Filtrar tipo UBS/Posto e gestão municipal. |
| Cadastro imobiliário (opcional) | Prefeitura – IPTU em CSV ou shapefile | Upload pela ferramenta; refina densidade e aponta áreas em expansão. |
| Malha viária (fase 2) | OpenStreetMap | Distância caminhável. |

**Escopo municipal:** creche, pré-escola e ensino fundamental da rede municipal, e UBS.
O ensino médio (rede estadual) aparece só como camada de contexto, fora dos indicadores.

## 4. Etapas

1. **Plano e estrutura** – este documento, `parametros.yaml`, ambiente. ✅
2. **Coleta e limpeza – Arapiraca** – baixar as fontes, recortar o município, padronizar
   em GeoParquet (SIRGAS 2000 / UTM 24S), conferir coordenadas e gerar relatório de checagem. ✅
3. **Cálculo de cobertura** – por setor (e por hexágono): população atendida e não atendida
   por tipo de equipamento; demanda por faixa etária × capacidade (matrículas, equipes);
   índice de prioridade.
4. **Mapa** – fundo OpenStreetMap; seletor de município; **pins com a localização de cada
   equipamento** (ícone e cor por tipo, popup com nome, matrículas/equipes e origem da
   coordenada); **círculo do raio de atendimento de cada equipamento na cor do seu tipo**
   (a mesma cor da legenda, com anéis concêntricos tipo radar); **marcador de radar pulsante
   nas áreas deficitárias** (gente fora de qualquer raio ou com capacidade insuficiente),
   na cor do equipamento que falta; camadas liga/desliga por tipo, coroplético do déficit, painel de indicadores,
   áreas prioritárias destacadas, upload do cadastro da prefeitura.
5. **Relatório PDF** – mapa, indicadores e metodologia, pronto para anexar a processos. ✅
6. *(Fase 2)* **Distância caminhável** pela malha do OSM no lugar do raio simples. ✅
   Malha de pedestres do OpenStreetMap (OSMnx, vias `walk`, limite do município + 2 km). Cada endereço do CNEFE,
   equipamento e centro de hexágono é ligado à via mais próxima; menor caminho por Dijkstra (SciPy) entre as pontas
   das vias. Conferência automática: nenhuma distância a pé pode ser menor que a linha reta. O modo que abre por
   padrão é `distancia_padrao` em `config/parametros.yaml` — hoje **a pé** (`rede`); o relatório por script também usa esse padrão.

## 5. Cuidados de método

- **População uniforme no setor + raio simples distorce o resultado**, principalmente em
  setores rurais grandes (Arapiraca tem extensa zona rural). Caminho de refinamento:
  1. distribuir a população do setor pelos pontos de endereço residencial do **CNEFE**
     (método dasimétrico) e, quando houver, pelo cadastro do IPTU;
  2. tratar setores rurais à parte (fator de raio, e depois tempo de deslocamento).
- **Distância a pé depende da qualidade do OpenStreetMap**: rua ou atalho que falta no mapa aumenta a distância;
  via mapeada mas intransitável a diminui. Em Arapiraca, 90% dos moradores estão a até 11 m (urbano) e 32 m (rural)
  de uma via mapeada. Não considera relevo, calçadas nem travessias perigosas.
- Os raios e metas em `config/parametros.yaml` são **padrões iniciais a revisar**; cada valor
  tem um campo `fonte` para registrar a referência adotada.
- Capacidade escolar usa **matrículas** como aproximação até haver dado de vagas.

## 6. Instalação (Windows)

1. Instale o **Miniforge** (distribuição do conda com o canal conda-forge):
   <https://github.com/conda-forge/miniforge> — é a forma mais estável de ter GeoPandas no Windows.
2. No *Miniforge Prompt*, dentro desta pasta:
   ```
   conda env create -f environment.yml
   conda activate equipamentos
   playwright install chromium
   ```

Neste computador o Miniforge está em `C:\Users\Public\miniforge3` (o nome de usuário tem
acento, o que quebra o conda). **Sempre ative o ambiente** antes de rodar: chamar o
`python.exe` do ambiente direto faz o Windows carregar DLLs de outros programas e o
matplotlib/GDAL falham.

### Rodar a preparação dos dados

```
conda activate equipamentos
python backend/scripts/baixar_dados.py        # baixa as fontes públicas
python backend/scripts/preparar_municipio.py  # gera dados/processados/*.parquet e a checagem
python backend/scripts/preparar_rede.py       # fase 2: malha de pedestres do OpenStreetMap
```

O Catálogo de Escolas do INEP é exportado à mão pelo portal inepdata (ver `docs/fontes.md`).

### Atenção: projeto dentro do Google Drive

A pasta está em `G:\Meu Drive`. O ambiente conda **não** deve ficar aqui (milhares de
arquivos pequenos sincronizando = lentidão e risco de corrupção) — o `conda env create`
acima já instala fora, na pasta do Miniforge. Os dados brutos (malhas, CNEFE) também são
grandes: o ideal é apontar `dados/` para uma pasta local fora do Drive, ou marcar
`dados/brutos` para não sincronizar.
