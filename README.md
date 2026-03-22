# TACO Optimizer

Webapp local para otimização quantitativa de alimentos com base na TACO.

## Como rodar

```bash
./start.sh
```

O script cria o ambiente virtual `.venv` se ele ainda não existir, instala as dependências definidas em `requirements.txt` e inicia a aplicação.

Depois abra `http://127.0.0.1:5589` no navegador.

Se preferir executar manualmente:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## O que a aplicação suporta

- alimentos candidatos selecionados pelo usuário
- variáveis de decisão em gramas
- metas nutricionais globais: mínimo, máximo, faixa e ideal
- limites por grupo TACO
- limites por refeição
- metas nutricionais por refeição
- limites globais por grupo customizado
- limites por grupo customizado dentro da refeição
- cardinalidade global por grupo customizado
- cardinalidade por grupo customizado dentro da refeição
- modos `exact` e `approximate`
- exportação do resultado em CSV

## Campo importante

- `selection_min_g`: quantidade mínima para um alimento contar como selecionado nas restrições de cardinalidade.

## Template CSV

Baixe o template pela própria interface ou use `data/candidate_template.csv`.

Colunas:

- `code`
- `enabled`
- `min_g`
- `max_g`
- `selection_min_g`
- `cost_per_100g`
- `meal`
- `planner_group`

## Exemplos de cardinalidade

- no almoço, exatamente 1 item do grupo `Proteína`
- no café da manhã, no máximo 2 itens do grupo `Fruta`
- no dia inteiro, entre 2 e 4 itens do grupo `Laticínio`

## Observações técnicas

- valores `Tr` são tratados como zero operacional no solver
- células vazias e `*` são tratadas como ausentes
- cardinalidade usa variáveis binárias internas, então a otimização passa a ser mista-inteira
