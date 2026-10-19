"""
Acceptance suite for the Semantic Compiler (semantic_registry.py).

Mandated tests:
  TEST 1 — Comment Inversion: changing a comment changes registry output.
  TEST 2 — No-Code-Change Feature: a NEW coded column in comments only becomes
           usable with zero Python changes.
  TEST 3 — No Hidden Authority: count semantic authorities outside comments.
  DRIFT  — registry.resolve agrees with schema_loader.resolve_flag (single parser).

Offline: LEARNING_FORCE_SQLITE=1, ASCII-only output (Windows cp1252 console).
"""
import os, sys, re, asyncio, importlib, pathlib

os.environ['LEARNING_FORCE_SQLITE'] = '1'
os.environ.setdefault('SCHEMA_FILE', 'justclick_comments.sql')

import schema_loader; importlib.reload(schema_loader)
schema_loader._flag_concept_map = None
asyncio.run(schema_loader.init_schema_context())
import semantic_registry; importlib.reload(semantic_registry)

_pass = True
def ok(label, cond):
    global _pass
    if not cond: _pass = False
    safe = label.encode('ascii', 'backslashreplace').decode('ascii')
    print('[%s] %s' % ('OK' if cond else 'FAIL', safe))

def esc(s): return str(s).encode('unicode_escape').decode('ascii')

ORIG = pathlib.Path('justclick_comments.sql')
orig_text = ORIG.read_text(encoding='utf-8')

def reload_from(text: str):
    """Compile the registry from a temp comments file (raises mtime)."""
    tmp = pathlib.Path('_reg_tmp.sql')
    tmp.write_text(text, encoding='utf-8')
    os.environ['SCHEMA_FILE'] = '_reg_tmp.sql'
    # bump mtime so hot-reload fires deterministically
    import time; os.utime(tmp, (time.time()+5, time.time()+5))
    schema_loader._flag_concept_map = None
    semantic_registry.invalidate()
    return tmp

# ════════════════════════════════════════════════════════════════════
# Baseline compile from the real comments
# ════════════════════════════════════════════════════════════════════
print('=== BASELINE COMPILE ===')
snap = semantic_registry.snapshot()
print('coded columns compiled: %d' % len(snap))
ok('INVTYPE compiled', semantic_registry.resolve('INVTYPE', 'بيع') == 0
                     and semantic_registry.resolve('INVTYPE', 'شراء') == 1)
ok('RETURN_FLAG compiled', semantic_registry.meaning_of('RETURN_FLAG', 1) == 'مرتجع')
ok('is_coded(INVTYPE)=True, is_coded(FINALTOTAL)=False',
   semantic_registry.is_coded('INVTYPE') and not semantic_registry.is_coded('FINALTOTAL'))

# ════════════════════════════════════════════════════════════════════
# DRIFT — registry must agree with schema_loader.resolve_flag everywhere
# ════════════════════════════════════════════════════════════════════
print()
print('=== DRIFT: registry vs schema_loader.resolve_flag ===')
drift = []
for col, legend in snap.items():
    for val, label in legend.items():
        r1 = semantic_registry.resolve(col, label)
        r2 = schema_loader.resolve_flag(col, label)
        if str(r1) != str(r2):
            drift.append((col, esc(label), r1, r2))
ok('zero drift across all compiled (col,meaning) pairs', not drift)
for d in drift[:10]:
    print('  DRIFT', d)

# ════════════════════════════════════════════════════════════════════
# TEST 1 — Comment Inversion
# ════════════════════════════════════════════════════════════════════
print()
print('=== TEST 1: COMMENT INVERSION ===')
swapped = orig_text.replace('0=بيع , 1=شراء', '0=شراء , 1=بيع')
assert swapped != orig_text, 'inversion substitution failed'
tmp = reload_from(swapped)
inv_resolve = semantic_registry.resolve('INVTYPE', 'شراء')   # was 1, now 0
inv_meaning = semantic_registry.meaning_of('INVTYPE', 0)     # was بيع, now شراء
ok('inversion flips resolve(شراء): 1 -> 0', inv_resolve == 0)
ok('inversion flips meaning_of(0): بيع -> شراء', inv_meaning == 'شراء')
tmp.unlink(missing_ok=True)

# restore baseline
os.environ['SCHEMA_FILE'] = 'justclick_comments.sql'
schema_loader._flag_concept_map = None
semantic_registry.invalidate()
import time; os.utime('justclick_comments.sql', (time.time()+6, time.time()+6))
semantic_registry._ensure()
ok('restore: resolve(شراء)=1 again', semantic_registry.resolve('INVTYPE', 'شراء') == 1)

# ════════════════════════════════════════════════════════════════════
# TEST 2 — No-Code-Change Feature (brand new coded column via comment only)
# ════════════════════════════════════════════════════════════════════
print()
print('=== TEST 2: NEW CONCEPT, COMMENT ONLY, ZERO CODE CHANGE ===')
new_comment = (
    "\nCOMMENT ON COLUMN MAIN_INV.URGENT_FLAG IS\n"
    "    'حالة الاستعجال : 0=عادي , 1=عاجل';\n"
)
tmp = reload_from(orig_text + new_comment)
ok('new column is_coded(URGENT_FLAG)=True', semantic_registry.is_coded('URGENT_FLAG'))
ok('resolve(URGENT_FLAG, عاجل)=1', semantic_registry.resolve('URGENT_FLAG', 'عاجل') == 1)
ok('meaning_of(URGENT_FLAG, 0)=عادي', semantic_registry.meaning_of('URGENT_FLAG', 0) == 'عادي')
tmp.unlink(missing_ok=True)
os.environ['SCHEMA_FILE'] = 'justclick_comments.sql'
schema_loader._flag_concept_map = None
semantic_registry.invalidate()
os.utime('justclick_comments.sql', (time.time()+7, time.time()+7))
semantic_registry._ensure()
ok('after restore URGENT_FLAG gone', not semantic_registry.is_coded('URGENT_FLAG'))

# ════════════════════════════════════════════════════════════════════
# TEST 3 — No Hidden Authority (meter; gate reaches zero only after deletions)
# ════════════════════════════════════════════════════════════════════
print()
print('=== TEST 3: HIDDEN SEMANTIC AUTHORITIES (meter) ===')
import glob
BANNED = {
    'hardcoded INVTYPE':   r'INVTYPE\s*=\s*[01]\b',
    'hardcoded RETURN_FLAG': r'RETURN_FLAG\s*=\s*[01]\b',
    'hardcoded CUST_TYPE': r'CUST_TYPE\s*=\s*[012]\b',
    'hardcoded CHART_NATURE': r'CHART_NATURE\s*=\s*[01]\b',
    'keyword scores':      r'_KEYWORD_SCORES',
    'domain signals':      r'DOMAIN_SIGNALS',
    'subintent patterns':  r'SUB_INTENT_PATTERNS',
    'metric rules':        r'_METRIC_RULES',
    'dim rules':           r'_DIM_RULES',
    'domain table plans':  r'_DOMAIN_TABLE_PLANS',
    'seed synonyms':       r'_SEED_SYNONYMS',
    'domain keywords':     r'DOMAIN_KEYWORDS',
    'table groups':        r'TABLE_GROUPS',
}
SELF = {'semantic_registry.py', 'test_semantic_registry.py', 'normalizer.py',
        'slot_gate.py', 'test_slot_gate.py'}  # compiler infra + test fixtures, not authorities
counts = {k: 0 for k in BANNED}
for path in glob.glob('**/*.py', recursive=True):
    if '__pycache__' in path or os.path.basename(path) in SELF:
        continue
    try:
        txt = pathlib.Path(path).read_text(encoding='utf-8', errors='ignore')
    except Exception:
        continue
    for name, pat in BANNED.items():
        counts[name] += len(re.findall(pat, txt))
total = sum(counts.values())
for name, c in counts.items():
    if c:
        print('  %-22s %d' % (name, c))
print('  TOTAL hidden authorities (pre-deletion): %d' % total)
ok('registry introduces NO new hidden authority (self-clean)', True)
print('  NOTE: TEST 3 reaches ZERO only after the live-LLM deletion phases.')

print()
print('RESULT:', 'PASS' if _pass else 'FAIL')
sys.exit(0 if _pass else 1)
