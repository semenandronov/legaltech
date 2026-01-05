-- Migration: Remove templates with default columns (Date, Document type, Summary, Author, Persons mentioned, Language)
-- This migration removes any templates that contain these unwanted default columns

-- Delete templates that contain 4+ of the target columns
DELETE FROM tabular_column_templates
WHERE id IN (
    SELECT id
    FROM tabular_column_templates,
    LATERAL jsonb_array_elements(columns) AS col
    WHERE (
        SELECT COUNT(*)
        FROM jsonb_array_elements(columns) AS c
        WHERE c->>'column_label' IN ('Date', 'Document type', 'Summary', 'Author', 'Persons mentioned', 'Language')
    ) >= 4
);

-- Also delete any template that has all 6 target columns
DELETE FROM tabular_column_templates
WHERE (
    SELECT COUNT(DISTINCT c->>'column_label')
    FROM jsonb_array_elements(columns) AS c
    WHERE c->>'column_label' IN ('Date', 'Document type', 'Summary', 'Author', 'Persons mentioned', 'Language')
) = 6;

