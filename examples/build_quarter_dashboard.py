"""Build an interactive quarter dashboard for Nizhnevartovsk.

The dashboard follows the structure of the MIASS quarter model: filters,
KPI cards, an interactive map, selected-quarter details, distribution
charts, a scatter plot and a searchable/downloadable table.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import mapping

PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "examples" / "data" / "nizhnevartovsk"
OUTPUT_DIR = PROJECT_DIR / "examples" / "outputs" / "nizhnevartovsk"
INPUT_PATH = DATA_DIR / "results" / "blocks_indicators_drive.geojson"
TEMPLATE_PATH = Path(__file__).with_name("quarter_dashboard_template.html")
LEAFLET_DIR = Path(__file__).with_name("vendor") / "leaflet"
OUTPUT_PATH = OUTPUT_DIR / "dashboard.html"

LAND_USE_LABELS = {
    "residential": "Жилое",
    "business": "Деловое",
    "recreation": "Рекреационное",
    "industrial": "Промышленное",
    "transport": "Транспортное",
    "special": "Специальное",
    "agriculture": "Сельскохозяйственное",
    "undefined": "Не определено",
}

MORPH_LABELS = {
    "individual residential": "Индивидуальная",
    "low-rise model": "Малоэтажная",
    "mid-rise": "Среднеэтажная",
    "high-rise soviet microdistrict": "Многоэтажная",
    "low-rise non-residential": "Малоэтажная нежилая",
    "undefined": "Не определено",
}

MONTHS_RU = [
    "янв.",
    "февр.",
    "мар.",
    "апр.",
    "мая",
    "июн.",
    "июл.",
    "авг.",
    "сент.",
    "окт.",
    "нояб.",
    "дек.",
]


def safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return None if pd.isna(result) else result


def safe_text(value: Any, default: str) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    text = str(value).strip()
    return text if text and text.lower() != "nan" else default


def round_coordinates(value: Any, digits: int = 6) -> Any:
    if isinstance(value, (list, tuple)):
        if value and all(isinstance(item, (int, float)) for item in value):
            return [round(float(item), digits) for item in value]
        return [round_coordinates(item, digits) for item in value]
    return value


def formatted_date() -> str:
    today = date.today()
    return f"{today.day} {MONTHS_RU[today.month - 1]} {today.year} г."


def build_features(gdf: gpd.GeoDataFrame) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for _, row in gdf.iterrows():
        land_use = safe_text(row.get("land_use"), "undefined")
        morph = safe_text(row.get("morphotype_strelka"), "undefined")
        site_area = safe_float(row.get("site_area"), 0.0) or 0.0
        population = safe_float(row.get("population"), 0.0) or 0.0
        fsi = safe_float(row.get("fsi"), 0.0) or 0.0
        gsi = safe_float(row.get("gsi"), 0.0) or 0.0
        area_ha = site_area / 10000
        footprint_m2 = gsi * site_area
        pop_density = population / area_ha if area_ha > 0 else 0.0
        share_living = safe_float(row.get("share_living"))
        accessibility = safe_float(row.get("area_accessibility_drive"))

        properties = {
            "block_id": int(row["block_id"]),
            "land_use": land_use,
            "land_use_label": LAND_USE_LABELS.get(land_use, land_use),
            "morph": morph,
            "morph_label": MORPH_LABELS.get(morph, morph),
            "area_ha": round(area_ha, 2),
            "population": int(round(population)),
            "fsi": round(fsi, 4),
            "gsi": round(gsi, 4),
            "gsi_m2ha": round(gsi * 10000, 1),
            "footprint_m2": round(footprint_m2, 0),
            "pop_density": round(pop_density, 2),
            "count_buildings": int(safe_float(row.get("count_buildings"), 0) or 0),
            "share_living": round(share_living, 3) if share_living is not None else None,
            "accessibility": round(accessibility, 1) if accessibility is not None else None,
            "provision_school": round(safe_float(row.get("provision_strong_school"), 0.0) or 0.0, 3),
            "provision_kindergarten": round(
                safe_float(row.get("provision_strong_kindergarten"), 0.0) or 0.0, 3
            ),
            "provision_polyclinic": round(
                safe_float(row.get("provision_strong_polyclinic"), 0.0) or 0.0, 3
            ),
            "count_school": int(safe_float(row.get("count_school"), 0) or 0),
            "count_kindergarten": int(safe_float(row.get("count_kindergarten"), 0) or 0),
            "count_polyclinic": int(safe_float(row.get("count_polyclinic"), 0) or 0),
        }

        geometry = mapping(row.geometry)
        geometry["coordinates"] = round_coordinates(geometry["coordinates"])
        features.append(
            {
                "type": "Feature",
                "properties": properties,
                "geometry": geometry,
            }
        )
    return features


def build_meta(gdf: gpd.GeoDataFrame, features: list[dict[str, Any]]) -> dict[str, Any]:
    area_ha = sum(feature["properties"]["area_ha"] for feature in features)
    population = sum(feature["properties"]["population"] for feature in features)
    fsi_values = [feature["properties"]["fsi"] for feature in features if feature["properties"]["fsi"] > 0]
    density_values = [
        feature["properties"]["pop_density"]
        for feature in features
        if feature["properties"]["population"] > 0
    ]
    median_fsi = float(pd.Series(fsi_values).median()) if fsi_values else 0.0
    median_density = float(pd.Series(density_values).median()) if density_values else 0.0

    return {
        "city": "Нижневартовск",
        "updated": formatted_date(),
        "total_blocks": len(features),
        "total_area_ha": round(area_ha, 1),
        "total_population": int(population),
        "median_fsi_built": round(median_fsi, 4),
        "median_density_built": round(median_density, 2),
        "graph": "drive",
        "max_travel_min": 180,
        "source": "OpenStreetMap / BlocksNet",
    }


def main() -> None:
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"Не найден слой кварталов: {INPUT_PATH}. "
            "Сначала выполните ноутбук examples/blocksnet_nizhnevartovsk.ipynb."
        )
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Не найден шаблон дашборда: {TEMPLATE_PATH}")
    leaflet_js_path = LEAFLET_DIR / "leaflet.js"
    leaflet_css_path = LEAFLET_DIR / "leaflet.css"
    if not leaflet_js_path.exists() or not leaflet_css_path.exists():
        raise FileNotFoundError(
            f"Не найдены файлы Leaflet в {LEAFLET_DIR}. "
            "Ожидаются leaflet.js и leaflet.css."
        )

    gdf = gpd.read_file(INPUT_PATH)
    if gdf.crs is None:
        raise ValueError(f"У слоя {INPUT_PATH} не задана CRS")
    gdf = gdf.to_crs(4326)
    gdf["geometry"] = gdf.geometry.make_valid()

    features = build_features(gdf)
    meta = build_meta(gdf, features)
    collection = {"type": "FeatureCollection", "features": features}

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    leaflet_js = leaflet_js_path.read_text(encoding="utf-8")
    leaflet_css = leaflet_css_path.read_text(encoding="utf-8")
    blocks_json = json.dumps(collection, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    meta_json = json.dumps(meta, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = (
        template.replace("__LEAFLET_CSS__", leaflet_css)
        .replace("__LEAFLET_JS__", leaflet_js)
        .replace("__BLOCKS_JSON__", blocks_json)
        .replace("__META_JSON__", meta_json)
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html, encoding="utf-8")

    print(f"Дашборд сохранён: {OUTPUT_PATH}")
    print(f"Кварталов: {meta['total_blocks']}")
    print(f"Площадь: {meta['total_area_ha']} га; население: {meta['total_population']:,}".replace(",", " "))
    print(f"Медиана FSI по застроенным: {meta['median_fsi_built']}")
    print(f"Медиана плотности населения: {meta['median_density_built']} чел./га")
    print(f"Размер файла: {OUTPUT_PATH.stat().st_size / 1024 / 1024:.2f} МБ")


if __name__ == "__main__":
    main()
