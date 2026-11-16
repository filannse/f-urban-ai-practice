from __future__ import annotations

import argparse
import json
import pickle
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
from pyrosm import OSM

from iduedu.modules.drive_walk_builder import get_max_speed
from iduedu.utils.utils import estimate_crs_for_bounds, remove_weakly_connected_nodes


DEFAULT_SLUG = "nizhnevartovsk"
DEFAULT_QUERY = "Нижневартовск, Ханты-Мансийский автономный округ — Югра, Россия"
DEFAULT_FALLBACK_QUERY = "Нижневартовск, Россия"
SERVICES = ("school", "kindergarten", "polyclinic")
SERVICE_TAGS = {
    "school": ["school"],
    "kindergarten": ["kindergarten"],
    "polyclinic": ["polyclinic", "clinic"],
}
WALK_SPEED_M_PER_MIN = 5 * 1000 / 60
GEOMETRY_TYPES = ("Polygon", "MultiPolygon", "LineString", "MultiLineString")


def find_project_root(start: Path) -> Path:
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate
    return start


def parse_args() -> argparse.Namespace:
    root = find_project_root(Path(__file__).parent)
    parser = argparse.ArgumentParser(
        description="Готовит кэш OSM-слоёв и графов для ноутбука BlocksNet из локального .osm.pbf."
    )
    parser.add_argument("--pbf", type=Path, required=True, help="Путь к файлу .osm.pbf с нужным регионом.")
    parser.add_argument("--slug", default=DEFAULT_SLUG, help="Имя территории (папка в examples/data).")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="Запрос Nominatim для границы территории.")
    parser.add_argument("--fallback-query", default=DEFAULT_FALLBACK_QUERY, help="Запасной запрос Nominatim.")
    parser.add_argument("--buffer-deg", type=float, default=0.05, help="Отступ вокруг границы в градусах.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=root / "examples" / "data" / DEFAULT_SLUG,
        help="Каталог кэша (по умолчанию examples/data/<slug>).",
    )
    return parser.parse_args()


def save_geo(gdf: gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if out.crs is None:
        out = out.set_crs(4326)
    elif out.crs.to_epsg() != 4326:
        out = out.to_crs(4326)
    if out.empty:
        path.write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
    else:
        out.to_file(path, driver="GeoJSON")
    print(f"Сохранено: {path} ({len(out)} объектов)")


def load_boundary(query: str, fallback: str) -> gpd.GeoDataFrame:
    try:
        boundary = ox.geocode_to_gdf(query)
    except Exception as exc:
        print(f"Предупреждение: не удалось геокодировать основной запрос: {exc}")
        boundary = ox.geocode_to_gdf(fallback)
    boundary = boundary.reset_index(drop=True)
    boundary = boundary[boundary.geometry.notna() & ~boundary.geometry.is_empty].copy()
    boundary = boundary[boundary.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    if boundary.empty:
        raise SystemExit("Не удалось получить границу территории.")
    boundary.geometry = boundary.geometry.make_valid()
    return boundary.to_crs(4326)


def keep_geometry(gdf: gpd.GeoDataFrame | None, allowed: tuple[str, ...] = GEOMETRY_TYPES) -> gpd.GeoDataFrame:
    if gdf is None or len(gdf) == 0:
        return gpd.GeoDataFrame(geometry=[], crs=4326)
    out = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    out = out[out.geom_type.isin(allowed)].copy()
    return out.reset_index(drop=True)


def filter_values(gdf: gpd.GeoDataFrame, column: str, values: list[str] | tuple[str, ...]) -> gpd.GeoDataFrame:
    if column not in gdf.columns:
        return gdf.iloc[0:0].copy()
    return gdf[gdf[column].isin(list(values))].copy()


def prepare_nodes(nodes: gpd.GeoDataFrame, local_crs) -> gpd.GeoDataFrame:
    nodes = nodes.copy()
    nodes["id"] = nodes["id"].astype("int64")
    nodes = nodes.set_index("id")
    nodes = nodes.to_crs(local_crs)
    nodes["x"] = nodes.geometry.x
    nodes["y"] = nodes.geometry.y
    return nodes[["x", "y", "geometry"]]


def prepare_drive_edges(edges: gpd.GeoDataFrame, nodes: gpd.GeoDataFrame, local_crs) -> gpd.GeoDataFrame:
    return _prepare_edges(edges, nodes, local_crs, "drive")


def prepare_walk_edges(edges: gpd.GeoDataFrame, nodes: gpd.GeoDataFrame, local_crs) -> gpd.GeoDataFrame:
    return _prepare_edges(edges, nodes, local_crs, "walk")


def _speed_for_highway(value) -> float:
    if isinstance(value, str):
        return get_max_speed(value)
    return 40 * 1000 / 60


def _prepare_edges(edges: gpd.GeoDataFrame, nodes: gpd.GeoDataFrame, local_crs, graph_type: str) -> gpd.GeoDataFrame:
    edges = edges.copy()
    edges["u"] = edges["u"].astype("int64")
    edges["v"] = edges["v"].astype("int64")
    edges = edges[edges["u"].isin(nodes.index) & edges["v"].isin(nodes.index)].copy()
    edges["key"] = edges.groupby(["u", "v"]).cumcount()
    edges = gpd.GeoDataFrame(edges, geometry="geometry", crs=edges.crs).to_crs(local_crs)
    edges["length_meter"] = edges.geometry.length.round(3)
    if graph_type == "drive":
        speeds = edges["highway"].apply(_speed_for_highway) if "highway" in edges.columns else 40 * 1000 / 60
        edges["time_min"] = (edges["length_meter"] / speeds).round(3)
        extra_columns: list[str] = []
    else:
        edges["time_min"] = (edges["length_meter"] / WALK_SPEED_M_PER_MIN).round(3)
        edges["type"] = "walk"
        extra_columns = ["type"]
    edges = edges.set_index(["u", "v", "key"])
    edges.index.names = ["u", "v", "key"]
    return edges[["length_meter", "time_min", *extra_columns, "geometry"]]


def build_graph(nodes: gpd.GeoDataFrame, edges: gpd.GeoDataFrame, local_crs, graph_type: str) -> nx.MultiDiGraph:
    graph = ox.graph_from_gdfs(nodes, edges)
    graph = remove_weakly_connected_nodes(graph)
    mapping = {old_label: new_label for new_label, old_label in enumerate(graph.nodes())}
    graph = nx.relabel_nodes(graph, mapping)
    graph.graph["crs"] = local_crs
    graph.graph["type"] = graph_type
    if graph_type == "walk":
        graph.graph["walk_speed"] = WALK_SPEED_M_PER_MIN
    return graph


def main() -> None:
    args = parse_args()
    data_dir = args.data_dir.resolve()
    raw_dir = data_dir / "raw"
    graph_dir = data_dir / "graphs"
    raw_dir.mkdir(parents=True, exist_ok=True)
    graph_dir.mkdir(parents=True, exist_ok=True)
    if not args.pbf.exists():
        raise SystemExit(f"Не найден файл PBF: {args.pbf}")

    boundary = load_boundary(args.query, args.fallback_query)
    save_geo(boundary, raw_dir / "boundaries.geojson")

    minx, miny, maxx, maxy = boundary.total_bounds
    pad = args.buffer_deg
    bbox = [minx - pad, miny - pad, maxx + pad, maxy + pad]
    local_crs = estimate_crs_for_bounds(minx, miny, maxx, maxy).to_epsg()
    print(f"Граница: {boundary.total_bounds}; bbox={bbox}; CRS={local_crs}")

    osm = OSM(str(args.pbf), bounding_box=bbox)

    landuse = keep_geometry(osm.get_landuse(), ("Polygon", "MultiPolygon"))
    save_geo(landuse, raw_dir / "functional_zones.geojson")

    natural = keep_geometry(osm.get_natural())
    waterway = keep_geometry(
        osm.get_data_by_custom_criteria(
            custom_filter={"waterway": ["riverbank", "dock", "canal"]},
            filter_type="keep",
            tags_as_columns=["waterway"],
        )
    )
    reservoir = landuse[landuse["landuse"].isin(["reservoir", "basin"])].copy() if "landuse" in landuse.columns else landuse.iloc[0:0]
    natural_water = filter_values(natural, "natural", ["water", "bay", "strait"]) if "natural" in natural.columns else natural.iloc[0:0]
    water = gpd.GeoDataFrame(
        pd.concat([natural_water, waterway, reservoir], ignore_index=True),
        geometry="geometry",
        crs=4326,
    )
    save_geo(keep_geometry(water), raw_dir / "water.geojson")

    railways = keep_geometry(
        osm.get_data_by_custom_criteria(
            custom_filter={"railway": ["rail", "light_rail", "subway", "tram", "narrow_gauge", "preserved", "funicular"]},
            filter_type="keep",
            tags_as_columns=["railway"],
        ),
        ("LineString", "MultiLineString"),
    )
    save_geo(railways, raw_dir / "railways.geojson")

    buildings = keep_geometry(osm.get_buildings())
    if "building" not in buildings.columns:
        buildings["building"] = "yes"
    if "building:levels" not in buildings.columns:
        buildings["building:levels"] = np.nan
    save_geo(buildings[["building", "building:levels", "geometry"]], raw_dir / "buildings.geojson")

    amenity_values = sorted({value for values in SERVICE_TAGS.values() for value in values})
    pois = keep_geometry(osm.get_pois(custom_filter={"amenity": amenity_values}))
    if "name" not in pois.columns:
        pois["name"] = np.nan
    if "capacity" not in pois.columns:
        pois["capacity"] = np.nan
    for service in SERVICES:
        selected = filter_values(pois, "amenity", SERVICE_TAGS[service]).copy()
        if len(selected):
            selected["amenity"] = service
        save_geo(selected[["amenity", "capacity", "name", "geometry"]], raw_dir / f"service_{service}.geojson")

    drive_nodes, drive_edges = osm.get_network(network_type="driving", nodes=True)
    drive_nodes_prepared = prepare_nodes(drive_nodes, local_crs)
    drive_edges_prepared = prepare_drive_edges(drive_edges, drive_nodes_prepared, local_crs)
    save_geo(gpd.GeoDataFrame(drive_edges_prepared, geometry="geometry", crs=local_crs), raw_dir / "roads.geojson")
    drive_graph = build_graph(drive_nodes_prepared, drive_edges_prepared, local_crs, "drive")
    with (graph_dir / "graph_drive.pickle").open("wb") as file:
        pickle.dump(drive_graph, file)
    print(f"Граф drive: узлов={drive_graph.number_of_nodes():,}, рёбер={drive_graph.number_of_edges():,}")

    walk_nodes, walk_edges = osm.get_network(network_type="walking", nodes=True)
    walk_nodes_prepared = prepare_nodes(walk_nodes, local_crs)
    walk_edges_prepared = prepare_walk_edges(walk_edges, walk_nodes_prepared, local_crs)
    walk_graph = build_graph(walk_nodes_prepared, walk_edges_prepared, local_crs, "walk")
    with (graph_dir / "graph_walk.pickle").open("wb") as file:
        pickle.dump(walk_graph, file)
    print(f"Граф walk: узлов={walk_graph.number_of_nodes():,}, рёбер={walk_graph.number_of_edges():,}")

    source = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pbf": str(args.pbf),
        "territory_query": args.query,
        "bbox": bbox,
        "local_crs": local_crs,
        "services": {service: int(len(filter_values(pois, "amenity", SERVICE_TAGS[service]))) for service in SERVICES},
        "buildings": int(len(buildings)),
        "landuse": int(len(landuse)),
        "water": int(len(water)),
        "railways": int(len(railways)),
        "drive_graph": {"nodes": drive_graph.number_of_nodes(), "edges": drive_graph.number_of_edges()},
        "walk_graph": {"nodes": walk_graph.number_of_nodes(), "edges": walk_graph.number_of_edges()},
    }
    (data_dir / "osm_source.json").write_text(json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Источник данных: {data_dir / 'osm_source.json'}")


if __name__ == "__main__":
    main()
