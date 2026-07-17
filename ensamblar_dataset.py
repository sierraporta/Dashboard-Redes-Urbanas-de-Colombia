#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ensamblador del dataset de caracterización urbana.

Junta todos los 'resultados/<ciudad>_resumen.csv' (una fila por ciudad, producidos por
urban_accessibility_batch.py o por el notebook) en un único dataset ordenado y limpio,
listo para el análisis comparativo México vs Colombia.

Uso:
    python ensamblar_dataset.py

Entrada:
    resultados/*_resumen.csv        (excluye los que empiezan por '_')

Salidas (en la carpeta 'dataset/'):
    dataset_ciudades_completo.csv    dataset ancho: 1 fila por ciudad, columnas agrupadas
    dataset_ciudades_completo.xlsx   igual, en Excel
    accesibilidad_largo.csv          formato tidy: 1 fila por (ciudad, servicio)
    correlaciones_largo.csv          formato tidy: 1 fila por (ciudad, servicio, métrica)
    diccionario_columnas.csv         nombre de columna -> descripción
    _reporte_calidad.csv             cobertura/método por ciudad
"""

import pandas as pd
import numpy as np
from pathlib import Path
import sys, re

# ============================================================
RES_DIR = Path("resultados")
OUT_DIR = Path("dataset")
# Orden canónico de servicios (para ordenar columnas y tablas largas)
SERVICIOS = ["hospital", "clinica", "farmacia", "escuela",
             "mercado", "parque", "policia", "bomberos"]
METRICAS_CENTRALIDAD = ["degree_c", "closeness_c", "betweenness_c"]
STATS = ["mean", "median", "std", "p90", "cv"]   # sufijos de agregación
UMBRAL_COBERTURA = 8      # n_pois_total por debajo del cual se marca cobertura baja
# ============================================================


def cargar_resumenes():
    if not RES_DIR.exists():
        sys.exit(f"No existe la carpeta '{RES_DIR}'. Ejecuta antes el batch o el notebook.")
    files = sorted(p for p in RES_DIR.glob("*_resumen.csv") if not p.name.startswith("_"))
    if not files:
        sys.exit(f"No hay archivos *_resumen.csv en '{RES_DIR}'.")
    dfs = []
    for f in files:
        try:
            d = pd.read_csv(f)
            if len(d):
                dfs.append(d)
        except Exception as e:
            print(f"  ⚠ no se pudo leer {f.name}: {e}")
    print(f"Leídos {len(dfs)} resúmenes de ciudad.")
    return pd.concat(dfs, ignore_index=True, sort=False)


def ordenar_columnas(df):
    """Reordena columnas por grupos lógicos; deja al final las no previstas."""
    meta = ["id", "pais", "ciudad", "estado_departamento", "region_geografica",
            "poblacion", "poblacion_metro", "altitud_m", "costero", "lat", "lon"]
    red = ["network_type", "metodo_red", "n_nodos", "n_aristas", "grado_promedio",
           "densidad_red", "long_prom_arista_m", "long_total_calles_m",
           "n_intersecciones", "circuity_avg", "clustering_prom"]
    cobertura = ["n_pois_total", "servicios_con_datos"] + \
                [f"n_pois_{s}" for s in SERVICIOS]
    centralidad = [f"{m}_{st}" for m in METRICAS_CENTRALIDAD for st in STATS]
    acceso = []
    for s in SERVICIOS:
        acceso += [f"dist_{s}_{st}" for st in STATS] + [f"pct_acceso_{s}"]
    corr = sorted(c for c in df.columns if c.startswith("corr_"))

    orden = meta + red + cobertura + centralidad + acceso + corr
    presentes = [c for c in orden if c in df.columns]
    resto = [c for c in df.columns if c not in presentes]
    return df[presentes + resto]


def a_largo_accesibilidad(df):
    """Tabla tidy: 1 fila por (ciudad, servicio) con métricas de accesibilidad."""
    filas = []
    meta_cols = [c for c in ["id", "pais", "ciudad", "region_geografica"] if c in df.columns]
    for _, r in df.iterrows():
        for s in SERVICIOS:
            if f"dist_{s}_mean" not in df.columns and f"n_pois_{s}" not in df.columns:
                continue
            fila = {c: r.get(c) for c in meta_cols}
            fila["servicio"] = s
            fila["n_pois"] = r.get(f"n_pois_{s}")
            for st in STATS:
                fila[f"dist_{st}"] = r.get(f"dist_{s}_{st}")
            fila["pct_acceso"] = r.get(f"pct_acceso_{s}")
            filas.append(fila)
    return pd.DataFrame(filas)


def a_largo_correlaciones(df):
    """Tabla tidy: 1 fila por (ciudad, servicio, métrica) con rho y p de Spearman."""
    filas = []
    meta_cols = [c for c in ["id", "pais", "ciudad", "region_geografica"] if c in df.columns]
    rho_cols = [c for c in df.columns if c.startswith("corr_") and c.endswith("_rho")]
    for _, r in df.iterrows():
        for rc in rho_cols:
            m = re.match(r"corr_(.+)_(degree_c|closeness_c|betweenness_c)_rho$", rc)
            if not m:
                continue
            serv, met = m.group(1), m.group(2)
            rho = r.get(rc)
            p = r.get(f"corr_{serv}_{met}_p")
            if pd.isna(rho):
                continue
            fila = {c: r.get(c) for c in meta_cols}
            fila.update({"servicio": serv, "metrica": met,
                         "spearman_rho": rho, "p_valor": p,
                         "significativo": (p < 0.05) if pd.notna(p) else np.nan})
            filas.append(fila)
    return pd.DataFrame(filas)


def diccionario_columnas(df):
    desc = {
        "id": "Identificador de la ciudad (correlativo del Excel maestro)",
        "pais": "País (México / Colombia)",
        "ciudad": "Nombre de la ciudad",
        "estado_departamento": "Estado (MX) o departamento (CO)",
        "region_geografica": "Zona geográfica dentro del país",
        "poblacion": "Población municipal (INEGI 2020 / DANE 2024)",
        "poblacion_metro": "Población del área metropolitana (si aplica)",
        "altitud_m": "Altitud media (m)",
        "costero": "La ciudad está sobre la costa (Sí/No)",
        "lat": "Latitud del centro (WGS84)",
        "lon": "Longitud del centro (WGS84)",
        "network_type": "Tipo de red descargada (walk/drive/bike)",
        "metodo_red": "Método de descarga (point_<r>m = disco lat/lon; place = límite admin.)",
        "n_nodos": "Nº de nodos (intersecciones) de la red no dirigida",
        "n_aristas": "Nº de aristas (tramos de calle)",
        "grado_promedio": "Grado medio de los nodos",
        "densidad_red": "Densidad del grafo (aristas / posibles)",
        "long_prom_arista_m": "Longitud media de tramo de calle (m)",
        "long_total_calles_m": "Longitud total de la red vial (m)",
        "n_intersecciones": "Nº de intersecciones (OSMnx basic_stats)",
        "circuity_avg": "Circuidad media (long. real / long. en línea recta)",
        "clustering_prom": "Coeficiente de clustering medio",
        "n_pois_total": "Nº total de POIs encontrados en OSM dentro del área",
        "servicios_con_datos": "Nº de tipos de servicio con al menos un POI",
    }
    for s in SERVICIOS:
        desc[f"n_pois_{s}"] = f"Nº de POIs de tipo '{s}'"
        for st in STATS:
            desc[f"dist_{s}_{st}"] = f"Distancia en red al '{s}' más cercano — {st}"
        desc[f"pct_acceso_{s}"] = f"% de nodos con un '{s}' a menos del umbral de acceso"
    for m in METRICAS_CENTRALIDAD:
        for st in STATS:
            desc[f"{m}_{st}"] = f"Centralidad {m} — {st} sobre los nodos"
    met_re = "|".join(METRICAS_CENTRALIDAD)
    filas = []
    for c in df.columns:
        mm = re.match(rf"corr_(.+)_({met_re})_(rho|p)$", c)
        if mm:
            serv, met, tipo = mm.group(1), mm.group(2), mm.group(3)
            if tipo == "rho":
                d = f"Spearman rho entre {met} y distancia a '{serv}'"
            else:
                d = f"p-valor de la correlación {met} vs distancia a '{serv}'"
        else:
            d = desc.get(c, "")
        filas.append({"columna": c, "descripcion": d})
    return pd.DataFrame(filas)


def reporte_calidad(df):
    cols = [c for c in ["id", "pais", "ciudad", "metodo_red", "n_nodos",
                        "n_pois_total", "servicios_con_datos"] if c in df.columns]
    rep = df[cols].copy()
    if "n_pois_total" in rep.columns:
        rep["cobertura_baja"] = rep["n_pois_total"] < UMBRAL_COBERTURA
    return rep


def main():
    OUT_DIR.mkdir(exist_ok=True)
    df = cargar_resumenes()

    # de-duplicar por id/ciudad (si se corrió una ciudad más de una vez, quedarse con la última)
    clave = "id" if "id" in df.columns else "ciudad"
    df = df.drop_duplicates(subset=clave, keep="last")
    if "id" in df.columns:
        df = df.sort_values("id")
    elif "pais" in df.columns:
        df = df.sort_values(["pais", "ciudad"])

    df = ordenar_columnas(df).reset_index(drop=True)

    # --- salidas ---
    p_csv = OUT_DIR / "dataset_ciudades_completo.csv"
    df.to_csv(p_csv, index=False)
    try:
        df.to_excel(OUT_DIR / "dataset_ciudades_completo.xlsx", index=False)
    except Exception as e:
        print(f"  (aviso: no se pudo escribir xlsx: {e})")

    a_largo_accesibilidad(df).to_csv(OUT_DIR / "accesibilidad_largo.csv", index=False)
    a_largo_correlaciones(df).to_csv(OUT_DIR / "correlaciones_largo.csv", index=False)
    diccionario_columnas(df).to_csv(OUT_DIR / "diccionario_columnas.csv", index=False)
    rep = reporte_calidad(df)
    rep.to_csv(OUT_DIR / "_reporte_calidad.csv", index=False)

    # --- resumen en consola ---
    print(f"\n★ Dataset completo: {p_csv}")
    print(f"   {df.shape[0]} ciudades × {df.shape[1]} columnas")
    if "pais" in df.columns:
        print("   Por país:", df["pais"].value_counts().to_dict())
    if "cobertura_baja" in rep.columns:
        bajas = rep.loc[rep["cobertura_baja"], "ciudad"].tolist()
        print(f"   Cobertura baja de POIs ({len(bajas)}):",
              ", ".join(bajas) if bajas else "ninguna")
    print(f"   Otras salidas en '{OUT_DIR}/': accesibilidad_largo, correlaciones_largo, "
          "diccionario_columnas, _reporte_calidad")


if __name__ == "__main__":
    main()
