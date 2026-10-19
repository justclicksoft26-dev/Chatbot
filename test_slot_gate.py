"""
Acceptance suite for Architecture A: constraint source + enforcement gate.
Offline (no Groq) — feeds synthetic LLM outputs to the gate.
"""
import os, sys, asyncio, importlib
os.environ['LEARNING_FORCE_SQLITE'] = '1'
os.environ.setdefault('SCHEMA_FILE', 'justclick_comments.sql')

import schema_loader; importlib.reload(schema_loader)
schema_loader._flag_concept_map = None
asyncio.run(schema_loader.init_schema_context())
import semantic_registry; importlib.reload(semantic_registry)
import slot_gate; importlib.reload(slot_gate)
from slot_gate import enforce_and_resolve, SlotViolation

_pass = True
def ok(label, cond):
    global _pass
    if not cond: _pass = False
    print('[%s] %s' % ('OK' if cond else 'FAIL', label.encode('ascii','backslashreplace').decode()))

# ── Constraint source: closed meaning-set per column ──────────────────
print('=== CONSTRAINT SOURCE (closed meaning-set) ===')
inv = semantic_registry.meaning_candidates('INVTYPE')
ok('INVTYPE candidates = [بيع, شراء] in value order', inv == ['بيع', 'شراء'])
ok('legal_meaning(INVTYPE, شراء)=True',  semantic_registry.legal_meaning('INVTYPE', 'شراء'))
ok('legal_meaning(INVTYPE, مرتجعات)=False (not comment-defined)',
   not semantic_registry.legal_meaning('INVTYPE', 'مرتجعات'))
block = semantic_registry.build_constraint_block()
ok('constraint block lists INVTYPE meanings', 'INVTYPE' in block and 'شراء' in block)

# ── Gate: accepts valid slot skeleton, resolves via registry ──────────
print()
print('=== GATE: VALID SKELETON ===')
sql = enforce_and_resolve(
    "SELECT COUNT(*) FROM MAIN_INV WHERE INVTYPE = {{flag:INVTYPE:شراء}}")
ok('valid slot resolves شراء -> INVTYPE = 1', 'INVTYPE = 1' in sql and '{{' not in sql)

# join condition (col=col) must NOT be flagged as a raw value
sql2 = enforce_and_resolve(
    "SELECT 1 FROM MAIN_INV m JOIN CUST cu ON cu.CUST_TYPE = m.CUST_TYPE "
    "WHERE m.INVTYPE = {{flag:INVTYPE:بيع}} AND cu.CUST_TYPE = {{flag:CUST_TYPE:عميل}}")
ok('join col=col preserved; slots resolved (INVTYPE=0, CUST_TYPE=0)',
   'cu.CUST_TYPE = m.CUST_TYPE' in sql2 and 'INVTYPE = 0' in sql2 and 'CUST_TYPE = 0' in sql2)

# ── Gate: REJECT raw numeric value on coded column ────────────────────
print()
print('=== GATE: REJECTIONS (hard enforcement) ===')
try:
    enforce_and_resolve("SELECT COUNT(*) FROM MAIN_INV WHERE INVTYPE = 1")
    ok('raw INVTYPE = 1 rejected', False)
except SlotViolation as e:
    ok('raw INVTYPE = 1 rejected', True)

# ── Gate: REJECT meaning not in registry ──────────────────────────────
try:
    enforce_and_resolve("SELECT 1 FROM MAIN_INV WHERE INVTYPE = {{flag:INVTYPE:مرتجعات}}")
    ok('alien meaning rejected', False)
except SlotViolation as e:
    ok('alien meaning rejected', True)

# ── TEST 4 — LLM Semantic Prohibition (structural check) ──────────────
print()
print('=== TEST 4: LLM output carries NO value, only slots ===')
# A compliant LLM output for "عدد فواتير المشتريات":
compliant = "SELECT COUNT(*) FROM MAIN_INV WHERE INVTYPE = {{flag:INVTYPE:شراء}}"
import re
has_raw = bool(re.search(r'\bINVTYPE\s*=\s*\d', compliant))
ok('compliant skeleton has NO raw coded value', not has_raw)
ok('compliant skeleton uses a slot', '{{flag:INVTYPE:' in compliant)
ok('gate turns it into executable SQL', 'INVTYPE = 1' in enforce_and_resolve(compliant))

print()
print('RESULT:', 'PASS' if _pass else 'FAIL')
sys.exit(0 if _pass else 1)
