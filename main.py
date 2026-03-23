from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from scipy.optimize import Bounds, LinearConstraint, milp

from reporting import (
    DetailedReportRequest,
    build_markdown_report,
    build_pdf_report,
    report_download_name,
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
EXAMPLES_DIR = DATA_DIR / "examples"
STATIC_DIR = BASE_DIR / "static"

APP_TITLE = "TACO Optimizer"
DEFAULT_APPROX_PENALTY = 10000.0
DEFAULT_IDEAL_WEIGHT = 1.0
DEFAULT_SELECTION_MIN_G = 1.0
DEFAULT_BIG_M_GRAMS = 10000.0
KEY_RESULT_METRICS = [
    "Energia (kcal)",
    "Proteína (g)",
    "Carboidrato (g)",
    "Lipídeos (g)",
    "Fibra Alimentar (g)",
]


def _load_data() -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    df = pd.read_csv(DATA_DIR / "taco_base.csv")
    with open(DATA_DIR / "taco_metadata.json", "r", encoding="utf-8") as f:
        meta = json.load(f)
    nutrient_cols = [item["name"] for item in meta["nutrients"]]
    return df, meta, nutrient_cols


def _load_example_presets() -> list[dict[str, Any]]:
    if not EXAMPLES_DIR.exists():
        return []
    examples: list[dict[str, Any]] = []
    for path in sorted(EXAMPLES_DIR.glob("*.json")):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["id"] = str(data.get("id") or path.stem)
        data["sort_order"] = int(data.get("sort_order", 999))
        examples.append(data)
    examples.sort(key=lambda item: (item.get("sort_order", 999), item.get("title", item["id"])))
    return examples


TACO_DF, TACO_META, NUTRIENT_COLS = _load_data()
FOOD_LOOKUP = {int(row["Código TACO"]): row.to_dict() for _, row in TACO_DF.iterrows()}
VALID_STANDARD_MODES = {"none", "min", "max", "range", "ideal"}
VALID_CARDINALITY_MODES = {"none", "min", "max", "range", "ideal", "exact"}


class CandidateFood(BaseModel):
    row_id: Optional[str] = None
    code: int
    min_g: Optional[float] = 0.0
    max_g: Optional[float] = None
    cost_per_100g: Optional[float] = None
    meal: Optional[str] = None
    planner_group: Optional[str] = None
    selection_min_g: Optional[float] = DEFAULT_SELECTION_MIN_G
    enabled: bool = True


class NutrientConstraint(BaseModel):
    nutrient: str
    mode: str = Field(description="none|min|max|range|ideal")
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    ideal_value: Optional[float] = None
    weight: Optional[float] = DEFAULT_IDEAL_WEIGHT


class GroupConstraint(BaseModel):
    group: str
    min_g: Optional[float] = None
    max_g: Optional[float] = None


class MealConstraint(BaseModel):
    meal: str
    min_g: Optional[float] = None
    max_g: Optional[float] = None


class MealNutrientConstraint(BaseModel):
    meal: str
    nutrient: str
    mode: str = Field(description="none|min|max|range|ideal")
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    ideal_value: Optional[float] = None
    weight: Optional[float] = DEFAULT_IDEAL_WEIGHT


class PlannerGroupConstraint(BaseModel):
    group: str
    mode: str = Field(description="none|min|max|range|ideal")
    min_g: Optional[float] = None
    max_g: Optional[float] = None
    ideal_g: Optional[float] = None
    weight: Optional[float] = DEFAULT_IDEAL_WEIGHT


class MealPlannerGroupConstraint(BaseModel):
    meal: str
    group: str
    mode: str = Field(description="none|min|max|range|ideal")
    min_g: Optional[float] = None
    max_g: Optional[float] = None
    ideal_g: Optional[float] = None
    weight: Optional[float] = DEFAULT_IDEAL_WEIGHT


class PlannerGroupCardinalityConstraint(BaseModel):
    group: str
    mode: str = Field(description="none|min|max|range|ideal|exact")
    min_count: Optional[int] = None
    max_count: Optional[int] = None
    exact_count: Optional[int] = None
    ideal_count: Optional[int] = None
    weight: Optional[float] = DEFAULT_IDEAL_WEIGHT


class MealPlannerGroupCardinalityConstraint(BaseModel):
    meal: str
    group: str
    mode: str = Field(description="none|min|max|range|ideal|exact")
    min_count: Optional[int] = None
    max_count: Optional[int] = None
    exact_count: Optional[int] = None
    ideal_count: Optional[int] = None
    weight: Optional[float] = DEFAULT_IDEAL_WEIGHT


class GlobalSettings(BaseModel):
    objective_mode: str = "target_matching"
    solver_mode: str = "exact"
    total_min_g: Optional[float] = None
    total_max_g: Optional[float] = None
    objective_weights: Optional[Dict[str, float]] = None


class OptimizationRequest(BaseModel):
    candidate_foods: List[CandidateFood]
    nutrient_constraints: List[NutrientConstraint] = []
    group_constraints: List[GroupConstraint] = []
    planner_group_constraints: List[PlannerGroupConstraint] = []
    planner_group_cardinality_constraints: List[PlannerGroupCardinalityConstraint] = []
    meal_constraints: List[MealConstraint] = []
    meal_nutrient_constraints: List[MealNutrientConstraint] = []
    meal_planner_group_constraints: List[MealPlannerGroupConstraint] = []
    meal_planner_group_cardinality_constraints: List[MealPlannerGroupCardinalityConstraint] = []
    settings: GlobalSettings = GlobalSettings()


class LPBuilder:
    def __init__(self, req: OptimizationRequest):
        self.req = req
        self.weights = normalize_weights(req.settings.objective_weights)
        self.candidates = [c for c in req.candidate_foods if c.enabled]
        self.food_df = self._build_food_df(self.candidates)
        self.var_names: list[str] = []
        self.bounds: list[tuple[Optional[float], Optional[float]]] = []
        self.integrality: list[int] = []
        self.c: list[float] = []
        self.a_ub: list[list[float]] = []
        self.b_ub: list[float] = []
        self.a_eq: list[list[float]] = []
        self.b_eq: list[float] = []
        self.messages: list[str] = []
        self.slack_var_labels: dict[int, str] = {}

    def _build_food_df(self, candidates: list[CandidateFood]) -> pd.DataFrame:
        rows = []
        for idx, item in enumerate(candidates):
            row = FOOD_LOOKUP[item.code].copy()
            row["_candidate_index"] = idx
            row["_row_id"] = item.row_id or f"row_{idx+1}"
            row["_min_g"] = sanitize_float(item.min_g) or 0.0
            row["_max_g"] = sanitize_float(item.max_g)
            row["_cost_per_100g"] = sanitize_float(item.cost_per_100g)
            row["_meal"] = normalize_meal_name(item.meal)
            row["_planner_group"] = normalize_group_name(item.planner_group)
            row["_selection_min_g"] = sanitize_float(item.selection_min_g)
            rows.append(row)
        return pd.DataFrame(rows)

    def add_var(
        self,
        name: str,
        lb: Optional[float] = 0.0,
        ub: Optional[float] = None,
        cost: float = 0.0,
        var_type: str = "continuous",
    ) -> int:
        self.var_names.append(name)
        self.bounds.append((lb, ub))
        self.c.append(float(cost))
        self.integrality.append(1 if var_type == "binary" else 0)
        return len(self.var_names) - 1

    def add_slack_var(self, name: str, label: str, cost: float) -> int:
        idx = self.add_var(name=name, lb=0.0, ub=None, cost=cost, var_type="continuous")
        self.slack_var_labels[idx] = label
        return idx

    def add_ub(self, coeffs: Dict[int, float], rhs: float):
        row = [0.0] * len(self.var_names)
        for idx, val in coeffs.items():
            row[idx] = float(val)
        self.a_ub.append(row)
        self.b_ub.append(float(rhs))

    def add_eq(self, coeffs: Dict[int, float], rhs: float):
        row = [0.0] * len(self.var_names)
        for idx, val in coeffs.items():
            row[idx] = float(val)
        self.a_eq.append(row)
        self.b_eq.append(float(rhs))

    def finalize_rows(self):
        n = len(self.var_names)
        self.a_ub = [row + [0.0] * (n - len(row)) for row in self.a_ub]
        self.a_eq = [row + [0.0] * (n - len(row)) for row in self.a_eq]

    def food_variable_indices(self) -> list[int]:
        out = []
        for _, row in self.food_df.iterrows():
            idx = self.add_var(
                name=f"food::{int(row['Código TACO'])}::{row['_row_id']}",
                lb=float(row["_min_g"]),
                ub=None if pd.isna(row["_max_g"]) else float(row["_max_g"]),
                cost=0.0,
                var_type="continuous",
            )
            out.append(idx)
        return out


def sanitize_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    if isinstance(value, (int, float, np.number)):
        if math.isnan(float(value)):
            return None
        return float(value)
    try:
        return float(value)
    except Exception:
        return None


def normalize_meal_name(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_group_name(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_weights(raw: Optional[Dict[str, float]]) -> Dict[str, float]:
    base = {"calories": 1.0, "protein": 1.0, "cost": 1.0, "grams": 0.0, "deviation": 1.0}
    if not raw:
        return base
    for k in base:
        if k in raw and raw[k] is not None:
            try:
                base[k] = float(raw[k])
            except Exception:
                pass
    return base


def _is_standard_inactive(mode: str, min_value: Optional[float], max_value: Optional[float], ideal_value: Optional[float]) -> bool:
    return (mode or "none") == "none" and min_value is None and max_value is None and ideal_value is None


def _is_cardinality_inactive(mode: str, min_count: Optional[int], max_count: Optional[int], exact_count: Optional[int], ideal_count: Optional[int]) -> bool:
    return (mode or "none") == "none" and min_count is None and max_count is None and exact_count is None and ideal_count is None


def _validate_standard_mode(
    mode: str,
    min_value: Optional[float],
    max_value: Optional[float],
    ideal_value: Optional[float],
    label: str,
    errors: list[str],
):
    if mode not in VALID_STANDARD_MODES:
        errors.append(f"Modo inválido para {label}: {mode}")
        return
    if mode in {"min", "range"} and min_value is None:
        errors.append(f"Defina mínimo para {label}.")
    if mode in {"max", "range"} and max_value is None:
        errors.append(f"Defina máximo para {label}.")
    if mode == "ideal" and ideal_value is None:
        errors.append(f"Defina ideal para {label}.")
    if min_value is not None and max_value is not None and float(min_value) > float(max_value):
        errors.append(f"Restrição inválida para {label}: mínimo maior que máximo.")


def _validate_cardinality_mode(
    mode: str,
    min_count: Optional[int],
    max_count: Optional[int],
    exact_count: Optional[int],
    ideal_count: Optional[int],
    label: str,
    errors: list[str],
):
    if mode not in VALID_CARDINALITY_MODES:
        errors.append(f"Modo inválido para {label}: {mode}")
        return
    if mode in {"min", "range"} and min_count is None:
        errors.append(f"Defina mínimo de itens para {label}.")
    if mode in {"max", "range"} and max_count is None:
        errors.append(f"Defina máximo de itens para {label}.")
    if mode == "exact" and exact_count is None:
        errors.append(f"Defina quantidade exata de itens para {label}.")
    if mode == "ideal" and ideal_count is None:
        errors.append(f"Defina quantidade ideal de itens para {label}.")
    if min_count is not None and min_count < 0:
        errors.append(f"Mínimo de itens inválido para {label}.")
    if max_count is not None and max_count < 0:
        errors.append(f"Máximo de itens inválido para {label}.")
    if exact_count is not None and exact_count < 0:
        errors.append(f"Quantidade exata inválida para {label}.")
    if ideal_count is not None and ideal_count < 0:
        errors.append(f"Quantidade ideal inválida para {label}.")
    if min_count is not None and max_count is not None and int(min_count) > int(max_count):
        errors.append(f"Restrição de cardinalidade inválida para {label}: mínimo maior que máximo.")


def validate_request(req: OptimizationRequest) -> list[str]:
    errors: list[str] = []
    if not req.candidate_foods:
        errors.append("Selecione pelo menos um alimento candidato.")
    enabled_items = [item for item in req.candidate_foods if item.enabled]
    if not enabled_items:
        errors.append("Nenhum alimento candidato está habilitado.")

    enabled_meals = {normalize_meal_name(item.meal) for item in enabled_items if normalize_meal_name(item.meal)}
    enabled_planner_groups = {normalize_group_name(item.planner_group) for item in enabled_items if normalize_group_name(item.planner_group)}
    cardinality_active = any(
        not _is_cardinality_inactive(c.mode, c.min_count, c.max_count, c.exact_count, c.ideal_count)
        for c in req.planner_group_cardinality_constraints + req.meal_planner_group_cardinality_constraints
    )

    for c in req.nutrient_constraints:
        if _is_standard_inactive(c.mode, c.min_value, c.max_value, c.ideal_value):
            continue
        if c.nutrient not in NUTRIENT_COLS:
            errors.append(f"Nutriente inválido: {c.nutrient}")
        _validate_standard_mode(c.mode, c.min_value, c.max_value, c.ideal_value, c.nutrient, errors)

    for c in req.meal_nutrient_constraints:
        if _is_standard_inactive(c.mode, c.min_value, c.max_value, c.ideal_value):
            continue
        if c.nutrient not in NUTRIENT_COLS:
            errors.append(f"Nutriente inválido na refeição '{c.meal}': {c.nutrient}")
        meal = normalize_meal_name(c.meal)
        if not meal:
            errors.append("Toda restrição nutricional por refeição precisa informar a refeição.")
        elif meal not in enabled_meals:
            errors.append(f"A refeição '{meal}' não existe entre os alimentos candidatos habilitados.")
        _validate_standard_mode(c.mode, c.min_value, c.max_value, c.ideal_value, f"{c.nutrient} na refeição '{c.meal}'", errors)

    for pgc in req.planner_group_constraints:
        if _is_standard_inactive(pgc.mode, pgc.min_g, pgc.max_g, pgc.ideal_g):
            continue
        group = normalize_group_name(pgc.group)
        if not group:
            errors.append("Toda restrição de grupo customizado precisa informar o grupo.")
        elif group not in enabled_planner_groups:
            errors.append(f"O grupo customizado '{group}' não existe entre os alimentos candidatos habilitados.")
        _validate_standard_mode(pgc.mode, pgc.min_g, pgc.max_g, pgc.ideal_g, f"grupo customizado '{pgc.group}'", errors)

    for mpgc in req.meal_planner_group_constraints:
        if _is_standard_inactive(mpgc.mode, mpgc.min_g, mpgc.max_g, mpgc.ideal_g):
            continue
        meal = normalize_meal_name(mpgc.meal)
        group = normalize_group_name(mpgc.group)
        if not meal:
            errors.append("Toda restrição de grupo por refeição precisa informar a refeição.")
        elif meal not in enabled_meals:
            errors.append(f"A refeição '{meal}' não existe entre os alimentos candidatos habilitados.")
        if not group:
            errors.append("Toda restrição de grupo por refeição precisa informar o grupo customizado.")
        elif group not in enabled_planner_groups:
            errors.append(f"O grupo customizado '{group}' não existe entre os alimentos candidatos habilitados.")
        _validate_standard_mode(mpgc.mode, mpgc.min_g, mpgc.max_g, mpgc.ideal_g, f"grupo customizado '{mpgc.group}' na refeição '{mpgc.meal}'", errors)

    for pgcc in req.planner_group_cardinality_constraints:
        if _is_cardinality_inactive(pgcc.mode, pgcc.min_count, pgcc.max_count, pgcc.exact_count, pgcc.ideal_count):
            continue
        group = normalize_group_name(pgcc.group)
        if not group:
            errors.append("Toda restrição de cardinalidade global por grupo customizado precisa informar o grupo.")
        elif group not in enabled_planner_groups:
            errors.append(f"O grupo customizado '{group}' não existe entre os alimentos candidatos habilitados.")
        _validate_cardinality_mode(pgcc.mode, pgcc.min_count, pgcc.max_count, pgcc.exact_count, pgcc.ideal_count, f"grupo customizado '{pgcc.group}'", errors)

    for mpgcc in req.meal_planner_group_cardinality_constraints:
        if _is_cardinality_inactive(mpgcc.mode, mpgcc.min_count, mpgcc.max_count, mpgcc.exact_count, mpgcc.ideal_count):
            continue
        meal = normalize_meal_name(mpgcc.meal)
        group = normalize_group_name(mpgcc.group)
        if not meal:
            errors.append("Toda restrição de cardinalidade por grupo dentro da refeição precisa informar a refeição.")
        elif meal not in enabled_meals:
            errors.append(f"A refeição '{meal}' não existe entre os alimentos candidatos habilitados.")
        if not group:
            errors.append("Toda restrição de cardinalidade por grupo dentro da refeição precisa informar o grupo customizado.")
        elif group not in enabled_planner_groups:
            errors.append(f"O grupo customizado '{group}' não existe entre os alimentos candidatos habilitados.")
        _validate_cardinality_mode(mpgcc.mode, mpgcc.min_count, mpgcc.max_count, mpgcc.exact_count, mpgcc.ideal_count, f"grupo customizado '{mpgcc.group}' na refeição '{mpgcc.meal}'", errors)

    for item in req.candidate_foods:
        if item.code not in FOOD_LOOKUP:
            errors.append(f"Código TACO inexistente: {item.code}")
        lo = sanitize_float(item.min_g) or 0.0
        hi = sanitize_float(item.max_g)
        if hi is not None and lo > hi:
            errors.append(f"Faixa inválida para o código {item.code}: mínimo maior que máximo.")
        selection_min = sanitize_float(item.selection_min_g)
        if selection_min is not None and selection_min < 0:
            errors.append(f"selection_min_g inválido para o código {item.code}.")
        if hi is not None and selection_min is not None and selection_min > hi:
            errors.append(f"selection_min_g maior que max_g para o código {item.code}.")
        if cardinality_active and item.enabled and (selection_min is None or selection_min <= 0):
            errors.append(f"Com cardinalidade ativa, selection_min_g deve ser maior que zero para o código {item.code}.")

    for gc in req.group_constraints:
        if not str(gc.group).strip():
            errors.append("Toda restrição por grupo precisa informar o grupo.")
        if gc.min_g is not None and gc.max_g is not None and float(gc.min_g) > float(gc.max_g):
            errors.append(f"Restrição de grupo inválida para '{gc.group}': mínimo maior que máximo.")

    for mc in req.meal_constraints:
        meal = normalize_meal_name(mc.meal)
        if not meal:
            errors.append("Toda restrição por refeição precisa informar a refeição.")
        elif meal not in enabled_meals:
            errors.append(f"A refeição '{meal}' não existe entre os alimentos candidatos habilitados.")
        if mc.min_g is not None and mc.max_g is not None and float(mc.min_g) > float(mc.max_g):
            errors.append(f"Restrição de refeição inválida para '{meal}': mínimo maior que máximo.")

    return errors


def build_and_solve(req: OptimizationRequest) -> dict[str, Any]:
    errors = validate_request(req)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    builder = LPBuilder(req)
    food_var_idx = builder.food_variable_indices()
    df = builder.food_df
    settings = req.settings
    solver_mode = settings.solver_mode
    objective_mode = settings.objective_mode
    weights = builder.weights
    use_cardinality = any(
        not _is_cardinality_inactive(c.mode, c.min_count, c.max_count, c.exact_count, c.ideal_count)
        for c in req.planner_group_cardinality_constraints + req.meal_planner_group_cardinality_constraints
    )
    selection_var_idx: list[int] = []

    active_nutrient_constraints = [c for c in req.nutrient_constraints if not _is_standard_inactive(c.mode, c.min_value, c.max_value, c.ideal_value)]
    active_meal_nutrient_constraints = [c for c in req.meal_nutrient_constraints if not _is_standard_inactive(c.mode, c.min_value, c.max_value, c.ideal_value)]
    active_planner_group_constraints = [c for c in req.planner_group_constraints if not _is_standard_inactive(c.mode, c.min_g, c.max_g, c.ideal_g)]
    active_meal_planner_group_constraints = [c for c in req.meal_planner_group_constraints if not _is_standard_inactive(c.mode, c.min_g, c.max_g, c.ideal_g)]
    active_planner_group_cardinality_constraints = [c for c in req.planner_group_cardinality_constraints if not _is_cardinality_inactive(c.mode, c.min_count, c.max_count, c.exact_count, c.ideal_count)]
    active_meal_planner_group_cardinality_constraints = [c for c in req.meal_planner_group_cardinality_constraints if not _is_cardinality_inactive(c.mode, c.min_count, c.max_count, c.exact_count, c.ideal_count)]

    def add_min_constraint(coeffs: Dict[int, float], value: float, label: str, penalty_weight: float = 1.0):
        scale = max(abs(value), 1.0)
        if solver_mode == "approximate":
            slack = builder.add_slack_var(
                name=f"slack::min::{label}",
                label=f"{label} abaixo do mínimo",
                cost=DEFAULT_APPROX_PENALTY * penalty_weight / scale,
            )
            builder.add_ub({**{k: -v for k, v in coeffs.items()}, slack: -1.0}, -value)
        else:
            builder.add_ub({k: -v for k, v in coeffs.items()}, -value)

    def add_max_constraint(coeffs: Dict[int, float], value: float, label: str, penalty_weight: float = 1.0):
        scale = max(abs(value), 1.0)
        if solver_mode == "approximate":
            slack = builder.add_slack_var(
                name=f"slack::max::{label}",
                label=f"{label} acima do máximo",
                cost=DEFAULT_APPROX_PENALTY * penalty_weight / scale,
            )
            builder.add_ub({**coeffs, slack: -1.0}, value)
        else:
            builder.add_ub(coeffs, value)

    def add_range_constraint(coeffs: Dict[int, float], min_value: float, max_value: float, label: str, penalty_weight: float = 1.0):
        add_min_constraint(coeffs, min_value, label, penalty_weight=penalty_weight)
        add_max_constraint(coeffs, max_value, label, penalty_weight=penalty_weight)

    def add_ideal_constraint(coeffs: Dict[int, float], value: float, label: str, penalty_weight: float = 1.0):
        scale = max(abs(value), 1.0)
        d_minus = builder.add_var(
            name=f"devminus::{label}",
            lb=0.0,
            ub=None,
            cost=weights["deviation"] * penalty_weight / scale,
            var_type="continuous",
        )
        d_plus = builder.add_var(
            name=f"devplus::{label}",
            lb=0.0,
            ub=None,
            cost=weights["deviation"] * penalty_weight / scale,
            var_type="continuous",
        )
        eq_coeffs = coeffs.copy()
        eq_coeffs[d_minus] = 1.0
        eq_coeffs[d_plus] = -1.0
        builder.add_eq(eq_coeffs, value)

    def add_exact_constraint(coeffs: Dict[int, float], value: float, label: str, penalty_weight: float = 1.0):
        scale = max(abs(value), 1.0)
        if solver_mode == "approximate":
            d_minus = builder.add_slack_var(
                name=f"slack::exact_minus::{label}",
                label=f"{label} abaixo do exato",
                cost=DEFAULT_APPROX_PENALTY * penalty_weight / scale,
            )
            d_plus = builder.add_slack_var(
                name=f"slack::exact_plus::{label}",
                label=f"{label} acima do exato",
                cost=DEFAULT_APPROX_PENALTY * penalty_weight / scale,
            )
            eq_coeffs = coeffs.copy()
            eq_coeffs[d_minus] = 1.0
            eq_coeffs[d_plus] = -1.0
            builder.add_eq(eq_coeffs, value)
        else:
            builder.add_eq(coeffs, value)

    kcal_coeff = df["Energia (kcal)"].fillna(0.0).to_numpy(dtype=float) / 100.0
    protein_coeff = df["Proteína (g)"].fillna(0.0).to_numpy(dtype=float) / 100.0
    total_gram_coeff = np.ones(len(df), dtype=float)

    if objective_mode == "minimize_calories":
        for i, var in enumerate(food_var_idx):
            builder.c[var] += float(kcal_coeff[i])
    elif objective_mode == "maximize_protein":
        for i, var in enumerate(food_var_idx):
            builder.c[var] += float(-protein_coeff[i])
    elif objective_mode == "minimize_cost":
        missing_cost = df["_cost_per_100g"].isna()
        if missing_cost.any():
            missing_codes = df.loc[missing_cost, "Código TACO"].astype(int).tolist()
            raise HTTPException(
                status_code=400,
                detail={
                    "errors": [
                        "O objetivo 'minimize_cost' exige custo por 100 g em todos os alimentos candidatos.",
                        f"Códigos sem custo: {missing_codes}",
                    ]
                },
            )
        for i, var in enumerate(food_var_idx):
            builder.c[var] += float(df.iloc[i]["_cost_per_100g"]) / 100.0
    elif objective_mode == "custom_weighted":
        cost_series = df["_cost_per_100g"].fillna(0.0).to_numpy(dtype=float) / 100.0
        for i, var in enumerate(food_var_idx):
            builder.c[var] += (
                weights["calories"] * float(kcal_coeff[i])
                - weights["protein"] * float(protein_coeff[i])
                + weights["cost"] * float(cost_series[i])
                + weights["grams"] * float(total_gram_coeff[i])
            )
    elif objective_mode == "target_matching":
        pass
    else:
        raise HTTPException(status_code=400, detail={"errors": [f"Objetivo inválido: {objective_mode}"]})

    if use_cardinality:
        fallback_upper_bound = float(settings.total_max_g) if settings.total_max_g is not None else DEFAULT_BIG_M_GRAMS
        if settings.total_max_g is None:
            builder.messages.append(
                f"Cardinalidade ativa sem total máximo global definido: foi usado limite técnico de {DEFAULT_BIG_M_GRAMS:.0f} g para candidatos sem max_g explícito."
            )
        for i, row in df.iterrows():
            y = builder.add_var(
                name=f"select::{int(row['Código TACO'])}::{row['_row_id']}",
                lb=0.0,
                ub=1.0,
                cost=0.0,
                var_type="binary",
            )
            selection_var_idx.append(y)
            upper = float(row["_max_g"]) if not pd.isna(row["_max_g"]) else fallback_upper_bound
            selection_min = float(row["_selection_min_g"]) if not pd.isna(row["_selection_min_g"]) else DEFAULT_SELECTION_MIN_G
            if selection_min > upper:
                raise HTTPException(
                    status_code=400,
                    detail={"errors": [f"selection_min_g maior que o limite superior efetivo para o código {int(row['Código TACO'])}."]},
                )
            builder.add_ub({food_var_idx[i]: 1.0, y: -upper}, 0.0)
            if selection_min > 0:
                builder.add_ub({food_var_idx[i]: -1.0, y: selection_min}, 0.0)

    all_food_coeffs = {food_var_idx[i]: 1.0 for i in range(len(food_var_idx))}
    if settings.total_min_g is not None:
        add_min_constraint(all_food_coeffs, float(settings.total_min_g), "Total de gramas")
    if settings.total_max_g is not None:
        add_max_constraint(all_food_coeffs, float(settings.total_max_g), "Total de gramas")

    for gc in req.group_constraints:
        mask = (df["Grupo"].fillna("") == gc.group).to_numpy()
        coeffs = {food_var_idx[i]: 1.0 for i in range(len(food_var_idx)) if mask[i]}
        if not coeffs:
            builder.messages.append(f"Restrição de grupo ignorada: nenhum candidato no grupo '{gc.group}'.")
            continue
        if gc.min_g is not None:
            add_min_constraint(coeffs, float(gc.min_g), f"Grupo {gc.group}")
        if gc.max_g is not None:
            add_max_constraint(coeffs, float(gc.max_g), f"Grupo {gc.group}")

    planner_group_names = sorted({group for group in df["_planner_group"].tolist() if group})
    planner_group_masks = {group: (df["_planner_group"] == group).to_numpy() for group in planner_group_names}

    for pgc in active_planner_group_constraints:
        group = normalize_group_name(pgc.group)
        mask = planner_group_masks.get(group)
        if mask is None:
            builder.messages.append(f"Restrição de grupo customizado ignorada: nenhum candidato no grupo '{group}'.")
            continue
        coeffs = {food_var_idx[i]: 1.0 for i in range(len(food_var_idx)) if mask[i]}
        weight = float(pgc.weight or DEFAULT_IDEAL_WEIGHT)
        label = f"Grupo customizado {group}"
        if pgc.mode == "min":
            add_min_constraint(coeffs, float(pgc.min_g), label, penalty_weight=weight)
        elif pgc.mode == "max":
            add_max_constraint(coeffs, float(pgc.max_g), label, penalty_weight=weight)
        elif pgc.mode == "range":
            add_range_constraint(coeffs, float(pgc.min_g), float(pgc.max_g), label, penalty_weight=weight)
        elif pgc.mode == "ideal":
            add_ideal_constraint(coeffs, float(pgc.ideal_g), label, penalty_weight=weight)

    meal_names = sorted({meal for meal in df["_meal"].tolist() if meal})
    meal_masks = {meal: (df["_meal"] == meal).to_numpy() for meal in meal_names}

    for mc in req.meal_constraints:
        meal = normalize_meal_name(mc.meal)
        mask = meal_masks.get(meal)
        if mask is None:
            builder.messages.append(f"Restrição de refeição ignorada: '{meal}' não aparece nos candidatos.")
            continue
        coeffs = {food_var_idx[i]: 1.0 for i in range(len(food_var_idx)) if mask[i]}
        if mc.min_g is not None:
            add_min_constraint(coeffs, float(mc.min_g), f"Refeição {meal}")
        if mc.max_g is not None:
            add_max_constraint(coeffs, float(mc.max_g), f"Refeição {meal}")

    for nc in active_nutrient_constraints:
        coeff_arr = df[nc.nutrient].fillna(0.0).to_numpy(dtype=float) / 100.0
        coeffs = {food_var_idx[i]: float(coeff_arr[i]) for i in range(len(food_var_idx))}
        weight = float(nc.weight or DEFAULT_IDEAL_WEIGHT)
        label = f"Nutriente {nc.nutrient}"
        if nc.mode == "min":
            add_min_constraint(coeffs, float(nc.min_value), label, penalty_weight=weight)
        elif nc.mode == "max":
            add_max_constraint(coeffs, float(nc.max_value), label, penalty_weight=weight)
        elif nc.mode == "range":
            add_range_constraint(coeffs, float(nc.min_value), float(nc.max_value), label, penalty_weight=weight)
        elif nc.mode == "ideal":
            add_ideal_constraint(coeffs, float(nc.ideal_value), label, penalty_weight=weight)

    for mnc in active_meal_nutrient_constraints:
        meal = normalize_meal_name(mnc.meal)
        mask = meal_masks.get(meal)
        if mask is None:
            builder.messages.append(f"Restrição nutricional por refeição ignorada: '{meal}' não aparece nos candidatos.")
            continue
        coeff_arr = df[mnc.nutrient].fillna(0.0).to_numpy(dtype=float) / 100.0
        coeffs = {food_var_idx[i]: float(coeff_arr[i]) for i in range(len(food_var_idx)) if mask[i]}
        weight = float(mnc.weight or DEFAULT_IDEAL_WEIGHT)
        label = f"Refeição {meal} | Nutriente {mnc.nutrient}"
        if mnc.mode == "min":
            add_min_constraint(coeffs, float(mnc.min_value), label, penalty_weight=weight)
        elif mnc.mode == "max":
            add_max_constraint(coeffs, float(mnc.max_value), label, penalty_weight=weight)
        elif mnc.mode == "range":
            add_range_constraint(coeffs, float(mnc.min_value), float(mnc.max_value), label, penalty_weight=weight)
        elif mnc.mode == "ideal":
            add_ideal_constraint(coeffs, float(mnc.ideal_value), label, penalty_weight=weight)

    for mpgc in active_meal_planner_group_constraints:
        meal = normalize_meal_name(mpgc.meal)
        group = normalize_group_name(mpgc.group)
        meal_mask = meal_masks.get(meal)
        if meal_mask is None:
            builder.messages.append(f"Restrição de grupo customizado por refeição ignorada: refeição '{meal}' não aparece nos candidatos.")
            continue
        planner_mask = planner_group_masks.get(group)
        if planner_mask is None:
            builder.messages.append(f"Restrição de grupo customizado por refeição ignorada: grupo '{group}' não aparece nos candidatos.")
            continue
        coeffs = {food_var_idx[i]: 1.0 for i in range(len(food_var_idx)) if meal_mask[i] and planner_mask[i]}
        if not coeffs:
            builder.messages.append(f"Restrição de grupo customizado por refeição ignorada: nenhum candidato em '{meal}' com grupo '{group}'.")
            continue
        weight = float(mpgc.weight or DEFAULT_IDEAL_WEIGHT)
        label = f"Refeição {meal} | Grupo customizado {group}"
        if mpgc.mode == "min":
            add_min_constraint(coeffs, float(mpgc.min_g), label, penalty_weight=weight)
        elif mpgc.mode == "max":
            add_max_constraint(coeffs, float(mpgc.max_g), label, penalty_weight=weight)
        elif mpgc.mode == "range":
            add_range_constraint(coeffs, float(mpgc.min_g), float(mpgc.max_g), label, penalty_weight=weight)
        elif mpgc.mode == "ideal":
            add_ideal_constraint(coeffs, float(mpgc.ideal_g), label, penalty_weight=weight)

    if use_cardinality:
        for pgcc in active_planner_group_cardinality_constraints:
            group = normalize_group_name(pgcc.group)
            mask = planner_group_masks.get(group)
            if mask is None:
                builder.messages.append(f"Cardinalidade global ignorada: grupo '{group}' não aparece nos candidatos.")
                continue
            coeffs = {selection_var_idx[i]: 1.0 for i in range(len(selection_var_idx)) if mask[i]}
            if not coeffs:
                builder.messages.append(f"Cardinalidade global ignorada: nenhum candidato no grupo '{group}'.")
                continue
            weight = float(pgcc.weight or DEFAULT_IDEAL_WEIGHT)
            label = f"Cardinalidade global do grupo {group}"
            if pgcc.mode == "min":
                add_min_constraint(coeffs, float(pgcc.min_count), label, penalty_weight=weight)
            elif pgcc.mode == "max":
                add_max_constraint(coeffs, float(pgcc.max_count), label, penalty_weight=weight)
            elif pgcc.mode == "range":
                add_range_constraint(coeffs, float(pgcc.min_count), float(pgcc.max_count), label, penalty_weight=weight)
            elif pgcc.mode == "ideal":
                add_ideal_constraint(coeffs, float(pgcc.ideal_count), label, penalty_weight=weight)
            elif pgcc.mode == "exact":
                add_exact_constraint(coeffs, float(pgcc.exact_count), label, penalty_weight=weight)

        for mpgcc in active_meal_planner_group_cardinality_constraints:
            meal = normalize_meal_name(mpgcc.meal)
            group = normalize_group_name(mpgcc.group)
            meal_mask = meal_masks.get(meal)
            planner_mask = planner_group_masks.get(group)
            if meal_mask is None:
                builder.messages.append(f"Cardinalidade por refeição ignorada: refeição '{meal}' não aparece nos candidatos.")
                continue
            if planner_mask is None:
                builder.messages.append(f"Cardinalidade por refeição ignorada: grupo '{group}' não aparece nos candidatos.")
                continue
            coeffs = {selection_var_idx[i]: 1.0 for i in range(len(selection_var_idx)) if meal_mask[i] and planner_mask[i]}
            if not coeffs:
                builder.messages.append(f"Cardinalidade por refeição ignorada: nenhum candidato em '{meal}' com grupo '{group}'.")
                continue
            weight = float(mpgcc.weight or DEFAULT_IDEAL_WEIGHT)
            label = f"Cardinalidade da refeição {meal} no grupo {group}"
            if mpgcc.mode == "min":
                add_min_constraint(coeffs, float(mpgcc.min_count), label, penalty_weight=weight)
            elif mpgcc.mode == "max":
                add_max_constraint(coeffs, float(mpgcc.max_count), label, penalty_weight=weight)
            elif mpgcc.mode == "range":
                add_range_constraint(coeffs, float(mpgcc.min_count), float(mpgcc.max_count), label, penalty_weight=weight)
            elif mpgcc.mode == "ideal":
                add_ideal_constraint(coeffs, float(mpgcc.ideal_count), label, penalty_weight=weight)
            elif mpgcc.mode == "exact":
                add_exact_constraint(coeffs, float(mpgcc.exact_count), label, penalty_weight=weight)

    builder.finalize_rows()

    constraints: list[LinearConstraint] = []
    if builder.a_ub:
        aub = np.array(builder.a_ub, dtype=float)
        bub = np.array(builder.b_ub, dtype=float)
        constraints.append(LinearConstraint(aub, -np.inf * np.ones(len(bub), dtype=float), bub))
    if builder.a_eq:
        aeq = np.array(builder.a_eq, dtype=float)
        beq = np.array(builder.b_eq, dtype=float)
        constraints.append(LinearConstraint(aeq, beq, beq))

    lower = np.array([(-np.inf if lb is None else lb) for lb, _ in builder.bounds], dtype=float)
    upper = np.array([(np.inf if ub is None else ub) for _, ub in builder.bounds], dtype=float)

    result = milp(
        c=np.array(builder.c, dtype=float),
        integrality=np.array(builder.integrality, dtype=np.int32),
        bounds=Bounds(lower, upper),
        constraints=constraints,
    )

    if not result.success:
        raise HTTPException(
            status_code=400,
            detail={
                "errors": [
                    f"O solver não encontrou solução. Status: {result.status} - {result.message}",
                    "Confira se há limites excessivamente restritivos, cardinalidades incompatíveis ou ausência de opções suficientes dentro de algum grupo/refeição.",
                ]
            },
        )

    x = np.array(result.x, dtype=float)
    solved_df = df.copy()
    solved_df["Gramas Otimizadas"] = [x[idx] for idx in food_var_idx]
    solved_df["Quantidade (100g) equivalente"] = solved_df["Gramas Otimizadas"] / 100.0
    if use_cardinality:
        solved_df["Selecionado"] = [int(round(x[idx])) for idx in selection_var_idx]
    else:
        activation = solved_df["_selection_min_g"].fillna(DEFAULT_SELECTION_MIN_G).astype(float)
        solved_df["Selecionado"] = (solved_df["Gramas Otimizadas"] >= activation - 1e-7).astype(int)
    solved_positive_df = solved_df[solved_df["Gramas Otimizadas"] > 1e-6].copy()

    food_solution: list[dict[str, Any]] = []
    for _, row in solved_positive_df.iterrows():
        item = {
            "row_id": row["_row_id"],
            "code": int(row["Código TACO"]),
            "description": row["Descrição"],
            "group": row.get("Grupo"),
            "planner_group": row.get("_planner_group") or None,
            "meal": row.get("_meal") or None,
            "grams": float(row["Gramas Otimizadas"]),
            "selected": int(row["Selecionado"]),
            "selection_min_g": None if pd.isna(row["_selection_min_g"]) else float(row["_selection_min_g"]),
            "cost_per_100g": None if pd.isna(row["_cost_per_100g"]) else float(row["_cost_per_100g"]),
            "estimated_cost": None if pd.isna(row["_cost_per_100g"]) else float(row["_cost_per_100g"] * row["Gramas Otimizadas"] / 100.0),
        }
        for metric in KEY_RESULT_METRICS:
            per100 = 0.0 if metric not in row or pd.isna(row[metric]) else float(row[metric])
            item[metric] = float(per100 * row["Gramas Otimizadas"] / 100.0)
        food_solution.append(item)

    vector = np.array([x[idx] for idx in food_var_idx], dtype=float)
    nutrient_summary = []
    selected_candidate_count = len(df)
    for nutrient in NUTRIENT_COLS:
        total = float((df[nutrient].fillna(0.0).to_numpy(dtype=float) / 100.0) @ vector)
        config = next((c for c in active_nutrient_constraints if c.nutrient == nutrient), None)
        nutrient_summary.append(
            {
                "nutrient": nutrient,
                "total": total,
                "constraint": None if not config else {
                    "mode": config.mode,
                    "min_value": config.min_value,
                    "max_value": config.max_value,
                    "ideal_value": config.ideal_value,
                    "weight": config.weight,
                },
                "missing_count_in_candidates": int(df[nutrient].isna().sum()),
                "selected_candidate_count": selected_candidate_count,
            }
        )

    def evaluate_constraint(total: float, mode: str, min_value: Optional[float], max_value: Optional[float], ideal_value: Optional[float]) -> tuple[str, Optional[float]]:
        tol = 1e-6
        if mode == "min" and min_value is not None:
            deviation = total - float(min_value)
            return ("ok" if deviation >= -tol else "violado", deviation)
        if mode == "max" and max_value is not None:
            deviation = float(max_value) - total
            return ("ok" if deviation >= -tol else "violado", deviation)
        if mode == "range" and min_value is not None and max_value is not None:
            if total < float(min_value) - tol:
                return ("violado", total - float(min_value))
            if total > float(max_value) + tol:
                return ("violado", float(max_value) - total)
            return ("ok", min(total - float(min_value), float(max_value) - total))
        if mode == "ideal" and ideal_value is not None:
            return ("ok", total - float(ideal_value))
        if mode == "exact" and ideal_value is not None:
            deviation = total - float(ideal_value)
            return ("ok" if abs(deviation) <= tol else "violado", deviation)
        return ("informativo", None)

    active_constraint_rows = []
    for nc in active_nutrient_constraints:
        total = next((row["total"] for row in nutrient_summary if row["nutrient"] == nc.nutrient), 0.0)
        status, deviation = evaluate_constraint(total, nc.mode, nc.min_value, nc.max_value, nc.ideal_value)
        active_constraint_rows.append(
            {
                "scope": "global",
                "nutrient": nc.nutrient,
                "mode": nc.mode,
                "realized": total,
                "min_value": nc.min_value,
                "max_value": nc.max_value,
                "ideal_value": nc.ideal_value,
                "deviation": deviation,
                "status": status,
            }
        )

    meal_summaries: list[dict[str, Any]] = []
    all_meals_for_summary = sorted({meal for meal in solved_positive_df["_meal"].fillna("").tolist() if meal})
    for meal in all_meals_for_summary:
        subset = solved_positive_df[solved_positive_df["_meal"] == meal]
        summary = {
            "meal": meal,
            "food_count": int(len(subset)),
            "selected_count": int(subset["Selecionado"].sum()),
            "total_grams": float(subset["Gramas Otimizadas"].sum()),
            "total_estimated_cost": float((pd.to_numeric(subset["_cost_per_100g"], errors="coerce").fillna(0.0) * subset["Gramas Otimizadas"] / 100.0).sum()),
        }
        for metric in KEY_RESULT_METRICS:
            summary[metric] = float((subset.get(metric, 0.0).fillna(0.0) * subset["Gramas Otimizadas"] / 100.0).sum()) if metric in subset.columns else 0.0
        meal_summaries.append(summary)

    active_meal_constraint_rows = []
    for mc in req.meal_constraints:
        meal = normalize_meal_name(mc.meal)
        subset = solved_positive_df[solved_positive_df["_meal"] == meal]
        total = float(subset["Gramas Otimizadas"].sum())
        realized_mode = "range" if mc.min_g is not None and mc.max_g is not None else ("min" if mc.min_g is not None else "max")
        status, deviation = evaluate_constraint(total, realized_mode, mc.min_g, mc.max_g, None)
        active_meal_constraint_rows.append(
            {
                "scope": "meal_total",
                "meal": meal,
                "constraint_label": "Total de gramas da refeição",
                "nutrient": None,
                "mode": realized_mode,
                "realized": total,
                "min_value": mc.min_g,
                "max_value": mc.max_g,
                "ideal_value": None,
                "deviation": deviation,
                "status": status,
            }
        )

    for mnc in active_meal_nutrient_constraints:
        meal = normalize_meal_name(mnc.meal)
        subset = solved_positive_df[solved_positive_df["_meal"] == meal]
        total = float((subset[mnc.nutrient].fillna(0.0) * subset["Gramas Otimizadas"] / 100.0).sum()) if mnc.nutrient in subset.columns else 0.0
        status, deviation = evaluate_constraint(total, mnc.mode, mnc.min_value, mnc.max_value, mnc.ideal_value)
        active_meal_constraint_rows.append(
            {
                "scope": "meal_nutrient",
                "meal": meal,
                "constraint_label": mnc.nutrient,
                "nutrient": mnc.nutrient,
                "mode": mnc.mode,
                "realized": total,
                "min_value": mnc.min_value,
                "max_value": mnc.max_value,
                "ideal_value": mnc.ideal_value,
                "deviation": deviation,
                "status": status,
            }
        )

    planner_group_summaries: list[dict[str, Any]] = []
    all_planner_groups_for_summary = sorted({group for group in solved_positive_df["_planner_group"].fillna("").tolist() if group})
    for group in all_planner_groups_for_summary:
        subset = solved_positive_df[solved_positive_df["_planner_group"] == group]
        planner_group_summaries.append(
            {
                "scope": "global_group",
                "group": group,
                "meal": None,
                "food_count": int(len(subset)),
                "selected_count": int(subset["Selecionado"].sum()),
                "total_grams": float(subset["Gramas Otimizadas"].sum()),
            }
        )
        for meal in sorted({m for m in subset["_meal"].fillna("").tolist() if m}):
            submeal = subset[subset["_meal"] == meal]
            planner_group_summaries.append(
                {
                    "scope": "meal_group",
                    "group": group,
                    "meal": meal,
                    "food_count": int(len(submeal)),
                    "selected_count": int(submeal["Selecionado"].sum()),
                    "total_grams": float(submeal["Gramas Otimizadas"].sum()),
                }
            )

    active_group_constraint_rows = []
    for pgc in active_planner_group_constraints:
        group = normalize_group_name(pgc.group)
        subset = solved_positive_df[solved_positive_df["_planner_group"] == group]
        total = float(subset["Gramas Otimizadas"].sum())
        status, deviation = evaluate_constraint(total, pgc.mode, pgc.min_g, pgc.max_g, pgc.ideal_g)
        active_group_constraint_rows.append(
            {
                "scope": "planner_group_global",
                "group": group,
                "meal": None,
                "mode": pgc.mode,
                "realized": total,
                "min_value": pgc.min_g,
                "max_value": pgc.max_g,
                "ideal_value": pgc.ideal_g,
                "deviation": deviation,
                "status": status,
            }
        )

    for mpgc in active_meal_planner_group_constraints:
        meal = normalize_meal_name(mpgc.meal)
        group = normalize_group_name(mpgc.group)
        subset = solved_positive_df[(solved_positive_df["_meal"] == meal) & (solved_positive_df["_planner_group"] == group)]
        total = float(subset["Gramas Otimizadas"].sum())
        status, deviation = evaluate_constraint(total, mpgc.mode, mpgc.min_g, mpgc.max_g, mpgc.ideal_g)
        active_group_constraint_rows.append(
            {
                "scope": "planner_group_meal",
                "group": group,
                "meal": meal,
                "mode": mpgc.mode,
                "realized": total,
                "min_value": mpgc.min_g,
                "max_value": mpgc.max_g,
                "ideal_value": mpgc.ideal_g,
                "deviation": deviation,
                "status": status,
            }
        )

    active_group_cardinality_rows = []
    for pgcc in active_planner_group_cardinality_constraints:
        group = normalize_group_name(pgcc.group)
        subset = solved_df[solved_df["_planner_group"] == group]
        total = float(subset["Selecionado"].sum())
        target = pgcc.exact_count if pgcc.mode == "exact" else pgcc.ideal_count
        status, deviation = evaluate_constraint(total, pgcc.mode, pgcc.min_count, pgcc.max_count, target)
        active_group_cardinality_rows.append(
            {
                "scope": "planner_group_global_count",
                "group": group,
                "meal": None,
                "mode": pgcc.mode,
                "realized": total,
                "min_value": pgcc.min_count,
                "max_value": pgcc.max_count,
                "ideal_value": target,
                "deviation": deviation,
                "status": status,
            }
        )

    for mpgcc in active_meal_planner_group_cardinality_constraints:
        meal = normalize_meal_name(mpgcc.meal)
        group = normalize_group_name(mpgcc.group)
        subset = solved_df[(solved_df["_meal"] == meal) & (solved_df["_planner_group"] == group)]
        total = float(subset["Selecionado"].sum())
        target = mpgcc.exact_count if mpgcc.mode == "exact" else mpgcc.ideal_count
        status, deviation = evaluate_constraint(total, mpgcc.mode, mpgcc.min_count, mpgcc.max_count, target)
        active_group_cardinality_rows.append(
            {
                "scope": "planner_group_meal_count",
                "group": group,
                "meal": meal,
                "mode": mpgcc.mode,
                "realized": total,
                "min_value": mpgcc.min_count,
                "max_value": mpgcc.max_count,
                "ideal_value": target,
                "deviation": deviation,
                "status": status,
            }
        )

    slack_messages = []
    any_violations = False
    for idx, label in builder.slack_var_labels.items():
        used = float(x[idx])
        if used > 1e-7:
            slack_messages.append(f"Violação aproximada usada: {label} (slack={used:.4f}).")
            any_violations = True

    warnings = []
    if objective_mode in {"maximize_protein", "minimize_cost"} and settings.total_max_g is None and not any(sanitize_float(c.max_g) is not None for c in req.candidate_foods):
        warnings.append("Sem limites superiores explícitos, alguns objetivos podem produzir soluções extremas. Considere definir máximo por alimento, máximo total de gramas ou máximos por refeição.")
    if use_cardinality:
        warnings.append("Cardinalidade por grupo usa variáveis binárias. Um alimento só conta como selecionado se atingir selection_min_g.")
    warnings.append("Valores 'Tr' foram tratados como zero operacional no solver.")
    warnings.append("Valores ausentes ('*' ou células vazias) foram tratados como desconhecidos e convertidos para zero no cálculo de totais para fins de otimização.")

    return {
        "status": "optimal_with_violations" if any_violations else "optimal",
        "objective_mode": objective_mode,
        "solver_mode": solver_mode,
        "objective_value": float(result.fun),
        "foods": food_solution,
        "meal_summaries": meal_summaries,
        "planner_group_summaries": planner_group_summaries,
        "nutrients": nutrient_summary,
        "active_constraints": active_constraint_rows,
        "active_group_constraints": active_group_constraint_rows,
        "active_group_cardinality_constraints": active_group_cardinality_rows,
        "active_meal_constraints": active_meal_constraint_rows,
        "warnings": warnings + slack_messages + builder.messages,
        "total_grams": float(sum(item["grams"] for item in food_solution)),
        "total_estimated_cost": float(sum(item["estimated_cost"] or 0.0 for item in food_solution)),
    }


app = FastAPI(title=APP_TITLE)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/meta")
def meta() -> dict[str, Any]:
    foods = (
        TACO_DF[["Código TACO", "Descrição", "Grupo"]]
        .rename(columns={"Código TACO": "code", "Descrição": "description", "Grupo": "group"})
        .to_dict(orient="records")
    )
    return {
        "foods": foods,
        "groups": TACO_META["groups"],
        "nutrients": TACO_META["nutrients"],
        "key_metrics": KEY_RESULT_METRICS,
    }


@app.get("/api/download/candidate-template")
def download_candidate_template() -> FileResponse:
    return FileResponse(DATA_DIR / "candidate_template.csv", filename="candidate_template.csv", media_type="text/csv")


@app.get("/api/examples")
def list_examples() -> dict[str, Any]:
    examples = _load_example_presets()
    return {
        "examples": [
            {key: value for key, value in item.items() if key not in {"payload", "sort_order"}}
            for item in examples
        ]
    }


@app.get("/api/examples/{example_id}")
def get_example(example_id: str) -> dict[str, Any]:
    examples = {item["id"]: item for item in _load_example_presets()}
    example = examples.get(example_id)
    if not example:
        raise HTTPException(status_code=404, detail={"errors": [f"Exemplo não encontrado: {example_id}"]})
    return example


@app.post("/api/reports/markdown")
def export_markdown_report(req: DetailedReportRequest) -> Response:
    try:
        content = build_markdown_report(req.result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from exc
    return Response(
        content=content.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{report_download_name("md")}"'},
    )


@app.post("/api/reports/pdf")
def export_pdf_report(req: DetailedReportRequest) -> Response:
    try:
        content = build_pdf_report(req.result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from exc
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{report_download_name("pdf")}"'},
    )


@app.post("/api/optimize")
def optimize(req: OptimizationRequest) -> dict[str, Any]:
    return build_and_solve(req)


@app.get("/healthz")
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "service": APP_TITLE}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "5589")))
