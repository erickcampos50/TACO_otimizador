# Relatório de testes e correções

## Escopo coberto

Foram executados testes automatizados de API/solver e uma revisão de interface para reduzir envio de restrições inativas.

## Cenários testados

1. **Carga de metadados**
   - endpoint `/api/meta`
   - valida presença de alimentos, nutrientes e grupos

2. **Download do template CSV**
   - endpoint `/api/download/candidate-template`
   - valida colunas `selection_min_g` e `planner_group`

3. **Solução factível com refeição + cardinalidade**
   - almoço com `Proteína` exata = 1 item
   - meta mínima global de proteína
   - limites por refeição

4. **Modo aproximado com problema inviável**
   - meta de proteína impossível com um único alimento candidato
   - valida retorno `optimal_with_violations`

5. **Objetivo econômico sem custos informados**
   - valida erro claro para `minimize_cost`

6. **Restrições inativas (`mode = none`)**
   - valida que linhas inativas não travam a otimização

7. **Cardinalidade com `selection_min_g <= 0`**
   - valida erro explícito para evitar contagem de item com 0 g

## Correções implementadas

### Backend

- **Ignorar restrições inativas (`mode = none`)** no solver e nos relatórios.
- **Validar `selection_min_g > 0` quando há cardinalidade ativa**, evitando que um alimento conte como selecionado com 0 g.
- **Filtrar relatórios de saída** para não listar restrições inativas como se fossem informativas.

### Frontend

- **Filtrar linhas inativas/vazias antes de montar o payload** enviado ao backend.
- Reduz o ruído na API e evita erros causados por linhas incompletas deixadas na tela.

## Resultado

Todos os testes automatizados passaram:

- 7 testes executados
- 7 testes aprovados
