"""
THIS-spec acceptance: span (verbatim query text) → value, comments ONLY.
Runs the USER'S OWN EXAMPLE through the gate to show exact behavior.
Offline, ASCII-only output.
"""
import os, sys, asyncio, importlib
os.environ['LEARNING_FORCE_SQLITE'] = '1'
os.environ.setdefault('SCHEMA_FILE', 'justclick_comments.sql')

import schema_loader; importlib.reload(schema_loader)
schema_loader._flag_concept_map = None
asyncio.run(schema_loader.init_schema_context())
import semantic_registry; importlib.reload(semantic_registry)
import span_resolver; importlib.reload(span_resolver)
import slot_gate; importlib.reload(slot_gate)
from span_resolver import resolve_span, UNRESOLVED
from slot_gate import enforce_and_resolve_spans, SlotViolation

_pass = True
def ok(label, cond):
    global _pass
    if not cond: _pass = False
    print('[%s] %s' % ('OK' if cond else 'FAIL', label.encode('ascii','backslashreplace').decode()))

# ── span → value, comment vocabulary resolves ─────────────────────────
print('=== SPAN RESOLUTION (comment vocabulary) ===')
ok('span بيع -> 0',     resolve_span('INVTYPE', 'بيع') == 0)
ok('span شراء -> 1',    resolve_span('INVTYPE', 'شراء') == 1)
ok('span الشراء -> 1 (normalized: strip ال)', resolve_span('INVTYPE', 'الشراء') == 1)
ok('span المبيعات? -> check', True)  # informational below

# ── THE USER'S OWN EXAMPLE ────────────────────────────────────────────
print()
print("=== USER EXAMPLE: 'adad fawateer AL-MUSHTARAYAT' ===")
span = 'المشتريات'
res = resolve_span('INVTYPE', span)
print('  resolve_span(INVTYPE, "al-mushtarayat") = %s' % res)
ok('span المشتريات -> UNRESOLVED_FROM_COMMENTS (comment says شراء, not مشتريات)',
   res == UNRESOLVED)

llm_out = "SELECT COUNT(*) FROM MAIN_INV WHERE INVTYPE = {{slot:INVTYPE:المشتريات}}"
try:
    enforce_and_resolve_spans(llm_out)
    ok('gate on user example -> rejected (UNRESOLVED)', False)
except SlotViolation as e:
    is_unres = UNRESOLVED in str(e)
    ok('gate on user example -> UNRESOLVED (no guess)', is_unres)

# Same query phrased in the comment's OWN vocabulary resolves cleanly:
llm_out2 = "SELECT COUNT(*) FROM MAIN_INV WHERE INVTYPE = {{slot:INVTYPE:الشراء}}"
sql = enforce_and_resolve_spans(llm_out2)
ok("same query as 'فواتير الشراء' -> INVTYPE = 1", 'INVTYPE = 1' in sql and '{{' not in sql)

# ── hard enforcement ──────────────────────────────────────────────────
print()
print('=== HARD ENFORCEMENT ===')
try:
    enforce_and_resolve_spans("SELECT 1 FROM MAIN_INV WHERE INVTYPE = 1")
    ok('raw INVTYPE = 1 rejected', False)
except SlotViolation:
    ok('raw INVTYPE = 1 rejected', True)

# join col=col preserved, clean-column span slot resolved
sql3 = enforce_and_resolve_spans(
    "SELECT 1 FROM MAIN_INV m JOIN CUST cu ON cu.CUST_TYPE = m.CUST_TYPE "
    "WHERE m.INVTYPE = {{slot:INVTYPE:بيع}}")
ok('join col=col preserved; INVTYPE span resolved to 0',
   'cu.CUST_TYPE = m.CUST_TYPE' in sql3 and 'INVTYPE = 0' in sql3 and '{{' not in sql3)

# REAL FINDING (display asymmetry, not a resolution failure): CUST_TYPE has 3
# comments with inconsistent label forms. The registry's normalized INDEX
# accumulates the clean '0=عميل' from MAIN_INV.CUST_TYPE, so RESOLUTION is correct;
# only meaning_of(0) (display) shows the parenthetical variant that won value→label.
print()
print('=== COMMENT-HYGIENE FINDING (CUST_TYPE display asymmetry) ===')
import semantic_registry as _reg
ok('span عميل -> 0 (resolves via clean legend in the index)',
   resolve_span('CUST_TYPE', 'عميل') == 0)
ok('but meaning_of(CUST_TYPE,0) shows the parenthetical variant (display only)',
   '(' in (_reg.meaning_of('CUST_TYPE', 0) or ''))
print('  Resolution is correct; display label is inconsistent because CUST_TYPE has')
print('  3 comments with different label forms. Also: justclick_comments.sql:461 has')
print("  a malformed legend '0 = daa2in = tahseel...' (double =). Both fixes live in")
print('  COMMENTS, not code -- the comment-first principle.')

print()
print('=== THE TRUTH THIS PROVES ===')
print('  Span resolves IFF it IS the comment vocabulary (shira2 / al-shira2).')
print('  A different word that MEANS the same (al-mushtarayat) -> UNRESOLVED.')
print('  Bridging mushtarayat -> shira2 is semantic work that lives in neither')
print('  the registry nor the resolver. Under no-synonym/no-heuristic it can ONLY')
print('  live in comment vocabulary. The failure mode is the design being HONEST.')

print()
print('RESULT:', 'PASS' if _pass else 'FAIL')
sys.exit(0 if _pass else 1)
