"""Catálogo das fontes de dados: de onde vem cada arquivo, a página oficial de referência
e para que a ferramenta usa. Usado pela pasta de conferência (scripts/fontes_conferencia.py)
e pela seção "Fontes" do relatório PDF (links clicáveis).
"""
from __future__ import annotations

IBGE_SET = "https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios"
CNEFE_FTP = ("https://ftp.ibge.gov.br/Cadastro_Nacional_de_Enderecos_para_Fins_Estatisticos/"
             "Censo_Demografico_2022/Arquivos_CNEFE/CSV")
GEOFTP = ("https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/"
          "malhas_de_setores_censitarios__divisoes_intramunicipais/censo_2022")
DATASUS_FTP = "ftp://ftp.datasus.gov.br/dissemin/publicos/CNES/200508_"

# Páginas oficiais (para o leitor do relatório conferir). As do ibge.gov.br bloqueiam
# robôs (403), mas abrem normalmente no navegador.
PAGINAS = {
    "censo2022": "https://www.ibge.gov.br/estatisticas/sociais/populacao/22827-censo-demografico-2022.html",
    "agregados_ftp": f"{IBGE_SET}/",
    "sidra9514": "https://sidra.ibge.gov.br/tabela/9514",
    "cnefe": "https://www.ibge.gov.br/estatisticas/sociais/populacao/38734-cadastro-nacional-de-enderecos-para-fins-estatisticos.html",
    "cnefe_ftp": f"{CNEFE_FTP}/",
    "censo_escolar": "https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/microdados/censo-escolar",
    "catalogo_escolas": "https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/inep-data/catalogo-de-escolas",
    "cnes": "https://opendatasus.saude.gov.br/dataset/cnes-cadastro-nacional-de-estabelecimentos-de-saude",
    "cnes_ftp": f"{DATASUS_FTP}/",
    # navegadores não abrem mais ftp://: no PDF vai a página de transferência de arquivos do DATASUS
    "cnes_transferencia": "https://datasus.saude.gov.br/transferencia-de-arquivos/",
    "cnes_consulta": "https://cnes.datasus.gov.br/",
    "osm": "https://www.openstreetmap.org/copyright",
}

# Fontes como aparecem no relatório PDF (ordem de leitura)
REFERENCIAS = [
    {"orgao": "IBGE", "titulo": "Censo Demográfico 2022 – agregados e malha por setor censitário",
     "uso": "população por setor e por faixa de idade", "links": [("página do Censo 2022", PAGINAS["censo2022"]),
                                                                  ("arquivos (FTP)", PAGINAS["agregados_ftp"])]},
    {"orgao": "IBGE", "titulo": "SIDRA, tabela 9514 – população por idade simples (Censo 2022)",
     "uso": "dividir as faixas de 5 anos em 0–3, 4–5, 6–10 e 11–14", "links": [("tabela 9514", PAGINAS["sidra9514"])]},
    {"orgao": "IBGE", "titulo": "CNEFE 2022 – Cadastro Nacional de Endereços para Fins Estatísticos",
     "uso": "onde as pessoas moram dentro do setor; localização de escolas", "links": [("página do CNEFE", PAGINAS["cnefe"]),
                                                                                      ("arquivos (FTP)", PAGINAS["cnefe_ftp"])]},
    {"orgao": "INEP", "titulo": "Microdados do Censo Escolar 2024",
     "uso": "escolas, rede, endereço e matrículas por etapa", "links": [("microdados", PAGINAS["censo_escolar"])]},
    {"orgao": "Ministério da Saúde", "titulo": "CNES – Cadastro Nacional de Estabelecimentos de Saúde",
     "uso": "UBS e postos (estabelecimentos) e equipes de Saúde da Família", "links": [("dados abertos", PAGINAS["cnes"]),
                                                                                     ("consulta CNES", PAGINAS["cnes_consulta"]),
                                                                                     ("arquivos de equipes (DATASUS)", PAGINAS["cnes_transferencia"])]},
    {"orgao": "OpenStreetMap", "titulo": "Ruas e caminhos de pedestres (© OpenStreetMap contributors, ODbL)",
     "uso": "distância e tempo a pé pelas ruas; mapa de fundo", "links": [("licença e créditos", PAGINAS["osm"])]},
]

# Documentação oficial baixada para a pasta de conferência (uma vez, compartilhada).
# tipo "url": download direto; "ftp": DATASUS; "zip": extraído sem alteração de um arquivo já baixado.
DOCUMENTOS = [
    {"arquivo": "IBGE_dicionario_agregados_por_setores_2022.xlsx", "tipo": "url",
     "url": f"{IBGE_SET}/dicionario_de_dados_agregados_por_setores_censitarios_20260520.xlsx",
     "descricao": "Dicionário de dados dos agregados por setor (variáveis V01006, V01031… usadas na população por idade)"},
    {"arquivo": "IBGE_dicionario_malha_com_atributos.xlsx", "tipo": "url",
     "url": f"{IBGE_SET}/malha_com_atributos/Dicionario_de_dados_malha_agregados.xlsx",
     "descricao": "Dicionário da malha de setores com atributos (v0001 = moradores, situação urbana/rural, bairro)"},
    {"arquivo": "IBGE_dicionario_CNEFE_2022.xls", "tipo": "url", "url": f"{CNEFE_FTP}/Dicionario_CNEFE_Censo_2022.xls",
     "descricao": "Dicionário do CNEFE 2022 (espécie do endereço, coordenadas, nível de precisão)"},
    {"arquivo": "IBGE_leia-me_area_efetivamente_ocupada.pdf", "tipo": "url",
     "url": f"{GEOFTP}/Leia_me_Area_efetivamente_ocupada.pdf",
     "descricao": "Nota do IBGE sobre a área efetivamente domiciliada dos setores"},
    {"arquivo": "INEP_leia-me_microdados_censo_escolar_2024.pdf", "tipo": "zip", "zip": "inep/microdados_censo_escolar_2024.zip",
     "membro": "leia-me/Leia-me.pdf", "url": "https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_2024.zip",
     "descricao": "Leia-me oficial dos microdados do Censo Escolar 2024"},
    {"arquivo": "INEP_dicionario_dados_educacao_basica_2024.xlsx", "tipo": "zip", "zip": "inep/microdados_censo_escolar_2024.zip",
     "membro": "dicionário_dados_educação_básica.xlsx", "url": "https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_2024.zip",
     "descricao": "Dicionário de dados da educação básica (QT_MAT_INF_CRE, TP_DEPENDENCIA…)"},
    {"arquivo": "INEP_questionario_escola_2024.pdf", "tipo": "zip", "zip": "inep/microdados_censo_escolar_2024.zip",
     "membro": "Escola 2024.pdf", "url": "https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_2024.zip",
     "descricao": "Questionário da escola no Censo Escolar 2024"},
    {"arquivo": "INEP_md5_microdados_2024.txt", "tipo": "zip", "zip": "inep/microdados_censo_escolar_2024.zip",
     "membro": "md5_microdados_ed_basica_2024.txt", "url": "https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_2024.zip",
     "descricao": "Soma MD5 publicada pelo INEP para conferir o arquivo de microdados"},
    {"arquivo": "DATASUS_informe_tecnico_CNES_IT_CNES_1706.pdf", "tipo": "ftp",
     "url": f"{DATASUS_FTP}/Doc/IT_CNES_1706.pdf",
     "descricao": "Informe técnico do DATASUS com o layout dos arquivos do CNES (inclui o arquivo de equipes EP)"},
]
