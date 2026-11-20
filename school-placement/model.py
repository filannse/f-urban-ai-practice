from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

import geopandas as gpd
import numpy as np
import pandas as pd
from blocksnet.analysis.provision import competitive_provision
from blocksnet.config import service_types_config
from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "examples" / "data" / "nizhnevartovsk"
RESULT_PATH = DATA_DIR / "results" / "blocks_indicators_drive.geojson"
MATRIX_PATH = DATA_DIR / "matrices" / "accessibility_matrix_drive.parquet"
LOCAL_MATRIX_PATH = Path(__file__).with_name("data") / "accessibility_matrix_drive.parquet"
MANIFEST_PATH = DATA_DIR / "manifest.json"
SCENARIOS_PATH = Path(__file__).with_name("scenarios.json")
TOLERANCE = 1e-6
RESIDENTIAL_LAND_USE = "residential"

logger.remove()


def _finite_number(value: Any, digits: int | None = None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, digits) if digits is not None else number


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, float) and math.isnan(value):
        return default
    text = str(value).strip()
    return text if text and text.lower() != "nan" else default


def is_residential(value: Any) -> bool:
    return _text(value).lower() == RESIDENTIAL_LAND_USE


def parse_capacity(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("Вместимость должна быть положительным целым числом")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Вместимость должна быть положительным целым числом") from exc
    if not math.isfinite(number) or number <= 0 or number != int(number):
        raise ValueError("Вместимость должна быть положительным целым числом")
    return int(number)


def parse_block_id(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("Некорректный номер квартала")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Некорректный номер квартала") from exc
    if not math.isfinite(number) or number < 0 or number != int(number):
        raise ValueError("Некорректный номер квартала")
    return int(number)


class SchoolPlacementModel:
    def __init__(self) -> None:
        self.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        gdf = gpd.read_file(RESULT_PATH)
        gdf["block_id"] = gdf["block_id"].astype(int)
        gdf = gdf.sort_values("block_id").reset_index(drop=True)
        self.blocks = gdf
        self.block_ids = gdf["block_id"].tolist()
        self.block_id_set = set(self.block_ids)
        self.block_meta = gdf.set_index("block_id")
        self.residential_blocks = gdf[gdf["land_use"].map(is_residential)].reset_index(drop=True)
        self.residential_block_ids = self.residential_blocks["block_id"].astype(int).tolist()
        self.residential_block_id_set = set(self.residential_block_ids)

        self.matrix_path = MATRIX_PATH if MATRIX_PATH.exists() else LOCAL_MATRIX_PATH
        if not self.matrix_path.exists():
            raise FileNotFoundError(
                "Не найдена матрица доступности. Ожидался файл "
                f"{MATRIX_PATH} или резервная копия {LOCAL_MATRIX_PATH}."
            )
        matrix = pd.read_parquet(self.matrix_path)
        matrix.index = matrix.index.astype(int)
        matrix.columns = matrix.columns.astype(int)
        matrix = matrix.reindex(index=self.block_ids, columns=self.block_ids)
        if matrix.isna().all(axis=None):
            raise ValueError("Матрица доступности не совпадает с идентификаторами кварталов")
        self.max_travel_min = float(self.manifest.get("parameters", {}).get("max_travel_min", 180))
        self.matrix = matrix.replace([np.inf, -np.inf], self.max_travel_min).fillna(self.max_travel_min)

        config = service_types_config["school"]
        self.demand_norm = int(config["demand"])
        self.accessibility_norm = int(config["accessibility"])
        self.population = gdf.set_index("block_id")["population"].fillna(0).astype(float)
        self.baseline_capacity = (
            gdf.set_index("block_id")["capacity_school"].fillna(0).round().astype(int)
        )
        self.baseline = self._run_capacity(None)
        self.baseline_deficit = float(self.baseline["demand_left"].sum())
        self.baseline_capacity_total = int(self.baseline["capacity"].sum())
        self.baseline_demand_total = float(self.baseline["demand"].sum())
        self.baseline_within_total = float(self.baseline["demand_within"].sum())
        self.baseline_provision = (
            self.baseline_within_total / self.baseline_demand_total
            if self.baseline_demand_total > 0
            else 0.0
        )
        self.verification = self._verify_baseline()
        self.scenarios = self._load_scenarios()

    def _run_capacity(self, added_capacity: pd.Series | dict[int, int] | None) -> pd.DataFrame:
        capacity = self.baseline_capacity.copy()
        if added_capacity is not None:
            if isinstance(added_capacity, dict):
                added_capacity = pd.Series(added_capacity, dtype=float)
            added = added_capacity.reindex(capacity.index).fillna(0)
            capacity = capacity.add(added, fill_value=0)
        capacity = capacity.round().astype(int)
        data = pd.DataFrame({"population": self.population, "capacity": capacity})
        result, _ = competitive_provision(
            data,
            self.matrix,
            accessibility=self.accessibility_norm,
            demand=self.demand_norm,
            self_supply=True,
            max_depth=1,
        )
        result = result.reindex(self.block_ids)
        result["capacity"] = result["capacity"].round().astype(int)
        result["population"] = self.population
        result["baseline_capacity"] = self.baseline_capacity
        result["added_capacity"] = result["capacity"] - self.baseline_capacity
        result["provision_strong"] = result["provision_strong"].where(result["demand"] > 0, np.nan)
        result["provision_weak"] = result["provision_weak"].where(result["demand"] > 0, np.nan)
        return result

    def _verify_baseline(self) -> dict[str, Any]:
        checks = {}
        for calculated, saved in (
            ("demand_left", "demand_left_school"),
            ("capacity", "capacity_school"),
            ("provision_strong", "provision_strong_school"),
        ):
            left = self.baseline[calculated]
            right = self.block_meta[saved].reindex(left.index)
            differences = (left - right).abs().to_numpy(dtype=float)
            max_difference = float(np.nanmax(differences)) if differences.size else 0.0
            checks[calculated] = _finite_number(max_difference, 9)
            if max_difference > TOLERANCE:
                raise RuntimeError(
                    f"Исходный расчёт не совпал с практикой 2 по колонке {calculated}: "
                    f"максимальное расхождение {max_difference:.9f}"
                )
        return {"ok": True, "max_abs_diff": checks}

    def _summary(self, result: pd.DataFrame) -> dict[str, Any]:
        demand = float(result["demand"].sum())
        capacity = int(result["capacity"].sum())
        within = float(result["demand_within"].sum())
        deficit = float(result["demand_left"].sum())
        provision = within / demand if demand > 0 else 0.0
        return {
            "blocks": int(len(result)),
            "demand": round(demand, 1),
            "capacity": capacity,
            "added_capacity": capacity - self.baseline_capacity_total,
            "within": round(within, 1),
            "deficit": round(deficit, 1),
            "deficit_reduction": round(self.baseline_deficit - deficit, 1),
            "provision": round(provision, 6),
            "provision_change": round(provision - self.baseline_provision, 6),
            "blocks_improved": int(
                (
                    (result["provision_strong"].fillna(0) - self.baseline["provision_strong"].fillna(0))
                    > TOLERANCE
                ).sum()
            ),
            "blocks_with_deficit": int((result["demand_left"] > TOLERANCE).sum()),
        }

    def _block_rows(
        self,
        result: pd.DataFrame,
        block_ids: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        rows = []
        for block_id in self.residential_block_ids if block_ids is None else block_ids:
            baseline = self.baseline.loc[block_id]
            scenario = result.loc[block_id]
            meta = self.block_meta.loc[block_id]
            baseline_provision = _finite_number(baseline["provision_strong"], 6)
            scenario_provision = _finite_number(scenario["provision_strong"], 6)
            baseline_deficit = _finite_number(baseline["demand_left"], 3)
            scenario_deficit = _finite_number(scenario["demand_left"], 3)
            rows.append(
                {
                    "block_id": int(block_id),
                    "population": _finite_number(meta["population"], 1),
                    "baseline_capacity": int(meta["capacity_school"]),
                    "scenario_capacity": int(scenario["capacity"]),
                    "added_capacity": int(scenario["capacity"]) - int(meta["capacity_school"]),
                    "baseline_provision": baseline_provision,
                    "scenario_provision": scenario_provision,
                    "provision_change": (
                        round(scenario_provision - baseline_provision, 6)
                        if scenario_provision is not None and baseline_provision is not None
                        else None
                    ),
                    "baseline_deficit": baseline_deficit,
                    "scenario_deficit": scenario_deficit,
                    "deficit_reduction": (
                        round(baseline_deficit - scenario_deficit, 3)
                        if scenario_deficit is not None and baseline_deficit is not None
                        else None
                    ),
                    "land_use": _text(meta.get("land_use"), "не определено"),
                    "morphotype": _text(meta.get("morphotype_strelka"), "не определено"),
                }
            )
        return rows

    def _features(self) -> list[dict[str, Any]]:
        features = []
        for _, row in self.residential_blocks.iterrows():
            block_id = int(row["block_id"])
            baseline = self.baseline.loc[block_id]
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "block_id": block_id,
                        "population": _finite_number(row.get("population"), 1),
                        "baseline_capacity": int(row.get("capacity_school", 0)),
                        "baseline_provision": _finite_number(baseline["provision_strong"], 6),
                        "baseline_deficit": _finite_number(baseline["demand_left"], 3),
                        "land_use": _text(row.get("land_use"), "не определено"),
                        "morphotype": _text(row.get("morphotype_strelka"), "не определено"),
                        "area_ha": _finite_number(
                            float(row.get("site_area", 0.0)) / 10000.0,
                            2,
                        ),
                    },
                    "geometry": row.geometry.__geo_interface__,
                }
            )
        return features

    def initial_payload(self) -> dict[str, Any]:
        return {
            "meta": {
                "city": "Нижневартовск",
                "source": "OpenStreetMap / BlocksNet 1.0.0a9",
                "graph": "drive",
                "method": "competitive_provision, self_supply=True, max_depth=1",
                "demand_norm": self.demand_norm,
                "accessibility_norm": self.accessibility_norm,
                "max_travel_min": self.max_travel_min,
                "block_count": len(self.block_ids),
                "display_block_count": len(self.residential_block_ids),
                "population_total": _finite_number(self.population.sum(), 1),
                "baseline": self._summary(self.baseline),
                "verification": self.verification,
                "data_paths": {
                    "blocks": "examples/data/nizhnevartovsk/results/blocks_indicators_drive.geojson",
                    "matrix": self.matrix_path.relative_to(ROOT).as_posix(),
                    "manifest": "examples/data/nizhnevartovsk/manifest.json",
                },
            },
            "blocks": {"type": "FeatureCollection", "features": self._features()},
            "scenarios": self.scenarios,
        }

    def calculate_scenario(self, placements: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(placements, list):
            raise ValueError("Список размещений должен быть массивом")
        if len(placements) > 20:
            raise ValueError("В одном сценарии можно разместить не более 20 школ")
        added: dict[int, int] = {}
        for placement in placements:
            if not isinstance(placement, dict):
                raise ValueError("Некорректное описание размещения школы")
            block_id = parse_block_id(placement.get("block_id"))
            capacity = parse_capacity(placement.get("capacity"))
            if block_id not in self.block_id_set:
                raise ValueError(f"Квартал {block_id} отсутствует в расчётных данных города")
            if block_id not in self.residential_block_id_set:
                raise ValueError("Школы можно размещать только в жилых кварталах")
            added[block_id] = added.get(block_id, 0) + capacity
        result = self._run_capacity(pd.Series(added, dtype=int) if added else None)
        return {
            "summary": self._summary(result),
            "blocks": self._block_rows(result),
            "placements": [
                {"block_id": int(block_id), "capacity": int(capacity)}
                for block_id, capacity in sorted(added.items())
            ],
        }

    def auto_search(
        self,
        capacity: int,
        progress: Callable[[int, int, int], None] | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        capacity = parse_capacity(capacity)
        rows = []
        errors = []
        candidate_ids = self.residential_block_ids
        total = len(candidate_ids)
        for checked, block_id in enumerate(candidate_ids, start=1):
            if cancel is not None and cancel():
                break
            try:
                result = self._run_capacity(pd.Series({block_id: capacity}, dtype=int))
                summary = self._summary(result)
                meta = self.block_meta.loc[block_id]
                rows.append(
                    {
                        "block_id": int(block_id),
                        "population": _finite_number(meta["population"], 1),
                        "baseline_capacity": int(self.block_meta.loc[block_id, "capacity_school"]),
                        "scenario_capacity": int(result.loc[block_id, "capacity"]),
                        "deficit": summary["deficit"],
                        "deficit_reduction": summary["deficit_reduction"],
                        "provision": summary["provision"],
                        "provision_change": summary["provision_change"],
                        "blocks_improved": summary["blocks_improved"],
                        "blocks_with_deficit": summary["blocks_with_deficit"],
                    }
                )
            except Exception as exc:
                errors.append({"block_id": int(block_id), "error": str(exc)})
            if progress is not None:
                progress(checked, total, int(block_id))
        rows.sort(
            key=lambda row: (
                -row["deficit_reduction"],
                -(row["population"] or 0),
                row["block_id"],
            )
        )
        if rows:
            best_reduction = rows[0]["deficit_reduction"]
            best = [
                row["block_id"]
                for row in rows
                if abs(row["deficit_reduction"] - best_reduction) <= TOLERANCE
            ]
        else:
            best_reduction = None
            best = []
        return {
            "capacity": capacity,
            "checked": len(errors) + len(rows),
            "total": total,
            "successful": len(rows),
            "complete": len(errors) == 0 and len(rows) == total,
            "errors": errors,
            "rows": rows,
            "best": best,
            "best_reduction": best_reduction,
            "recommended": rows[0]["block_id"] if rows else None,
        }

    def _load_scenarios(self) -> dict[str, Any]:
        if not SCENARIOS_PATH.exists():
            return {}
        return json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
