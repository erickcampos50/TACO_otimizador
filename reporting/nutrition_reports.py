from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .simple_pdf import render_simple_pdf

OBJECTIVE_LABELS = {
    "target_matching": "Bater metas com menor desvio",
    "minimize_calories": "Minimizar calorias",
    "maximize_protein": "Maximizar proteína",
    "minimize_cost": "Minimizar custo",
    "custom_weighted": "Objetivo ponderado customizado",
}
SOLVER_LABELS = {
    "exact": "Apenas soluções factíveis",
    "approximate": "Melhor aproximação quando inviável",
}
STATUS_LABELS = {
    "optimal": "Solução encontrada",
    "optimal_with_violations": "Solução encontrada com ajustes aproximados",
}
MODE_LABELS = {
    "min": "mínimo",
    "max": "máximo",
    "range": "faixa",
    "ideal": "ideal",
    "exact": "exato",
}
SCOPE_LABELS = {
    "global_group": "Grupo no dia inteiro",
    "meal_group": "Grupo dentro da refeição",
    "planner_group_global": "Grupo customizado no dia inteiro",
    "planner_group_meal": "Grupo customizado na refeição",
    "planner_group_global_count": "Quantidade de itens no dia inteiro",
    "planner_group_meal_count": "Quantidade de itens na refeição",
    "meal_total": "Peso total da refeição",
    "meal_nutrient": "Meta nutricional da refeição",
}
KEY_METRICS = [
    "Energia (kcal)",
    "Proteína (g)",
    "Carboidrato (g)",
    "Lipídeos (g)",
    "Fibra Alimentar (g)",
]
REPORT_BASENAME = "relatorio_cardapio_detalhado"


class DetailedReportRequest(BaseModel):
    result: dict[str, Any] = Field(default_factory=dict)


def report_download_name(extension: str) -> str:
    return f"{REPORT_BASENAME}.{extension.lstrip('.')}"


def _validate_result(result: dict[str, Any]) -> None:
    if not isinstance(result, dict):
        raise ValueError("Calcule um cardápio antes de gerar o relatório detalhado.")
    foods = result.get("foods") or []
    if not foods:
        raise ValueError("Calcule um cardápio antes de gerar o relatório detalhado.")


def _label_for(mapping: dict[str, str], value: Any) -> str:
    if value is None:
        return "—"
    return mapping.get(str(value), str(value))


def _format_number(value: Any, digits: int = 1) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    text = f"{number:,.{digits}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def _format_currency(value: Any) -> str:
    if value is None:
        return "custos não informados"
    try:
        return f"R$ {_format_number(float(value), 2)}"
    except (TypeError, ValueError):
        return "custos não informados"


def _has_cost_data(result: dict[str, Any]) -> bool:
    return any(item.get("cost_per_100g") is not None for item in result.get("foods") or [])


def _meal_sections(result: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for food in result.get("foods") or []:
        grouped[food.get("meal") or "Itens sem refeição definida"].append(food)

    summary_by_meal = {item.get("meal"): item for item in result.get("meal_summaries") or [] if item.get("meal")}
    ordered_meals = [item["meal"] for item in result.get("meal_summaries") or [] if item.get("meal")]
    for meal in sorted(grouped):
        if meal not in ordered_meals:
            ordered_meals.append(meal)

    sections: list[dict[str, Any]] = []
    for meal in ordered_meals:
        foods = sorted(grouped.get(meal, []), key=lambda item: (-float(item.get("grams") or 0.0), item.get("description") or ""))
        if not foods:
            continue
        sections.append({"meal": meal, "summary": summary_by_meal.get(meal, {}), "foods": foods})
    return sections


def _global_constraint_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = result.get("active_constraints") or []
    return [row for row in rows if row.get("nutrient")]


def _extra_constraint_rows(result: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for item in result.get("active_meal_constraints") or []:
        label = item.get("constraint_label") or _label_for(SCOPE_LABELS, item.get("scope"))
        lines.append(
            f"{item.get('meal')}: {label} em modo {_label_for(MODE_LABELS, item.get('mode'))}; "
            f"realizado {_format_number(item.get('realized'), 1)}."
        )
    for item in result.get("active_group_constraints") or []:
        scope = _label_for(SCOPE_LABELS, item.get("scope"))
        meal_note = f" na refeição {item.get('meal')}" if item.get("meal") else ""
        lines.append(
            f"{scope}: grupo {item.get('group')}{meal_note} em modo {_label_for(MODE_LABELS, item.get('mode'))}; "
            f"realizado {_format_number(item.get('realized'), 1)} g."
        )
    for item in result.get("active_group_cardinality_constraints") or []:
        scope = _label_for(SCOPE_LABELS, item.get("scope"))
        meal_note = f" na refeição {item.get('meal')}" if item.get("meal") else ""
        lines.append(
            f"{scope}: grupo {item.get('group')}{meal_note} em modo {_label_for(MODE_LABELS, item.get('mode'))}; "
            f"realizado {_format_number(item.get('realized'), 0)} item(ns)."
        )
    return lines


def _key_nutrient_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    nutrients = {item.get("nutrient"): item for item in result.get("nutrients") or []}
    rows = []
    for nutrient in KEY_METRICS:
        if nutrient in nutrients:
            rows.append(nutrients[nutrient])
    return rows


def _target_text(item: dict[str, Any], unit: str) -> str:
    mode = item.get("mode")
    if mode == "min" and item.get("min_value") is not None:
        return f"pelo menos {_format_number(item['min_value'], 1)} {unit}"
    if mode == "max" and item.get("max_value") is not None:
        return f"até {_format_number(item['max_value'], 1)} {unit}"
    if mode == "range" and item.get("min_value") is not None and item.get("max_value") is not None:
        return f"entre {_format_number(item['min_value'], 1)} e {_format_number(item['max_value'], 1)} {unit}"
    if mode in {"ideal", "exact"} and item.get("ideal_value") is not None:
        prefix = "próximo de" if mode == "ideal" else "exatamente"
        return f"{prefix} {_format_number(item['ideal_value'], 1)} {unit}"
    return "sem meta explícita"


def _constraint_status_text(status: Any) -> str:
    if status == "ok":
        return "dentro do esperado"
    if status == "violado":
        return "fora do esperado"
    return "informativo"


def _patient_guidance(result: dict[str, Any]) -> list[str]:
    meal_count = len(result.get("meal_summaries") or [])
    total_grams = _format_number(result.get("total_grams"), 1)
    guidance = [
        f"Explique que o plano foi organizado para {_label_for(OBJECTIVE_LABELS, result.get('objective_mode')).lower()}, sem perder a distribuição por refeições.",
        f"Diga ao paciente que o dia totaliza cerca de {total_grams} g de alimentos distribuídos em {meal_count} refeição(ões).",
        "Apresente primeiro as refeições e as porções em gramas; depois relacione essas porções com a meta nutricional do dia.",
        "Use o relatório como apoio de conversa e ajuste preferências, rotina, cultura alimentar e condições clínicas antes de transformar isso em orientação individual.",
    ]
    if _has_cost_data(result):
        guidance.append(f"Se o custo fizer parte do caso estudado, informe que a estimativa total do dia ficou em {_format_currency(result.get('total_estimated_cost'))}.")
    if result.get("status") == "optimal_with_violations":
        guidance.append("Como houve ajustes aproximados, revise com cuidado as metas marcadas como fora do esperado antes de apresentar o plano como exemplo final.")
    return guidance


def _report_header_lines(result: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        ("Status da solução", _label_for(STATUS_LABELS, result.get("status"))),
        ("Objetivo principal", _label_for(OBJECTIVE_LABELS, result.get("objective_mode"))),
        ("Modo de cálculo", _label_for(SOLVER_LABELS, result.get("solver_mode"))),
        ("Alimentos selecionados", str(len(result.get("foods") or []))),
        ("Total do dia", f"{_format_number(result.get('total_grams'), 1)} g"),
        ("Custo estimado", _format_currency(result.get("total_estimated_cost")) if _has_cost_data(result) else "custos não informados"),
    ]


def build_markdown_report(result: dict[str, Any]) -> str:
    _validate_result(result)
    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")
    sections = _meal_sections(result)
    global_constraints = _global_constraint_rows(result)
    extra_constraints = _extra_constraint_rows(result)
    key_nutrients = _key_nutrient_rows(result)
    warnings = result.get("warnings") or []

    lines: list[str] = [
        "# Relatório detalhado do cardápio otimizado",
        "",
        f"_Gerado em {generated_at}_",
        "",
        "## Resumo executivo",
        "",
        "| Item | Valor |",
        "| --- | --- |",
    ]
    for label, value in _report_header_lines(result):
        lines.append(f"| {label} | {value} |")

    lines.extend([
        "",
        "## Como explicar para o paciente",
        "",
    ])
    lines.extend(f"- {item}" for item in _patient_guidance(result))

    lines.extend([
        "",
        "## Distribuição por refeição",
        "",
        "| Refeição | Itens | Quantidade total | Energia | Proteína | Fibra | Custo |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ])
    for item in result.get("meal_summaries") or []:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item.get("meal") or "—"),
                    str(item.get("food_count") or 0),
                    f"{_format_number(item.get('total_grams'), 1)} g",
                    f"{_format_number(item.get('Energia (kcal)'), 1)} kcal",
                    f"{_format_number(item.get('Proteína (g)'), 1)} g",
                    f"{_format_number(item.get('Fibra Alimentar (g)'), 1)} g",
                    _format_currency(item.get("total_estimated_cost")) if _has_cost_data(result) else "—",
                ]
            )
            + " |"
        )

    lines.extend([
        "",
        "## Cardápio sugerido por refeição",
        "",
    ])
    for section in sections:
        summary = section["summary"]
        lines.append(f"### {section['meal']}")
        lines.append("")
        if summary:
            lines.append(
                f"Resumo da refeição: {_format_number(summary.get('total_grams'), 1)} g, "
                f"{_format_number(summary.get('Energia (kcal)'), 1)} kcal, "
                f"{_format_number(summary.get('Proteína (g)'), 1)} g de proteína e "
                f"{_format_number(summary.get('Fibra Alimentar (g)'), 1)} g de fibra."
            )
            lines.append("")
        for food in section["foods"]:
            lines.append(
                f"- **{food.get('description', 'Alimento')}**: {_format_number(food.get('grams'), 1)} g "
                f"({ _format_number(food.get('Energia (kcal)'), 1)} kcal, "
                f"{_format_number(food.get('Proteína (g)'), 1)} g de proteína, "
                f"{_format_number(food.get('Fibra Alimentar (g)'), 1)} g de fibra)."
            )
        lines.append("")

    lines.extend([
        "## Resumo nutricional do dia",
        "",
        "| Nutriente | Total encontrado |",
        "| --- | --- |",
    ])
    for item in key_nutrients:
        unit = "kcal" if "kcal" in str(item.get("nutrient")) else "g"
        lines.append(f"| {item.get('nutrient')} | {_format_number(item.get('total'), 1)} {unit} |")

    lines.extend([
        "",
        "## Metas nutricionais acompanhadas",
        "",
    ])
    if global_constraints:
        lines.extend([
            "| Nutriente | Meta | Total encontrado | Situação |",
            "| --- | --- | --- | --- |",
        ])
        for item in global_constraints:
            unit = "kcal" if "kcal" in str(item.get("nutrient")) else "g"
            lines.append(
                f"| {item.get('nutrient')} | {_target_text(item, unit)} | "
                f"{_format_number(item.get('realized'), 1)} {unit} | {_constraint_status_text(item.get('status'))} |"
            )
    else:
        lines.append("Nenhuma meta global de nutriente estava ativa nesta solução.")

    lines.extend([
        "",
        "## Regras de refeições e grupos",
        "",
    ])
    if extra_constraints:
        lines.extend(f"- {line}" for line in extra_constraints)
    else:
        lines.append("- Não havia regras adicionais de refeições ou grupos ativadas.")

    lines.extend([
        "",
        "## Alertas e observações",
        "",
    ])
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- Sem alertas adicionais nesta execução.")

    lines.extend([
        "",
        "## Nota para estudo",
        "",
        "Este relatório organiza o resultado da otimização em linguagem mais próxima da prática de atendimento. "
        "Ele é útil para discutir raciocínio nutricional, mas não substitui avaliação clínica, anamnese e adaptação individual.",
    ])
    return "\n".join(lines)


def build_pdf_report(result: dict[str, Any]) -> bytes:
    _validate_result(result)
    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")
    sections = _meal_sections(result)
    global_constraints = _global_constraint_rows(result)
    extra_constraints = _extra_constraint_rows(result)
    warnings = result.get("warnings") or []

    blocks: list[tuple[str, str]] = [
        ("title", "Relatório detalhado do cardápio otimizado"),
        ("small", f"Gerado em {generated_at}"),
        ("body", "Documento de apoio para apresentar o cardápio, discutir metas nutricionais e explicar o caso ao paciente com linguagem mais clara."),
        ("heading", "Resumo executivo"),
    ]
    blocks.extend(("bullet", f"{label}: {value}") for label, value in _report_header_lines(result))

    blocks.append(("heading", "Como explicar para o paciente"))
    blocks.extend(("bullet", item) for item in _patient_guidance(result))

    blocks.append(("heading", "Distribuição por refeição"))
    for item in result.get("meal_summaries") or []:
        cost_text = _format_currency(item.get("total_estimated_cost")) if _has_cost_data(result) else "custos não informados"
        blocks.append(
            (
                "bullet",
                f"{item.get('meal')}: {int(item.get('food_count') or 0)} item(ns), "
                f"{_format_number(item.get('total_grams'), 1)} g, "
                f"{_format_number(item.get('Energia (kcal)'), 1)} kcal, "
                f"{_format_number(item.get('Proteína (g)'), 1)} g de proteína, custo {cost_text}.",
            )
        )

    blocks.append(("heading", "Cardápio sugerido por refeição"))
    for section in sections:
        blocks.append(("subheading", section["meal"]))
        summary = section["summary"]
        if summary:
            blocks.append(
                (
                    "body",
                    f"Resumo: {_format_number(summary.get('total_grams'), 1)} g; "
                    f"{_format_number(summary.get('Energia (kcal)'), 1)} kcal; "
                    f"{_format_number(summary.get('Proteína (g)'), 1)} g de proteína; "
                    f"{_format_number(summary.get('Fibra Alimentar (g)'), 1)} g de fibra.",
                )
            )
        for food in section["foods"]:
            blocks.append(
                (
                    "bullet",
                    f"{food.get('description', 'Alimento')}: {_format_number(food.get('grams'), 1)} g, "
                    f"{_format_number(food.get('Energia (kcal)'), 1)} kcal, "
                    f"{_format_number(food.get('Proteína (g)'), 1)} g de proteína, "
                    f"{_format_number(food.get('Fibra Alimentar (g)'), 1)} g de fibra.",
                )
            )

    blocks.append(("heading", "Metas nutricionais acompanhadas"))
    if global_constraints:
        for item in global_constraints:
            unit = "kcal" if "kcal" in str(item.get("nutrient")) else "g"
            blocks.append(
                (
                    "bullet",
                    f"{item.get('nutrient')}: meta {_target_text(item, unit)}; "
                    f"realizado {_format_number(item.get('realized'), 1)} {unit}; "
                    f"situação {_constraint_status_text(item.get('status'))}.",
                )
            )
    else:
        blocks.append(("body", "Nenhuma meta global de nutriente estava ativa nesta solução."))

    blocks.append(("heading", "Regras de refeições e grupos"))
    if extra_constraints:
        blocks.extend(("bullet", line) for line in extra_constraints)
    else:
        blocks.append(("body", "Não havia regras adicionais de refeições ou grupos ativadas."))

    blocks.append(("heading", "Alertas e observações"))
    if warnings:
        blocks.extend(("bullet", warning) for warning in warnings)
    else:
        blocks.append(("body", "Sem alertas adicionais nesta execução."))

    blocks.append(("heading", "Nota para estudo"))
    blocks.append(
        (
            "body",
            "Use este relatório para treinar a explicação do raciocínio nutricional ao paciente. "
            "Antes de qualquer uso real, confirme rotina, preferências, contexto social e necessidades clínicas.",
        )
    )
    return render_simple_pdf(blocks)
