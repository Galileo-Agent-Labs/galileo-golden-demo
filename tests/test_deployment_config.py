import unittest

from domain_manager import domain_url_path, select_default_domain


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


if __name__ == "__main__":
    unittest.main()
