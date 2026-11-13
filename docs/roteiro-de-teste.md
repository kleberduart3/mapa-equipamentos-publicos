# Roteiro de teste – Equicidade

Leva uns 15 minutos. Os testes rodam no computador onde está o projeto, porque o servidor local (`localhost`) só abre
nele.

## 0. Subir o servidor (se não estiver rodando)

No *Miniforge Prompt*, na pasta do projeto:

```
conda activate equipamentos
set MAPA_URL_BASE=http://localhost:8000
uvicorn backend.app.api.main:app --port 8000
```

Espere aparecer `Application startup complete` e abra <http://localhost:8000>.

Ainda não tem conta? Crie a sua e abra o link que aparecer:

```
python -m backend.app.acesso.cli criar-admin seu@email "Seu Nome"
```

## 1. Login e contas

1. Abra o link de convite, defina uma senha (mínimo de 12 caracteres) e entre em <http://localhost:8000/entrar>.
2. Erre a senha 5 vezes seguidas com outro e-mail de teste. A conta fica bloqueada por 15 minutos.
3. No menu com o seu nome, vá em **Administrar contas** e crie uma conta de teste:
   - libere só **Palmeira dos Índios**, como **consulta**;
   - copie o link, abra numa janela anônima, defina a senha e entre.

   Essa conta deve ver só Palmeira e não deve ter o botão "Importar dados da prefeitura".
4. De volta ao painel, clique em **Desconectar** nessa conta. A janela anônima volta para o login ao recarregar.

## 2. Mapa

Escolha **Arapiraca – AL** no seletor do topo.

| O que fazer | O que deve acontecer |
|---|---|
| Trocar entre **Linha reta** e **A pé pelas ruas** | Círculos viram manchas das ruas alcançáveis; a cobertura cai (creche: 36% → 24%) |
| Mexer no raio da creche | O número ao lado mostra metros e minutos a pé; painel, ranking e mapa se recalculam |
| Em **Mostrar no mapa**, trocar **Hexágonos** por **Setores do IBGE** | O déficit passa a aparecer por setor censitário |
| Clicar numa área colorida | Popup com pessoas fora do raio e tempo médio a pé até a unidade mais próxima |
| Clicar num pin | Popup com matrículas ou equipes, rede, bairro e raio em minutos |
| Ligar e desligar camadas | Pins, raios e radares de cada tipo somem e voltam |

## 3. Ranking de bairros

- A lista **Bairros com mais gente fora do raio** segue o tipo escolhido em "Mostrar no mapa".
- Clicar num bairro aproxima o mapa nele.
- **Ver todos** mostra a lista inteira, e **Baixar planilha (CSV)** abre no Excel.
- Mude o raio ou o modo de distância: o ranking muda junto.

## 4. Simulador de nova unidade

1. Em **Simular nova unidade**, escolha o tipo (ex.: Creche) e clique em **Escolher o local no mapa**.
2. Clique num bairro com muito déficit. Aparecem:
   - a mancha do novo alcance;
   - quantas crianças passariam a ter creche no raio;
   - a cobertura do município antes e depois.
3. Arraste o marcador para outro terreno e compare os resultados.
4. Clique no centro de um radar numerado. O resultado deve bater com o popup do radar.

## 5. Relatório PDF

**Exportar relatório PDF** gera o relatório com os raios da tela em cerca de 40 s. Confira:
- a marca Equicidade;
- o ranking de bairros na página de cada tipo;
- o tempo médio a pé.

## 6. Palmeira dos Índios

Troque o município no topo. É a cidade processada sem a exportação manual do INEP: muitas escolas têm localização
aproximada (contorno coral tracejado). A lista para a prefeitura conferir está em
`dados/saidas/2706307/checagem_dados.md`.

## Achou algo estranho?

Anote o município, o tipo, o raio e o modo (linha reta ou a pé) e o que esperava ver.
