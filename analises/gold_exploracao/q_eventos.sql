WITH b AS (SELECT c.prefixo, p.rede, c.slot_utc, c.mm, coalesce(c.mm, 0) >= 0.2 AS chove
           FROM onibus.silver.chuva_10min c JOIN onibus.silver.postos p USING (prefixo)
           WHERE p.status = 'ok' AND p.duplicata_de IS NULL),
r AS (SELECT prefixo, rede, slot_utc,
             lag(slot_utc) OVER (PARTITION BY prefixo ORDER BY slot_utc) ant
      FROM b WHERE chove),
s AS (SELECT *, sum(CASE WHEN ant IS NULL OR unix_timestamp(slot_utc) - unix_timestamp(ant) > MIT * 60 THEN 1 ELSE 0 END)
                  OVER (PARTITION BY prefixo ORDER BY slot_utc) seq
      FROM r),
e AS (SELECT prefixo, rede, seq, min(slot_utc) inicio, max(slot_utc) + INTERVAL 10 MINUTES fim, count(*) slots_chuva
      FROM s GROUP BY 1, 2, 3),
m AS (SELECT e.prefixo, e.rede, e.seq, e.inicio, e.fim, e.slots_chuva,
             (unix_timestamp(e.fim) - unix_timestamp(e.inicio)) / 60 dur_min,
             sum(b.mm) mm_total, count(*) slots, count(b.mm) slots_validos, max(b.mm) * 6 pico_10min_mm_h
      FROM e JOIN b ON b.prefixo = e.prefixo AND b.slot_utc >= e.inicio AND b.slot_utc < e.fim
      GROUP BY 1, 2, 3, 4, 5, 6)
SELECT rede, count(*) eventos, round(count(*) / count(DISTINCT prefixo), 0) por_posto,
       round(percentile_approx(dur_min, 0.5)) dur_med_min, round(percentile_approx(dur_min, 0.9)) dur_p90_min, round(max(dur_min) / 60, 1) dur_max_h,
       round(percentile_approx(mm_total, 0.5), 1) mm_mediano, round(percentile_approx(mm_total, 0.9), 1) mm_p90,
       round(100 * avg(CAST(mm_total >= 1 AS INT)), 1) pct_ge_1mm, round(100 * avg(CAST(slots_validos < slots AS INT)), 1) pct_com_faltante
FROM m GROUP BY 1 ORDER BY 1
