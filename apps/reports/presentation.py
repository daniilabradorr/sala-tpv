from decimal import Decimal


def chart_rows(rows, *keys):
    """Attach visual-only bar heights without changing analytical values."""
    maximum = max((abs(row[key]) for row in rows for key in keys), default=Decimal("0"))
    result = []
    for row in rows:
        visual = dict(row)
        for key in keys:
            visual[f"{key}_height"] = (
                round(abs(row[key]) / maximum * 100) if maximum else 0
            )
        result.append(visual)
    return result
