"""
Layer-1 (lexical) acceptance: synonyms come ONLY from comments (@lex).
Proves the full chain span → lexical → registry → value, BOTH ways:
  - WITHOUT @lex (today's comments): 'المشتريات' → UNRESOLVED
  - WITH @lex in a temp comment:     'المشتريات' → شراء → INVTYPE = 1
Offline, ASCII-only output.
"""
import os, sys, time, asyncio, importlib, pathlib
os.environ['LEARNING_FORCE_SQLITE'] = '1'

ORIG = pathlib.Path('justclick_comments.sql')
orig_text = ORIG.read_text(encoding='utf-8')

def boot(schema_file):
    os.environ['SCHEMA_FILE'] = schema_file
    import schema_loader, semantic_registry, lexical_layer, span_resolver, slot_gate
    importlib.reload(schema_loader)
    schema_loader._flag_concept_map = None
    asyncio.run(schema_loader.init_schema_context())
    importlib.reload(semantic_registry); semantic_registry.invalidate()
    importlib.reload(lexical_layer);     lexical_layer.invalidate()
    importlib.reload(span_resolver)
    importlib.reload(slot_gate)
    return span_resolver, slot_gate

_pass = True
def ok(label, cond):
    global _pass
    if not cond: _pass = False
    print('[%s] %s' % ('OK' if cond else 'FAIL', label.encode('ascii','backslashreplace').decode()))

# ── 1. WITHOUT @lex (today's real comments) ───────────────────────────
print("=== WITHOUT @lex (today comments: 0=bay3 , 1=shira2) ===")
sr, sg = boot('justclick_comments.sql')
ok('canonical شراء -> 1 (self-map, no synonyms needed)', sr.resolve_span('INVTYPE','شراء') == 1)
ok('canonical الشراء -> 1 (normalization)', sr.resolve_span('INVTYPE','الشراء') == 1)
ok("USER EXAMPLE 'المشتريات' -> UNRESOLVED (synonym not in comments)",
   sr.resolve_span('INVTYPE','المشتريات') == 'UNRESOLVED_FROM_COMMENTS')

# ── 2. WITH @lex synonyms added to the INVTYPE comment (temp file) ─────
print()
print('=== WITH @lex synonyms in the comment (temp) ===')
injected = orig_text.replace(
    "'نوع الفاتورة : 0=بيع , 1=شراء'",
    "'نوع الفاتورة : 0=بيع , 1=شراء.\n     @lex بيع = المبيعات | مبيعات ؛ شراء = المشتريات | توريد | مشتريات'"
)
assert injected != orig_text, '@lex injection failed (legend string not found)'
tmp = pathlib.Path('_lex_tmp.sql'); tmp.write_text(injected, encoding='utf-8')
os.utime(tmp, (time.time()+5, time.time()+5))
sr, sg = boot('_lex_tmp.sql')

ok("USER EXAMPLE 'المشتريات' -> شراء -> INVTYPE = 1", sr.resolve_span('INVTYPE','المشتريات') == 1)
ok("synonym 'توريد' -> 1",  sr.resolve_span('INVTYPE','توريد') == 1)
ok("synonym 'المبيعات' -> 0", sr.resolve_span('INVTYPE','المبيعات') == 0)
ok("canonical 'شراء' still -> 1 (self-map preserved)", sr.resolve_span('INVTYPE','شراء') == 1)
ok("unknown 'حاجة غريبة' -> UNRESOLVED", sr.resolve_span('INVTYPE','حاجةغريبة') == 'UNRESOLVED_FROM_COMMENTS')

# full chain through the gate on the user's exact query skeleton
final = sg.enforce_and_resolve_spans(
    "SELECT COUNT(*) FROM MAIN_INV WHERE INVTYPE = {{slot:INVTYPE:المشتريات}}")
ok("gate: 'عدد فواتير المشتريات' skeleton -> INVTYPE = 1", 'INVTYPE = 1' in final and '{{' not in final)

# legend compilation unaffected by @lex (value<->meaning still clean)
import semantic_registry as reg
ok("@lex did NOT pollute legend: meaning_of(INVTYPE,1)=شراء", reg.meaning_of('INVTYPE',1) == 'شراء')

tmp.unlink(missing_ok=True)

print()
print('=== TRUTH ===')
print('  Synonyms resolve ONLY because they were declared in the comment (@lex).')
print('  Same engine, no code change between the two runs — only the comment changed.')
print('  This is the lexical layer being TRULY comment-derived.')

print()
print('RESULT:', 'PASS' if _pass else 'FAIL')
sys.exit(0 if _pass else 1)
