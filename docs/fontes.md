# Fontes de dados e decisões da Etapa 2

Data da coleta: 12/11/2026. Município piloto: Arapiraca/AL (IBGE 2700300).

| Dado | Arquivo em `dados/brutos/` | Origem | Observações |
|---|---|---|---|
| Malha de setores + população total | `ibge/setores_uf.gpkg` | IBGE – Censo 2022, *malha com atributos* (UF) | 427 setores; v0001 = moradores. |
| Faixas etárias por setor | `ibge/agregados_demografia_BR.zip` | IBGE – Agregados por setor, Demografia | Só faixas **quinquenais** (0–4, 5–9, 10–14, 15–19). |
| Idade simples do município | `ibge/sidra_9514_idade_simples.json` | SIDRA, tabela 9514 | Usada para quebrar as faixas quinquenais em 0–3, 4–5, 6–10, 11–14, 15–17. |
| Endereços com coordenadas | `ibge/cnefe_municipio.zip` | IBGE – CNEFE 2022 | 120 mil endereços; 96 mil residenciais. |
| Área domiciliada dos setores | `ibge/area_domiciliada_setores.xlsx` | IBGE | Baixado, ainda não usado (o CNEFE cobre a função). |
| Escolas com coordenadas | `inep/catalogo_escolas_arapiraca_publicas.tsv` | INEP – Catálogo de Escolas (portal inepdata) | Exportado do portal filtrando Município = Arapiraca; mantidas só as públicas. **Passo manual** (o portal não tem API). |
| Endereços das escolas sem coordenada | `inep/escolas_sem_coordenadas_enderecos.tsv` | idem | Usado para geocodificar pelo CNEFE. |
| Matrículas por etapa | `inep/microdados_censo_escolar_2024.zip` | INEP – Microdados do Censo Escolar 2024 | Ano mais recente publicado no endereço padrão. |
| Estabelecimentos de saúde | `cnes/cnes_estabelecimentos_BR.zip` | Ministério da Saúde – dados abertos CNES | A API por município devolveu lista incompleta (40 de 471); usamos o arquivo nacional. |
| Equipes de saúde | `cnes/EPAL2609.dbc` | DATASUS FTP – CNES/EP, competência 09/2026 | Contadas eSF (tipo 70) e eAP (76) ativas. `DT_DESAT = 900001` = ativa. |
| Malha viária de pedestres | `osm/malha_pe_2700300.graphml` | OpenStreetMap via Overpass API (OSMnx `network_type="walk"`), baixada em 12/11/2026 | Limite do município + 2 km. 2.137 km de vias. Licença ODbL: citar “© OpenStreetMap contributors”. |

## Decisões de tratamento

- **Faixas etárias:** população da faixa no setor = Σ (faixa quinquenal do setor × fração dessa faixa que cai na idade-alvo, segundo a idade simples do município). Hipótese: a pirâmide etária dentro de cada faixa é igual em todos os setores. Erro total contra o SIDRA: −0,2%.
- **Endereços → setor:** o CNEFE traz códigos de setor *preliminares* (sufixo P), renumerados na malha final. O setor de cada endereço é obtido pela posição do ponto (junção espacial).
- **Conferência das transcrições:** os dois TSV do INEP foram conferidos contra a exportação original
  pelo SHA-256 de `codigo_inep|latitude|longitude` (117 linhas) e `codigo_inep|endereço` (30 linhas). Os
  hashes são idênticos.
- **Coordenadas faltantes de escolas** (29 de 96 municipais), em ordem de confiança:
  1. estabelecimento de ensino do CNEFE **no mesmo CEP com nome conferido**: aceito (10 casos);
  2. estabelecimento de ensino com nome parecido em outro CEP: **conferir** (pode ser homônimo);
  3. mesmo CEP + mesmo número de porta: **conferir**;
  4. centroide dos endereços do CEP: aproximado, **conferir**;
  5. CEP genérico (…-899, …-970): sem coordenada, **conferir**.
- **Equipes em UBS fora do cadastro aberto:** duas UBS com equipes ativas no arquivo EP (CNES 5747872
  Agreste e 5802911 Planalto II) não aparecem no arquivo aberto de estabelecimentos. Foram incluídas
  com localização pelo CEP, quando possível.
- **UBS:** CNES tipos 1 e 2, gestão municipal; excluídas Unidades de Acolhimento, presídio e ambulatório de saúde mental.
- **Distância a pé (fase 2):** cada ponto é ligado à via mais próxima (trecho em linha reta até ela) e segue pela via; menor caminho por Dijkstra. Ida e volta e vias paralelas entre os mesmos nós: fica a mais curta. Sem mão de direção (pedestre). Conferido que nenhuma distância a pé é menor que a linha reta.
- **Rede de responsabilidade municipal:** escolas com dependência Municipal; estaduais e federais ficam como contexto.

## Pendências para a prefeitura

1. Confirmar a localização das 14 escolas listadas em `dados/saidas/checagem_dados.md`.
2. **UBS Poção (CNES 3047113):** a coordenada do CNES cai 3,7 km fora do limite municipal. Conferir.
3. **UBS Agreste (CNES 5747872)** sem localização e **UBS Planalto II (5802911)** só com o centro do CEP.
4. Fornecer vagas reais de creche, se houver (hoje usamos matrículas).
