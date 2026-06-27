from merger.lenskit.retrieval.review_router import plan_review_query


def test_review_plan_is_deterministic_and_role_ordered():
    query = "Find widget implementation, tests, and contract"

    first = plan_review_query(query)
    second = plan_review_query(query)

    assert first == second
    assert first["version"] == "review_intent.v1"
    assert first["requested_roles"] == ["source", "test", "contract"]
    assert first["anchor_terms"] == ["widget"]
    assert [lane["name"] for lane in first["lanes"]] == [
        "source",
        "test",
        "contract",
    ]
    assert first["fusion"]["method"] == "round_robin_unique_path"
    assert first["fusion"]["compatibility_lane"] == "legacy"
    assert first["fusion"]["lane_order"] == [
        "legacy",
        "source",
        "test",
        "contract",
    ]


def test_review_plan_uses_bounded_role_path_filters():
    plan = plan_review_query(
        "Find retrieval evaluation implementation, tests, output contract, and CLI"
    )
    lanes = {lane["name"]: lane for lane in plan["lanes"]}

    assert "path_tokens:test" in lanes["test"]["strict_fts_query"]
    assert "path_tokens:contract" in lanes["contract"]["strict_fts_query"]
    assert "path_tokens:cli" in lanes["cli"]["strict_fts_query"]
    assert "path_tokens:" not in lanes["source"]["strict_fts_query"]
    assert " OR " in lanes["source"]["relaxed_fts_query"]


def test_review_plan_uses_explicit_variants_without_generic_stemming():
    plan = plan_review_query("Find lens selection implementation and tests")
    source = next(lane for lane in plan["lanes"] if lane["name"] == "source")

    assert "(lens OR lenses)" in source["strict_fts_query"]
    assert "statuses" not in source["strict_fts_query"]


def test_review_plan_retains_leading_contract_subject():
    plan = plan_review_query("Find contracts inventory and contracts matrix documentation")

    assert plan["anchor_terms"][0] == "contracts"
    assert "docs" in plan["requested_roles"]


def test_review_plan_empty_query_is_non_executable():
    plan = plan_review_query("")

    assert plan["intent"] == "unknown"
    assert plan["lanes"] == []
    assert plan["fusion"]["lane_order"] == ["legacy"]
