import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
import main


class TacoOptimizerReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def _base_candidates(self):
        return [
            {"code": 182, "max_g": 200, "meal": "Café da manhã", "planner_group": "Fruta", "selection_min_g": 60, "enabled": True},
            {"code": 458, "max_g": 300, "meal": "Café da manhã", "planner_group": "Laticínio", "selection_min_g": 100, "enabled": True},
            {"code": 53, "max_g": 120, "meal": "Café da manhã", "planner_group": "Cereal", "selection_min_g": 40, "enabled": True},
            {"code": 410, "max_g": 250, "meal": "Almoço", "planner_group": "Proteína", "selection_min_g": 80, "enabled": True},
            {"code": 3, "max_g": 250, "meal": "Almoço", "planner_group": "Cereal", "selection_min_g": 70, "enabled": True},
            {"code": 326, "max_g": 220, "meal": "Almoço", "planner_group": "Leguminosa", "selection_min_g": 60, "enabled": True},
        ]

    def _solve_example(self):
        payload = {
            "candidate_foods": self._base_candidates(),
            "nutrient_constraints": [
                {"nutrient": "Proteína (g)", "mode": "min", "min_value": 35},
            ],
            "meal_constraints": [
                {"meal": "Café da manhã", "min_g": 150, "max_g": 500},
                {"meal": "Almoço", "min_g": 250, "max_g": 650},
            ],
            "settings": {"objective_mode": "target_matching", "solver_mode": "exact", "total_max_g": 900},
        }
        response = self.client.post("/api/optimize", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_markdown_report_endpoint_returns_patient_friendly_content(self):
        result = self._solve_example()
        response = self.client.post("/api/reports/markdown", json={"result": result})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("text/markdown", response.headers["content-type"])
        self.assertIn("attachment;", response.headers["content-disposition"])
        text = response.text
        self.assertIn("## Como explicar para o paciente", text)
        self.assertIn("## Cardápio sugerido por refeição", text)
        self.assertIn("Café da manhã", text)
        self.assertIn("Proteína (g)", text)

    def test_pdf_report_endpoint_returns_pdf_bytes(self):
        result = self._solve_example()
        response = self.client.post("/api/reports/pdf", json={"result": result})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertIn("attachment;", response.headers["content-disposition"])
        self.assertTrue(response.content.startswith(b"%PDF-1.4"))
        self.assertIn(b"/WinAnsiEncoding", response.content)
        self.assertIn("Relatório detalhado do cardápio otimizado".encode("cp1252"), response.content)
        self.assertIn("Café da manhã".encode("cp1252"), response.content)
        self.assertIn(b"%%EOF", response.content)

    def test_report_requires_solution_data(self):
        response = self.client.post("/api/reports/markdown", json={"result": {}})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Calcule um cardápio", response.text)


if __name__ == "__main__":
    unittest.main()
