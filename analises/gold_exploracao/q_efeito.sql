WITH po AS (SELECT prefixo, lat, lon FROM onibus.silver.postos
            WHERE status = 'ok' AND duplicata_de IS NULL AND rede = 'daee'),
st AS (SELECT CAST(stop_id AS STRING) stop_id, stop_lat, stop_lon FROM onibus.silver.gtfs_stops
       WHERE versao = (SELECT max(versao) FROM onibus.silver.gtfs_stops)),
tr AS (SELECT DISTINCT parada_de, parada_ate FROM onibus.silver.velocidade_trecho),
trg AS (SELECT tr.parada_de, tr.parada_ate, (a.stop_lat + b.stop_lat) / 2 lat, (a.stop_lon + b.stop_lon) / 2 lon
        FROM tr JOIN st a ON a.stop_id = tr.parada_de JOIN st b ON b.stop_id = tr.parada_ate),
dist AS (SELECT trg.parada_de, trg.parada_ate, po.prefixo,
                st_distancesphere(st_point(trg.lon, trg.lat), st_point(po.lon, po.lat)) / 1000 d_km
         FROM trg CROSS JOIN po),
viz AS (SELECT parada_de, parada_ate, prefixo, d_km FROM dist
        QUALIFY row_number() OVER (PARTITION BY parada_de, parada_ate ORDER BY d_km) = 1),
ch AS (SELECT prefixo, slot_sp,
              sum(mm) OVER w3 mm30, count(mm) OVER w3 n30,
              sum(mm) OVER w18 mm3h, count(mm) OVER w18 n3h
       FROM onibus.silver.chuva_10min
       WHERE prefixo IN (SELECT prefixo FROM po) AND dt BETWEEN '2026-08-24' AND '2026-10-24'
       WINDOW w3 AS (PARTITION BY prefixo ORDER BY slot_utc ROWS BETWEEN 2 PRECEDING AND CURRENT ROW),
              w18 AS (PARTITION BY prefixo ORDER BY slot_utc ROWS BETWEEN 17 PRECEDING AND CURRENT ROW)),
v AS (SELECT parada_de, parada_ate, janela_sp, hour(janela_sp) h, sum(dist_m) d, sum(tempo_s) t
      FROM onibus.silver.velocidade_trecho
      WHERE tipo_dia = 'util' AND hour(janela_sp) BETWEEN 6 AND 21
      GROUP BY 1, 2, 3, 4),
x AS (SELECT v.*, viz.d_km, ch.mm30, ch.n30, ch.mm3h, ch.n3h
      FROM v JOIN viz USING (parada_de, parada_ate)
      JOIN ch ON ch.prefixo = viz.prefixo AND ch.slot_sp = v.janela_sp),
base AS (SELECT parada_de, parada_ate, h, sum(d) / sum(t) v_base, count(*) n_base
         FROM x WHERE n3h = 18 AND mm3h = 0 GROUP BY 1, 2, 3),
y AS (SELECT x.*, base.v_base FROM x JOIN base USING (parada_de, parada_ate, h) WHERE base.n_base >= 10)
SELECT CASE WHEN n30 < 3 OR n3h < 18 THEN '0 sem dado de chuva'
            WHEN mm3h = 0 THEN '1 seco (3h sem chuva)'
            WHEN mm30 = 0 THEN '2 pos-chuva (choveu nas 3h, nao nos 30 min)'
            WHEN mm30 * 2 < 2.5 THEN '3 fraca (< 2,5 mm/h)'
            WHEN mm30 * 2 < 10 THEN '4 moderada (2,5-10 mm/h)'
            WHEN mm30 * 2 < 25 THEN '5 forte (10-25 mm/h)'
            ELSE '6 muito forte (>= 25 mm/h)' END classe,
       CASE WHEN h BETWEEN 6 AND 9 THEN 'a pico manha' WHEN h BETWEEN 16 AND 19 THEN 'c pico tarde' ELSE 'b fora do pico' END periodo,
       count(*) janelas, round(sum(t) / 3600) horas_onibus,
       round(sum(d) / sum(t * v_base), 4) razao_vs_base
FROM y GROUP BY 1, 2 ORDER BY 1, 2
