from __future__ import annotations

import unittest

from kicad_parts_collectors.app import dropped_zip_paths


class AppTests(unittest.TestCase):
    def test_dropped_zip_paths_filters_zip_files(self) -> None:
        paths = dropped_zip_paths(("C:/parts/LIB_53261-0271.zip", "C:/parts/readme.txt"))

        self.assertEqual(["C:/parts/LIB_53261-0271.zip"], paths)


if __name__ == "__main__":
    unittest.main()
