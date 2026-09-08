"""``kgent route`` — 只读裁决（B7/FM4；Task 5）。

``route`` 在提出任何写之前回答「这段内容能落到哪些 backend」：先用
``analyze_sensitivity`` 定 tier，再对每个候选 backend 重跑 ``enforce_zone``
这同一道门（与真实写入共用判定，不另设第二套规则）。只读：零 write_calls、
零台账、零审计；全部被拒 → exit 3（沿用 router 的 policy-rejected 语义）。
"""

# pyright: basic
from __future__ import annotations

import json

import pytest

from kgent.adapters import registry
from kgent.cli import main
from tests.conftest import _full_caps
from tests.fakes.fake_backend import FakeBackend


@pytest.fixture
def route_world(tmp_home, monkeypatch, capsys):
    """按 tests/test_cli.py ``e2e``/``undo_world`` 惯例：fake backends 进
    registry + config.yaml 落 tmp_home，teardown ``registry.clear()``。

    返回的 ``_world(backends, *, content, ...)`` 跑一次 ``main(["route", ...])``
    并返回 ``(exit_code, payload_or_text)``；注册过的 FakeBackend 经
    ``registry.get(name)`` 取回做副作用断言。confidential tier 用注入
    classifier 的方式拿到——stub 只会回 internal，而 sensitivity.py 的模块
    docstring 明说真实分类器由 skill 层后注入，测试与 production 走同一缝。
    """

    def _world(
        backends,
        *,
        content,
        zones=None,
        tier=None,
        select=None,
        as_json=True,
        register_fakes=True,
    ):
        zones = zones or {}
        if register_fakes:
            for name in backends:
                registry.register(
                    name,
                    FakeBackend(
                        name=name,
                        trust_zone=zones.get(name, "internal"),
                        capabilities=_full_caps(),
                    ),
                )
        backend_lines = []
        for name in backends:
            backend_lines += [
                f"  {name}:",
                "    enabled: true",
                "    type: cli",
                f"    cli_name: {name}-cli",
                f"    trust_zone: {zones.get(name, 'internal')}",
            ]
        config_text = (
            "version: 1\n"
            "defaults:\n"
            "  routing_mode: configured\n"
            f"  default_backends: [{', '.join(backends)}]\n"
            "  approval_ttl_hours: 24\n"
            "  timeouts:\n"
            "    search_seconds: 10\n"
            "    write_seconds: 30\n"
            "  concurrency:\n"
            "    max_parallel_backends: 4\n"
            "backends:\n" + "\n".join(backend_lines) + "\n"
        )
        (tmp_home / "config.yaml").write_text(config_text, encoding="utf-8")
        if tier is not None:

            def _classifier(content_text, confidence):
                return tier, confidence, f"test classifier: injected tier {tier}"

            monkeypatch.setattr("kgent.router.sensitivity.analyze_sensitivity", _classifier)
        argv = ["route", "--content", content]
        if select is not None:
            argv += ["--backends", select]
        if as_json:
            # --json 放子命令之后：argparse 子解析器默认值会覆盖前置 --json
            # （仓库既有惯例，见 test_cli.py journal 用例的注释）。
            argv.append("--json")
        code = main(argv)
        out = capsys.readouterr().out
        return code, (json.loads(out) if as_json else out)

    yield _world
    registry.clear()


# ---------------------------------------------------------------------------
# B7：internal 放行 / external zone 拒绝
# ---------------------------------------------------------------------------


def test_route_allows_internal_for_confidential(route_world):
    """confidential 内容 → internal-zone backend 放行（brief B7 用例 1）。"""
    rc, out = route_world(["lark"], content="密: token-rotate-30d", tier="confidential")
    assert rc == 0
    assert out["operation"] == "route"
    assert out["dry_run"] is True
    assert out["schema_version"] == 1
    assert out["sensitivity"] == "confidential"
    assert out["provenance"]
    assert out["allowed_backends"] == ["lark"]
    assert out["rejected"] == []


def test_route_allows_all_internal_fanout(route_world):
    """三平台都 internal → 全放行、零 rejected（brief Step 1「三平台 internal 放行」）。"""
    rc, out = route_world(
        ["lark", "dingtalk", "wecom"],
        content="密: token-rotate-30d",
        tier="confidential",
    )
    assert out["allowed_backends"] == ["lark", "dingtalk", "wecom"]
    assert out["rejected"] == []
    assert rc == 0


def test_route_rejects_external_zone(route_world):
    """confidential 内容 → external-zone backend 硬拒、全被拒 → exit 3（B7 用例 2）。"""
    rc, out = route_world(
        ["partner-x"],
        zones={"partner-x": "external"},
        content="confidential material",
        tier="confidential",
    )
    assert out["allowed_backends"] == []
    assert [entry["backend"] for entry in out["rejected"]] == ["partner-x"]
    assert "confidential" in out["rejected"][0]["reason"]
    assert "partner-x" in out["rejected"][0]["reason"]
    assert rc == 3


def test_route_mixed_fanout_reports_both_sides(route_world):
    """internal 放行与 external 拒绝同报；仍有可落 → exit 0（不是 3）。"""
    rc, out = route_world(
        ["lark", "dingtalk", "wecom"],
        zones={"dingtalk": "external", "wecom": "external"},
        content="confidential roadmap",
        tier="confidential",
    )
    assert out["allowed_backends"] == ["lark"]
    assert [entry["backend"] for entry in out["rejected"]] == ["dingtalk", "wecom"]
    assert rc == 0


def test_route_internal_content_allows_external_zone(route_world):
    """zone 门只拦 confidential：internal 内容可落 external backend（不过拒）。"""
    rc, out = route_world(
        ["dingtalk"], zones={"dingtalk": "external"}, content="team standup notes"
    )
    assert out["sensitivity"] == "internal"
    assert out["allowed_backends"] == ["dingtalk"]
    assert out["rejected"] == []
    assert rc == 0


def test_route_real_stub_provenance_surfaces(route_world):
    """无注入（真实 stub 分类路径）：internal tier + provenance 原样透出。"""
    rc, out = route_world(["lark"], content="team standup notes")
    assert out["sensitivity"] == "internal"
    assert "deterministic stub" in out["provenance"]
    assert rc == 0


def test_route_real_adapter_zone_comes_from_config(route_world):
    """真实 LarkAdapter（无 trust_zone 属性）也必须可路由；zone 取自 config。

    回归（fix round 1）：``_cmd_route`` 曾直接读 ``backend.trust_zone`` →
    对本机真实 config 首跑即 ``AttributeError: 'LarkAdapter' object has no
    attribute 'trust_zone'``。FakeBackend 有该字段，把缺陷整个掩蔽了。这里
    注册 registry 里的真实类（仅构造，零网络——``CliCapabilityAdapter.__init__``
    只存 cmd/name/timeout），并让 config 把 lark 标成 external（本机真实
    config 正是 ``lark: trust_zone: external``）：confidential 被拒证明 zone
    真的来自 config，而不是任何 adapter 属性；config 改回 internal 则同一
    tier 放行——source of truth 可随配置翻转。
    """
    from kgent.adapters.lark import LarkAdapter

    registry.register("lark", LarkAdapter())
    rc, out = route_world(
        ["lark"],
        zones={"lark": "external"},
        content="密: token-rotate-30d",
        tier="confidential",
        register_fakes=False,
    )
    assert out["sensitivity"] == "confidential"
    assert out["allowed_backends"] == []
    assert "lark" in out["rejected"][0]["reason"]
    assert rc == 3

    rc, out = route_world(
        ["lark"],
        content="密: token-rotate-30d",
        tier="confidential",
        register_fakes=False,
    )
    assert out["allowed_backends"] == ["lark"]
    assert out["rejected"] == []
    assert rc == 0


# ---------------------------------------------------------------------------
# FM4：只读——零写、零台账、零审计
# ---------------------------------------------------------------------------


def test_route_is_read_only(route_world, tmp_home):
    """裁决不落盘：零 write_calls、零台账 entry、零审计行。"""
    rc, out = route_world(
        ["lark", "dingtalk"],
        zones={"dingtalk": "external"},
        content="confidential material",
        tier="confidential",
    )
    assert out["allowed_backends"] == ["lark"]
    assert rc == 0
    assert registry.get("lark").write_calls == []
    assert registry.get("dingtalk").write_calls == []
    assert not (tmp_home / "journal" / "journal.ndjson").exists()
    assert not (tmp_home / "audit.ndjson").exists()


def test_route_all_rejected_is_read_only_too(route_world, tmp_home):
    """全被拒（exit 3）同样零副作用——拒绝路径不偷偷落盘。"""
    rc, _out = route_world(
        ["partner-x"],
        zones={"partner-x": "external"},
        content="confidential material",
        tier="confidential",
    )
    assert rc == 3
    assert registry.get("partner-x").write_calls == []
    assert not (tmp_home / "journal" / "journal.ndjson").exists()
    assert not (tmp_home / "audit.ndjson").exists()


# ---------------------------------------------------------------------------
# --backends 选择 / 文本输出 / 失败映射
# ---------------------------------------------------------------------------


def test_route_without_backends_flag_adjudicates_all_configured(route_world):
    """省略 --backends → 对配置里的每个 backend 裁决（brief: list(router.backends)）。"""
    rc, out = route_world(
        ["lark", "partner-x"],
        zones={"partner-x": "external"},
        content="confidential material",
        tier="confidential",
        select=None,
    )
    assert out["allowed_backends"] == ["lark"]
    assert [entry["backend"] for entry in out["rejected"]] == ["partner-x"]
    assert rc == 0


def test_route_text_output(route_world):
    """无 --json → 单行文本裁决结果。"""
    rc, text = route_world(["lark"], content="team standup notes", as_json=False)
    assert rc == 0
    assert "internal: allowed=['lark']" in text
    assert "rejected=[]" in text


def test_route_unknown_backend_is_failure_not_policy(route_world):
    """点名不存在的 backend → exit 1（失败），不冒充 exit 3 的政策拒绝。"""
    rc, out = route_world(["lark"], content="x", select="lark,ghost")
    assert rc == 1
    assert "ghost" in out["error"]


def test_route_requires_content():
    """--content 必填：缺省 → argparse usage error → main 映射 exit 1。"""
    assert main(["route"]) == 1


def test_route_accepts_spec_dry_run_flag(route_world):
    """spec 口径的 ``route --dry-run``：旗标被接受（恒真，route 从不写），rc==0。

    文档/spec 一致地把裁决前调用写成 ``kgent route --dry-run``，agent 会原样
    执行——CLI 必须认。旗标语义上恒真（route 本身只读），裁决行为不变。
    """
    rc, out = route_world(["lark"], content="team standup notes")
    assert rc == 0
    assert out["dry_run"] is True
    # 同一裁决以 spec 写法重放（旗标置于子命令后，与文件头 --json 惯例同因）
    assert main(["route", "--dry-run", "--content", "x", "--backends", "lark"]) == 0


# ---------------------------------------------------------------------------
# Fix round 1 — zone 的 fail-closed 底（防御分支；公共 route 路径不可达）
# ---------------------------------------------------------------------------


def test_backend_trust_zone_falls_closed_on_unexpected_spec():
    """读不到 zone（名字缺失 / spec 形态不对）→ 落回 schema 默认 external。

    经 ``kgent route`` 不可达：``_cmd_route`` 先拒绝 ``router.backends`` 之外的
    名字，而那些键就来自 ``config.backends``；schema 也只收 dict spec。这一
    分支是 route 的 fail-closed 底——zone 读不出来就当 external，绝不把未知
    当 internal 放行（docstring 明写的契约，这里钉死它）。
    """
    from kgent.cli import _backend_trust_zone
    from kgent.config.schema import Config

    config = Config(
        version=1,
        defaults={},
        backends={"lark": {"enabled": True, "trust_zone": "internal"}},
    )
    assert _backend_trust_zone(config, "lark") == "internal"  # 常规路径不受影响
    assert _backend_trust_zone(config, "ghost") == "external"  # 名字不在 config 里
    config.backends["legacy"] = "internal"  # 形态漂移：非 dict spec
    assert _backend_trust_zone(config, "legacy") == "external"
    config.backends["nozone"] = {"enabled": True}  # dict 但没有 trust_zone 键
    assert _backend_trust_zone(config, "nozone") == "external"
