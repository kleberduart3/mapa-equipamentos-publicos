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

## Domínios e publicação

| Endereço | O quê | Onde roda |
|---|---|---|
| `equicidade.com.br` e `www.` | landing page | **GitHub Pages**, repositório [`equicidade-site`](https://github.com/kleberduart3/equicidade-site) |
| `mapa.equicidade.com.br` | a ferramenta (login, mapa, API) | VPS com Docker + Caddy (`docs/implantacao.md`) |

O domínio foi registrado no Registro.br em 13/11/2026 e usa o DNS do próprio Registro.br. Em **Registro.br → equicidade.com.br → DNS → Editar zona**, crie:

| Nome | Tipo | Valor |
|---|---|---|
| *(vazio, o próprio domínio)* | A | `185.199.108.153` |
| *(vazio)* | A | `185.199.109.153` |
| *(vazio)* | A | `185.199.110.153` |
| *(vazio)* | A | `185.199.111.153` |
| `www` | CNAME | `kleberduart3.github.io.` |
| `mapa` | A | IP da VPS (quando ela existir) |

Depois que o DNS propagar (de minutos a algumas horas), o GitHub emite o certificado. Em seguida, em
**equicidade-site → Settings → Pages**, marque **Enforce HTTPS**.

**Atualizar a landing:**
1. A cópia de trabalho fica em [`landing/`](../landing/) neste repositório.
2. Para publicar, copie o conteúdo de `landing/` para o repositório `equicidade-site` e faça o push. Fica de fora só
   o `README.md` de lá.

Por enquanto a landing é publicada por dois caminhos (esta cópia e o `equicidade-site`). Para ter um só, desligue o
Pages do `equicidade-site` e ative o deste repositório com o domínio. Isso é uma decisão sua, porque mexe no outro
repositório.

O botão "Entrar" da landing aponta para `https://mapa.equicidade.com.br/`, que só funciona depois da VPS.

**Formulário de demonstração:** não envia nada ao servidor. Ele abre o WhatsApp `(82) 98818-9617` com os dados
preenchidos (`landing/assets/js/main.js`).

## Promessas da landing × a ferramenta

Desde 13/11/2026, a ferramenta faz tudo o que a landing descreve.

| Na landing | Na ferramenta |
|---|---|
| Mapa de cobertura com camadas | ✅ camadas por tipo, raios, radar de áreas sugeridas |
| Distância real pelas ruas | ✅ modo "a pé pelas ruas" (malha do OpenStreetMap) |
| Tempo a pé de cada moradia até a unidade mais próxima | ✅ calculado para cada endereço. Aparece como tempo médio no painel, no ranking, ao clicar numa área do mapa e no PDF (80 m/min, `velocidade_caminhada_m_min`) |
| Considerando a capacidade de cada unidade | ✅ método 2SFCA (matrículas e equipes de saúde) |
| Mapa por setor censitário | ✅ botão "Setores do IBGE" em "Mostrar no mapa" (os hexágonos continuam como opção) |
| Ranking de bairros | ✅ seção "Bairros com mais gente fora do raio", com zoom no bairro e planilha CSV; também no PDF |
| Simulador de nova unidade | ✅ "Simular nova unidade": marcar no mapa e arrastar para comparar terrenos |
| Relatórios em PDF | ✅ |
| Cadastro do IPTU | o texto da landing foi ajustado: a prefeitura *pode enviar* o cadastro. Hoje ele é recebido e validado, mas ainda não entra no cálculo |

**Como o ranking agrupa as moradias:** pelo bairro do IBGE.
- **Setor urbano sem bairro no IBGE:** recebe o bairro do setor nomeado mais próximo.
- **Setor rural:** entra como "Zona rural", com o nome do distrito quando o município tem mais de um.

O simulador usa a mesma regra de raio, inclusive o rural, e a mesma medida de distância do mapa. Por isso, no centro de
uma área sugerida, ele dá exatamente a demanda da sugestão (há teste automático para isso).

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
