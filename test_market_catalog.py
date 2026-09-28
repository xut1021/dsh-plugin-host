import io
import json
import unittest
from unittest.mock import patch

import market


class MarketCatalogTests(unittest.TestCase):
    def test_stars_accept_nonnegative_integer_counts_including_zero(self):
        for value in (0, 2, 272, 72899, 2.0):
            with self.subTest(value=value):
                self.assertEqual(market.normalize_stars(value), int(value))
                self.assertIs(type(market.normalize_stars(value)), int)

    def test_missing_invalid_or_unsafe_counts_stay_unknown(self):
        for value in (None, -1, -2.0, True, False, '272', '1.2k', 'unknown',
                      1.5, float('inf'), float('-inf'), float('nan'), 2**53, {}, []):
            with self.subTest(value=repr(value)):
                self.assertIsNone(market.normalize_stars(value))
        item = market.normalize_catalog({'plugins': [{'name': 'missing-count'}]})['items'][0]
        self.assertIsNone(item['stars'])
        self.assertIsNone(item['stars_as_of'])

    def test_metric_does_not_change_catalog_selection_or_installability(self):
        source = {'updated': '2026-09-28', 'categories': {'tools': {'zh': '工具'}},
                  'plugins': [
                      {'name': 'first', 'npm': '@scope/first', 'version': '1.2.3',
                       'stars': 0, 'category': 'tools'},
                      {'name': 'second', 'npm': 'second', 'version': 'latest', 'stars': -5},
                      {'name': 'third', 'npm': 'third', 'version': '0.1.0', 'stars': None},
                      {'name': None, 'stars': 200}, 'invalid-row']}
        result = market.normalize_catalog(source)
        self.assertEqual([p['name'] for p in result['items']], ['first', 'second', 'third'])
        self.assertEqual([p['installable'] for p in result['items']], [True, False, True])
        self.assertEqual([p['stars'] for p in result['items']], [0, None, None])
        self.assertEqual(result['categories'], {'tools': '工具'})
        self.assertEqual(result['items'][0]['categories'], ['tools'])
        self.assertEqual(result['source'], market.CATALOG_URL)
        self.assertTrue(all(p['stars_source'] == market.CATALOG_URL for p in result['items']))
        self.assertTrue(all(p['stars_as_of'] == '2026-09-28' for p in result['items']))

    def test_captured_live_catalog_sample(self):
        # Read directly from CATALOG_URL on 2026-09-29; its snapshot date is 09-28.
        # The source contains integer stars (4371 rows) and null (11 rows).
        result = market.normalize_catalog({'updated': '2026-09-28', 'plugins': [
            {'name': 'dsh-memory', 'npm': '@furongjun1999/dsh-memory',
             'owner': 'FuRongJun-1999', 'version': '0.6.0',
             'url': 'https://github.com/FuRongJun-1999/dsh-memory', 'stars': 272}]})
        item = result['items'][0]
        self.assertEqual(item['stars'], 272)
        self.assertEqual(item['stars_as_of'], '2026-09-28')
        self.assertEqual(item['stars_source'], market.CATALOG_URL)
        self.assertEqual(item['npm'], '@furongjun1999/dsh-memory')
        self.assertTrue(item['installable'])

    def test_fetch_uses_one_catalog_request_for_all_star_counts(self):
        payload = json.dumps({'updated': '2026-09-28', 'plugins': [
            {'name': 'first', 'stars': 3}, {'name': 'second', 'stars': 0}]}).encode()
        with patch.object(market, 'urlopen', return_value=io.BytesIO(payload)) as request:
            catalog = market.fetch_catalog()
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[0].full_url, market.CATALOG_URL)
        self.assertEqual([p['stars'] for p in catalog['items']], [3, 0])


if __name__ == '__main__':
    unittest.main()
