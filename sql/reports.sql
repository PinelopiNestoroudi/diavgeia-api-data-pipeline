-- Organization counts within the collected snapshot, not API-wide totals.
SELECT organization_id, COUNT(*) AS decisions
FROM decisions GROUP BY organization_id ORDER BY decisions DESC, organization_id;

-- Monthly activity using UTC issue timestamps. Unknown dates are excluded.
SELECT substr(issued_at_utc, 1, 7) AS month_utc, COUNT(*) AS decisions
FROM decisions WHERE issued_at_utc IS NOT NULL
GROUP BY month_utc ORDER BY month_utc;

-- Revocation and private-data metadata, with explicit unknown counts.
SELECT organization_id,
    SUM(CASE WHEN status = 'REVOKED' THEN 1 ELSE 0 END) AS revoked,
    SUM(CASE WHEN status = 'REVOKED' AND private_data = 1 THEN 1 ELSE 0 END) AS revoked_with_private_indicator,
    SUM(CASE WHEN private_data IS NULL THEN 1 ELSE 0 END) AS unknown_private_indicator
FROM decisions GROUP BY organization_id ORDER BY organization_id;

-- Top organizations in this database snapshot.
SELECT organization_id, COUNT(*) AS decisions
FROM decisions GROUP BY organization_id ORDER BY decisions DESC, organization_id LIMIT 10;

-- Month-on-month count changes. Missing months are absent, not assumed zero.
WITH monthly AS (
    SELECT substr(issued_at_utc, 1, 7) AS month_utc, COUNT(*) AS decisions
    FROM decisions WHERE issued_at_utc IS NOT NULL GROUP BY month_utc
)
SELECT month_utc, decisions,
    decisions - LAG(decisions) OVER (ORDER BY month_utc) AS change_from_previous_observed_month
FROM monthly ORDER BY month_utc;
