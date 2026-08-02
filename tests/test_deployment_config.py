import tomllib
import unittest
from pathlib import Path

import yaml

from domain_manager import domain_url_path, select_default_domain


REPO_ROOT = Path(__file__).resolve().parents[1]


class DefaultDomainTests(unittest.TestCase):
    def test_configured_domain_wins(self):
        self.assertEqual(
            select_default_domain(["bank", "healthcare"], "bank"), "bank"
        )

    def test_healthcare_is_evercrest_fallback(self):
        self.assertEqual(
            select_default_domain(["bank", "healthcare", "restaurant"]),
            "healthcare",
        )

    def test_first_domain_is_last_resort(self):
        self.assertEqual(select_default_domain(["bank", "restaurant"]), "bank")

    def test_empty_domain_list_is_rejected(self):
        with self.assertRaises(ValueError):
            select_default_domain([])

    def test_healthcare_uses_patient_chart_path(self):
        self.assertEqual(domain_url_path("healthcare"), "patientchart")

    def test_other_domains_keep_their_name(self):
        self.assertEqual(domain_url_path("bank"), "bank")


class GalileoFallbackTests(unittest.TestCase):
    def test_healthcare_keeps_original_galileo_target(self):
        config = yaml.safe_load(
            (REPO_ROOT / "domains/healthcare/config.yaml").read_text()
        )
        self.assertEqual(config["galileo"]["project"], "demo-test")
        self.assertEqual(config["galileo"]["log_stream"], "Agent")

    def test_hosted_template_does_not_override_domain_target(self):
        secrets = tomllib.loads(
            (REPO_ROOT / ".streamlit/secrets.toml.template").read_text()
        )
        self.assertNotIn("galileo_project", secrets)
        self.assertNotIn("galileo_log_stream", secrets)


if __name__ == "__main__":
    unittest.main()
