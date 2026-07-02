from dynamic_scheduling_master.src.dynamic_scheduling.ops_dashboard import format_indian_number


def test_format_indian_number_uses_indian_grouping():
    assert format_indian_number(2283367) == "22,83,367"
    assert format_indian_number(10000000) == "1,00,00,000"
    assert format_indian_number(0) == "0"
