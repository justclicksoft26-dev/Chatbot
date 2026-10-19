"""Ontology graph, embeddings cache and chart recommendation."""
import os
import re

import pytest

import profiles
from learning import embeddings, ontology, visualization


@pytest.fixture
def graph(monkeypatch):
    monkeypatch.setenv("APP_PROFILE", "justclick")
    ontology.seed_ontology()
    yield ontology
    ontology.seed_ontology()


# ── ontology ──────────────────────────────────────────────────────────
def test_seed_replaces_the_graph_instead_of_stacking(graph, monkeypatch):
    first = graph.get_ontology_stats()["nodes"]["total_nodes"]
    graph.seed_ontology()
    assert graph.get_ontology_stats()["nodes"]["total_nodes"] == first
    monkeypatch.setenv("APP_PROFILE", "ecosafe")
    graph.seed_ontology()
    assert graph.find_join_path("ACTIVITIES", "CUST")
    assert graph.find_join_path("MAIN_INV", "CUST") is None             # the CRM has no invoices


def test_erp_ontology_has_no_crm_nodes(graph):
    assert graph.get_tables_for_concept("whatsapp") == []
    assert graph.get_tables_for_concept("invoice") == ["MAIN_INV"]
    assert "ACTIVITIES" not in graph.get_tables_for_domain("customers")


def test_join_paths_follow_the_real_schema(graph):
    direct = graph.find_join_path("MAIN_INV", "CUST")
    assert len(direct) == 1 and "CUST_TYPE" in direct[0]["metadata_json"]
    assert len(graph.find_join_path("CUST", "ITEMS")) == 3              # CUST - MAIN_INV - DETAIL_INV - ITEMS
    assert graph.find_join_path("CUST", "ITEMS", max_depth=2) is None
    assert graph.find_join_path("CUST", "CUST") == []
    assert graph.find_join_path("CUST", "NO_SUCH_TABLE") is None


def test_domain_and_neighbour_queries(graph):
    assert set(graph.get_tables_for_domain("accounting")) == {"VOUCHERS", "VOUCHERS_DET", "CHARTS"}
    out = graph.get_neighbors("tbl:MAIN_INV", relation="joins_to")
    assert {n["target_key"] for n in out} == {"tbl:DETAIL_INV", "tbl:CUST", "tbl:MAIN_INV_PAYED"}
    inbound = graph.get_neighbors("tbl:CUST", relation="joins_to", direction="in")
    assert inbound and inbound[0]["source_key"] == "tbl:MAIN_INV"


def test_add_node_and_edge_are_idempotent(graph):
    graph.add_node("tbl:X", "table", "إكس")
    graph.add_node("tbl:X", "table")                                    # keeps the label
    graph.add_edge("tbl:X", "tbl:CUST", "joins_to", 0.5)
    graph.add_edge("tbl:X", "tbl:CUST", "joins_to", 0.9, {"join": "A = B"})
    edges = graph.get_neighbors("tbl:X", relation="joins_to")
    assert len(edges) == 1 and edges[0]["weight"] == 0.9 and "A = B" in edges[0]["metadata_json"]
    assert graph._NODES["tbl:X"]["label_ar"] == "إكس"


@pytest.mark.parametrize("question,table", [
    ("رصيد العميل", "CUST"), ("أرصدة المخازن", "STORE"), ("القيود المحاسبية", "VOUCHERS"), ("فاتورة بيع", "MAIN_INV"),
])
def test_related_tables_for_a_question(graph, question, table):
    assert table in graph.find_related_tables(question)


def test_related_tables_ignores_noise(graph):
    assert graph.find_related_tables("") == []
    assert graph.find_related_tables("xyzzy qwerty") == []
    assert len(graph.find_related_tables("فاتورة عميل صنف مخزن قيد حساب موظف", limit=3)) <= 3


def test_arabic_normalisation():
    assert ontology._normalize_arabic("أإآ ة ى") == "ااا ه ي"
    assert "في" not in ontology._tokenize_arabic("رصيد في العميل")


@pytest.mark.parametrize("name", profiles.available())
def test_every_ontology_table_and_join_exists_in_the_profile_schema(name, monkeypatch):
    """The ontology feeds join hints to the LLM, so it may only mention tables the profile really has."""
    monkeypatch.setenv("APP_PROFILE", name)
    comments = profiles.comments_file().read_text(encoding="utf-8").upper()
    known = set(re.findall(r'COMMENT ON TABLE\s+"?([A-Z0-9_]+)', comments))
    module = profiles.active().ONTOLOGY
    tables = {key[4:] for key, ntype, *_ in module.SEED_NODES if ntype == "table"}
    assert tables and tables <= known, tables - known
    node_keys = {n[0] for n in module.SEED_NODES}
    for src, tgt, *_ in module.SEED_EDGES:
        assert src in node_keys and tgt in node_keys, (src, tgt)


# ── embeddings ────────────────────────────────────────────────────────
@pytest.fixture
def vectors(monkeypatch):
    embeddings._CACHE.clear()
    table = {"عميل": [1.0, 0.0], "زبون": [0.9, 0.1], "مخزن": [0.0, 1.0]}
    calls = []

    def fake(text):
        calls.append(text)
        for key, vec in table.items():
            if key in text:
                return vec
        return None

    monkeypatch.setattr(embeddings, "_get_embedding_gemini", fake)
    yield calls
    embeddings._CACHE.clear()


def test_cosine_similarity_basics():
    assert embeddings.cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert embeddings.cosine_similarity([1, 0], [0, 1]) == 0.0
    assert embeddings.cosine_similarity([0, 0], [1, 1]) == 0.0


def test_embedding_is_computed_once_per_text(vectors):
    assert embeddings.get_embedding("عميل") == [1.0, 0.0]
    assert embeddings.get_embedding("عميل") == [1.0, 0.0]
    assert vectors == ["عميل"]
    assert embeddings.get_embedding("غير معروف") is None


def test_similar_questions_are_found_by_category_and_score(vectors):
    assert embeddings.index_question("عميل", "customer_list", "customers")
    assert embeddings.index_question("مخزن", "stock_balance", "inventory")
    assert embeddings.index_erp_term("عميل", "customer", "customers")
    found = embeddings.find_similar("زبون", category="question", min_score=0.8)
    assert [f["text"] for f in found] == ["عميل"] and found[0]["metadata"]["sub_intent"] == "customer_list"
    assert embeddings.find_similar_intent("زبون")[0]["text"] == "عميل"
    assert embeddings.find_similar("غير معروف") == []
    assert len(embeddings.find_similar("زبون", min_score=0.0, top_k=1)) == 1


def test_indexing_fails_quietly_without_an_embedding(vectors):
    assert not embeddings.index_question("غير معروف", "x")
    assert not embeddings.index_erp_term("غير", "معروف")
    stats = embeddings.get_embedding_stats()
    assert stats["total"] == 0 and stats["db_persistence"] is False


def test_no_api_key_means_no_embedding(monkeypatch):
    embeddings._CACHE.clear()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert embeddings._get_embedding_gemini("x") is None


# ── chart recommendation ──────────────────────────────────────────────
@pytest.mark.parametrize("rows,shape", [
    ([], "tabular"),
    ([{"TOTAL": 5}], "single_value"),
    ([{"MONTH": "01", "V": 1}, {"MONTH": "02", "V": 2}], "time_series"),
    ([{"MONTH": "01", "A": 1, "B": 2}, {"MONTH": "02", "A": 1, "B": 2}], "multi_series"),
    ([{"N": "a", "V": 1}, {"N": "b", "V": 2}], "category_value"),
    ([{"N": str(i), "V": i} for i in range(30)], "ranking"),
    ([{"A": 1, "B": 2}, {"A": 3, "B": 4}], "comparison"),
    ([{"N": "a", "V": 9, "W": "x"}, {"N": "b", "V": 5, "W": "y"}, {"N": "c", "V": 1, "W": "z"}], "ranking"),
    ([{f"C{j}": "t" for j in range(8)}] * 30, "tabular"),
])
def test_data_shape(rows, shape):
    assert visualization.analyze_data_shape(rows) == shape


def test_metadata_columns_are_ignored_in_shape_analysis():
    assert visualization.analyze_data_shape([{"TOTAL": 5, "__limit__": 500}]) == "single_value"


def test_chart_recommendation_defaults_and_overrides():
    ranking = [{"N": str(i), "V": 100 - i} for i in range(30)]
    assert visualization.recommend_chart(ranking, domain="invoicing")["chart_type"] == "horizontal_bar"
    assert visualization.recommend_chart([{"T": 5}])["chart_type"] == "metric"
    assert visualization.recommend_chart([])["chart_type"] == "table"
    rec = visualization.recommend_chart([{"N": "a", "V": 1}, {"N": "b", "V": 2}], domain="accounting", sub_intent="revenue_by_month")
    assert rec["chart_type"] == "bar" and rec["source"] == "default"
    visualization.record_chart_selection("d", "s", "bar", "bar")
    assert visualization.get_viz_stats() == {}
