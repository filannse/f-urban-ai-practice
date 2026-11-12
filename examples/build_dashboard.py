from __future__ import annotations

import argparse
import html
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import mapping


DEFAULT_SLUG = "nizhnevartovsk"
DEFAULT_TITLE = "Нижневартовск — аналитический дашборд"
DEFAULT_SERVICES = ("school", "kindergarten", "polyclinic")
SERVICE_LABELS = {
    "school": "школы",
    "kindergarten": "детские сады",
    "polyclinic": "поликлиники",
}
GRAPH_LABELS = {"drive": "авто", "walk": "пешком"}
GRAPH_ORDER = {"drive": 0, "walk": 1}
COMMON_COLUMNS = {
    "site_area",
    "population",
    "count_buildings",
    "fsi",
    "gsi",
    "mxi",
    "l",
    "osr",
    "share_living",
    "share_non_living",
    "land_use",
    "land_use_str",
    "share",
    "morphotype_strelka",
    "morphotype_spacematrix",
    "cluster",
}
CORE_METRICS = (
    "population",
    "count_buildings",
    "fsi",
    "gsi",
    "mxi",
    "l",
    "osr",
    "share_living",
    "share_non_living",
)
METRIC_LABELS = {
    "population": "Население, чел.",
    "count_buildings": "Количество зданий",
    "fsi": "FSI — коэффициент застройки",
    "gsi": "GSI — коэффициент покрытия",
    "mxi": "MXI — коэффициент смешанности",
    "l": "L — средняя этажность",
    "osr": "OSR — обеспеченность озеленением",
    "share_living": "Доля жилой площади",
    "share_non_living": "Доля нежилой площади",
    "site_area": "Площадь квартала, м²",
    "land_use": "Функциональное использование",
    "land_use_str": "Функциональное использование",
    "morphotype_strelka": "Морфотип Strelka",
    "morphotype_spacematrix": "Морфотип Spacematrix",
    "cluster": "Кластер Spacematrix",
}
CATEGORY_COLUMNS = (
    "land_use_str",
    "land_use",
    "morphotype_strelka",
    "morphotype_spacematrix",
    "cluster",
)
CATEGORY_PALETTE = (
    "#2563eb",
    "#16a34a",
    "#f59e0b",
    "#dc2626",
    "#7c3aed",
    "#0891b2",
    "#db2777",
    "#65a30d",
    "#ea580c",
    "#4f46e5",
    "#0d9488",
    "#be123c",
    "#a16207",
    "#475569",
    "#9333ea",
    "#0284c7",
    "#c2410c",
    "#15803d",
    "#b45309",
    "#7e22ce",
)
PALETTES = {
    "population": ("#fff5eb", "#fee6ce", "#fdd0a2", "#fdae6b", "#fd8d3c", "#e6550d", "#a63603"),
    "density": ("#fcfbfd", "#efedf5", "#dadaeb", "#bcbddc", "#9e9ac8", "#756bb1", "#54278f"),
    "accessibility": ("#1a9850", "#a6d96a", "#ffffbf", "#fdae61", "#d73027"),
    "provision": ("#d73027", "#fdae61", "#ffffbf", "#a6d96a", "#1a9850"),
    "generic": ("#eff6ff", "#dbeafe", "#bfdbfe", "#93c5fd", "#60a5fa", "#3b82f6", "#1d4ed8"),
}
POPUP_COLUMNS = (
    "block_id",
    "population",
    "count_buildings",
    "fsi",
    "gsi",
    "mxi",
    "l",
    "osr",
    "land_use_str",
    "morphotype_strelka",
    "morphotype_spacematrix",
)


def find_project_root(start: Path) -> Path:
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate
    return start


def parse_args() -> argparse.Namespace:
    root = find_project_root(Path(__file__).parent)
    parser = argparse.ArgumentParser(
        description="Собирает автономный HTML-дашборд по сохранённым результатам BlocksNet."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=root / "examples" / "data" / DEFAULT_SLUG,
        help="Каталог с папками results, blocks, services и manifest.json.",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=None,
        help="Каталог с GeoJSON-результатами, если он расположен отдельно от --data-dir.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "examples" / "outputs" / DEFAULT_SLUG / "dashboard.html",
        help="Путь к итоговому HTML-файлу.",
    )
    parser.add_argument("--title", default=DEFAULT_TITLE, help="Заголовок дашборда.")
    parser.add_argument(
        "--max-table-rows",
        type=int,
        default=5000,
        help="Максимальное число кварталов в интерактивной таблице.",
    )
    return parser.parse_args()


def safe_json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if hasattr(value, "value"):
        return safe_json_value(value.value)
    if isinstance(value, dict):
        return {str(key): safe_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [safe_json_value(item) for item in value]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def read_geojson(path: Path) -> gpd.GeoDataFrame | None:
    if not path.exists():
        return None
    try:
        gdf = gpd.read_file(path)
    except Exception as exc:
        print(f"Предупреждение: не удалось прочитать {path}: {exc}")
        return None
    if gdf.crs is None:
        gdf = gdf.set_crs(4326)
    else:
        try:
            gdf = gdf.to_crs(4326)
        except Exception as exc:
            print(f"Предупреждение: не удалось перепроецировать {path}: {exc}")
    if "block_id" not in gdf.columns:
        if gdf.index.name == "block_id" or "block_id" in (gdf.index.names or []):
            gdf = gdf.reset_index()
        else:
            gdf = gdf.reset_index(drop=True)
            gdf["block_id"] = np.arange(len(gdf))
    gdf["block_id"] = gdf["block_id"].astype(str)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if len(gdf):
        try:
            gdf.geometry = gdf.geometry.make_valid()
        except Exception:
            pass
    gdf = gdf.drop_duplicates(subset="block_id", keep="first")
    return gdf.reset_index(drop=True)


def merge_layer(
    base: gpd.GeoDataFrame,
    layer: gpd.GeoDataFrame | None,
    graph: str | None = None,
) -> gpd.GeoDataFrame:
    if layer is None or len(layer) == 0:
        return base
    if len(base) == 0:
        return layer.copy()
    base_indexed = base.set_index("block_id", drop=False)
    layer_indexed = layer.set_index("block_id", drop=False)
    for column in layer.columns:
        if column in ("block_id", layer.geometry.name):
            continue
        if column not in base_indexed.columns:
            base_indexed[column] = layer_indexed[column].reindex(base_indexed.index)
            continue
        if column in COMMON_COLUMNS or column.startswith("count_"):
            continue
        if graph == "walk":
            target = column if column.endswith("_walk") else f"{column}_walk"
            if target not in base_indexed.columns:
                base_indexed[target] = layer_indexed[column].reindex(base_indexed.index)
    return base_indexed.reset_index(drop=True)


def read_manifest(data_dir: Path) -> dict[str, Any]:
    for path in (data_dir / "manifest.json", data_dir.parent / "manifest.json"):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception as exc:
            print(f"Предупреждение: не удалось прочитать манифест {path}: {exc}")
    return {}


def graph_sort_key(graph: str) -> tuple[int, str]:
    return GRAPH_ORDER.get(graph, 99), graph


def detect_graphs(results_dir: Path, data_dir: Path) -> list[str]:
    graphs: set[str] = set()
    for folder in (results_dir, data_dir / "graphs", data_dir / "matrices"):
        if not folder.exists():
            continue
        for path in folder.glob("*"):
            match = re.search(r"(?:^|_)(drive|walk)(?:\.[^.]+)?$", path.stem)
            if match:
                graphs.add(match.group(1))
    for path in results_dir.glob("blocks_indicators_*.geojson"):
        graphs.add(path.stem.removeprefix("blocks_indicators_"))
    return sorted(graphs, key=graph_sort_key)


def detect_services(results_dir: Path, data_dir: Path, manifest: dict[str, Any], base: gpd.GeoDataFrame) -> list[str]:
    services: set[str] = set()
    manifest_services = manifest.get("services")
    if isinstance(manifest_services, dict):
        services.update(str(key) for key in manifest_services)
    for path in results_dir.glob("provision_*.geojson"):
        match = re.match(r"provision_(.+)_(?:drive|walk)\.geojson$", path.name)
        if match:
            services.add(match.group(1))
    for folder in (data_dir / "blocks", data_dir / "services"):
        if folder.exists():
            for path in folder.glob("*.geojson"):
                if path.stem.startswith("blocks_") and path.stem not in COMMON_COLUMNS:
                    service = path.stem.removeprefix("blocks_")
                    if service not in {"buildings", "land_use"}:
                        services.add(service)
    for column in base.columns:
        match = re.match(r"provision_strong_(.+?)(?:_(?:walk|drive))?$", column)
        if match:
            services.add(match.group(1))
    ordered = [service for service in DEFAULT_SERVICES if service in services]
    ordered.extend(sorted(services - set(ordered)))
    return ordered


def choose_base(results_dir: Path, data_dir: Path) -> tuple[Path | None, gpd.GeoDataFrame | None]:
    candidates = [
        results_dir / "blocks_indicators.geojson",
        results_dir / "blocks_indicators_drive.geojson",
        results_dir / "blocks_indicators_walk.geojson",
    ]
    candidates.extend(sorted(results_dir.glob("blocks_indicators_*.geojson")))
    candidates.extend(
        [
            data_dir / "blocks" / "blocks_land_use.geojson",
            data_dir / "blocks" / "blocks_buildings.geojson",
            data_dir / "blocks" / "blocks.geojson",
        ]
    )
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        gdf = read_geojson(path)
        if gdf is not None and len(gdf):
            return path, gdf
    return None, None


def load_data(
    data_dir: Path, results_dir: Path
) -> tuple[gpd.GeoDataFrame, dict[str, Any], list[str], list[str], list[str], list[str]]:
    manifest = read_manifest(data_dir)
    base_path, base = choose_base(results_dir, data_dir)
    if base is None or base_path is None:
        expected = results_dir / "blocks_indicators_drive.geojson"
        raise SystemExit(
            "Не найдены результаты BlocksNet.\n"
            f"Проверены: {results_dir}\n"
            f"Ожидается, например: {expected}\n"
            "Сначала выполните ноутбук examples/blocksnet_nizhnevartovsk.ipynb "
            "или укажите правильный каталог через --data-dir / --results-dir."
        )
    sources = [str(base_path)]
    blocks_dir = data_dir / "blocks"
    for path in (
        blocks_dir / "blocks_land_use.geojson",
        blocks_dir / "blocks_buildings.geojson",
    ):
        if path.exists() and path != base_path:
            layer = read_geojson(path)
            if layer is not None and len(layer):
                base = merge_layer(base, layer, graph=None)
                sources.append(str(path))
    base_graph = None
    match = re.match(r"blocks_indicators_(drive|walk)$", base_path.stem)
    if match:
        base_graph = match.group(1)
    graphs = detect_graphs(results_dir, data_dir)
    if not graphs and base_graph:
        graphs = [base_graph]
    services = detect_services(results_dir, data_dir, manifest, base)
    for service in services:
        path = blocks_dir / f"blocks_{service}.geojson"
        if path.exists() and path != base_path:
            layer = read_geojson(path)
            if layer is not None and len(layer):
                base = merge_layer(base, layer, graph=None)
                sources.append(str(path))
    for graph in graphs:
        path = results_dir / f"blocks_indicators_{graph}.geojson"
        if path.exists() and path != base_path:
            layer = read_geojson(path)
            if layer is not None and len(layer):
                base = merge_layer(base, layer, graph=graph)
                sources.append(str(path))
    for graph in graphs:
        area_path = results_dir / f"area_accessibility_{graph}.geojson"
        if area_path.exists():
            layer = read_geojson(area_path)
            if layer is not None and len(layer):
                base = merge_layer(base, layer, graph=graph)
                sources.append(str(area_path))
        for service in services:
            provision_path = results_dir / f"provision_{service}_{graph}.geojson"
            if provision_path.exists():
                layer = read_geojson(provision_path)
                if layer is not None and len(layer):
                    base = merge_layer(base, layer, graph=graph)
                    sources.append(str(provision_path))
    unique_sources = list(dict.fromkeys(sources))
    return base, manifest, graphs, services, unique_sources, [str(results_dir), str(data_dir)]


def ensure_area_column(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if "site_area" in gdf.columns:
        values = pd.to_numeric(gdf["site_area"], errors="coerce")
        if values.notna().any() and float(values.fillna(0).max()) > 0:
            gdf["site_area"] = values
            return gdf
    if len(gdf) == 0 or gdf.crs is None:
        gdf["site_area"] = np.nan
        return gdf
    try:
        metric = gdf.to_crs(gdf.estimate_utm_crs())
        gdf["site_area"] = metric.geometry.area
    except Exception:
        gdf["site_area"] = np.nan
    return gdf


def numeric_columns(gdf: gpd.GeoDataFrame) -> list[str]:
    columns: list[str] = []
    for column in gdf.columns:
        if column in ("block_id", gdf.geometry.name):
            continue
        if column in CATEGORY_COLUMNS:
            continue
        series = gdf[column]
        if pd.api.types.is_bool_dtype(series):
            continue
        if not pd.api.types.is_numeric_dtype(series):
            continue
        values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
        if values.notna().any():
            columns.append(column)
    return columns


def categorical_columns(gdf: gpd.GeoDataFrame) -> list[str]:
    columns: list[str] = []
    for column in CATEGORY_COLUMNS:
        if column not in gdf.columns:
            continue
        values = gdf[column].dropna().map(str).str.strip()
        values = values[values != ""]
        if 1 <= values.nunique() <= 60:
            columns.append(column)
    for column in gdf.columns:
        if column in columns or column in ("block_id", gdf.geometry.name):
            continue
        if column in METRIC_LABELS or column in numeric_columns(gdf):
            continue
        series = gdf[column]
        if series.dtype != object:
            continue
        values = series.dropna().map(str).str.strip()
        values = values[values != ""]
        if 2 <= values.nunique() <= 40:
            columns.append(column)
    return columns


def service_label(service: str) -> str:
    return SERVICE_LABELS.get(service, service.replace("_", " "))


def metric_graph(column: str, all_columns: set[str]) -> str | None:
    if column.endswith("_walk"):
        return "walk"
    if column.endswith("_drive"):
        return "drive"
    if column.startswith(("provision_", "demand_", "capacity_")) and f"{column}_walk" in all_columns:
        return "drive"
    return None


def metric_label(column: str, all_columns: set[str]) -> str:
    if column in METRIC_LABELS:
        return METRIC_LABELS[column]
    service_match = re.match(r"^count_(.+)$", column)
    if service_match:
        return f"Количество: {service_label(service_match.group(1))}"
    accessibility_match = re.match(r"^area_accessibility(?:_(drive|walk))?$", column)
    if accessibility_match:
        graph = accessibility_match.group(1)
        suffix = f" ({GRAPH_LABELS[graph]})" if graph in GRAPH_LABELS else ""
        return f"Зональная доступность, мин{suffix}"
    provision_match = re.match(
        r"^(provision_strong|provision_weak|demand_left|demand_within|demand_without|demand|"
        r"capacity_left|capacity_within|capacity_without|capacity)_(.+?)(?:_(walk|drive))?$",
        column,
    )
    if provision_match:
        kind, service, graph = provision_match.groups()
        graph = graph or metric_graph(column, all_columns)
        titles = {
            "provision_strong": "Сильная обеспеченность",
            "provision_weak": "Слабая обеспеченность",
            "demand": "Спрос",
            "capacity": "Вместимость",
            "demand_left": "Остаточный спрос",
            "demand_within": "Спрос в зоне доступности",
            "demand_without": "Спрос вне зоны доступности",
            "capacity_left": "Остаточная вместимость",
            "capacity_within": "Вместимость в зоне доступности",
            "capacity_without": "Вместимость вне зоны доступности",
        }
        suffix = f" ({GRAPH_LABELS[graph]})" if graph in GRAPH_LABELS else ""
        return f"{titles.get(kind, kind)}: {service_label(service)}{suffix}"
    return column.replace("_", " ")


def metric_group(column: str) -> str:
    if column in CORE_METRICS or column == "site_area":
        return "Застройка и население"
    if column.startswith("count_"):
        return "Объекты обслуживания"
    if "area_accessibility" in column:
        return "Доступность"
    if column.startswith("provision_"):
        return "Обеспеченность"
    if column.startswith(("demand", "capacity")):
        return "Спрос и вместимость"
    if column in CATEGORY_COLUMNS:
        return "Функции и морфология"
    return "Прочие показатели"


def choose_palette(column: str) -> tuple[str, ...]:
    if column == "population":
        return PALETTES["population"]
    if column in ("fsi", "gsi", "mxi", "l", "osr"):
        return PALETTES["density"]
    if "area_accessibility" in column:
        return PALETTES["accessibility"]
    if column.startswith(("provision_", "demand", "capacity")):
        return PALETTES["provision"]
    return PALETTES["generic"]


def build_metric_config(
    gdf: gpd.GeoDataFrame, numeric: Iterable[str], categorical: Iterable[str]
) -> tuple[dict[str, dict[str, Any]], list[str], list[dict[str, Any]]]:
    all_columns = set(gdf.columns)
    metrics: dict[str, dict[str, Any]] = {}
    for column in numeric:
        values = pd.to_numeric(gdf[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
        values = values.dropna()
        if values.empty:
            continue
        minimum = float(values.min())
        maximum = float(values.max())
        if not math.isfinite(minimum) or not math.isfinite(maximum):
            continue
        if column in ("provision_strong", "provision_weak") or column.startswith(
            ("provision_strong_", "provision_weak_")
        ):
            minimum, maximum = 0.0, 1.0
        elif column in ("share_living", "share_non_living", "osr"):
            minimum, maximum = min(0.0, minimum), max(1.0, maximum)
        metrics[column] = {
            "kind": "numeric",
            "label": metric_label(column, all_columns),
            "group": metric_group(column),
            "min": minimum,
            "max": maximum,
            "colors": list(choose_palette(column)),
        }
    for column in categorical:
        values = gdf[column].dropna().map(str).str.strip()
        values = values[values != ""]
        unique = sorted(values.unique())
        if not unique:
            continue
        if len(unique) > 24:
            unique = unique[:24]
        colors = {value: CATEGORY_PALETTE[index % len(CATEGORY_PALETTE)] for index, value in enumerate(unique)}
        metrics[column] = {
            "kind": "category",
            "label": metric_label(column, all_columns),
            "group": metric_group(column),
            "colors": colors,
            "order": unique,
        }
    group_order = [
        "Застройка и население",
        "Доступность",
        "Обеспеченность",
        "Спрос и вместимость",
        "Объекты обслуживания",
        "Функции и морфология",
        "Прочие показатели",
    ]
    groups: list[dict[str, Any]] = []
    for group in group_order:
        keys = [key for key, value in metrics.items() if value["group"] == group]
        if keys:
            groups.append({"label": group, "keys": keys})
    ordered_keys = [key for group in groups for key in group["keys"]]
    return metrics, ordered_keys, groups


def finite_values(series: pd.Series) -> list[float]:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return [float(value) for value in values if math.isfinite(float(value))]


def format_number(value: Any, digits: int | None = None) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "—"
    if digits is not None:
        text = f"{number:,.{digits}f}"
    elif abs(number) >= 1_000_000:
        text = f"{number / 1_000_000:,.2f} млн"
    elif abs(number) >= 10_000:
        text = f"{number / 1_000:,.1f} тыс."
    elif abs(number) >= 100:
        text = f"{number:,.0f}"
    elif abs(number) >= 10:
        text = f"{number:,.1f}"
    else:
        text = f"{number:,.2f}"
    return text.replace(",", " ").replace(".", ",")


def format_cell(value: Any, column: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, (bool, np.bool_)):
        return "да" if value else "нет"
    if isinstance(value, (int, np.integer)):
        return format_number(value, 0)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if not math.isfinite(number):
            return "—"
        return format_number(number)
    text = str(value).strip()
    return text if text else "—"


def escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def empty_chart(message: str) -> str:
    return (
        '<svg class="chart-svg" viewBox="0 0 620 180" role="img">'
        '<rect width="620" height="180" rx="12" fill="#f8fafc"/>'
        f'<text x="310" y="96" text-anchor="middle" fill="#64748b" font-size="14">{escape(message)}</text>'
        "</svg>"
    )


def svg_histogram(values: list[float], x_label: str, color: str = "#2563eb", bins: int = 20) -> str:
    if not values:
        return empty_chart("Нет данных для графика")
    minimum = min(values)
    maximum = max(values)
    if maximum <= minimum:
        maximum = minimum + 1.0
    counts, edges = np.histogram(values, bins=bins, range=(minimum, maximum))
    max_count = max(int(counts.max()), 1)
    width, height = 620, 260
    left, right, top, bottom = 48, 16, 18, 50
    plot_width = width - left - right
    plot_height = height - top - bottom
    bar_width = plot_width / len(counts)
    bars: list[str] = []
    for index, count in enumerate(counts):
        x = left + index * bar_width
        bar_height = plot_height * int(count) / max_count
        y = top + plot_height - bar_height
        label = f"{format_number(edges[index])}–{format_number(edges[index + 1])}: {int(count)}"
        bars.append(
            f'<rect x="{x + 1:.2f}" y="{y:.2f}" width="{max(bar_width - 2, 1):.2f}" '
            f'height="{bar_height:.2f}" rx="2" fill="{color}" opacity="0.86">'
            f"<title>{escape(label)}</title></rect>"
        )
    axis_y = top + plot_height
    x_tick_values = [minimum, (minimum + maximum) / 2, maximum]
    ticks: list[str] = []
    for index, value in enumerate(x_tick_values):
        x = left + plot_width * index / 2
        anchor = "start" if index == 0 else "end" if index == 2 else "middle"
        ticks.append(
            f'<text x="{x:.2f}" y="{height - 20}" text-anchor="{anchor}" '
            f'fill="#64748b" font-size="11">{escape(format_number(value))}</text>'
        )
    return (
        f'<svg class="chart-svg" viewBox="0 0 {width} {height}" role="img">'
        f'<text x="{left}" y="12" fill="#64748b" font-size="11">{escape(x_label)}</text>'
        f'<line x1="{left}" y1="{axis_y}" x2="{width - right}" y2="{axis_y}" stroke="#cbd5e1"/>'
        f'<text x="{left - 8}" y="{top + 10}" text-anchor="end" fill="#64748b" font-size="11">{max_count}</text>'
        f'<text x="{left - 8}" y="{axis_y}" text-anchor="end" fill="#64748b" font-size="11">0</text>'
        + "".join(bars)
        + "".join(ticks)
        + "</svg>"
    )


def truncated(text: str, limit: int = 30) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def svg_hbar(
    items: list[tuple[str, float]],
    value_label: str = "",
    color: str = "#2563eb",
    max_items: int | None = None,
) -> str:
    items = [(label, value) for label, value in items if value is not None and math.isfinite(float(value))]
    if not items:
        return empty_chart("Нет данных для графика")
    items = sorted(items, key=lambda item: float(item[1]), reverse=True)
    if max_items is not None:
        items = items[:max_items]
    maximum = max(float(value) for _, value in items)
    if maximum <= 0:
        maximum = 1.0
    width = 620
    left, right, top, bottom = 180, 86, 10, 10
    row_height = 28
    height = top + len(items) * row_height + bottom
    plot_width = width - left - right
    rows: list[str] = []
    for index, (label, value) in enumerate(items):
        y = top + index * row_height
        bar_width = max(plot_width * float(value) / maximum, 1)
        rows.append(
            f'<text x="{left - 8}" y="{y + 17}" text-anchor="end" fill="#334155" font-size="12">'
            f"{escape(truncated(str(label), 28))}</text>"
            f'<rect x="{left}" y="{y + 5}" width="{plot_width}" height="16" rx="5" fill="#eef2f7"/>'
            f'<rect x="{left}" y="{y + 5}" width="{bar_width:.2f}" height="16" rx="5" fill="{color}" opacity="0.9">'
            f"<title>{escape(str(label))}: {escape(format_number(value))} {escape(value_label)}</title></rect>"
            f'<text x="{left + bar_width + 8:.2f}" y="{y + 17}" fill="#475569" font-size="11">'
            f"{escape(format_number(value))}</text>"
        )
    return (
        f'<svg class="chart-svg" viewBox="0 0 {width} {height}" role="img">'
        + "".join(rows)
        + "</svg>"
    )


def svg_grouped_hbar(
    categories: list[str],
    series: list[dict[str, Any]],
    value_label: str = "",
) -> str:
    if not categories or not series:
        return empty_chart("Нет данных для графика")
    maximum = 0.0
    for item in series:
        for value in item["values"]:
            if value is not None and math.isfinite(float(value)):
                maximum = max(maximum, float(value))
    if maximum <= 0:
        maximum = 1.0
    width = 680
    left, right, top, bottom = 185, 74, 42, 10
    row_height = 44
    bar_height = 14
    gap = 4
    height = top + len(categories) * row_height + bottom
    plot_width = width - left - right
    parts: list[str] = []
    legend_x = left
    for item in series:
        parts.append(
            f'<rect x="{legend_x}" y="12" width="12" height="12" rx="3" fill="{item["color"]}"/>'
            f'<text x="{legend_x + 18}" y="22" fill="#475569" font-size="12">{escape(item["label"])}</text>'
        )
        legend_x += 30 + 7 * len(item["label"])
    for cat_index, category in enumerate(categories):
        y = top + cat_index * row_height
        parts.append(
            f'<text x="{left - 8}" y="{y + 25}" text-anchor="end" fill="#334155" font-size="12">'
            f"{escape(truncated(category, 28))}</text>"
        )
        for series_index, item in enumerate(series):
            value = item["values"][cat_index]
            if value is None or not math.isfinite(float(value)):
                continue
            bar_width = max(plot_width * float(value) / maximum, 1)
            bar_y = y + 7 + series_index * (bar_height + gap)
            parts.append(
                f'<rect x="{left}" y="{bar_y}" width="{bar_width:.2f}" height="{bar_height}" rx="4" '
                f'fill="{item["color"]}" opacity="0.9">'
                f"<title>{escape(category)} · {escape(item['label'])}: "
                f"{escape(format_number(value))} {escape(value_label)}</title></rect>"
                f'<text x="{left + bar_width + 7:.2f}" y="{bar_y + 11}" fill="#475569" font-size="10.5">'
                f"{escape(format_number(value))}</text>"
            )
    return (
        f'<svg class="chart-svg" viewBox="0 0 {width} {height}" role="img">'
        + "".join(parts)
        + "</svg>"
    )


def summary_stats_row(column: str, values: list[float], total_rows: int, label: str, group: str) -> dict[str, Any]:
    if values:
        array = np.array(values, dtype=float)
        return {
            "column": column,
            "label": label,
            "group": group,
            "count": len(values),
            "missing": total_rows - len(values),
            "min": float(np.min(array)),
            "median": float(np.median(array)),
            "mean": float(np.mean(array)),
            "p95": float(np.percentile(array, 95)),
            "max": float(np.max(array)),
            "sum": float(np.sum(array)),
        }
    return {
        "column": column,
        "label": label,
        "group": group,
        "count": 0,
        "missing": total_rows,
        "min": None,
        "median": None,
        "mean": None,
        "p95": None,
        "max": None,
        "sum": None,
    }


def render_kpi_cards(cards: list[dict[str, str]]) -> str:
    blocks: list[str] = []
    for card in cards:
        tone = card.get("tone", "blue")
        blocks.append(
            f'<article class="kpi kpi-{tone}">'
            f'<div class="kpi-label">{escape(card["label"])}</div>'
            f'<div class="kpi-value">{escape(card["value"])}</div>'
            f'<div class="kpi-note">{escape(card.get("note", ""))}</div>'
            "</article>"
        )
    return "".join(blocks)


def render_table(
    df: pd.DataFrame,
    table_id: str,
    search_id: str,
    columns: list[str] | None = None,
    max_rows: int | None = None,
    sort_column: str | None = None,
    labels: dict[str, str] | None = None,
) -> tuple[str, int, int]:
    view = df.copy()
    labels = labels or {}
    if columns is None:
        columns = [column for column in view.columns if column != "geometry"]
    else:
        columns = [column for column in columns if column in view.columns]
    if sort_column and sort_column in view.columns:
        view = view.sort_values(sort_column, ascending=False, na_position="last")
    total = len(view)
    if max_rows is not None:
        view = view.head(max_rows)
    header = "".join(f"<th>{escape(labels.get(column, column))}</th>" for column in columns)
    body: list[str] = []
    for _, row in view.iterrows():
        cells: list[str] = []
        for column in columns:
            value = row[column]
            raw = safe_json_value(value)
            text = format_cell(raw, column)
            sort_value = raw if isinstance(raw, (int, float)) and not isinstance(raw, bool) else text
            numeric_class = " class=\"num\"" if isinstance(raw, (int, float)) and not isinstance(raw, bool) else ""
            cells.append(
                f'<td{numeric_class} data-sort="{escape(sort_value)}" title="{escape(text)}">{escape(text)}</td>'
            )
        body.append("<tr>" + "".join(cells) + "</tr>")
    shown_text = f"{len(view):,}".replace(",", " ")
    total_text = f"{total:,}".replace(",", " ")
    table = (
        f'<div class="table-tools"><input id="{search_id}" class="table-search" type="search" '
        f'placeholder="Поиск по таблице…"><span>{shown_text} из {total_text} строк</span></div>'
        f'<div class="table-wrap"><table id="{table_id}" class="data-table"><thead><tr>{header}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>'
    )
    return table, len(view), total


def metric_series(gdf: gpd.GeoDataFrame, column: str) -> list[float]:
    if column not in gdf.columns:
        return []
    return finite_values(gdf[column])


def land_use_area_items(gdf: gpd.GeoDataFrame) -> list[tuple[str, float]]:
    column = "land_use_str" if "land_use_str" in gdf.columns else "land_use" if "land_use" in gdf.columns else None
    if column is None or "site_area" not in gdf.columns:
        return []
    frame = gdf[[column, "site_area"]].copy()
    frame["site_area"] = pd.to_numeric(frame["site_area"], errors="coerce")
    frame[column] = frame[column].fillna("Не определено").astype(str)
    grouped = frame.groupby(column, dropna=False)["site_area"].sum().sort_values(ascending=False)
    return [(str(index).replace("_", " "), float(value) / 10_000) for index, value in grouped.items()]


def land_use_population_items(gdf: gpd.GeoDataFrame) -> list[tuple[str, float]]:
    column = "land_use_str" if "land_use_str" in gdf.columns else "land_use" if "land_use" in gdf.columns else None
    if column is None or "population" not in gdf.columns:
        return []
    frame = gdf[[column, "population"]].copy()
    frame["population"] = pd.to_numeric(frame["population"], errors="coerce").fillna(0)
    frame[column] = frame[column].fillna("Не определено").astype(str)
    grouped = frame.groupby(column, dropna=False)["population"].sum().sort_values(ascending=False)
    return [(str(index).replace("_", " "), float(value)) for index, value in grouped.items()]


def categorical_items(gdf: gpd.GeoDataFrame, column: str) -> list[tuple[str, float]]:
    if column not in gdf.columns:
        return []
    values = gdf[column].dropna().astype(str).str.strip()
    values = values[values != ""]
    counts = values.value_counts()
    return [(str(index).replace("_", " "), float(value)) for index, value in counts.items()]


def top_population_items(gdf: gpd.GeoDataFrame, limit: int = 10) -> list[tuple[str, float]]:
    if "population" not in gdf.columns:
        return []
    frame = gdf[["block_id", "population"]].copy()
    frame["population"] = pd.to_numeric(frame["population"], errors="coerce").fillna(0)
    frame = frame.sort_values("population", ascending=False).head(limit)
    return [(f"Квартал {row.block_id}", float(row.population)) for row in frame.itertuples()]


def top_missing_items(gdf: gpd.GeoDataFrame, numeric: list[str], limit: int = 10) -> list[tuple[str, float]]:
    items: list[tuple[str, float]] = []
    total = len(gdf)
    if not total:
        return items
    for column in numeric:
        missing = int(gdf[column].isna().sum())
        share = missing / total * 100
        if missing:
            items.append((column, share))
    return sorted(items, key=lambda item: item[1], reverse=True)[:limit]


def build_conclusions(
    gdf: gpd.GeoDataFrame,
    manifest: dict[str, Any],
    graphs: list[str],
    services: list[str],
    area_km2: float,
) -> list[dict[str, str]]:
    conclusions: list[dict[str, str]] = []
    population = float(pd.to_numeric(gdf.get("population", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    blocks = len(gdf)
    conclusions.append(
        {
            "tone": "info",
            "title": "Территория и масштаб",
            "text": (
                f"В расчёт вошло {blocks:,} кварталов на площади {format_number(area_km2)} км². "
                f"Оценка населения — {format_number(population)} чел."
            ).replace(",", " "),
        }
    )
    access_values: dict[str, dict[str, float]] = {}
    for graph in graphs:
        column = f"area_accessibility_{graph}"
        values = metric_series(gdf, column)
        if not values:
            continue
        array = np.array(values)
        access_values[graph] = {
            "median": float(np.median(array)),
            "p95": float(np.percentile(array, 95)),
            "max": float(np.max(array)),
        }
    if len(access_values) >= 2 and "drive" in access_values and "walk" in access_values:
        drive = access_values["drive"]["median"]
        walk = access_values["walk"]["median"]
        better = "пешая" if walk < drive else "автомобильная"
        difference = abs(walk - drive)
        conclusions.append(
            {
                "tone": "good" if difference > 1 else "info",
                "title": "Доступность: авто и пешком",
                "text": (
                    f"Медианная зональная доступность: {format_number(drive)} мин на автомобиле и "
                    f"{format_number(walk)} мин пешком. Лучше {better} доступность; разница — "
                    f"{format_number(difference)} мин."
                ),
            }
        )
    elif access_values:
        graph, stats = next(iter(access_values.items()))
        conclusions.append(
            {
                "tone": "info",
                "title": "Доступность",
                "text": (
                    f"Медианная зональная доступность ({GRAPH_LABELS.get(graph, graph)}) — "
                    f"{format_number(stats['median'])} мин, 95-й процентиль — {format_number(stats['p95'])} мин."
                ),
            }
        )
    provision_candidates: list[tuple[str, str, float, float]] = []
    for service in services:
        for graph in graphs:
            column = f"provision_strong_{service}"
            if graph == "walk" and f"{column}_walk" in gdf.columns:
                column = f"{column}_walk"
            values = metric_series(gdf, column)
            if not values:
                continue
            array = np.array(values, dtype=float)
            average = float(np.mean(array))
            low_share = float(np.mean(array < 0.5) * 100)
            provision_candidates.append((service, graph, average, low_share))
    if provision_candidates:
        service, graph, average, low_share = min(provision_candidates, key=lambda item: item[2])
        conclusions.append(
            {
                "tone": "warn" if average < 0.75 or low_share > 25 else "good",
                "title": "Обеспеченность услугами",
                "text": (
                    f"Минимальная средняя сильная обеспеченность — {service_label(service)} "
                    f"({GRAPH_LABELS.get(graph, graph)}): {format_number(average)}. "
                    f"Ниже 0,5 обеспеченности находятся {format_number(low_share, 1)}% кварталов."
                ),
            }
        )
    land_area = land_use_area_items(gdf)
    if land_area:
        label, value = land_area[0]
        conclusions.append(
            {
                "tone": "info",
                "title": "Функциональная структура",
                "text": (
                    f"Наибольшая площадь приходится на «{label}» — {format_number(value)} га. "
                    "Площадь рассчитана по атрибуту site_area."
                ),
            }
        )
    for column, title in (
        ("morphotype_strelka", "Морфотипы Strelka"),
        ("morphotype_spacematrix", "Морфотипы Spacematrix"),
    ):
        items = categorical_items(gdf, column)
        if items:
            label, count = items[0]
            share = count / max(len(gdf), 1) * 100
            conclusions.append(
                {
                    "tone": "info",
                    "title": title,
                    "text": (
                        f"Самый частый тип — «{label}»: {format_number(count, 0)} кварталов "
                        f"({format_number(share, 1)}%)."
                    ),
                }
            )
            break
    numeric = numeric_columns(gdf)
    missing = top_missing_items(gdf, numeric)
    if missing:
        column, share = missing[0]
        conclusions.append(
            {
                "tone": "warn" if share > 20 else "info",
                "title": "Полнота данных",
                "text": (
                    f"Наибольшая доля пропусков — у показателя «{metric_label(column, set(gdf.columns))}»: "
                    f"{format_number(share, 1)}%. Пропуски не заменялись нулями."
                ),
            }
        )
    if "population" in gdf.columns:
        top = top_population_items(gdf, 1)
        if top:
            label, value = top[0]
            conclusions.append(
                {
                    "tone": "info",
                    "title": "Концентрация населения",
                    "text": f"Максимум населения среди кварталов — {label}: {format_number(value)} чел.",
                }
            )
    return conclusions


def render_conclusions(conclusions: list[dict[str, str]]) -> str:
    items: list[str] = []
    for item in conclusions:
        items.append(
            f'<article class="conclusion conclusion-{item["tone"]}">'
            f'<h3>{escape(item["title"])}</h3><p>{escape(item["text"])}</p></article>'
        )
    return "".join(items)


def build_feature_collection(
    gdf: gpd.GeoDataFrame, metrics: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    columns = [column for column in gdf.columns if column in metrics or column in POPUP_COLUMNS]
    if "block_id" not in columns:
        columns.append("block_id")
    features: list[dict[str, Any]] = []
    for _, row in gdf.iterrows():
        properties = {column: safe_json_value(row[column]) for column in columns if column in row.index}
        for column in list(properties):
            if metrics.get(column, {}).get("kind") == "category" and properties[column] is not None:
                properties[column] = str(properties[column])
        features.append(
            {
                "type": "Feature",
                "id": str(row["block_id"]),
                "properties": properties,
                "geometry": mapping(row.geometry),
            }
        )
    return {"type": "FeatureCollection", "features": features}


def build_map_html(
    gdf: gpd.GeoDataFrame,
    metrics: dict[str, dict[str, Any]],
    metric_order: list[str],
    metric_groups: list[dict[str, Any]],
) -> str:
    if len(gdf):
        minx, miny, maxx, maxy = gdf.total_bounds
        center = [(miny + maxy) / 2, (minx + maxx) / 2]
    else:
        center = [61.0, 76.6]
    fmap = folium.Map(
        location=center,
        zoom_start=11,
        tiles="CartoDB positron",
        control_scale=True,
        prefer_canvas=True,
    )
    features = build_feature_collection(gdf, metrics)
    popup_columns: list[dict[str, str]] = []
    for column in POPUP_COLUMNS:
        if column not in gdf.columns:
            continue
        label = metric_label(column, set(gdf.columns))
        if column == "block_id":
            label = "Квартал"
        popup_columns.append({"key": column, "label": label})
    for column in metrics:
        if column.startswith("area_accessibility") and column not in {item["key"] for item in popup_columns}:
            popup_columns.append({"key": column, "label": metrics[column]["label"]})
    for column in metrics:
        if column.startswith("provision_strong") and column not in {item["key"] for item in popup_columns}:
            popup_columns.append({"key": column, "label": metrics[column]["label"]})
    payload = {
        "features": features,
        "metrics": metrics,
        "metricOrder": metric_order,
        "groups": metric_groups,
        "popupColumns": popup_columns,
    }
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    custom = f"""
<style>
  html, body {{ margin: 0; padding: 0; font-family: "Segoe UI", Arial, sans-serif; background: #eef2f7; }}
  #map {{ position: absolute; inset: 0; }}
  .map-panel {{
    background: rgba(255,255,255,.96); color: #0f172a; border: 1px solid #dbe3ee;
    border-radius: 12px; padding: 10px 12px; box-shadow: 0 6px 22px rgba(15,23,42,.12);
    font-size: 12px; min-width: 230px; max-width: 320px;
  }}
  .map-panel-title {{ font-weight: 700; margin-bottom: 6px; font-size: 11px; letter-spacing: .04em; text-transform: uppercase; color: #64748b; }}
  .map-panel select {{
    width: 100%; border: 1px solid #cbd5e1; border-radius: 8px; background: #fff;
    color: #0f172a; padding: 7px 8px; font-size: 12px; outline: none;
  }}
  .map-panel select:focus {{ border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37,99,235,.16); }}
  .legend-gradient {{ height: 10px; border-radius: 999px; margin: 8px 0 4px; }}
  .legend-labels {{ display: flex; justify-content: space-between; gap: 8px; color: #475569; font-size: 10.5px; }}
  .legend-list {{ display: grid; gap: 4px; max-height: 220px; overflow: auto; }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; color: #334155; font-size: 11px; }}
  .legend-swatch {{ width: 10px; height: 10px; border-radius: 3px; flex: 0 0 auto; }}
  .popup {{
    font-family: "Segoe UI", Arial, sans-serif; color: #0f172a; min-width: 230px; max-width: 340px;
  }}
  .popup-title {{ font-size: 14px; font-weight: 700; margin-bottom: 6px; }}
  .popup-grid {{ display: grid; grid-template-columns: minmax(100px, 1fr) minmax(90px, auto); gap: 3px 10px; }}
  .popup-key {{ color: #64748b; }}
  .popup-value {{ font-weight: 600; text-align: right; }}
  .leaflet-popup-content {{ margin: 12px 14px; }}
</style>
<script>
window.addEventListener("load", function () {{
  const payload = {payload_json};
  const map = {fmap.get_name()};
  const metrics = payload.metrics;
  const metricOrder = payload.metricOrder;
  const groups = payload.groups;
  const popupColumns = payload.popupColumns;
  if (!metricOrder.length) {{
    const empty = L.control({{position: "topright"}});
    empty.onAdd = function () {{
      const div = L.DomUtil.create("div", "map-panel");
      div.textContent = "Нет числовых показателей для карты";
      return div;
    }};
    empty.addTo(map);
    return;
  }}
  let current = metricOrder.indexOf("population") >= 0 ? "population" : metricOrder[0];
  let legendDiv = null;
  function esc(value) {{
    return String(value).replace(/[&<>"']/g, function (char) {{
      return {{"&": "&amp;", "<": "&lt;", ">": "&gt;", "\\"": "&quot;", "'": "&#39;"}}[char];
    }});
  }}
  function fmt(value) {{
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "number") {{
      if (!isFinite(value)) return "—";
      const abs = Math.abs(value);
      if (abs >= 1000000) return (value / 1000000).toLocaleString("ru-RU", {{maximumFractionDigits: 2}}) + " млн";
      if (abs >= 10000) return (value / 1000).toLocaleString("ru-RU", {{maximumFractionDigits: 1}}) + " тыс.";
      if (abs >= 100) return value.toLocaleString("ru-RU", {{maximumFractionDigits: 0}});
      if (abs >= 10) return value.toLocaleString("ru-RU", {{maximumFractionDigits: 1}});
      return value.toLocaleString("ru-RU", {{maximumFractionDigits: 2}});
    }}
    return esc(value);
  }}
  function colorForNumeric(value, config) {{
    if (value === null || value === undefined || !isFinite(value)) return "#cbd5e1";
    const min = config.min;
    const max = config.max;
    if (!isFinite(min) || !isFinite(max) || max === min) return config.colors[Math.floor(config.colors.length / 2)];
    const ratio = Math.max(0, Math.min(0.999999, (value - min) / (max - min)));
    return config.colors[Math.floor(ratio * config.colors.length)];
  }}
  function styleFor(feature) {{
    const config = metrics[current];
    const value = feature.properties[current];
    let fill = "#cbd5e1";
    if (config.kind === "numeric") fill = colorForNumeric(value, config);
    else fill = config.colors[String(value)] || "#cbd5e1";
    return {{ fillColor: fill, fillOpacity: 0.78, color: "#ffffff", weight: 0.65, opacity: 0.85 }};
  }}
  function popupHtml(properties) {{
    const rows = popupColumns.map(function (item) {{
      const value = properties[item.key];
      if (value === null || value === undefined || value === "") return "";
      return '<div class="popup-key">' + esc(item.label) + '</div><div class="popup-value">' + fmt(value) + '</div>';
    }}).join("");
    return '<div class="popup"><div class="popup-title">Квартал ' + esc(properties.block_id ?? "—") +
      '</div><div class="popup-grid">' + rows + '</div></div>';
  }}
  const layer = L.geoJSON(payload.features, {{
    style: styleFor,
    onEachFeature: function (feature, item) {{
      item.bindPopup(function () {{ return popupHtml(feature.properties); }}, {{maxWidth: 360}});
      item.on("mouseover", function () {{ this.setStyle({{weight: 2.2, color: "#0f172a"}}); this.bringToFront(); }});
      item.on("mouseout", function () {{ layer.resetStyle(this); }});
    }}
  }}).addTo(map);
  if (layer.getBounds().isValid()) map.fitBounds(layer.getBounds(), {{padding: [24, 24]}});
  function updateLegend() {{
    if (!legendDiv) return;
    const config = metrics[current];
    let content = '<div class="map-panel-title">' + esc(config.label) + '</div>';
    if (config.kind === "numeric") {{
      content += '<div class="legend-gradient" style="background:linear-gradient(90deg,' + config.colors.join(",") + ')"></div>';
      content += '<div class="legend-labels"><span>' + fmt(config.min) + '</span><span>' + fmt(config.max) + '</span></div>';
    }} else {{
      content += '<div class="legend-list">';
      config.order.forEach(function (value) {{
        const color = config.colors[value] || "#cbd5e1";
        content += '<div class="legend-item"><span class="legend-swatch" style="background:' + color + '"></span>' +
          '<span>' + esc(value) + '</span></div>';
      }});
      content += '</div>';
    }}
    legendDiv.innerHTML = content;
  }}
  const selector = L.control({{position: "topright"}});
  selector.onAdd = function () {{
    const div = L.DomUtil.create("div", "map-panel");
    const title = L.DomUtil.create("div", "map-panel-title", div);
    title.textContent = "Показатель карты";
    const select = document.createElement("select");
    groups.forEach(function (group) {{
      const optgroup = document.createElement("optgroup");
      optgroup.label = group.label;
      group.keys.forEach(function (key) {{
        const option = document.createElement("option");
        option.value = key;
        option.textContent = metrics[key].label;
        if (key === current) option.selected = true;
        optgroup.appendChild(option);
      }});
      select.appendChild(optgroup);
    }});
    select.addEventListener("change", function () {{
      current = select.value;
      layer.setStyle(styleFor);
      updateLegend();
    }});
    div.appendChild(select);
    L.DomEvent.disableClickPropagation(div);
    L.DomEvent.disableScrollPropagation(div);
    return div;
  }};
  selector.addTo(map);
  const legend = L.control({{position: "bottomright"}});
  legend.onAdd = function () {{
    legendDiv = L.DomUtil.create("div", "map-panel");
    updateLegend();
    L.DomEvent.disableClickPropagation(legendDiv);
    return legendDiv;
  }};
  legend.addTo(map);
}});
</script>
"""
    rendered = fmap.get_root().render()
    return rendered.replace("</body>", custom + "</body>")


def render_summary_csv(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        return f'<p class="muted">Не удалось прочитать summary.csv: {escape(exc)}</p>'
    if frame.empty:
        return ""
    table, _, _ = render_table(frame, "summary-table", "summary-search")
    return (
        '<section class="card">'
        "<h2>Сводная статистика BlocksNet</h2>"
        '<p class="muted">Файл outputs/…/tables/summary.csv, сохранённый ноутбуком.</p>'
        f"{table}</section>"
    )


def build_html(
    gdf: gpd.GeoDataFrame,
    manifest: dict[str, Any],
    graphs: list[str],
    services: list[str],
    sources: list[str],
    dirs: list[str],
    title: str,
    output_path: Path,
    max_table_rows: int,
) -> str:
    numeric = numeric_columns(gdf)
    categorical = categorical_columns(gdf)
    metrics, metric_order, metric_groups = build_metric_config(gdf, numeric, categorical)
    area_values = pd.to_numeric(gdf.get("site_area", pd.Series(dtype=float)), errors="coerce").fillna(0)
    area_km2 = float(manifest.get("area_km2") or area_values.sum() / 1_000_000)
    population = float(pd.to_numeric(gdf.get("population", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    built_blocks = int((pd.to_numeric(gdf.get("fsi", pd.Series(dtype=float)), errors="coerce").fillna(0) > 0).sum())
    cards = [
        {
            "label": "Кварталы",
            "value": format_number(len(gdf), 0),
            "note": f"застроено {format_number(built_blocks, 0)}",
            "tone": "blue",
        },
        {
            "label": "Население",
            "value": format_number(population),
            "note": "оценка по зданиям",
            "tone": "green",
        },
        {
            "label": "Площадь",
            "value": f"{format_number(area_km2)} км²",
            "note": "по границам территории",
            "tone": "violet",
        },
    ]
    for graph in graphs:
        values = metric_series(gdf, f"area_accessibility_{graph}")
        if values:
            cards.append(
                {
                    "label": f"Доступность · {GRAPH_LABELS.get(graph, graph)}",
                    "value": f"{format_number(float(np.median(values)))} мин",
                    "note": "медиана по кварталам",
                    "tone": "amber",
                }
            )
    if services:
        provision_values: list[tuple[str, str, float]] = []
        for service in services:
            for graph in graphs:
                column = f"provision_strong_{service}"
                if graph == "walk" and f"{column}_walk" in gdf.columns:
                    column = f"{column}_walk"
                values = metric_series(gdf, column)
                if values:
                    provision_values.append((service, graph, float(np.mean(values))))
        if provision_values:
            service, graph, value = min(provision_values, key=lambda item: item[2])
            cards.append(
                {
                    "label": "Минимальная обеспеченность",
                    "value": format_number(value),
                    "note": f"{service_label(service)} · {GRAPH_LABELS.get(graph, graph)}",
                    "tone": "rose",
                }
            )
    conclusions = build_conclusions(gdf, manifest, graphs, services, area_km2)
    population_values = metric_series(gdf, "population")
    fsi_values = metric_series(gdf, "fsi")
    gsi_values = metric_series(gdf, "gsi")
    accessibility_categories = ["Медиана", "95-й процентиль", "Максимум"]
    accessibility_series: list[dict[str, Any]] = []
    graph_colors = {"drive": "#2563eb", "walk": "#16a34a"}
    for graph in graphs:
        values = metric_series(gdf, f"area_accessibility_{graph}")
        if not values:
            continue
        array = np.array(values)
        accessibility_series.append(
            {
                "label": GRAPH_LABELS.get(graph, graph).capitalize(),
                "color": graph_colors.get(graph, "#7c3aed"),
                "values": [
                    float(np.median(array)),
                    float(np.percentile(array, 95)),
                    float(np.max(array)),
                ],
            }
        )
    provision_categories: list[str] = []
    provision_series: list[dict[str, Any]] = []
    for graph in graphs:
        values: list[float | None] = []
        for service in services:
            column = f"provision_strong_{service}"
            if graph == "walk" and f"{column}_walk" in gdf.columns:
                column = f"{column}_walk"
            service_values = metric_series(gdf, column)
            values.append(float(np.mean(service_values)) if service_values else None)
        if any(value is not None for value in values):
            provision_series.append(
                {
                    "label": GRAPH_LABELS.get(graph, graph).capitalize(),
                    "color": graph_colors.get(graph, "#7c3aed"),
                    "values": values,
                }
            )
    if not provision_categories and services:
        provision_categories = [service_label(service) for service in services]
    charts = [
        (
            "Распределение населения",
            "Население квартала, чел.",
            svg_histogram(population_values, "Население квартала, чел.", "#e6550d"),
        ),
        (
            "Распределение FSI",
            "FSI",
            svg_histogram(fsi_values, "FSI", "#54278f"),
        ),
        (
            "Распределение GSI",
            "GSI",
            svg_histogram(gsi_values, "GSI", "#0891b2"),
        ),
        (
            "Зональная доступность",
            "Минуты, медиана / P95 / максимум",
            svg_grouped_hbar(accessibility_categories, accessibility_series, "мин"),
        ),
        (
            "Обеспеченность услугами",
            "Средняя сильная обеспеченность, 0–1",
            svg_grouped_hbar(provision_categories, provision_series, ""),
        ),
        (
            "Топ кварталов по населению",
            "Человек",
            svg_hbar(top_population_items(gdf, 12), "чел.", "#e6550d", 12),
        ),
        (
            "Функциональные зоны по площади",
            "Гектары",
            svg_hbar(land_use_area_items(gdf), "га", "#2563eb", 15),
        ),
        (
            "Морфотипы Strelka",
            "Количество кварталов",
            svg_hbar(categorical_items(gdf, "morphotype_strelka"), "кварталов", "#7c3aed", 15),
        ),
    ]
    if "morphotype_strelka" not in gdf.columns or not gdf["morphotype_strelka"].notna().any():
        charts = [chart for chart in charts if chart[0] != "Морфотипы Strelka"]
    stats_rows = []
    for column in numeric:
        values = metric_series(gdf, column)
        stats_rows.append(
            summary_stats_row(
                column,
                values,
                len(gdf),
                metric_label(column, set(gdf.columns)),
                metric_group(column),
            )
        )
    stats_frame = pd.DataFrame(stats_rows).rename(
        columns={
            "label": "Показатель",
            "group": "Группа",
            "count": "N",
            "missing": "Пропуски",
            "min": "Мин.",
            "median": "Медиана",
            "mean": "Среднее",
            "p95": "P95",
            "max": "Макс.",
            "sum": "Сумма",
        }
    )
    if "column" in stats_frame.columns:
        stats_frame = stats_frame.drop(columns=["column"])
    stats_table, _, _ = render_table(stats_frame, "stats-table", "stats-search")
    table_frame = gdf.drop(columns=[gdf.geometry.name]).copy()
    table_labels: dict[str, str] = {}
    used_labels: set[str] = set()
    for column in table_frame.columns:
        label = "Квартал" if column == "block_id" else metric_label(column, set(gdf.columns))
        if label in used_labels:
            label = f"{label} ({column})"
        used_labels.add(label)
        table_labels[column] = label
    block_table, shown_rows, total_rows = render_table(
        table_frame,
        "blocks-table",
        "blocks-search",
        max_rows=max_table_rows,
        sort_column="population" if "population" in table_frame.columns else None,
        labels=table_labels,
    )
    map_html = build_map_html(gdf, metrics, metric_order, metric_groups)
    chart_cards = "".join(
        f'<article class="card chart-card"><h3>{escape(name)}</h3>'
        f'<p class="muted">{escape(note)}</p>{svg}</article>'
        for name, note, svg in charts
    )
    manifest_rows = []
    if manifest:
        manifest_rows.extend(
            [
                ("Территория", manifest.get("territory_query", "—")),
                ("Площадь, км²", format_number(manifest.get("area_km2", area_km2))),
                ("Кварталов", format_number(manifest.get("blocks", len(gdf)), 0)),
                ("Население", format_number(manifest.get("population_estimate", population))),
                ("CRS", manifest.get("crs", "—")),
                ("Сформировано", manifest.get("generated_at", "—")),
                ("Параметры", json.dumps(manifest.get("parameters", {}), ensure_ascii=False)),
                ("Версии", json.dumps(manifest.get("versions", {}), ensure_ascii=False)),
            ]
        )
    manifest_html = "".join(
        f"<tr><th>{escape(key)}</th><td>{escape(value)}</td></tr>" for key, value in manifest_rows
    )
    sources_html = "".join(f"<li>{escape(Path(path).name)}</li>" for path in sources)
    generated_at = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    summary_html = render_summary_csv(output_path.parent / "tables" / "summary.csv")
    if not summary_html:
        summary_html = render_summary_csv(Path(dirs[0]).parent / "outputs" / DEFAULT_SLUG / "tables" / "summary.csv")
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>
:root {{
  --ink: #0f172a; --muted: #64748b; --line: #dbe3ee; --bg: #f4f7fb; --card: #ffffff;
  --blue: #2563eb; --green: #16a34a; --amber: #d97706; --rose: #e11d48; --violet: #7c3aed;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--ink); font-family: "Segoe UI", Arial, sans-serif; line-height: 1.45; }}
.hero {{ background: radial-gradient(circle at 15% 10%, #1e3a8a 0, #0f172a 48%, #020617 100%); color: #fff; padding: 42px 24px 52px; }}
.hero-inner {{ max-width: 1440px; margin: 0 auto; }}
.eyebrow {{ color: #93c5fd; text-transform: uppercase; letter-spacing: .12em; font-size: 12px; font-weight: 700; }}
h1 {{ font-size: clamp(28px, 4vw, 48px); line-height: 1.08; margin: 8px 0 12px; letter-spacing: -.02em; }}
.hero p {{ color: #cbd5e1; max-width: 900px; margin: 0; font-size: 15px; }}
.hero-meta {{ display: flex; gap: 16px; flex-wrap: wrap; margin-top: 22px; color: #dbeafe; font-size: 12.5px; }}
.container {{ max-width: 1440px; margin: -28px auto 0; padding: 0 24px 48px; }}
.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(185px, 1fr)); gap: 14px; margin-bottom: 18px; }}
.kpi {{ background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 16px 18px; box-shadow: 0 10px 24px rgba(15,23,42,.06); border-top: 4px solid var(--blue); }}
.kpi-green {{ border-top-color: var(--green); }} .kpi-violet {{ border-top-color: var(--violet); }}
.kpi-amber {{ border-top-color: var(--amber); }} .kpi-rose {{ border-top-color: var(--rose); }}
.kpi-label {{ color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .07em; font-weight: 700; }}
.kpi-value {{ font-size: 26px; font-weight: 800; margin: 5px 0 2px; letter-spacing: -.02em; }}
.kpi-note {{ color: var(--muted); font-size: 12px; }}
.card {{ background: var(--card); border: 1px solid var(--line); border-radius: 18px; padding: 20px; box-shadow: 0 12px 28px rgba(15,23,42,.055); margin-bottom: 18px; }}
.card h2 {{ margin: 0 0 6px; font-size: 22px; letter-spacing: -.01em; }}
.card h3 {{ margin: 0 0 4px; font-size: 16px; }}
.muted {{ color: var(--muted); font-size: 12.5px; margin: 0 0 12px; }}
.map-card {{ padding: 0; overflow: hidden; }}
.map-head {{ padding: 20px 20px 14px; display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; flex-wrap: wrap; }}
.map-frame {{ width: 100%; height: 670px; border: 0; display: block; background: #e2e8f0; }}
.conclusions {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(310px, 1fr)); gap: 12px; }}
.conclusion {{ border: 1px solid var(--line); border-left: 5px solid var(--blue); border-radius: 12px; padding: 14px 16px; background: #fbfdff; }}
.conclusion h3 {{ font-size: 14px; margin: 0 0 5px; }}
.conclusion p {{ margin: 0; font-size: 13px; color: #334155; }}
.conclusion-good {{ border-left-color: var(--green); }} .conclusion-warn {{ border-left-color: var(--amber); }}
.conclusion-info {{ border-left-color: var(--blue); }}
.chart-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(520px, 1fr)); gap: 16px; }}
.chart-card {{ margin: 0; min-width: 0; }}
.chart-svg {{ width: 100%; height: auto; display: block; overflow: visible; }}
.chart-card .muted {{ margin-bottom: 4px; }}
.table-tools {{ display: flex; gap: 12px; align-items: center; justify-content: space-between; margin: 12px 0; flex-wrap: wrap; }}
.table-tools span {{ color: var(--muted); font-size: 12px; }}
.table-search {{ min-width: 280px; flex: 1; max-width: 460px; border: 1px solid #cbd5e1; border-radius: 10px; padding: 9px 12px; font-size: 13px; outline: none; }}
.table-search:focus {{ border-color: var(--blue); box-shadow: 0 0 0 3px rgba(37,99,235,.14); }}
.table-wrap {{ overflow: auto; max-height: 620px; border: 1px solid var(--line); border-radius: 12px; }}
.data-table {{ border-collapse: separate; border-spacing: 0; width: 100%; font-size: 12px; white-space: nowrap; }}
.data-table th {{ position: sticky; top: 0; z-index: 2; background: #f1f5f9; color: #334155; text-align: left; padding: 9px 10px; border-bottom: 1px solid var(--line); cursor: pointer; font-weight: 700; }}
.data-table td {{ padding: 7px 10px; border-bottom: 1px solid #edf2f7; color: #334155; }}
.data-table td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.data-table tr:hover td {{ background: #f8fbff; }}
.data-table th.sort-asc::after {{ content: " ↑"; }} .data-table th.sort-desc::after {{ content: " ↓"; }}
.manifest-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
.manifest-table th {{ text-align: left; width: 180px; color: var(--muted); font-weight: 600; padding: 7px 10px; border-bottom: 1px solid #edf2f7; vertical-align: top; }}
.manifest-table td {{ padding: 7px 10px; border-bottom: 1px solid #edf2f7; word-break: break-word; }}
.source-list {{ columns: 2; font-size: 12.5px; color: #334155; }}
.footer {{ text-align: center; color: var(--muted); font-size: 12px; padding: 10px 0 30px; }}
@media (max-width: 700px) {{
  .container {{ padding: 0 12px 30px; }} .hero {{ padding: 30px 16px 46px; }}
  .chart-grid {{ grid-template-columns: 1fr; }} .map-frame {{ height: 520px; }} .source-list {{ columns: 1; }}
}}
@media print {{
  .hero {{ background: #0f172a !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  .card, .kpi {{ break-inside: avoid; box-shadow: none; }} .table-wrap {{ max-height: none; }}
}}
</style>
</head>
<body>
<header class="hero">
  <div class="hero-inner">
    <div class="eyebrow">BlocksNet · Urban analytics</div>
    <h1>{escape(title)}</h1>
    <p>Интерактивный отчёт по сохранённым результатам расчёта: морфология, плотность, доступность и обеспеченность услугами. Данные не скачиваются и не пересчитываются.</p>
    <div class="hero-meta">
      <span>{escape(manifest.get("territory_query", "Территория по результатам BlocksNet"))}</span>
      <span>Собрано {escape(generated_at)}</span>
      <span>{len(sources)} исходных файлов</span>
    </div>
  </div>
</header>
<main class="container">
  <section class="kpis">{render_kpi_cards(cards)}</section>
  <section class="card map-card">
    <div class="map-head">
      <div>
        <h2>Карта кварталов</h2>
        <p class="muted">Выберите показатель в правом верхнем углу карты. Наведите курсор для подсветки, нажмите на квартал для карточки.</p>
      </div>
      <p class="muted">Показателей на карте: {len(metric_order)} · слоёв: {len(graphs)} · услуг: {len(services)}</p>
    </div>
    <iframe class="map-frame" title="Интерактивная карта кварталов" srcdoc="{escape(map_html)}"></iframe>
  </section>
  <section class="card">
    <h2>Ключевые выводы</h2>
    <p class="muted">Автоматически сформированы по сохранённым значениям; это описательная статистика, а не нормативная оценка.</p>
    <div class="conclusions">{render_conclusions(conclusions)}</div>
  </section>
  <section>
    <div class="chart-grid">{chart_cards}</div>
  </section>
  <section class="card">
    <h2>Статистика показателей</h2>
    <p class="muted">Все числовые поля, найденные в результатах. Пропуски показаны отдельно.</p>
    {stats_table}
  </section>
  <section class="card">
    <h2>Таблица кварталов</h2>
    <p class="muted">Поиск по любой ячейке и сортировка по клику на заголовок. Показано {shown_rows:,} из {total_rows:,} строк.</p>
    {block_table}
  </section>
  {summary_html}
  <section class="card">
    <h2>Источники и параметры</h2>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:24px">
      <div>
        <h3>Манифест</h3>
        <table class="manifest-table">{manifest_html or "<tr><td>manifest.json не найден</td></tr>"}</table>
      </div>
      <div>
        <h3>Прочитанные файлы</h3>
        <p class="muted">Каталоги: {escape("; ".join(dirs))}</p>
        <ul class="source-list">{sources_html}</ul>
      </div>
    </div>
  </section>
  <p class="footer">Сгенерировано {escape(generated_at)} из {len(sources)} локальных файлов. Для подложки карты требуется доступ к интернету.</p>
</main>
<script>
function initTable(tableId, searchId) {{
  const table = document.getElementById(tableId);
  const search = document.getElementById(searchId);
  if (!table || !search) return;
  const body = table.tBodies[0];
  const rows = Array.from(body.rows);
  search.addEventListener("input", function () {{
    const query = search.value.trim().toLowerCase();
    rows.forEach(function (row) {{
      row.style.display = row.textContent.toLowerCase().includes(query) ? "" : "none";
    }});
  }});
  Array.from(table.tHead.rows[0].cells).forEach(function (th, index) {{
    th.addEventListener("click", function () {{
      const current = th.dataset.order === "asc" ? "desc" : "asc";
      Array.from(table.tHead.rows[0].cells).forEach(function (cell) {{
        cell.classList.remove("sort-asc", "sort-desc");
        delete cell.dataset.order;
      }});
      th.dataset.order = current;
      th.classList.add(current === "asc" ? "sort-asc" : "sort-desc");
      const sorted = rows.slice().sort(function (a, b) {{
        const av = a.cells[index].dataset.sort ?? a.cells[index].textContent;
        const bv = b.cells[index].dataset.sort ?? b.cells[index].textContent;
        const an = parseFloat(String(av).replace(/\\s/g, "").replace(",", "."));
        const bn = parseFloat(String(bv).replace(/\\s/g, "").replace(",", "."));
        let result;
        if (!isNaN(an) && !isNaN(bn)) result = an - bn;
        else result = String(av).localeCompare(String(bv), "ru");
        return current === "asc" ? result : -result;
      }});
      sorted.forEach(function (row) {{ body.appendChild(row); }});
    }});
  }});
}}
initTable("stats-table", "stats-search");
initTable("blocks-table", "blocks-search");
initTable("summary-table", "summary-search");
</script>
</body>
</html>
"""


def main() -> None:
    args = parse_args()
    data_dir = args.data_dir.expanduser().resolve()
    if args.results_dir is not None:
        results_dir = args.results_dir.expanduser().resolve()
    elif (data_dir / "results").is_dir():
        results_dir = data_dir / "results"
    elif data_dir.name == "results":
        results_dir = data_dir
        data_dir = data_dir.parent
    else:
        results_dir = data_dir / "results"
    output_path = args.output.expanduser().resolve()
    gdf, manifest, graphs, services, sources, dirs = load_data(data_dir, results_dir)
    if len(gdf) == 0:
        raise SystemExit("Результаты найдены, но слой кварталов пуст.")
    gdf = ensure_area_column(gdf)
    if "population" not in gdf.columns:
        gdf["population"] = np.nan
    if "site_area" not in gdf.columns:
        gdf["site_area"] = np.nan
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = build_html(
        gdf,
        manifest,
        graphs,
        services,
        sources,
        dirs,
        args.title,
        output_path,
        args.max_table_rows,
    )
    output_path.write_text(document, encoding="utf-8")
    print(f"Дашборд сохранён: {output_path}")
    print(f"Кварталов: {len(gdf):,}".replace(",", " "))
    print(f"Показателей: {len(numeric_columns(gdf))} числовых, {len(categorical_columns(gdf))} категориальных")
    print(f"Услуги: {', '.join(services) if services else 'не найдены'}")
    print(f"Графы: {', '.join(graphs) if graphs else 'не найдены'}")


if __name__ == "__main__":
    main()
