import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from kicad_parts_collectors.parts_search import search_parts


class PartsSearchTests(unittest.TestCase):
    @patch("kicad_parts_collectors.parts_search.urllib.request.urlopen")
    def test_keyword_page_and_zero_stock(self, urlopen):
        data = {"code": 200, "data": {"componentPageInfo": {
            "total": 21, "list": [{"componentCode": "C1", "stockCount": 0}]}}}
        response = MagicMock()
        response.read.return_value = json.dumps(data).encode()
        urlopen.return_value.__enter__.return_value = response
        result = search_parts(" MOSFET ", 2)
        self.assertEqual(result["results"][0]["stockCount"], 0)
        body = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(body, {"keyword": "MOSFET", "currentPage": 2, "pageSize": 20})

    @patch("kicad_parts_collectors.parts_search.urllib.request.urlopen")
    def test_empty_search_accepts_null_list(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = (
            b'{"code":200,"data":{"componentPageInfo":{"total":0,"list":null}}}')
        self.assertEqual(search_parts("no-match"), {"results": [], "total": 0})

    @patch("kicad_parts_collectors.parts_search.urllib.request.urlopen")
    def test_network_failure_is_not_empty_result(self, urlopen):
        urlopen.side_effect = URLError("offline")
        with self.assertRaises(URLError):
            search_parts("MOSFET")

    @patch("kicad_parts_collectors.parts_search.urllib.request.urlopen")
    def test_server_error_is_not_empty_result(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"success":false}'
        with self.assertRaises(ValueError):
            search_parts("MOSFET")
