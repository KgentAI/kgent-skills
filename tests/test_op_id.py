"""B1: op_id 同秒唯一（2026-09-05 事故回归：op-20260905-01 全天撞号）。"""
from kgent.router.policy import _next_op_id


def test_same_second_two_ids_differ():
    a, b = _next_op_id(), _next_op_id()
    assert a != b


def test_format_keeps_op_prefix_and_date():
    import re
    oid = _next_op_id()
    assert re.fullmatch(r"op-\d{8}-[0-9a-f]{8}", oid), oid
