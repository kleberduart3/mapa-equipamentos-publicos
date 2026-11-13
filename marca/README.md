# Equicidade

Equicidade é uma ferramenta para prefeituras que cruza onde a população mora com onde estão as escolas, creches e postos de saúde, e mostra no mapa os bairros que ficam sem atendimento. O nome junta equidade e cidade, e a marca existe para passar essa ideia: um serviço público bem distribuído pelo território.

## A marca

O símbolo são curvas de nível irregulares em volta de um ponto. São isócronas, as linhas que marcam até onde se chega a partir de um equipamento em certo tempo de deslocamento. O ponto coral é o equipamento; o miolo azul é a área bem atendida; o anel claro de fora é o limite da cobertura. As curvas são orgânicas de propósito, porque a cidade real não se distribui em círculos perfeitos.

O nome se escreve sempre em minúsculas, **equi** em negrito e **cidade** em peso médio, para deixar visível a junção das duas palavras. No texto corrido, escreva Equicidade, com inicial maiúscula.

### Versões

Use a **horizontal** (`equicidade-horizontal.svg`) como padrão em site, documentos e apresentações. A **vertical** (`equicidade-vertical.svg`) entra em capas, crachás e espaços quadrados. O **símbolo** sozinho vale para ícone de app, favicon, avatar de redes e marca-d'água em mapas. Sobre azul-900 ou fotos escuras, use a **negativa** (`equicidade-horizontal-negativo.svg`, `equicidade-simbolo-branco.svg`).

### Área de proteção e tamanho mínimo

Deixe em volta da marca um espaço livre igual à altura do miolo do símbolo, que é cerca de um terço da altura do símbolo. A versão horizontal não deve ficar com menos de 120 px de largura na tela nem 30 mm no impresso. Abaixo disso, use só o símbolo, que funciona a partir de 16 px.

### O que evitar

Não troque as cores das curvas entre si, não gire o símbolo, não aplique sombra nem contorno, não mude o peso das duas metades do nome e não coloque a marca colorida sobre o azul-500.

## Cores

A paleta tem dois protagonistas. O `azul-500` (#2F4BFF) é a cor da marca e dos elementos interativos. O `coral-500` (#FF6B57) aparece pouco, sempre como ponto de atenção: o equipamento no símbolo e os marcadores de déficit nos mapas. O `azul-900` (#0D1450) faz o papel de preto, nos textos e nas superfícies escuras, e a `nevoa` (#F5F6FB) substitui o branco puro como fundo.

Uma proporção que funciona nas peças: 60% nevoa e branco, 25% azul-900, 12% azul-500 e 3% coral. Se o coral passar disso, ele deixa de indicar o que importa.

O coral-500 não serve para texto sobre fundo claro (2,6:1). Para palavras e números em coral, use `coral-700` ou o token `accent-text`. Nas telas da ferramenta, prefira os tokens semânticos (`surface`, `ink`, `brand`, `accent`, `coverage`), que já resolvem o tema escuro.

Nos mapas, a área atendida usa `coverage` e o déficit usa `accent`. As duas diferem em matiz e em luminosidade, então continuam distinguíveis para quem tem daltonismo.

## Tipografia

Instrument Sans é a família da marca, das telas e dos impressos. Títulos em 600 ou 700, com espaçamento levemente negativo; texto corrido em 400. Para números, indicadores e tabelas de dados, use IBM Plex Mono, que alinha os algarismos e dá ao produto um tom técnico sem ficar frio. As duas estão no Google Fonts.

Escreva títulos em frase normal, sem caixa alta. A caixa alta fica só para rótulos curtos no estilo `label`.

## Tom de voz

A Equicidade fala com secretários, técnicos de planejamento e prefeitos. O texto é direto, usa dados concretos e evita jargão de tecnologia. Prefira "o bairro Primavera tem 1.200 crianças e nenhuma creche a menos de 1 km" a "otimize a alocação de recursos com inteligência geoespacial". Os números são o argumento; o texto só os apresenta.

## Padrão gráfico

As curvas de nível do símbolo podem ser ampliadas e cortadas como fundo de capas, slides e banners, em `azul-200` sobre `nevoa` ou em `azul-500` sobre `azul-900`. Use no máximo três curvas por composição e deixe sempre um ponto coral, que dá a referência de onde está o equipamento.

## Formas e espaçamento

Os cantos são arredondados: `radius-md` (12 px) para botões e `radius-lg` (20 px) para cartões e painéis. O espaçamento segue uma grade de 4 px (`space-1` a `space-24`). A sombra só aparece em cartões sobre fundo claro (`shadow-card`) e em painéis flutuando sobre mapas (`shadow-float`).

## Iconografia

Ícones de linha com traço de 1,75 px, cantos arredondados e grade de 24 px, na cor do texto. Bibliotecas como Lucide seguem esse desenho. Não use emojis nem ícones preenchidos misturados aos de linha.
