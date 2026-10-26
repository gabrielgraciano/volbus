WITH po AS (SELECT prefixo, lat, lon FROM onibus.silver.postos
            WHERE status = 'ok' AND duplicata_de IS NULL AND rede = 'daee'),
st AS (SELECT CAST(stop_id AS STRING) stop_id, stop_lat, stop_lon FROM onibus.silver.gtfs_stops
       WHERE versao = (SELECT max(versao) FROM onibus.silver.gtfs_stops)),
tr AS (SELECT DISTINCT parada_de, parada_ate FROM onibus.silver.velocidade_trecho),
trg AS (SELECT tr.parada_de, tr.parada_ate, (a.stop_lat + b.stop_lat) / 2 lat, (a.stop_lon + b.stop_lon) / 2 lon
        FROM tr JOIN st a ON a.stop_id = tr.parada_de JOIN st b ON b.stop_id = tr.parada_ate),
viz AS (SELECT parada_de, parada_ate, prefixo FROM (
          SELECT trg.parada_de, trg.parada_ate, po.prefixo,
                 st_distancesphere(st_point(trg.lon, trg.lat), st_point(po.lon, po.lat)) d
          FROM trg CROSS JOIN po)
        QUALIFY row_number() OVER (PARTITION BY parada_de, parada_ate ORDER BY d) = 1),
c0 AS (SELECT prefixo, slot_utc, slot_sp, mm, coalesce(mm, 0) >= 0.2 AS chove
       FROM onibus.silver.chuva_10min
       WHERE prefixo IN (SELECT prefixo FROM po) AND dt BETWEEN '2026-08-23' AND '2026-10-24'),
c1 AS (SELECT *,
         sum(mm) OVER (PARTITION BY prefixo ORDER BY slot_utc ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) mm30,
         count(mm) OVER (PARTITION BY prefixo ORDER BY slot_utc ROWS BETWEEN 17 PRECEDING AND CURRENT ROW) n3h,
         sum(mm) OVER (PARTITION BY prefixo ORDER BY slot_utc ROWS BETWEEN 17 PRECEDING AND CURRENT ROW) mm3h,
         sum(mm) OVER (PARTITION BY prefixo ORDER BY slot_utc ROWS BETWEEN 35 PRECEDING AND CURRENT ROW) mm6h,
         count(mm) OVER (PARTITION BY prefixo ORDER BY slot_utc ROWS BETWEEN 35 PRECEDING AND CURRENT ROW) n6h,
         last_value(CASE WHEN chove THEN slot_utc END, true)
           OVER (PARTITION BY prefixo ORDER BY slot_utc ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) ultima_chuva
       FROM c0),
c2 AS (SELECT *, max(mm30) OVER (PARTITION BY prefixo ORDER BY slot_utc ROWS BETWEEN 35 PRECEDING AND CURRENT ROW) pico30_6h,
              (unix_timestamp(slot_utc) - unix_timestamp(ultima_chuva)) / 60 AS min_desde
       FROM c1),
v AS (SELECT parada_de, parada_ate, janela_sp, hour(janela_sp) h, sum(dist_m) d, sum(tempo_s) t
      FROM onibus.silver.velocidade_trecho
      WHERE tipo_dia = 'util' AND hour(janela_sp) BETWEEN 6 AND 21 GROUP BY 1, 2, 3, 4),
x AS (SELECT v.*, c2.mm30, c2.mm3h, c2.n3h, c2.mm6h, c2.n6h, c2.pico30_6h, c2.min_desde
      FROM v JOIN viz USING (parada_de, parada_ate) JOIN c2 ON c2.prefixo = viz.prefixo AND c2.slot_sp = v.janela_sp),
b3 AS (SELECT parada_de, parada_ate, h, sum(d) / sum(t) v3, count(*) n3 FROM x WHERE n3h = 18 AND mm3h = 0 GROUP BY 1,2,3),
b6 AS (SELECT parada_de, parada_ate, h, sum(d) / sum(t) v6, count(*) n6 FROM x WHERE n6h = 36 AND mm6h = 0 GROUP BY 1,2,3),
y AS (SELECT x.*, b3.v3, b6.v6 FROM x JOIN b3 USING (parada_de, parada_ate, h) JOIN b6 USING (parada_de, parada_ate, h)
      WHERE b3.n3 >= 10 AND b6.n6 >= 10)
SELECT CASE WHEN pico30_6h * 2 >= 10 THEN 'forte (pico >= 10 mm/h)' WHEN pico30_6h * 2 >= 2.5 THEN 'moderada' ELSE 'fraca' END intensidade,
       least(floor(min_desde / 20) * 20, 360) AS min_desde_fim,
       count(*) janelas,
       round(sum(d) / sum(t * v3), 4) razao_base3h,
       round(sum(d) / sum(t * v6), 4) razao_base6h
FROM y
WHERE mm30 = 0 AND min_desde IS NOT NULL AND min_desde <= 360 AND n3h = 18
GROUP BY 1, 2 ORDER BY 1, 2
