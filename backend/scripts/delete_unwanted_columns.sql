-- Script to delete unwanted columns (Date, Document type, Summary, Author, Persons mentioned, Language) from all tabular reviews
-- This script deletes all related data (cells, comments, history) before deleting the columns

BEGIN;

-- Step 1: Delete all cells for unwanted columns
DELETE FROM tabular_cells
WHERE column_id IN (
    SELECT id FROM tabular_columns
    WHERE column_label IN ('Date', 'Document type', 'Summary', 'Author', 'Persons mentioned', 'Language')
       OR LOWER(column_label) IN ('date', 'document type', 'summary', 'author', 'persons mentioned', 'language')
       OR (LOWER(column_label) LIKE '%per on%' AND LOWER(column_label) LIKE '%mentioned%')
);

-- Step 2: Delete all comments for unwanted columns
DELETE FROM cell_comments
WHERE column_id IN (
    SELECT id FROM tabular_columns
    WHERE column_label IN ('Date', 'Document type', 'Summary', 'Author', 'Persons mentioned', 'Language')
       OR LOWER(column_label) IN ('date', 'document type', 'summary', 'author', 'persons mentioned', 'language')
       OR (LOWER(column_label) LIKE '%per on%' AND LOWER(column_label) LIKE '%mentioned%')
);

-- Step 3: Delete all history records for unwanted columns
DELETE FROM cell_history
WHERE column_id IN (
    SELECT id FROM tabular_columns
    WHERE column_label IN ('Date', 'Document type', 'Summary', 'Author', 'Persons mentioned', 'Language')
       OR LOWER(column_label) IN ('date', 'document type', 'summary', 'author', 'persons mentioned', 'language')
       OR (LOWER(column_label) LIKE '%per on%' AND LOWER(column_label) LIKE '%mentioned%')
);

-- Step 4: Delete the unwanted columns themselves
DELETE FROM tabular_columns
WHERE column_label IN ('Date', 'Document type', 'Summary', 'Author', 'Persons mentioned', 'Language')
   OR LOWER(column_label) IN ('date', 'document type', 'summary', 'author', 'persons mentioned', 'language')
   OR (LOWER(column_label) LIKE '%per on%' AND LOWER(column_label) LIKE '%mentioned%');

-- Show summary
SELECT 
    'Deleted unwanted columns' as action,
    COUNT(*) as count
FROM tabular_columns
WHERE column_label IN ('Date', 'Document type', 'Summary', 'Author', 'Persons mentioned', 'Language')
   OR LOWER(column_label) IN ('date', 'document type', 'summary', 'author', 'persons mentioned', 'language')
   OR (LOWER(column_label) LIKE '%per on%' AND LOWER(column_label) LIKE '%mentioned%');

COMMIT;

