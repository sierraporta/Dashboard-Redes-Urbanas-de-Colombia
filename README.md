# Dashboard-Redes-Urbanas-de-Colombia
Redes Urbanas de Colombia. Caracterización de 140 ciudades desde su red vial peatonal: estructura, centralidad y accesibilidad.

# Redes Urbanas de Colombia

**Caracterización de 140 ciudades colombianas a partir de la estructura de su red vial peatonal: forma, centralidad y accesibilidad.**
*Characterization of 140 Colombian cities from the structure of their pedestrian street network: form, centrality and accessibility.*

![Cartagena de Indias](docs/ColombiaImagenes/leandro-loureiro-J0suKy48jfk-unsplash.jpg)
<sub>📷 Leandro Loureiro · Cartagena · Unsplash</sub>

---

## 🌐 Página en vivo / Live site

> **https://sierraporta.github.io/Dashboard-Redes-Urbanas-de-Colombia/**

Un **dashboard interactivo y bilingüe (ES/EN)** con cinco vistas: Inicio, Ranking, Perfil de ciudad, Comparar, Mapa y Metodología.

---

## Resumen

Este proyecto mide la **forma física** de las ciudades colombianas —cómo se conectan sus calles— y su **accesibilidad peatonal** a servicios esenciales, usando datos abiertos de OpenStreetMap y análisis de redes. No mide transporte público ni tecnología: mide el esqueleto urbano y qué tan cerca queda todo a pie, como un **proxy data-driven** de caminabilidad, compacidad y equidad urbana.

A partir de las métricas se construyen cuatro **índices 0–100** (percentiles entre las 140 ciudades):

| Índice | Qué captura |
|---|---|
| **Conectividad estructural** | Densidad de intersecciones, grado, closeness y rectitud (centralidades como proxy de caracterización). |
| **Accesibilidad** | % de la ciudad con servicios esenciales a menos de 1 km ("ciudad de distancias cortas"). |
| **Equidad** | Qué tan parejo es ese acceso entre barrios (inverso de la desigualdad). |
| **Índice general** | Promedio de los tres. |

### Abstract (EN)

An open, data-driven tool characterizing 140 Colombian cities by their pedestrian street-network structure (centralities) and their accessibility to essential services (POIs), from OpenStreetMap data. Four 0–100 percentile indices —connectivity, accessibility, equity and an overall index— summarize each city.

---

## Metodología (resumen)

1. **Fuente**: extractos nacionales de **OpenStreetMap** (Geofabrik), leídos localmente con `pyrosm` (sin depender de servidores). Ventana común: **disco de 6 km** de radio (~113 km²) por ciudad.
2. **Red**: red vial **peatonal** convertida a grafo con `OSMnx` y **simplificada topológicamente** (grado, densidad de intersecciones y circuidad con significado real).
3. **Métricas** (con `igraph`): forma global (densidad, grado, circuidad, clustering, longitud de tramo), **centralidades** (grado, closeness, betweenness) y **distancia en red** al servicio más cercano de 8 tipos (Dijkstra multi-fuente) → mediana, % a <1 km y coeficiente de variación.
4. **Índices**: cada métrica se normaliza por **percentil** entre las 140 ciudades y se promedia por bloque.
5. **Calidad de datos**: etiquetas **A** (confiable) · **B** (media) · **C** (cobertura OSM limitada; excluidas del ranking por defecto).

> El detalle completo está en la pestaña **Metodología** del dashboard.

---

## Cobertura

- **140 ciudades** de Colombia.
- **33 entes territoriales**: los 32 departamentos + Bogotá D.C.
- **6 regiones**: Andina, Caribe, Pacífica, Orinoquía, Amazonía e Insular.

---

## Estructura del repositorio

```
.
├── docs/                     ← el sitio web publicado (GitHub Pages)
│   ├── index.html            ← el dashboard
│   ├── isologo11.png
│   ├── ColombiaImagenes/     ← fotos (Unsplash) optimizadas + créditos
│   └── figuras/              ← mapas de red (closeness) por ciudad
├── dashboard_colombia.html   ← versión de trabajo (usa las carpetas full-res)
├── ciudades_mexico_colombia.xlsx
├── analisis_colombia.ipynb   ← notebook de análisis
├── urban_accessibility_batch_pyrosm.py  ← pipeline de cálculo (offline)
├── ensamblar_dataset.py      ← ensamblado del dataset
└── dataset/                  ← CSV ensamblados (dataset maestro, curado, etc.)
```

> Los extractos `*.osm.pbf` y la carpeta `figuras/` completa **no se versionan** (ver `.gitignore`): son pesados y no los necesita la página.

---

## Publicar en GitHub Pages

1. Sube el repositorio a GitHub (público).
2. **Settings → Pages → Build and deployment → Source: “Deploy from a branch”** → rama `main`, carpeta **`/docs`** → *Save*.
3. En ~1 minuto la página estará en `https://TU_USUARIO.github.io/redes-urbanas-colombia/`.

---

## Herramientas

`Python` · `OSMnx` · `pyrosm` · `igraph` · `NetworkX` · `GeoPandas` · `SciPy` · `pandas` · `Chart.js` · `Leaflet`

---

## Créditos

**Idea, desarrollo, conceptualización, análisis de redes, cálculo de índices y desarrollo del tablero:**
**David Sierra Porta** — Universidad Tecnológica de Bolívar, Cartagena de Indias, Colombia · dporta@utb.edu.co · *julio de 2026.*

Esta idea surge de un proyecto en el marco de las **estancias Delfín 2026** en Cartagena (Colombia), en la Universidad Tecnológica de Bolívar, con estudiantes de intercambio de México (Sonora y Valle de Bravo). Agradecemos a la **Dirección de Internacionalización de la Universidad Tecnológica de Bolívar** por sus gestiones y acompañamiento continuo.

- **Datos**: © OpenStreetMap contributors (licencia **ODbL**).
- **Fotografías**: bajo licencia **Unsplash** (uso libre). Autores y enlaces en `docs/ColombiaImagenes/imagenes_creditos.txt` y en el botón **©** del dashboard.

> Inspirado en el formato de dashboards como el *Urban Mobility Readiness Index* de Oliver Wyman, pero **no está afiliado ni pretende equivaler** a él: aquí solo se mide estructura de red y accesibilidad peatonal.

---

## Licencia

- **Código y dashboard**: se sugiere licencia **MIT** (añade un archivo `LICENSE` si lo deseas).
- **Datos de OpenStreetMap**: **ODbL**.
- **Fotografías**: **Unsplash License**.
