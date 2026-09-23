from __future__ import annotations

import unittest

from kicad_parts_collectors.app import dropped_zip_paths, ordered_property_names


class AppTests(unittest.TestCase):
    def test_dropped_zip_paths_filters_zip_files(self) -> None:
        paths = dropped_zip_paths(("C:/parts/LIB_53261-0271.zip", "C:/parts/readme.txt"))

        self.assertEqual(["C:/parts/LIB_53261-0271.zip"], paths)

    def test_ordered_property_names_places_common_fields_first(self) -> None:
        properties = {
            "Manufacturer_Name": "Analog Devices",
            "Value": "ADM3055",
            "MPN": "ADM3055EBRIZ-RL",
            "Datasheet": "https://example.com/ds.pdf",
            "LCSC Part": "C658105",
            "LCSC": "C658105",
            "Footprint": "hrobotics:ADM3055",
        }

        self.assertEqual(
            ["Value", "Footprint", "Datasheet", "MPN", "LCSC", "LCSC Part", "Manufacturer_Name"],
            ordered_property_names(properties),
        )


if __name__ == "__main__":
    unittest.main()
