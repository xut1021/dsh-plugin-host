"""Bounded preview text fitting without per-character font measurements."""

ELLIPSIS = '…'


def _prefix_length(value, width, measure, suffix=''):
    """Find the longest fitting prefix; the empty prefix is already known to fit."""
    low, high = 0, min(32, len(value))
    while high:
        if measure(value[:high] + suffix) > width:
            break
        low = high
        if high == len(value):
            return high
        high = min(len(value), high * 2)
    while low + 1 < high:
        middle = (low + high) // 2
        if measure(value[:middle] + suffix) <= width:
            low = middle
        else:
            high = middle
    return low


def fit_text(value, width, measure):
    """Fit a single-line string, reserving the measured ellipsis width when cut."""
    if not value or width <= 0:
        return ''
    if measure(value) <= width:
        return value
    if measure(ELLIPSIS) > width:
        return ''
    length = _prefix_length(value, width, measure, ELLIPSIS)
    return value[:length].rstrip() + ELLIPSIS


def wrap_preview(value, width, measure, lines=3):
    """Normalize whitespace and fit at most `lines`, truncating only the last.

    Backtrack to a space only when the cut splits an ASCII word. Chinese text,
    punctuation boundaries and long words use the longest fitting prefix.
    """
    remaining = ' '.join(value.split())
    if not remaining or width <= 0 or lines <= 0:
        return ''
    result = []
    for index in range(lines):
        if index == lines - 1:
            last = fit_text(remaining, width, measure)
            if last:
                result.append(last)
            break
        length = _prefix_length(remaining, width, measure)
        if length == len(remaining):
            result.append(remaining)
            break
        if length == 0:
            last = fit_text(remaining, width, measure)
            if last:
                result.append(last)
            break
        splits_word = all(char.isascii() and (char.isalnum() or char in '-_')
                          for char in remaining[length - 1:length + 1])
        if splits_word:
            space = remaining.rfind(' ', 0, length + 1)
            if space > 0:
                length = space
        result.append(remaining[:length])
        remaining = remaining[length:].lstrip()
        if not remaining:
            break
    return '\n'.join(result)
