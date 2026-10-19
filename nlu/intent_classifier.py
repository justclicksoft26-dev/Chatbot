"""
intent_classifier.py — ERP Intelligence Router (v2)
2-Level classification:
  Level 1: Regex fast-path         → confidence 0.95  (< 1ms)
  Level 2: LLM micro-classify      → confidence 0.80-0.90  (200ms)

Plus:
  - Context-need detection (does the question need conversation history?)
  - Dashboard vs data detection
  - Entity-based domain overrides
"""
import re
import json
import logging
from dataclasses import dataclass, field

import profiles

log = logging.getLogger("intent")


def _intents():
    """Intent tables of the active profile."""
    return profiles.part("intents")


def __getattr__(name):
    # `from intent_classifier import DOMAIN_SIGNALS` keeps working (normalizer does this)
    if name in ("DOMAIN_SIGNALS", "SUB_INTENT_PATTERNS", "ENTITY_PATTERNS"):
        return getattr(_intents(), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


@dataclass
class Intent:
    category: str              # greeting | data_query | comparison | aggregation | detail_lookup | action_request | help | unclear
    domain: str = ""           # accounting | invoicing | inventory | customers | hr | system
    sub_intent: str = ""       # e.g. "balance_lookup", "invoice_detail", "sales_summary"
    entities: dict = field(default_factory=dict)
    confidence: float = 1.0
    needs_history: bool = False  # هل السؤال محتاج context من المحادثة السابقة؟
    original_question: str = ""
    source: str = "none"       # regex | keywords | llm | none


# ══════════════════════════════════════════════════════════════════
# Patterns & Signals
# ══════════════════════════════════════════════════════════════════
# Domain keywords, sub-intent regexes and entity regexes belong to the active
# business profile (profiles/<name>/intents.py). Only the signals that are the
# same for every system stay here.

# ── Greeting patterns ────────────────────────────────────────────
_GREETINGS = re.compile(
    r"^(مرحبا|اهلا|السلام عليكم|صباح الخير|مساء الخير|هاي|هلا|يا هلا|"
    r"hello|hi|hey|good morning|good evening|مرحب|اهلاً|سلام)\b",
    re.IGNORECASE
)

# ── Help patterns ────────────────────────────────────────────────
_HELP = re.compile(
    r"(ايه الاسئلة|اقدر اسال|تقدر تعمل|ممكن تساعدني|المساعد|"
    r"مساعده?|ساعدني|محتاج\s*مساعد|"
    r"what can you|help|how to use|ازاي اسال|ازاي استخدم)",
    re.IGNORECASE
)

# ── Contextual signals (السؤال محتاج history) ────────────────────
_CONTEXTUAL_SIGNALS = re.compile(
    r"(نفس|كمان|برضو|تاني|أكمل|فصّل|وضح\s*أكتر|الحاجة\s*دي|اللي\s*فات|"
    r"زي\s*ما\s*قلت|أكثر\s*تفصيل|same|more|also|continue|explain|"
    r"ليه\s*كده|وبعدين|وايه\s*كمان|طيب\s*و|هو\s*ليه)",
    re.IGNORECASE
)

# ── Dashboard signals (عرض شامل مش استعلام محدد) ─────────────────
_DASHBOARD_SIGNALS = re.compile(
    r"(داش\s*بورد|داشبورد|لوحة|لوحات|تحليلات|إحصائيات|احصائيات|"
    r"نظرة\s*عامة|ملخص\s*شامل|تقرير\s*شامل|overview|analytics|"
    r"dashboard|statistics|summary\s+report)",
    re.IGNORECASE
)





# ══════════════════════════════════════════════════════════════════
# Entity extraction
# ══════════════════════════════════════════════════════════════════


# ── Arabic month names → month number ────────────────────────────
# Covers Egyptian, Gulf, and Levantine Arabic month names so date-range
# questions like "من يناير لمارس" or "شهر آذار" are correctly detected.
# Used only for entity extraction — business meaning still comes from comments.
_AR_MONTHS: dict[str, int] = {
    # Egyptian / international
    'يناير': 1,  'جانفي': 1,  'كانون الثاني': 1,
    'فبراير': 2, 'فيفري': 2,  'شباط': 2,
    'مارس': 3,   'آذار': 3,
    'أبريل': 4,  'إبريل': 4,  'ابريل': 4,  'نيسان': 4,
    'مايو': 5,   'أيار': 5,
    'يونيو': 6,  'يونيه': 6,  'حزيران': 6,
    'يوليو': 7,  'يوليه': 7,  'تموز': 7,
    'أغسطس': 8,  'اغسطس': 8,  'آب': 8,
    'سبتمبر': 9, 'أيلول': 9,
    'أكتوبر': 10,'اكتوبر': 10,'تشرين الأول': 10,
    'نوفمبر': 11,'تشرين الثاني': 11,
    'ديسمبر': 12,'كانون الأول': 12,
}

# Month names sorted longest-first so the multi-word names match before
# single-word ones (e.g. "تشرين الأول" before "تشرين").
_AR_MONTH_PATTERN = re.compile(
    '(' + '|'.join(re.escape(m) for m in
                   sorted(_AR_MONTHS, key=len, reverse=True)) + ')',
    re.UNICODE,
)

# "من يناير لـمارس" / "من يناير إلى مارس" / "بين يناير و مارس"
_DATE_RANGE_RE = re.compile(
    r'(?:من|بين)\s+'
    r'(' + '|'.join(re.escape(m) for m in sorted(_AR_MONTHS, key=len, reverse=True)) + r')'
    r'\s+(?:ل(?:ـ\s*|\s+)?|إلى\s+|الى\s+|حتى\s+|و\s*)'
    r'(' + '|'.join(re.escape(m) for m in sorted(_AR_MONTHS, key=len, reverse=True)) + r')',
    re.UNICODE,
)


def _extract_entities(question: str) -> dict:
    """Extract named entities from the question.

    In addition to the ENTITY_PATTERNS regex table, detects:
      • Arabic month-range  → date_month_from / date_month_to  (1-12)
      • Single Arabic month → date_month_from  (1-12)
    These two extra entities are used by the semantic gate in pipeline.py
    to demote templates that can't honor a specific month range to the LLM path.
    """
    entities: dict = {}
    for name, pattern in _intents().ENTITY_PATTERNS.items():
        match = re.search(pattern, question, re.IGNORECASE)
        if match:
            entities[name] = match.group(1).strip()

    # ── Arabic month range ──────────────────────────────────────
    m = _DATE_RANGE_RE.search(question)
    if m:
        f = _AR_MONTHS.get(m.group(1))
        t = _AR_MONTHS.get(m.group(2))
        if f:
            entities['date_month_from'] = str(f)
        if t:
            entities['date_month_to'] = str(t)
    else:
        # Single month name (no range)
        sm = _AR_MONTH_PATTERN.search(question)
        if sm:
            num = _AR_MONTHS.get(sm.group(1))
            if num:
                entities['date_month_from'] = str(num)

    return entities


# ══════════════════════════════════════════════════════════════════
# Context-need detection
# ══════════════════════════════════════════════════════════════════

def _detect_needs_history(question: str, history: list = None) -> bool:
    """
    هل السؤال محتاج context من المحادثة السابقة؟
    يرجع True لو:
    1. فيه إشارات سياقية (نفس، كمان، برضو)
    2. أو السؤال قصير وعام + فيه history
    3. أو داشبورد بدون domain محدد + فيه history
    """
    if not history or len(history) < 2:
        return False

    # إشارات سياقية صريحة
    if _CONTEXTUAL_SIGNALS.search(question):
        return True

    # سؤال قصير جداً (أقل من 5 كلمات) + فيه history
    word_count = len(question.split())
    if word_count <= 4:
        return True

    # داشبورد/ملخص بدون domain keywords
    if _DASHBOARD_SIGNALS.search(question):
        has_domain = False
        q_lower = question.lower()
        for keywords in _intents().DOMAIN_SIGNALS.values():
            for kw in keywords:
                if kw in q_lower:
                    has_domain = True
                    break
            if has_domain:
                break
        if not has_domain:
            return True

    return False


# ══════════════════════════════════════════════════════════════════
# Main Classification
# ══════════════════════════════════════════════════════════════════

def classify_intent(question: str, history: list = None) -> Intent:
    """
    2-Level intent classification:
      Level 1: Regex exact match → confidence 0.95
      Level 2: LLM fallback      → confidence 0.80-0.90
    """
    q = question.strip()

    # Pre-normalize Arabic: collapse repeats, fix informal ة/ه, Levenshtein-1 typos
    try:
        from nlu.normalizer import normalize_question
        q_fixed, _corr = normalize_question(q)
        if _corr:
            log.info(f"[INTENT] Arabic corrected: {_corr}")
            q = q_fixed
    except Exception:
        pass

    q_lower = q.lower()

    # ── Greeting ──
    if _GREETINGS.match(q):
        return Intent(category="greeting", original_question=q)

    # ── Help ──
    if _HELP.search(q_lower):
        return Intent(category="help", original_question=q)

    # ── Context-need detection ──
    needs_history = _detect_needs_history(q, history)

    # ── Domain detection ──
    matched_domains = []
    domain_scores: dict[str, int] = {}
    for domain, keywords in _intents().DOMAIN_SIGNALS.items():
        count = 0
        for kw in keywords:
            if kw in q_lower:
                count += 1
        if count > 0:
            matched_domains.append(domain)
            domain_scores[domain] = count

    # Pick domain with highest keyword count
    if domain_scores:
        domain = max(domain_scores, key=domain_scores.get)
    else:
        domain = ""

    # ══ Level 1: Regex exact match ══
    sub_intent = ""
    confidence = 0.7  # default (no match)
    source = "none"

    for intent_name, pattern in _intents().SUB_INTENT_PATTERNS.items():
        if re.search(pattern, q, re.IGNORECASE):
            sub_intent = intent_name
            confidence = 0.95
            source = "regex"
            break

    # ══ Level 2: LLM fallback (if regex missed) ══
    if not sub_intent:
        llm_result = _llm_classify(q, history)
        if llm_result:
            sub_intent = llm_result.get("sub_intent", "")
            confidence = 0.85
            source = "llm"
            if not domain and llm_result.get("domain"):
                domain = llm_result["domain"]
            log.info(f"[INTENT] LLM fallback: sub_intent={sub_intent} domain={domain}")

    # ── Entity extraction (always regex) ──
    entities = _extract_entities(q)

    # ── Entity-based overrides ──
    if "store_name" in entities:
        domain = "inventory"
        if not sub_intent or sub_intent in ("sales_summary", "invoice_detail", "customer_list"):
            sub_intent = "stock_balance"
            log.info("[INTENT] Override: store_name found -> inventory/stock_balance")

    # ── Category determination ──
    category = _determine_category(q_lower, sub_intent, entities)

    # ── Infer domain from sub_intent ──
    # When regex gives a high-confidence match (0.95), sub_intent domain
    # overrides DOMAIN_SIGNALS keyword detection (e.g. "رصيد المخزن" has
    # both "رصيد"→accounting and "مخزن"→inventory — sub_intent wins).
    if sub_intent:
        inferred = _infer_domain_from_sub_intent(sub_intent)
        if inferred and (not domain or (source == "regex" and confidence >= 0.95)):
            domain = inferred

    # ── Default domain ──
    if not domain and category == "data_query":
        domain = _intents().DEFAULT_DOMAIN

    log.info(f"[INTENT] result: cat={category} domain={domain} sub={sub_intent} "
             f"conf={confidence} source={source} needs_history={needs_history}")

    return Intent(
        category=category,
        domain=domain,
        sub_intent=sub_intent,
        entities=entities,
        confidence=confidence,
        needs_history=needs_history,
        original_question=q,
        source=source,
    )


# ══════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════

def _determine_category(q_lower: str, sub_intent: str, entities: dict) -> str:
    """Determine the intent category."""
    # Aggregation signals
    agg_signals = [
        "إجمالي", "اجمالي", "مجموع", "total", "sum", "count",
        "عدد", "كم", "أكثر", "اكثر", "أعلى", "اعلى", "أقل", "اقل",
        "how many", "how much", "top", "bottom",
    ]
    for sig in agg_signals:
        if sig in q_lower:
            return "aggregation"

    # Comparison signals
    cmp_signals = ["مقارنة", "قارن", "الفرق", "compare", "difference", "vs", "مقابل"]
    for sig in cmp_signals:
        if sig in q_lower:
            return "comparison"

    # Detail lookup signals
    if sub_intent and ("detail" in sub_intent or "info" in sub_intent):
        return "detail_lookup"

    if entities.get("account_code") or entities.get("invoice_id"):
        return "detail_lookup"

    return "data_query"


def _infer_domain_from_sub_intent(sub_intent: str) -> str:
    """Infer domain from sub-intent name."""
    mapping = _intents().SUB_INTENT_DOMAIN_PREFIXES
    for prefix, domain in mapping.items():
        if sub_intent.startswith(prefix) or sub_intent == prefix:
            return domain
    return ""


# ══════════════════════════════════════════════════════════════════
# Level 3: LLM-assisted classification
# ══════════════════════════════════════════════════════════════════

def _valid_sub_intents() -> list:
    return list(_intents().SUB_INTENT_PATTERNS.keys())


def _valid_domains() -> list:
    return list(_intents().DOMAIN_SIGNALS.keys())


def _classify_prompt() -> str:
    """System prompt of the LLM micro-classifier: profile intro + lists + examples."""
    p = _intents()
    return (
        p.CLASSIFY_PROMPT_INTRO
        + "أرجع JSON فقط بدون أي نص إضافي — بالشكل:\n"
        + '{"sub_intent": "...", "domain": "..."}\n\n'
        + f"القيم المتاحة لـ sub_intent:\n{json.dumps(_valid_sub_intents())}\n\n"
        + f"القيم المتاحة لـ domain:\n{json.dumps(_valid_domains())}\n\n"
        + 'إذا لم تتعرف على السؤال، أرجع:\n{"sub_intent": "", "domain": ""}\n\n'
        + p.CLASSIFY_PROMPT_EXAMPLES
    )


def _llm_classify(question: str, history: list = None) -> dict:
    """
    Level 3: LLM micro-classification.
    Returns {{sub_intent, domain}} or None on failure.
    Uses low max_tokens (100) for speed.
    Includes recent history for contextual understanding.
    """
    try:
        from llm.llm_client import _call_llm
        messages = [
            {"role": "system", "content": _classify_prompt()},
        ]
        # Include recent conversation history for context
        if history:
            for msg in history[-4:]:
                content = msg.get("content", "")[:200]
                messages.append({"role": msg["role"], "content": content})
        messages.append({"role": "user", "content": question})
        raw = _call_llm(messages, temperature=0, max_tokens=500)

        # Parse JSON from response
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"```json?\s*", "", raw)
            raw = re.sub(r"```\s*$", "", raw)
            raw = raw.strip()

        result = json.loads(raw)
        sub = result.get("sub_intent", "")
        dom = result.get("domain", "")

        # Validate against known values
        if sub and sub not in _valid_sub_intents():
            log.warning(f"[INTENT] LLM returned unknown sub_intent: {sub}")
            sub = ""
        if dom and dom not in _valid_domains():
            dom = ""

        if sub or dom:
            return {"sub_intent": sub, "domain": dom, "entities": {}}
        return None

    except Exception as e:
        log.warning(f"[INTENT] LLM classification failed: {e}")
        return None
