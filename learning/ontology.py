"""
learning/ontology.py — CRM Ontology Graph Engine
Maps entity relationships: tables, columns, business concepts, intents.
Enables intelligent join-path discovery and contextual SQL generation.
"""
import json
import re
import logging
import threading
from typing import Optional

log = logging.getLogger("learning.ontology")

# ── In-memory graph store ────────────────────────────────────────────
# _NODES: node_key → {node_type, label_ar, label_en, domain, metadata}
# _EDGES_OUT/_IN: node_key → list of edge dicts
_NODES: dict[str, dict] = {}
_EDGES_OUT: dict[str, list] = {}   # source_key → edges
_EDGES_IN:  dict[str, list] = {}   # target_key → edges
_graph_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════
# Node Types
# ═══════════════════════════════════════════════════════════════════

class NodeType:
    TABLE = "table"
    COLUMN = "column"
    CONCEPT = "concept"     # business concept (e.g., "invoice", "customer")
    INTENT = "intent"       # sub_intent
    DOMAIN = "domain"
    METRIC = "metric"       # KPI / measure


class Relation:
    HAS_COLUMN = "has_column"       # table → column
    JOINS_TO = "joins_to"           # table → table (via FK)
    BELONGS_TO = "belongs_to"       # column → concept
    USED_BY = "used_by"             # table/column → intent
    IN_DOMAIN = "in_domain"         # * → domain
    ALIAS_OF = "alias_of"           # Arabic term → canonical
    COMPUTED_FROM = "computed_from"  # metric → columns
    PARENT_OF = "parent_of"         # hierarchical


# ═══════════════════════════════════════════════════════════════════
# Seed Data — ECO SAFE CRM Schema Ontology
# ═══════════════════════════════════════════════════════════════════

_SEED_NODES = [
    # Core CRM tables
    ("tbl:ACTIVITIES",    NodeType.TABLE,  "الأنشطة",           "Activities",         "activities"),
    ("tbl:CUST",          NodeType.TABLE,  "العملاء",            "Customers",          "customers"),
    ("tbl:EMPLOYEES",     NodeType.TABLE,  "جهات الاتصال",      "Contacts/Leads",     "contacts"),
    ("tbl:ACC_USERS",     NodeType.TABLE,  "موظفو النظام",      "System Staff",       "hr"),
    ("tbl:COURSES_PLAN",  NodeType.TABLE,  "الدورات التدريبية", "Training Courses",   "courses"),
    # Domains
    ("dom:activities", NodeType.DOMAIN, "الأنشطة والتواصل", "Activities & Comms", None),
    ("dom:customers",  NodeType.DOMAIN, "العملاء",           "Customers",          None),
    ("dom:contacts",   NodeType.DOMAIN, "جهات الاتصال",     "Contacts & Leads",   None),
    ("dom:hr",         NodeType.DOMAIN, "الفريق الداخلي",   "Internal Team",      None),
    ("dom:courses",    NodeType.DOMAIN, "الدورات",           "Courses",            None),
    # Business concepts
    ("con:activity",  NodeType.CONCEPT, "نشاط",          "Activity",       "activities"),
    ("con:call",      NodeType.CONCEPT, "مكالمة",        "Call",           "activities"),
    ("con:whatsapp",  NodeType.CONCEPT, "واتساب",        "WhatsApp",       "activities"),
    ("con:meeting",   NodeType.CONCEPT, "اجتماع",        "Meeting",        "activities"),
    ("con:followup",  NodeType.CONCEPT, "فولو أب",       "Follow-up",      "activities"),
    ("con:email",     NodeType.CONCEPT, "ايميل",         "Email",          "activities"),
    ("con:client",    NodeType.CONCEPT, "عميل",          "Client",         "customers"),
    ("con:contact",   NodeType.CONCEPT, "جهة اتصال",     "Contact",        "contacts"),
    ("con:lead",      NodeType.CONCEPT, "عميل محتمل",   "Lead",           "contacts"),
    ("con:staff",     NodeType.CONCEPT, "موظف",          "Staff Member",   "hr"),
    ("con:course",    NodeType.CONCEPT, "دورة تدريبية", "Training Course","courses"),
    # Key CRM metrics
    ("met:activity_count",    NodeType.METRIC, "عدد الأنشطة",      "Activity Count",      "activities"),
    ("met:top_staff",         NodeType.METRIC, "أكثر موظف نشاطاً", "Top Active Staff",    "activities"),
    ("met:overdue_followups", NodeType.METRIC, "متابعات متأخرة",   "Overdue Follow-ups",  "activities"),
    ("met:customer_count",    NodeType.METRIC, "عدد العملاء",      "Customer Count",      "customers"),
    ("met:contact_pipeline",  NodeType.METRIC, "مسار المتابعة",    "Contact Pipeline",    "contacts"),
    ("met:course_delegates",  NodeType.METRIC, "عدد المسجلين",     "Course Delegates",    "courses"),
]

_SEED_EDGES = [
    # Table relationships (JOINs)
    ("tbl:ACTIVITIES",  "tbl:ACC_USERS",  Relation.JOINS_TO, 1.0, '{"join": "CREATED_BY = USER_NAME"}'),
    ("tbl:ACTIVITIES",  "tbl:CUST",       Relation.JOINS_TO, 1.0, '{"join": "CUST_ID = CUSTID"}'),
    ("tbl:EMPLOYEES",   "tbl:CUST",       Relation.JOINS_TO, 1.0, '{"join": "CUST_ID = CUSTID"}'),
    # Table → Domain
    ("tbl:ACTIVITIES",   "dom:activities", Relation.IN_DOMAIN, 1.0, None),
    ("tbl:CUST",         "dom:customers",  Relation.IN_DOMAIN, 1.0, None),
    ("tbl:EMPLOYEES",    "dom:contacts",   Relation.IN_DOMAIN, 1.0, None),
    ("tbl:ACC_USERS",    "dom:hr",         Relation.IN_DOMAIN, 1.0, None),
    ("tbl:COURSES_PLAN", "dom:courses",    Relation.IN_DOMAIN, 1.0, None),
    # Concept → Table
    ("con:activity", "tbl:ACTIVITIES",   Relation.USED_BY, 1.0, None),
    ("con:call",     "tbl:ACTIVITIES",   Relation.USED_BY, 1.0, None),
    ("con:whatsapp", "tbl:ACTIVITIES",   Relation.USED_BY, 1.0, None),
    ("con:meeting",  "tbl:ACTIVITIES",   Relation.USED_BY, 1.0, None),
    ("con:followup", "tbl:ACTIVITIES",   Relation.USED_BY, 1.0, None),
    ("con:email",    "tbl:ACTIVITIES",   Relation.USED_BY, 1.0, None),
    ("con:client",   "tbl:CUST",         Relation.USED_BY, 1.0, None),
    ("con:contact",  "tbl:EMPLOYEES",    Relation.USED_BY, 1.0, None),
    ("con:lead",     "tbl:EMPLOYEES",    Relation.USED_BY, 0.9, None),
    ("con:staff",    "tbl:ACC_USERS",    Relation.USED_BY, 1.0, None),
    ("con:course",   "tbl:COURSES_PLAN", Relation.USED_BY, 1.0, None),
    # Metric → Tables
    ("met:activity_count",    "tbl:ACTIVITIES",   Relation.COMPUTED_FROM, 1.0, None),
    ("met:top_staff",         "tbl:ACTIVITIES",   Relation.COMPUTED_FROM, 1.0, None),
    ("met:top_staff",         "tbl:ACC_USERS",    Relation.COMPUTED_FROM, 0.9, None),
    ("met:overdue_followups", "tbl:ACTIVITIES",   Relation.COMPUTED_FROM, 1.0, None),
    ("met:customer_count",    "tbl:CUST",         Relation.COMPUTED_FROM, 1.0, None),
    ("met:contact_pipeline",  "tbl:EMPLOYEES",    Relation.COMPUTED_FROM, 1.0, None),
    ("met:course_delegates",  "tbl:COURSES_PLAN", Relation.COMPUTED_FROM, 1.0, None),
]


def seed_ontology() -> int:
    """Load built-in CRM ontology into in-memory graph."""
    count = 0
    with _graph_lock:
        for key, ntype, label_ar, label_en, domain in _SEED_NODES:
            _NODES[key] = {
                "node_type": ntype, "label_ar": label_ar,
                "label_en": label_en, "domain": domain, "metadata": {},
            }
            count += 1
        for src, tgt, rel, weight, meta in _SEED_EDGES:
            edge = {
                "source_key": src, "target_key": tgt,
                "relation": rel, "weight": weight,
                "metadata_json": meta or "{}",
            }
            _EDGES_OUT.setdefault(src, []).append(edge)
            _EDGES_IN.setdefault(tgt, []).append(edge)
            count += 1
    log.info(f"[ONTOLOGY] Seeded {count} nodes+edges (in-memory)")
    return count


# ═══════════════════════════════════════════════════════════════════
# Graph Queries
# ═══════════════════════════════════════════════════════════════════

def add_node(key: str, node_type: str, label_ar: str = "",
             label_en: str = "", domain: str = "",
             metadata: dict = None) -> bool:
    """Add or update an ontology node in-memory."""
    with _graph_lock:
        existing = _NODES.get(key, {})
        _NODES[key] = {
            "node_type": node_type,
            "label_ar": label_ar or existing.get("label_ar", ""),
            "label_en": label_en or existing.get("label_en", ""),
            "domain": domain or existing.get("domain", ""),
            "metadata": metadata or existing.get("metadata", {}),
        }
    return True


def add_edge(source: str, target: str, relation: str,
             weight: float = 1.0, metadata: dict = None) -> bool:
    """Add or update an ontology edge in-memory."""
    with _graph_lock:
        # Check duplicate
        for edge in _EDGES_OUT.get(source, []):
            if edge["target_key"] == target and edge["relation"] == relation:
                edge["weight"] = weight
                if metadata:
                    edge["metadata_json"] = json.dumps(metadata, ensure_ascii=False)
                return True
        edge = {
            "source_key": source, "target_key": target,
            "relation": relation, "weight": weight,
            "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
        }
        _EDGES_OUT.setdefault(source, []).append(edge)
        _EDGES_IN.setdefault(target, []).append(edge)
    return True


def get_neighbors(node_key: str, relation: str = "",
                  direction: str = "out") -> list[dict]:
    """Get neighboring nodes from in-memory graph."""
    results = []
    with _graph_lock:
        if direction in ("out", "both"):
            for edge in sorted(_EDGES_OUT.get(node_key, []),
                               key=lambda e: e["weight"], reverse=True):
                if relation and edge["relation"] != relation:
                    continue
                tgt = edge["target_key"]
                node = _NODES.get(tgt, {})
                d = {
                    "target_key": tgt, "relation": edge["relation"],
                    "weight": edge["weight"], "metadata_json": edge["metadata_json"],
                    "node_type": node.get("node_type", ""),
                    "label_ar": node.get("label_ar", ""),
                    "label_en": node.get("label_en", ""),
                    "domain": node.get("domain", ""),
                    "direction": "out",
                }
                results.append(d)

        if direction in ("in", "both"):
            for edge in sorted(_EDGES_IN.get(node_key, []),
                               key=lambda e: e["weight"], reverse=True):
                if relation and edge["relation"] != relation:
                    continue
                src = edge["source_key"]
                node = _NODES.get(src, {})
                d = {
                    "source_key": src, "relation": edge["relation"],
                    "weight": edge["weight"], "metadata_json": edge["metadata_json"],
                    "node_type": node.get("node_type", ""),
                    "label_ar": node.get("label_ar", ""),
                    "label_en": node.get("label_en", ""),
                    "domain": node.get("domain", ""),
                    "direction": "in",
                }
                results.append(d)
    return results


def find_join_path(from_table: str, to_table: str,
                   max_depth: int = 3) -> list[dict] | None:
    """
    Find the shortest join path between two tables.
    Returns list of edges forming the path, or None if not reachable.
    Uses BFS on the ontology graph.
    """
    src = f"tbl:{from_table}"
    tgt = f"tbl:{to_table}"

    if src == tgt:
        return []

    visited = {src}
    queue = [(src, [])]

    for _ in range(max_depth):
        next_queue = []
        for current, path in queue:
            neighbors = get_neighbors(current, relation=Relation.JOINS_TO,
                                      direction="both")
            for n in neighbors:
                neighbor_key = (n.get("target_key") or n.get("TARGET_KEY")
                                or n.get("source_key") or n.get("SOURCE_KEY"))
                if not neighbor_key or neighbor_key in visited:
                    continue

                new_path = path + [n]
                if neighbor_key == tgt:
                    return new_path

                visited.add(neighbor_key)
                next_queue.append((neighbor_key, new_path))
        queue = next_queue
        if not queue:
            break

    return None  # no path found


def get_tables_for_concept(concept: str) -> list[str]:
    """Get related tables for a business concept."""
    key = f"con:{concept}"
    neighbors = get_neighbors(key, relation=Relation.USED_BY, direction="out")
    tables = []
    for n in neighbors:
        target = n.get("target_key") or n.get("TARGET_KEY", "")
        if target.startswith("tbl:"):
            tables.append(target.replace("tbl:", ""))
    return tables


def get_tables_for_domain(domain: str) -> list[str]:
    """Get all tables in a domain."""
    dom_key = f"dom:{domain}"
    neighbors = get_neighbors(dom_key, relation=Relation.IN_DOMAIN,
                              direction="in")
    tables = []
    for n in neighbors:
        src = n.get("source_key") or n.get("SOURCE_KEY", "")
        if src.startswith("tbl:"):
            tables.append(src.replace("tbl:", ""))
    return tables


def _normalize_arabic(text: str) -> str:
    """Normalize Arabic text for fuzzy matching.
    Removes diacritics, normalizes alef/ya/ta-marbuta variants.
    """
    if not text:
        return ""
    # Remove diacritics (tashkeel)
    import re
    text = re.sub(r'[ً-ٰٟ]', '', text)
    # Normalize alef variants (أإآا → ا)
    text = re.sub(r'[أإآٱ]', 'ا', text)
    # Normalize ta-marbuta → ha
    text = text.replace('ة', 'ه')
    # Normalize alef-maqsura → ya
    text = text.replace('ى', 'ي')
    return text.lower().strip()


def _tokenize_arabic(text: str) -> set[str]:
    """Tokenize Arabic/English text into meaningful tokens (>= 2 chars)."""
    import re
    normalized = _normalize_arabic(text)
    tokens = set(re.split(r'\s+', normalized))
    # Remove very short tokens and stop words
    _STOP = {'في', 'من', 'على', 'الي', 'ال', 'هي', 'ما', 'لا', 'و', 'the', 'of', 'in', 'a'}
    return {t for t in tokens if len(t) >= 2 and t not in _STOP}


def find_related_tables(question: str, limit: int = 8) -> list[str]:
    """
    Phase 9: Find tables related to a question using ontology graph.
    Uses token-level matching with Arabic normalization for fuzzy matching.
    Searches concepts, tables, and metrics in the ontology.
    """
    q_normalized = _normalize_arabic(question)
    q_tokens = _tokenize_arabic(question)
    matched_tables: dict[str, float] = {}  # table -> score

    if not q_tokens:
        return []

    try:
        with _graph_lock:
            candidate_nodes = [
                (key, node) for key, node in _NODES.items()
                if node.get("node_type") in ("concept", "table", "metric")
            ]

        scored_keys: list[tuple[str, str, float]] = []

        for node_key, node in candidate_nodes:
            label_ar = node.get("label_ar", "")
            label_en = node.get("label_en", "")
            node_type = node.get("node_type", "")

            score = 0.0

            # Method 1: Full label substring match (highest confidence)
            label_ar_norm = _normalize_arabic(label_ar)
            label_en_lower = label_en.lower()
            if label_ar_norm and label_ar_norm in q_normalized:
                score = 3.0
            elif label_en_lower and label_en_lower in q_normalized:
                score = 2.5

            # Method 2: Token overlap matching
            if score == 0.0:
                label_tokens = _tokenize_arabic(label_ar)
                if label_en:
                    label_tokens.update(_tokenize_arabic(label_en))
                if label_tokens:
                    overlap = q_tokens & label_tokens
                    if overlap:
                        token_score = len(overlap) / len(label_tokens)
                        if token_score >= 0.5:
                            score = 1.5 * token_score

            # Method 3: Arabic root/stem partial matching (strict)
            if score == 0.0 and label_ar_norm:
                label_words = label_ar_norm.split()
                for lw in label_words:
                    if len(lw) >= 4:
                        root = lw[:4]
                        for qt in q_tokens:
                            if len(qt) >= 4 and qt.startswith(root):
                                if len(root) / len(qt) >= 0.6:
                                    score = max(score, 0.8)
                                    break

            if score > 0:
                scored_keys.append((node_key, node_type, score))

        # Sort by score descending, filter low-confidence matches
        scored_keys = [(k, t, s) for k, t, s in scored_keys if s >= 1.0]
        scored_keys.sort(key=lambda x: -x[2])

        for key, ntype, score in scored_keys[:8]:
            if ntype == "table" and key.startswith("tbl:"):
                tbl_name = key.replace("tbl:", "")
                matched_tables[tbl_name] = max(matched_tables.get(tbl_name, 0), score)
            elif ntype in ("concept", "metric"):
                neighbors = get_neighbors(key, relation=Relation.USED_BY, direction="out")
                for n in neighbors:
                    target = n.get("target_key", "")
                    if target.startswith("tbl:"):
                        tbl_name = target.replace("tbl:", "")
                        matched_tables[tbl_name] = max(
                            matched_tables.get(tbl_name, 0), score * 0.9
                        )

    except Exception as e:
        log.debug(f"[ONTOLOGY] find_related_tables failed: {e}")

    # Return sorted by score
    sorted_tables = sorted(matched_tables.items(), key=lambda x: -x[1])
    return [t for t, _ in sorted_tables[:limit]]


def get_ontology_stats() -> dict:
    """Get ontology graph statistics from in-memory graph."""
    with _graph_lock:
        node_types = {n.get("node_type", "") for n in _NODES.values()}
        domains = {n.get("domain", "") for n in _NODES.values()}
        all_edges = [e for edges in _EDGES_OUT.values() for e in edges]
        relations = {e["relation"] for e in all_edges}
    return {
        "nodes": {
            "total_nodes": len(_NODES),
            "node_types": len(node_types),
            "domains": len(domains),
        },
        "edges": {
            "total_edges": len(all_edges),
            "relation_types": len(relations),
        },
    }
