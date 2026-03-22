import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
import main


class TacoOptimizerApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def base_candidates(self):
        return [
            {"code": 182, "max_g": 200, "meal": "Café da manhã", "planner_group": "Fruta", "selection_min_g": 60, "enabled": True},
            {"code": 458, "max_g": 300, "meal": "Café da manhã", "planner_group": "Laticínio", "selection_min_g": 100, "enabled": True},
            {"code": 53, "max_g": 120, "meal": "Café da manhã", "planner_group": "Cereal", "selection_min_g": 40, "enabled": True},
            {"code": 410, "max_g": 250, "meal": "Almoço", "planner_group": "Proteína", "selection_min_g": 80, "enabled": True},
            {"code": 3, "max_g": 250, "meal": "Almoço", "planner_group": "Cereal", "selection_min_g": 70, "enabled": True},
            {"code": 326, "max_g": 220, "meal": "Almoço", "planner_group": "Leguminosa", "selection_min_g": 60, "enabled": True},
        ]

    def test_meta_endpoint(self):
        res = self.client.get('/api/meta')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('foods', data)
        self.assertIn('nutrients', data)
        self.assertGreater(len(data['foods']), 100)
        self.assertGreater(len(data['nutrients']), 20)

    def test_candidate_template_download(self):
        res = self.client.get('/api/download/candidate-template')
        self.assertEqual(res.status_code, 200)
        text = res.text
        self.assertIn('selection_min_g', text)
        self.assertIn('planner_group', text)

    def test_feasible_exact_solution_with_meal_and_cardinality(self):
        payload = {
            'candidate_foods': self.base_candidates(),
            'nutrient_constraints': [
                {'nutrient': 'Proteína (g)', 'mode': 'min', 'min_value': 35},
            ],
            'meal_constraints': [
                {'meal': 'Café da manhã', 'min_g': 150, 'max_g': 500},
                {'meal': 'Almoço', 'min_g': 250, 'max_g': 650},
            ],
            'meal_planner_group_cardinality_constraints': [
                {'meal': 'Almoço', 'group': 'Proteína', 'mode': 'exact', 'exact_count': 1},
            ],
            'settings': {'objective_mode': 'target_matching', 'solver_mode': 'exact', 'total_max_g': 900},
        }
        res = self.client.post('/api/optimize', json=payload)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data['status'], 'optimal')
        # protein exact count at lunch respected
        count_row = next(row for row in data['active_group_cardinality_constraints'] if row['group'] == 'Proteína' and row['meal'] == 'Almoço')
        self.assertEqual(int(round(count_row['realized'])), 1)
        self.assertEqual(count_row['status'], 'ok')
        self.assertGreater(data['total_grams'], 0)

    def test_approximate_mode_reports_violations_for_infeasible_problem(self):
        payload = {
            'candidate_foods': [
                {'code': 182, 'max_g': 100, 'meal': 'Café', 'planner_group': 'Fruta', 'selection_min_g': 50, 'enabled': True},
            ],
            'nutrient_constraints': [
                {'nutrient': 'Proteína (g)', 'mode': 'min', 'min_value': 50},
            ],
            'settings': {'objective_mode': 'target_matching', 'solver_mode': 'approximate', 'total_max_g': 100},
        }
        res = self.client.post('/api/optimize', json=payload)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data['status'], 'optimal_with_violations')
        self.assertTrue(any('Violação aproximada usada' in w for w in data['warnings']))

    def test_minimize_cost_requires_costs_for_all_candidates(self):
        payload = {
            'candidate_foods': self.base_candidates(),
            'settings': {'objective_mode': 'minimize_cost', 'solver_mode': 'exact'},
        }
        res = self.client.post('/api/optimize', json=payload)
        self.assertEqual(res.status_code, 400)
        text = res.text
        self.assertIn('minimize_cost', text)
        self.assertIn('custo', text.lower())

    def test_inactive_none_constraints_are_ignored(self):
        payload = {
            'candidate_foods': self.base_candidates(),
            'nutrient_constraints': [
                {'nutrient': 'Proteína (g)', 'mode': 'none'},
            ],
            'planner_group_constraints': [
                {'group': '', 'mode': 'none'},
            ],
            'planner_group_cardinality_constraints': [
                {'group': '', 'mode': 'none'},
            ],
            'meal_nutrient_constraints': [
                {'meal': '', 'nutrient': 'Energia (kcal)', 'mode': 'none'},
            ],
            'meal_planner_group_constraints': [
                {'meal': '', 'group': '', 'mode': 'none'},
            ],
            'meal_planner_group_cardinality_constraints': [
                {'meal': '', 'group': '', 'mode': 'none'},
            ],
            'settings': {'objective_mode': 'target_matching', 'solver_mode': 'exact', 'total_max_g': 600},
        }
        res = self.client.post('/api/optimize', json=payload)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data['status'], 'optimal')
        self.assertEqual(data['active_constraints'], [])
        self.assertEqual(data['active_group_constraints'], [])
        self.assertEqual(data['active_group_cardinality_constraints'], [])
        self.assertEqual(data['active_meal_constraints'], [])

    def test_cardinality_requires_positive_selection_min(self):
        payload = {
            'candidate_foods': [
                {'code': 410, 'max_g': 250, 'meal': 'Almoço', 'planner_group': 'Proteína', 'selection_min_g': 0, 'enabled': True},
                {'code': 412, 'max_g': 250, 'meal': 'Almoço', 'planner_group': 'Proteína', 'selection_min_g': 0, 'enabled': True},
            ],
            'meal_planner_group_cardinality_constraints': [
                {'meal': 'Almoço', 'group': 'Proteína', 'mode': 'exact', 'exact_count': 1},
            ],
            'settings': {'objective_mode': 'target_matching', 'solver_mode': 'exact', 'total_max_g': 500},
        }
        res = self.client.post('/api/optimize', json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn('selection_min_g', res.text)
        self.assertIn('maior que zero', res.text)


if __name__ == '__main__':
    unittest.main()
