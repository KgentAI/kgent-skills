import dataclasses

from kgent.types import (
    ApprovalBinding,
    ApprovalStatus,
    BackendResolution,
    DocumentMetadata,
    RoutingIntent,
    SearchResult,
)


def test_document_metadata_fields():
    names = {f.name for f in dataclasses.fields(DocumentMetadata)}
    assert {
        "doc_uri",
        "title",
        "backend",
        "location_url",
        "location_description",
        "content_type",
        "sensitivity",
        "tags",
        "owner",
        "created_at",
        "updated_at",
        "version",
        "content_fingerprint",
        "size_bytes",
    } <= names


def test_search_result_defaults():
    r = SearchResult(
        doc_uri="kgent://lark/a",
        metadata=DocumentMetadata(
            doc_uri="kgent://lark/a",
            title="t",
            backend="lark",
            sensitivity="internal",
            created_at=None,
            updated_at=None,
        ),
    )
    assert r.access == "ok" and r.also_available_in == [] and r.mode_used is None


def test_approval_binding_fields():
    names = {f.name for f in dataclasses.fields(ApprovalBinding)}
    assert {"doc_uri", "operation", "content_fingerprint"} == names
    st = ApprovalStatus(
        approval_id="ap1",
        binding=ApprovalBinding(
            doc_uri="kgent://lark/d1", operation="update", content_fingerprint="fp1"
        ),
    )
    assert st.binding.operation == "update" and st.binding.content_fingerprint == "fp1"


def test_routing_intent_shape():
    ri = RoutingIntent(
        operation="update",
        doc_uri="kgent://lark/docA",
        targets=[
            BackendResolution(
                backend="lark",
                adapter_type="skill",
                adapter_name="lark-doc",
                capabilities_needed=["document_storage.update"],
            )
        ],
        policy_gates=[],
        provenance={},
    )
    assert ri.targets[0].adapter_name == "lark-doc"
