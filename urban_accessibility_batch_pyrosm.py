#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Caracterización de redes urbanas — LOTE OFFLINE con pyrosm (SIN Overpass).

En vez de descargar de servidores Overpass (con sus bloqueos y timeouts), lee extractos
locales '.osm.pbf' de cada país (descargados UNA sola vez desde Geofabrik) y construye la
red vial y los POIs localmente. Todo el cálculo (igraph, distancias, resumen, figuras) es
idéntico al batch por Overpass.

──────────────────────────────────────────────────────────────────────────────
PREPARACIÓN (una sola vez):
  1) Instala pyrosm:
        pip install pyrosm
  2) Descarga los extractos de Geofabrik (desde el navegador o con wget):
        México  : https://download.geofabrik.de/north-america/mexico-latest.osm.pbf
        Colombia: https://download.geofabrik.de/south-america/colombia-latest.osm.pbf
     (son archivos grandes, cientos de MB; guárdalos junto a este script o ajusta PBF_PATHS)
  3) Ejecuta:
        python urban_accessibility_batch_pyrosm.py
──────────────────────────────────────────────────────────────────────────────

Salidas: idénticas al batch por Overpass (resultados/, figuras/, _resumen_TODAS.csv).
NOTA: usa una ventana en DISCO de radio DIST_PUNTO centrada en lat/lon (igual criterio que
el modo 'point'), así que es comparable entre ciudades. Sin POIs extra.
"""

import matplotlib
matplotlib.use("Agg")

import osmnx as ox
import igraph as ig
import geopandas as gpd
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import folium
from scipy import stats
from shapely.geometry import Point
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import time, re, sys, os, math, traceback, warnings
warnings.filterwarnings("ignore")

# ============================================================
#  CONFIGURACIÓN — editar aquí
# ============================================================
EXCEL_PATH = "ciudades_mexico_colombia.xlsx"
HOJA       = "Ciudades"

# Ruta al extracto .osm.pbf de cada país (columna 'pais' del Excel -> archivo)
PBF_PATHS = {
    "México":   "mexico-latest.osm.pbf",
    "Colombia": "colombia-latest.osm.pbf",
}

NETWORK_TYPE = "walk"            # 'walk' | 'drive' | 'bike'
# Traducción a los tipos de pyrosm
_PYROSM_NET = {"walk": "walking", "drive": "driving", "bike": "cycling"}

POI_TAGS = {
    "hospital":  {"amenity": "hospital"},
    "clinica":   {"amenity": ["clinic", "doctors"]},
    "farmacia":  {"amenity": ["pharmacy"]},
    "escuela":   {"amenity": ["school", "college", "university", "kindergarten"]},
    "mercado":   {"shop": ["supermarket", "convenience", "greengrocer"],
                  "amenity": ["marketplace"]},
    "parque":    {"leisure": ["park", "garden"]},
    "policia":   {"amenity": ["police"]},
    "bomberos":  {"amenity": ["fire_station"]},
}

BETWEENNESS_CUTOFF = None        # None = exacto (igraph/C). Nº de saltos = aproximado
UMBRAL_ACCESO_M    = 1000        # umbral de "acceso a pie" (m)
DIST_PUNTO         = 6000        # radio (m) del disco centrado en lat/lon (~12 km diámetro)
MIN_POIS_CIUDAD    = 8           # aviso de baja cobertura

# Simplificar la topología (fusiona los nodos que NO son intersección, como hace OSMnx).
# Deja el grado, la densidad de intersecciones y la circuidad con significado real.
# No afecta distancias/accesibilidad (son geométricas). Requiere recomputar las ciudades.
SIMPLIFICAR = True

SAVE_FIGURAS = True
SAVE_MAPA    = True
FORCE        = False             # True = recalcular aunque ya exista el resumen
SOLO_PAIS    = None              # None | "México" | "Colombia"

# Paralelismo: como es offline, se pueden procesar varias ciudades a la vez (1 por núcleo).
# El betweenness exacto usa bastante RAM por ciudad grande: si el equipo se queda sin memoria,
# BAJA este número. 1 = secuencial.
N_WORKERS = min(4, os.cpu_count() or 1)

FIG_DIR = Path("figuras");    FIG_DIR.mkdir(exist_ok=True)
RES_DIR = Path("resultados"); RES_DIR.mkdir(exist_ok=True)
# ============================================================


def slug(s):
    return re.sub(r"[^\w]+", "_", str(s).strip().lower()).strip("_")


# ---------- utilidades de cálculo (idénticas al batch por Overpass) ----------
def nx_to_igraph(G):
    osmids = list(G.nodes())
    idx = {o: i for i, o in enumerate(osmids)}
    edges, lengths = [], []
    for u, v, data in G.edges(data=True):
        edges.append((idx[u], idx[v]))
        lengths.append(float(data.get("length", 1.0)))
    Gig = ig.Graph(n=len(osmids), edges=edges, directed=True)
    Gig.es["length"] = lengths
    Gig.vs["osmid"] = osmids
    return Gig, osmids, idx


def agg(series, prefix):
    s = pd.Series(series).dropna()
    if len(s) == 0:
        return {f"{prefix}_{k}": np.nan for k in ["mean", "median", "std", "p90", "cv"]}
    m = s.mean()
    return {
        f"{prefix}_mean":   round(m, 6),
        f"{prefix}_median": round(s.median(), 6),
        f"{prefix}_std":    round(s.std(), 6),
        f"{prefix}_p90":    round(s.quantile(0.9), 6),
        f"{prefix}_cv":     round(s.std() / m, 4) if m else np.nan,
    }


def _matches(gdf, spec):
    mask = pd.Series(False, index=gdf.index)
    for key, vals in spec.items():
        if key not in gdf.columns:
            continue
        vals = [vals] if isinstance(vals, str) else vals
        mask = mask | gdf[key].isin(vals)
    return mask


def distancias_servicio(G, Gu, osmids, idx, crs_grafo, pois_gdf):
    if pois_gdf is None or len(pois_gdf) == 0:
        return {o: np.nan for o in osmids}
    pois_proj = pois_gdf.to_crs(crs_grafo)
    xs = pois_proj.geometry.x.values
    ys = pois_proj.geometry.y.values
    nn = ox.nearest_nodes(G, xs, ys)
    src = sorted({idx[o] for o in np.atleast_1d(nn)})
    dmat = Gu.distances(source=src, weights="length")
    dmin = np.min(np.asarray(dmat, dtype=float), axis=0)
    dmin[~np.isfinite(dmin)] = np.nan
    return dict(zip(osmids, dmin))


# ---------- pyrosm: red y POIs (offline, desde .osm.pbf) ----------
def _bbox_disco(lat, lon, dist_m):
    """Bounding box [minx, miny, maxx, maxy] (lon/lat) de un cuadrado que contiene el disco."""
    dlat = dist_m / 111320.0
    dlon = dist_m / (111320.0 * max(math.cos(math.radians(lat)), 1e-6))
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


def _osm_para(pais):
    from pyrosm import OSM
    pbf = PBF_PATHS.get(pais)
    if pbf is None:
        raise ValueError(f"No hay .pbf configurado para el país '{pais}' (revisa PBF_PATHS)")
    if not Path(pbf).exists():
        raise FileNotFoundError(f"No se encuentra el extracto '{pbf}'. Descárgalo de Geofabrik.")
    return OSM, pbf


def descargar_red(pais, lat, lon):
    """Construye la red desde el .pbf del país, recortada al disco de radio DIST_PUNTO."""
    OSM, pbf = _osm_para(pais)
    bbox = _bbox_disco(lat, lon, DIST_PUNTO)
    osm = OSM(pbf, bounding_box=bbox)
    nodes, edges = osm.get_network(network_type=_PYROSM_NET[NETWORK_TYPE], nodes=True)
    if nodes is None or edges is None or len(edges) == 0:
        raise ValueError("sin red vial en el área (¿país o coordenadas equivocados?)")
    G = osm.to_graph(nodes, edges, graph_type="networkx", osmnx_compatible=True)
    if SIMPLIFICAR:
        try:
            G = ox.simplify_graph(G)
        except Exception as e:
            print(f"    (aviso: no se pudo simplificar: {type(e).__name__}); sigo sin simplificar")
    G = ox.project_graph(G)
    # recorte a DISCO (mismo criterio que el modo 'point'): nodos a <= DIST_PUNTO del centro
    cen = gpd.GeoSeries([Point(lon, lat)], crs="EPSG:4326").to_crs(G.graph["crs"]).iloc[0]
    dentro = [n for n, d in G.nodes(data=True)
              if (d["x"] - cen.x) ** 2 + (d["y"] - cen.y) ** 2 <= DIST_PUNTO ** 2]
    G = G.subgraph(dentro).copy()
    G = ox.truncate.largest_component(G, strongly=True)
    return G, f"pbf_disk_{DIST_PUNTO}m", osm


def descargar_pois(osm, area_poly):
    """{servicio: GeoDataFrame de puntos} desde el .pbf, clasificados por servicio."""
    vacio = lambda: gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    # filtro combinado para una sola lectura de POIs
    custom = {}
    for spec in POI_TAGS.values():
        for k, v in spec.items():
            v = [v] if isinstance(v, str) else list(v)
            custom.setdefault(k, set()).update(v)
    custom = {k: sorted(vals) for k, vals in custom.items()}

    try:
        gdf = osm.get_pois(custom_filter=custom)
    except Exception:
        gdf = None
    if gdf is None or len(gdf) == 0:
        return {s: vacio() for s in POI_TAGS}

    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    gdf = gdf.copy()
    gdf["geometry"] = [g if g.geom_type == "Point" else g.centroid for g in gdf.geometry]
    # limitar al área de la red
    gdf = gdf[gdf.within(area_poly)]

    pois = {}
    if len(gdf) == 0:
        return {s: vacio() for s in POI_TAGS}
    asignado = pd.Series(False, index=gdf.index)
    for servicio, spec in POI_TAGS.items():
        m = _matches(gdf, spec) & (~asignado)
        sub = gdf.loc[m, ["geometry"]].copy()
        asignado = asignado | m
        pois[servicio] = sub if len(sub) else vacio()
    return pois


# ---------- figuras ----------
def figuras_ciudad(G, df, ciudad, city_slug, servicios_c):
    fig, ax = plt.subplots(figsize=(8, 7))
    ox.plot_graph(G, ax=ax, node_size=2, node_color="steelblue", edge_color="#555555",
                  edge_linewidth=0.4, bgcolor="white", show=False, close=False)
    ax.set_title(f"Red vial ({NETWORK_TYPE})\n{ciudad}", fontsize=13, fontweight="bold")
    fig.savefig(FIG_DIR / f"{city_slug}_red.png", bbox_inches="tight", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 8), facecolor="white")
    val = df["closeness_c"].values
    nrm = mcolors.Normalize(vmin=np.nanpercentile(val, 5), vmax=np.nanpercentile(val, 95))
    col = [mcolors.to_hex(cm.RdYlGn(nrm(v))) for v in val]
    ox.plot_graph(G, ax=ax, node_color=col, node_size=6, edge_color="#444",
                  edge_linewidth=0.3, bgcolor="white", show=False, close=False)
    ax.set_title(f"Closeness centrality\n{ciudad}", fontsize=12, fontweight="bold")
    sm = cm.ScalarMappable(cmap=cm.RdYlGn, norm=nrm); sm.set_array([])
    fig.colorbar(sm, ax=ax, label="Centralidad (rojo=bajo, verde=alto)",
                 shrink=0.7, orientation="horizontal", pad=0.04)
    fig.savefig(FIG_DIR / f"{city_slug}_closeness.png", bbox_inches="tight", dpi=150)
    plt.close(fig)

    for servicio in servicios_c:
        col_dist = f"dist_{servicio}"
        fig, ax = plt.subplots(figsize=(10, 8), facecolor="white")
        v = df[col_dist].fillna(df[col_dist].max())
        nrm = mcolors.Normalize(vmin=np.nanpercentile(v, 5), vmax=np.nanpercentile(v, 95))
        col = [mcolors.to_hex(cm.RdYlGn_r(nrm(x))) for x in v]
        ox.plot_graph(G, ax=ax, node_color=col, node_size=8, edge_color="#444",
                      edge_linewidth=0.3, bgcolor="white", show=False, close=False)
        sm = cm.ScalarMappable(cmap=cm.RdYlGn_r, norm=nrm); sm.set_array([])
        fig.colorbar(sm, ax=ax, label="Distancia (verde=cerca, rojo=lejos)",
                     shrink=0.7, orientation="horizontal", pad=0.04)
        ax.set_title(f"Distancia al {servicio} más cercano\n{ciudad}",
                     fontsize=12, fontweight="bold")
        fig.savefig(FIG_DIR / f"{city_slug}_dist_{servicio}.png",
                    bbox_inches="tight", dpi=150, facecolor="white")
        plt.close(fig)

        vals = df[col_dist].dropna()
        fig, ax = plt.subplots(figsize=(8, 5), facecolor="white")
        ax.hist(vals, bins=50, color="steelblue", alpha=0.75, edgecolor="white", linewidth=0.3)
        mediana, p90 = vals.median(), vals.quantile(0.9)
        ax.axvline(mediana, color="black", ls="--", lw=2, label=f"Mediana: {mediana:.0f}m")
        ax.axvline(p90, color="red", ls=":", lw=2, label=f"P90: {p90:.0f}m")
        cv = vals.std() / vals.mean() if vals.mean() else 0
        ax.set_title(f"{ciudad} · {servicio}\nCV = {cv:.2f}", fontsize=11)
        ax.set_xlabel(f"Distancia al {servicio} más cercano (m)")
        ax.set_ylabel("Número de nodos"); ax.legend(fontsize=9)
        fig.savefig(FIG_DIR / f"{city_slug}_hist_{servicio}.png",
                    bbox_inches="tight", dpi=150, facecolor="white")
        plt.close(fig)

        sub = df[["closeness_c", col_dist]].dropna()
        fig, ax = plt.subplots(figsize=(8, 5), facecolor="white")
        muestra = sub.sample(min(3000, len(sub)), random_state=42)
        ax.scatter(muestra["closeness_c"], muestra[col_dist], alpha=0.3, s=4, color="steelblue")
        if len(muestra) > 1:
            z = np.polyfit(muestra["closeness_c"], muestra[col_dist], 1)
            xs = np.linspace(muestra["closeness_c"].min(), muestra["closeness_c"].max(), 100)
            ax.plot(xs, np.poly1d(z)(xs), "r-", lw=2, label="Tendencia"); ax.legend(fontsize=9)
        ax.set_title(f"{ciudad} · closeness vs distancia a {servicio}", fontsize=11)
        ax.set_xlabel("Closeness centrality"); ax.set_ylabel(f"Distancia al {servicio} (m)")
        fig.savefig(FIG_DIR / f"{city_slug}_scatter_{servicio}.png",
                    bbox_inches="tight", dpi=150, facecolor="white")
        plt.close(fig)


def mapa_folium(pois, city_slug, nodes_gdf):
    colores = {"hospital": "red", "clinica": "orange", "farmacia": "green",
               "escuela": "blue", "mercado": "purple", "parque": "pink",
               "policia": "brown", "bomberos": "darkred"}
    wgs = nodes_gdf.to_crs("EPSG:4326")
    m = folium.Map(location=[wgs.geometry.y.mean(), wgs.geometry.x.mean()],
                   zoom_start=13, tiles="OpenStreetMap")
    for servicio, pg in pois.items():
        if pg is None or len(pg) == 0:
            continue
        pw = pg.to_crs("EPSG:4326") if pg.crs else pg
        grupo = folium.FeatureGroup(name=servicio.capitalize())
        for _, r in pw.iterrows():
            try:
                folium.CircleMarker(location=[r.geometry.y, r.geometry.x], radius=5,
                                    color=colores.get(servicio, "gray"), fill=True,
                                    fill_opacity=0.8).add_to(grupo)
            except Exception:
                pass
        grupo.add_to(m)
    folium.LayerControl().add_to(m)
    m.save(str(RES_DIR / f"{city_slug}_mapa.html"))


# ---------- procesar una ciudad ----------
def procesar_ciudad(row):
    ciudad = str(row["ciudad"]); pais = str(row["pais"])
    lat, lon = row["lat"], row["lon"]
    city_slug = slug(ciudad)
    t0 = time.time()
    def paso(msg):
        print(f"    · {msg} [{time.time()-t0:.0f}s]", flush=True)

    paso("leyendo red del .pbf...")
    G, metodo, osm = descargar_red(pais, lat, lon)
    nodes_gdf = ox.graph_to_gdfs(G, edges=False)
    crs_grafo = nodes_gdf.crs
    area_poly = nodes_gdf.to_crs("EPSG:4326").union_all().convex_hull

    Gig, osmids, idx = nx_to_igraph(G)
    Gu = Gig.as_undirected(mode="collapse", combine_edges={"length": "min"})
    N = Gu.vcount()
    paso(f"red lista ({N:,} nodos, {Gu.ecount():,} aristas)")

    try:
        bs = ox.stats.basic_stats(G)
    except Exception:
        bs = {}
    grados = Gu.degree()

    degree_c = np.array(grados, dtype=float) / (N - 1)
    closeness_c = np.array(Gu.closeness(weights=None, normalized=True), dtype=float)
    paso(f"calculando betweenness ({'exacto' if BETWEENNESS_CUTOFF is None else f'cutoff={BETWEENNESS_CUTOFF}'})...")
    bet_raw = np.array(Gu.betweenness(weights=None, cutoff=BETWEENNESS_CUTOFF), dtype=float)
    nrm = 2.0 / ((N - 1) * (N - 2)) if N > 2 else 1.0
    betweenness_c = bet_raw * nrm
    paso("centralidades listas")

    df = nodes_gdf[["geometry"]].copy()
    df["degree_c"] = pd.Series(degree_c, index=osmids)
    df["closeness_c"] = pd.Series(closeness_c, index=osmids)
    df["betweenness_c"] = pd.Series(betweenness_c, index=osmids)

    paso("leyendo POIs del .pbf...")
    pois = descargar_pois(osm, area_poly)
    n_pois_total = int(sum(len(v) for v in pois.values()))
    servicios_con = int(sum(1 for v in pois.values() if len(v) > 0))
    paso(f"POIs listos ({n_pois_total} en {servicios_con} servicios); calculando distancias...")
    for servicio in POI_TAGS:
        dser = distancias_servicio(G, Gu, osmids, idx, crs_grafo, pois.get(servicio))
        df[f"dist_{servicio}"] = pd.Series(dser)

    metricas_c = ["degree_c", "closeness_c", "betweenness_c"]
    servicios_c = [s for s in POI_TAGS
                   if f"dist_{s}" in df.columns and df[f"dist_{s}"].notna().any()]
    corr = []
    for servicio in servicios_c:
        sub = df[[f"dist_{servicio}"] + metricas_c].dropna()
        if len(sub) < 30:
            continue
        for m in metricas_c:
            rho, p = stats.spearmanr(sub[m], sub[f"dist_{servicio}"])
            corr.append((servicio, m, round(rho, 4), float(p)))

    resumen = {
        "id": row.get("id"), "pais": pais, "ciudad": ciudad,
        "estado_departamento": row.get("estado_departamento"),
        "region_geografica": row.get("region_geografica"),
        "poblacion": row.get("poblacion"), "poblacion_metro": row.get("poblacion_metro"),
        "altitud_m": row.get("altitud_m"), "costero": row.get("costero"),
        "lat": lat, "lon": lon,
        "network_type": NETWORK_TYPE, "metodo_red": metodo,
        "n_nodos": N, "n_aristas": Gu.ecount(),
        "grado_promedio": round(float(np.mean(grados)), 3),
        "densidad_red": round(Gu.density(), 6),
        "long_prom_arista_m": round(bs.get("street_length_avg", np.nan), 1),
        "long_total_calles_m": round(bs.get("street_length_total", np.nan), 1),
        "n_intersecciones": bs.get("intersection_count", np.nan),
        "circuity_avg": round(bs.get("circuity_avg", np.nan), 4),
        "clustering_prom": round(Gu.transitivity_avglocal_undirected(mode="zero"), 4),
        "n_pois_total": n_pois_total, "servicios_con_datos": servicios_con,
    }
    for m in metricas_c:
        resumen.update(agg(df[m], m))
    for servicio in POI_TAGS:
        d = df[f"dist_{servicio}"].dropna()
        resumen[f"n_pois_{servicio}"] = int(len(pois.get(servicio, [])))
        resumen.update(agg(d, f"dist_{servicio}"))
        resumen[f"pct_acceso_{servicio}"] = (
            round(100.0 * (d < UMBRAL_ACCESO_M).mean(), 2) if len(d) else np.nan)
    for servicio, m, rho, p in corr:
        resumen[f"corr_{servicio}_{m}_rho"] = rho
        resumen[f"corr_{servicio}_{m}_p"] = round(p, 6)

    pd.DataFrame([resumen]).to_csv(RES_DIR / f"{city_slug}_resumen.csv", index=False)
    df.drop(columns="geometry").to_csv(RES_DIR / f"{city_slug}_nodos.csv")
    if SAVE_FIGURAS:
        figuras_ciudad(G, df, ciudad, city_slug, servicios_c)
    if SAVE_MAPA:
        mapa_folium(pois, city_slug, nodes_gdf)

    dt = time.time() - t0
    aviso = " ⚠ COBERTURA BAJA" if (n_pois_total < MIN_POIS_CIUDAD or servicios_con < 3) else ""
    print(f"    ✓ {N:,} nodos | {n_pois_total} POIs ({servicios_con}/{len(POI_TAGS)} serv.) "
          f"| {metodo} | {dt:.0f}s{aviso}")
    return resumen


def _tarea(row_dict):
    """Envuelve procesar_ciudad para usarse en el pool de procesos (devuelve estado)."""
    row = pd.Series(row_dict)
    ciudad = str(row["ciudad"])
    try:
        procesar_ciudad(row)
        return {"ciudad": ciudad, "estado": "ok"}
    except Exception as e:
        traceback.print_exc()
        return {"ciudad": ciudad, "estado": "error", "detalle": f"{type(e).__name__}: {e}"}


def ensamblar_maestro():
    files = sorted(p for p in RES_DIR.glob("*_resumen.csv") if not p.name.startswith("_"))
    if not files:
        return
    maestro = pd.concat([pd.read_csv(f) for f in files], ignore_index=True, sort=False)
    if "id" in maestro.columns:
        maestro = maestro.sort_values("id")
    out = RES_DIR / "_resumen_TODAS.csv"
    maestro.to_csv(out, index=False)
    print(f"\n★ CSV maestro: {out}  ({len(maestro)} ciudades, {maestro.shape[1]} columnas)")


def main():
    if not Path(EXCEL_PATH).exists():
        sys.exit(f"No se encuentra el Excel: {EXCEL_PATH}")
    try:
        import pyrosm  # noqa: F401
    except ImportError:
        sys.exit("Falta pyrosm. Instálalo con:  pip install pyrosm")
    # avisar de .pbf faltantes según los países a procesar
    ciudades = pd.read_excel(EXCEL_PATH, sheet_name=HOJA)
    if SOLO_PAIS:
        ciudades = ciudades[ciudades["pais"] == SOLO_PAIS]
    faltan = sorted({p for p in ciudades["pais"].unique()
                     if not Path(PBF_PATHS.get(p, "")).exists()})
    if faltan:
        print("⚠ Faltan extractos .pbf para:", ", ".join(faltan))
        print("  Descárgalos de Geofabrik y ajusta PBF_PATHS. Continúo con los disponibles.\n")

    total = len(ciudades)

    # separar ya-hechas (se omiten) de pendientes
    log = []
    pendientes = []
    for _, row in ciudades.iterrows():
        ciudad = str(row["ciudad"])
        destino = RES_DIR / f"{slug(ciudad)}_resumen.csv"
        if destino.exists() and not FORCE:
            log.append({"ciudad": ciudad, "estado": "omitida"})
        else:
            pendientes.append(row)

    nw = max(1, int(N_WORKERS))
    print(f"Procesando {len(pendientes)} ciudades pendientes de {total} "
          f"(network_type={NETWORK_TYPE}, workers={nw})\n")

    if nw > 1 and len(pendientes) > 1:
        # --- paralelo: varias ciudades a la vez (offline, sin límites de servidor) ---
        with ProcessPoolExecutor(max_workers=nw) as ex:
            futs = {ex.submit(_tarea, row.to_dict()): str(row["ciudad"]) for row in pendientes}
            hechas = 0
            for fut in as_completed(futs):
                res = fut.result(); hechas += 1
                marca = "✓" if res["estado"] == "ok" else "✗"
                print(f"[{hechas}/{len(pendientes)}] {marca} {res['ciudad']} ({res['estado']})",
                      flush=True)
                log.append(res)
    else:
        # --- secuencial (con prints de progreso por paso) ---
        for i, row in enumerate(pendientes, 1):
            ciudad = str(row["ciudad"])
            print(f"[{i}/{len(pendientes)}] {ciudad} ({row.get('pais')})")
            log.append(_tarea(row.to_dict()))

    pd.DataFrame(log).to_csv(RES_DIR / "_log_batch.csv", index=False)
    ensamblar_maestro()
    ok = sum(1 for x in log if x["estado"] == "ok")
    err = sum(1 for x in log if x["estado"] == "error")
    om = sum(1 for x in log if x["estado"] == "omitida")
    print(f"\nResumen: {ok} ok · {err} con error · {om} omitidas · de {total}")


if __name__ == "__main__":
    main()
