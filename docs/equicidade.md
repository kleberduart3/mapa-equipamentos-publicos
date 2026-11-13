# Equicidade – marca, landing page e domínio

A ferramenta passa a se chamar **Equicidade** (equidade + cidade). Identidade visual e landing page foram feitas numa
sessão de chat do Claude em 12–13/11/2026 e trazidas para este repositório em 13/11/2026. **Daqui em diante, a fonte
oficial é este repositório**; os artefatos no claude.ai ficam como referência visual.

## O que veio e onde está

| Item | No repositório | Origem (claude.ai) |
|---|---|---|
| Landing page pronta (HTML/CSS/JS, favicons, imagem de compartilhamento) | [`landing/`](../landing/) | [Equicidade · site](https://claude.ai/artifact/8xxCFJw23kUiJhmZAZ5owL) |
| Manual da marca (texto): símbolo, versões, cores, tipografia, tom de voz, padrão gráfico, ícones | [`marca/README.md`](../marca/README.md) | [Design system Equicidade](https://claude.ai/artifact/9ctwzqbxUYvVtfyqXbmeJn) |
| Tokens (cores claro/escuro, tipos, espaçamentos, raios, sombras) | [`marca/tokens.json`](../marca/tokens.json) | idem |
| Logos em SVG: horizontal, horizontal negativa, vertical, wordmark, símbolo, símbolo branco, ícone de app | [`marca/logos/`](../marca/logos/) | idem |
| Manual visual (capa, marca, proteção e usos, cores, tipografia, padrão e ícones, papelaria, digital) e a landing desenhada | só no claude.ai | [Identidade visual e landing page](https://claude.ai/artifact/4jiewLmfjhEZFnB7USbWHC) |
| Exploração: 10 propostas de logo | só no claude.ai | [10 propostas de logo](https://claude.ai/artifact/QxGL2HYCExVfaj7CoHy6kV) |

Decisão registrada no design system: identidade criada a partir da **proposta 16, paleta 03**.

Os artefatos do manual visual são desenhos no editor do claude.ai (usam o runtime de lá e imagens hospedadas lá) e
não rodam fora dele: não foram copiados.

## Resumo da marca

Detalhes e regras de uso: [`marca/README.md`](../marca/README.md).

- **Símbolo:** curvas de nível irregulares (isócronas) em volta de um ponto coral. O ponto é o equipamento, o miolo
  azul é a área bem atendida e o anel claro é o limite da cobertura.
- **Nome:** sempre em minúsculas, com **equi** em negrito e **cidade** em peso médio. No texto corrido, escreve-se
  "Equicidade".
- **Cores:**

  | Nome | Hex | Papel |
  |---|---|---|
  | azul-500 | #2F4BFF | marca, botões, links |
  | azul-900 | #0D1450 | texto e fundos escuros |
  | coral-500 | #FF6B57 | só ponto de atenção e déficit; nunca texto sobre claro (usar coral-700 #C93A27) |
  | azul-200 | #A9B6FF | área atendida nos mapas |
  | névoa | #F5F6FB | fundo (no lugar do branco puro) |

  Proporção sugerida nas peças: 60% névoa e branco, 25% azul-900, 12% azul-500 e 3% coral.
- **Tipografia:** Instrument Sans (títulos 600/700 e texto 400) e IBM Plex Mono para números e dados, ambas do
  Google Fonts.
- **Tom:** direto, com dados concretos e sem jargão de tecnologia. Exemplo: "o bairro Primavera tem 1.200 crianças e
  nenhuma creche a menos de 1 km".

## Domínios

| Endereço | O quê | Servido por |
|---|---|---|
| `equicidade.com.br` (e `www.`, que redireciona) | landing page | Caddy, arquivos de `landing/` |
| `mapa.equicidade.com.br` | a ferramenta (login, mapa, API) | Caddy → container `app` |

DNS: dois registros **A** (e **AAAA** se houver IPv6) apontando para a VPS:
- `equicidade.com.br`;
- `mapa.equicidade.com.br`.

Opcionalmente, `www.equicidade.com.br`. O botão "Entrar" da landing já aponta para `https://mapa.equicidade.com.br/`.

**Formulário de demonstração:** não envia nada ao servidor. Ele abre o WhatsApp `(82) 98818-9617` com os dados
preenchidos (`landing/assets/js/main.js`).

## Promessas da landing × o que a ferramenta faz hoje

A landing descreve recursos que ainda não existem.

| Na landing | Situação na ferramenta |
|---|---|
| Mapa de cobertura com camadas | ✅ existe |
| Distância real pelas ruas | ✅ existe (modo "a pé") |
| Relatórios em PDF | ✅ existe |
| "Tempo a pé" de cada moradia | ⚠️ calcula distância a pé, não mostra minutos |
| Dados do IPTU | ⚠️ o upload só valida o arquivo; ainda não refina a densidade |
| **Ranking de déficit** (bairros ordenados pela população sem atendimento) | ❌ não existe |
| **Simulador de nova unidade** (marcar um terreno e ver quantos passaria a atender) | ❌ não existe |

**Antes de divulgar a landing:** implemente os dois itens ❌ ou tire-os do texto.

**Identidade na ferramenta (aplicada em 13/11/2026).** Mapa, login, definir senha, painel de contas e relatório PDF
já seguem a marca Equicidade:
- logo e favicon (`frontend/img/`);
- azul-500 nos botões e controles, azul-900 no texto e névoa no fundo;
- Instrument Sans no texto e IBM Plex Mono nos números;
- déficit e prioridade em escala de coral (no mapa e no PDF);
- alertas em coral-700, como pede o manual.

As cores de cada **tipo de equipamento** (creche laranja, pré-escola amarelo, anos iniciais azul, anos finais roxo,
UBS verde) foram mantidas: o manual não define uma paleta categórica, e são elas que diferenciam os cinco tipos no
mapa. Se quiser, dá para criar uma paleta categórica da marca.
