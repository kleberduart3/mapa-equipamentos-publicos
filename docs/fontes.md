# Fontes de dados e decisões da Etapa 2

Data da coleta: 12/11/2026. Município piloto: Arapiraca/AL (IBGE 2700300).

| Dado | Arquivo em `dados/brutos/` | Origem | Observações |
|---|---|---|---|
| Malha de setores + população total | `uf/{UF}/setores.gpkg` | IBGE – Censo 2022, *malha com atributos* (UF) | 427 setores; v0001 = moradores. |
| Faixas etárias por setor | `ibge/agregados_demografia_BR.zip` | IBGE – Agregados por setor, Demografia | Só faixas **quinquenais** (0–4, 5–9, 10–14, 15–19). |
| Idade simples do município | `municipios/{código}/sidra_9514.json` | SIDRA, tabela 9514 | Usada para quebrar as faixas quinquenais em 0–3, 4–5, 6–10, 11–14, 15–17. |
| Endereços com coordenadas | `municipios/{código}/cnefe.zip` | IBGE – CNEFE 2022 | 120 mil endereços; 96 mil residenciais. |
| Área domiciliada dos setores | `ibge/area_domiciliada_setores.xlsx` | IBGE | Baixado, ainda não usado (o CNEFE cobre a função). |
| Escolas com coordenadas | `municipios/{código}/inep_catalogo.tsv` (opcional) | INEP – Catálogo de Escolas (portal inepdata) | Exportado do portal filtrando Município = Arapiraca; mantidas só as públicas. **Passo manual** (o portal não tem API). |
| Endereços das escolas sem coordenada | `municipios/{código}/inep_enderecos.tsv` (opcional) | idem | Usado para geocodificar pelo CNEFE. |
| Matrículas por etapa | `inep/microdados_censo_escolar_2024.zip` | INEP – Microdados do Censo Escolar 2024 | Ano mais recente publicado no endereço padrão. |
| Estabelecimentos de saúde | `cnes/cnes_estabelecimentos_BR.zip` | Ministério da Saúde – dados abertos CNES | A API por município devolveu lista incompleta (40 de 471); usamos o arquivo nacional. |
| Equipes de saúde | `uf/{UF}/cnes_EP{UF}{AAMM}.dbc` | DATASUS FTP – CNES/EP, competência mais recente (baixada automaticamente) | Contadas eSF (tipo 70) e eAP (76) ativas. `DT_DESAT = 900001` = ativa. |
| Malha viária de pedestres | `municipios/{código}/osm_malha_pe.graphml` | OpenStreetMap via Overpass API (OSMnx `network_type="walk"`), baixada em 12/11/2026 | Limite do município + 2 km. 2.137 km de vias. Licença ODbL: citar “© OpenStreetMap contributors”. |

Os números de setores, endereços e km de vias acima são de Arapiraca. O relatório de cada município
fica em `dados/saidas/{código}/checagem_dados.md`.

**Escolas sem o Catálogo (demais municípios).** O endereço do microdado do Censo Escolar
(`DS_ENDERECO`, `NU_ENDERECO`, `NO_BAIRRO`, `CO_CEP`) é localizado no CNEFE, em ordem de confiança:
1. estabelecimento de ensino do mesmo CEP com nome parecido (semelhança ≥ 0,5, com palavras raras
   pesando mais, ou o nome do CNEFE inteiro contido no da escola). Este é o único caso tratado como preciso;
2. nome muito parecido em qualquer CEP do município (≥ 2 palavras e semelhança ≥ 0,6);
3. mesmo CEP e número de porta;
4. centro do CEP.

Os casos 2 a 4 e os sem coordenada vão para a conferência. Testado contra o Catálogo de Arapiraca:
- mediana do erro de 42 m e 57% das escolas a até 100 m;
- 13% das escolas a mais de 1 km, quase todas rurais com endereço genérico ("Povoado X, S/N").

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
