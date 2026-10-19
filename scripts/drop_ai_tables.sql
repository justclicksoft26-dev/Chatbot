-- drop_ai_tables.sql
-- Run this as the JUSTCLICK schema owner to remove all AI_ tables
-- created by old versions of the chatbot system.
-- These tables are no longer used — all learning data is stored in SQLite files.
--
-- Usage (SQL*Plus):
--   @scripts/drop_ai_tables.sql
--
-- Usage (SQL Developer): run as script (F5)

BEGIN
    FOR t IN (
        SELECT table_name
        FROM user_tables
        WHERE table_name IN (
            'AI_ACTION_AUDIT',
            'AI_ACTION_LOG',
            'AI_ALERT_SNAPSHOT',
            'AI_ANALYTICS_PREFS',
            'AI_AUDIT_LOG',
            'AI_BI_CONTEXT',
            'AI_CHAT_SESSIONS',
            'AI_EMBEDDINGS_CACHE',
            'AI_ERP_KNOWLEDGE',
            'AI_EVENTS',
            'AI_FEEDBACK',
            'AI_LEARNED_PATTERNS',
            'AI_METRICS',
            'AI_ONTOLOGY_EDGES',
            'AI_ONTOLOGY_NODES',
            'AI_STYLE_PREFS',
            'AI_SYNONYMS',
            'AI_TEMPLATE_STATS',
            'AI_VIZ_RULES',
            'AI_WORKFLOW_PATTERNS'
        )
    ) LOOP
        EXECUTE IMMEDIATE 'DROP TABLE "' || t.table_name || '" CASCADE CONSTRAINTS PURGE';
        DBMS_OUTPUT.PUT_LINE('Dropped: ' || t.table_name);
    END LOOP;
END;
/

-- Verify: should return 0 rows
SELECT table_name
FROM user_tables
WHERE table_name LIKE 'AI_%'
ORDER BY table_name;
