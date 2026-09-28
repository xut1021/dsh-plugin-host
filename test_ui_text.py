import unittest

from ui_text import fit_text, wrap_preview


class MeasuredFont:
    """Count font crossings; CJK and ellipsis deliberately have unequal widths."""
    def __init__(self):
        self.calls = 0

    @staticmethod
    def width(value):
        return sum(2 if '\u4e00' <= char <= '\u9fff' or char == '…' else 1 for char in value)

    def __call__(self, value):
        self.calls += 1
        return self.width(value)


class TextPreviewTests(unittest.TestCase):
    def test_empty_and_nonpositive_bounds(self):
        measure = MeasuredFont()
        for width in (-1, 0, 10):
            self.assertEqual(fit_text('', width, measure), '')
            self.assertEqual(wrap_preview(' \t\n ', width, measure), '')
        self.assertEqual(fit_text('abc', 0, measure), '')
        self.assertEqual(wrap_preview('abc', 10, measure, lines=0), '')
        self.assertEqual(measure.calls, 0)

    def test_exact_fit_is_unchanged(self):
        for value in ('abcdef', '中文测试', '中A文B'):
            measure = MeasuredFont()
            self.assertEqual(fit_text(value, measure.width(value), measure), value)
            self.assertEqual(measure.calls, 1)

    def test_ellipsis_has_its_own_width(self):
        measure = MeasuredFont()
        self.assertEqual(fit_text('abcdefgh', 5, measure), 'abc…')
        self.assertEqual(fit_text('中文测试', 5, measure), '中…')
        self.assertEqual(fit_text('abcdef', 2, measure), '…')
        self.assertEqual(fit_text('abcdef', 1, measure), '')
        # A short complete string remains visible even when an ellipsis cannot fit.
        self.assertEqual(fit_text('a', 1, measure), 'a')

    def test_wrap_chinese_and_exact_last_line(self):
        measure = MeasuredFont()
        self.assertEqual(wrap_preview('中文测试文本', 4, measure), '中文\n测试\n文本')
        self.assertEqual(wrap_preview('中文测试文本更多', 4, measure), '中文\n测试\n文…')

    def test_wrap_english_whitespace_and_long_words(self):
        measure = MeasuredFont()
        self.assertEqual(wrap_preview(' one\t two\nthree ', 7, measure), 'one two\nthree')
        self.assertEqual(wrap_preview('one two three four five', 7, measure), 'one two\nthree\nfour…')
        self.assertEqual(wrap_preview('abcdefghijklmnop', 5, measure), 'abcde\nfghij\nklm…')
        self.assertEqual(wrap_preview('a b c d', 5, measure, lines=1), 'a b…')

    def test_mixed_text_does_not_backtrack_to_a_distant_english_space(self):
        examples = [
            ('DeepSeek Harness 的判断内核：认识循环', '让判断有来处，反馈有归因，规划可回看；海马体把运行经历保存。'),
            ('DeepSeek Harness 的判断内核', '：认识循环让判断有来处。'),
            ('DeepSeek Harness 的判断内核：', '认识循环让判断有来处。'),
            ('Alpha Beta,', 'Gamma Delta'),
            ('DeepSeek Harness', '中文内容继续显示'),
        ]
        for prefix, remainder in examples:
            with self.subTest(prefix=prefix):
                measure = MeasuredFont()
                result = wrap_preview(prefix + remainder, measure.width(prefix), measure)
                self.assertEqual(result.splitlines()[0], prefix)
                self.assertLessEqual(measure.calls, 40)
        measure = MeasuredFont()
        self.assertEqual(wrap_preview('use abc-123 now', 10, measure), 'use\nabc-123\nnow')

    def test_narrow_width_never_loops_or_overflows(self):
        measure = MeasuredFont()
        self.assertEqual(wrap_preview('中文', 1, measure), '')
        self.assertEqual(wrap_preview('abc中文', 2, measure), 'ab\nc\n…')
        for value in ('abc 中文 def', '中文' * 50, 'W' * 200):
            for width in range(1, 10):
                rendered = wrap_preview(value, width, measure)
                self.assertLessEqual(len(rendered.splitlines()), 3)
                self.assertTrue(all(measure.width(line) <= width for line in rendered.splitlines()))

    def test_long_text_has_bounded_measurement_calls(self):
        for value, width in [('中文测试' * 10000, 80), ('anEnglishWord' * 10000, 80)]:
            measure = MeasuredFont()
            result = wrap_preview(value, width, measure)
            self.assertEqual(len(result.splitlines()), 3)
            self.assertTrue(result.endswith('…'))
            self.assertLessEqual(measure.calls, 40)
            self.assertTrue(all(measure.width(line) <= width for line in result.splitlines()))
            single = MeasuredFont()
            self.assertTrue(fit_text(value, width, single).endswith('…'))
            self.assertLessEqual(single.calls, 16)


if __name__ == '__main__':
    unittest.main()
