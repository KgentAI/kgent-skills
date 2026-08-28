"""Minimal sanity test for the test world — Task 1.1/1.2 will replace/extend
this with full schema tests."""

from tests.fakes.fake_backend import FakeBackend


def test_test_world_provides_three_backends(test_world):
    backends = test_world["backends"]
    assert set(backends) == {"lark", "dingtalk", "wecom"}
    assert all(isinstance(b, FakeBackend) for b in backends.values())
    assert test_world["user"] == "alice"
    assert test_world["config"].version == 1
    assert backends["lark"].trust_zone == "internal"
    assert backends["dingtalk"].trust_zone == "external"
