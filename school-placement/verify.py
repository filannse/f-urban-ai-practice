from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

from model import SchoolPlacementModel  # noqa: E402

TOLERANCE = 1e-6
checks: list[tuple[str, bool, str]] = []


def check(name: str, condition: Any, detail: str = "") -> bool:
    passed = bool(condition)
    checks.append((name, passed, detail))
    print(f"{'PASS' if passed else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    return passed


def close(left: Any, right: Any, tolerance: float = TOLERANCE) -> bool:
    if left is None or right is None:
        return left is right
    return math.isclose(float(left), float(right), abs_tol=tolerance)


def summaries_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    keys = [
        "blocks",
        "demand",
        "capacity",
        "added_capacity",
        "within",
        "deficit",
        "deficit_reduction",
        "provision",
        "provision_change",
        "blocks_improved",
        "blocks_with_deficit",
    ]
    return all(close(left.get(key), right.get(key)) for key in keys)


def main() -> None:
    model = SchoolPlacementModel()
    baseline = model._summary(model.baseline)

    check(
        "Baseline совпадает с практикой 2",
        model.verification.get("ok") is True,
        str(model.verification.get("max_abs_diff")),
    )
    check(
        "Базовые показатели практики 2",
        close(baseline["capacity"], 10500)
        and close(baseline["demand"], 40699)
        and close(baseline["deficit"], 30199)
        and close(baseline["provision"], 0.257992),
        f"capacity={baseline['capacity']}, demand={baseline['demand']}, "
        f"deficit={baseline['deficit']}, provision={baseline['provision']}",
    )

    block_rows = model._block_rows(model.baseline)
    rows_by_id = {row["block_id"]: row for row in block_rows}
    residential_ids = set(model.residential_block_ids)
    check(
        "Для размещения доступны только жилые кварталы",
        len(model.residential_block_ids) == 99
        and {row["block_id"] for row in block_rows} == residential_ids
        and all(row["land_use"] == "residential" for row in block_rows),
        f"displayed={len(block_rows)}, residential={len(residential_ids)}",
    )
    check(
        "Сценарии эксперимента используют только жилые кварталы",
        len(rows_by_id) == 99
        and {233, 255, 287, 436} <= residential_ids
        and all(
            model.block_meta.loc[placement["block_id"], "land_use"] == "residential"
            for definition in model.scenarios.values()
            for placement in definition.get("placements", [])
        ),
        str(
            {
                key: [placement["block_id"] for placement in definition.get("placements", [])]
                for key, definition in model.scenarios.items()
            }
        ),
    )
    rejected_nonresidential = False
    try:
        model.calculate_scenario([{"block_id": 107, "capacity": 600}])
    except ValueError:
        rejected_nonresidential = True
    check(
        "Размещение школы в нежилом квартале отклоняется",
        rejected_nonresidential,
    )

    empty = model.calculate_scenario([])
    check(
        "Пустой сценарий равен исходному состоянию",
        summaries_equal(empty["summary"], baseline),
        str(empty["summary"]),
    )
    check(
        "Пустой сценарий не меняет кварталы",
        all(
            abs(row["deficit_reduction"] or 0) <= TOLERANCE
            and abs(row["provision_change"] or 0) <= TOLERANCE
            and abs(row["added_capacity"] or 0) <= TOLERANCE
            for row in empty["blocks"]
        ),
    )

    single = model.calculate_scenario([{"block_id": 436, "capacity": 600}])
    summary = single["summary"]
    check(
        "Школа на 600 мест в жилом квартале 436",
        summary["added_capacity"] == 600
        and close(summary["deficit"], 29599)
        and close(summary["deficit_reduction"], 600)
        and close(summary["provision"], 0.272734)
        and summary["blocks_improved"] == 1
        and len(single["blocks"]) == 99,
        str(summary),
    )
    experiment_effects = {}
    for key, definition in model.scenarios.items():
        result = model.calculate_scenario(definition["placements"])
        experiment_effects[key] = result["summary"]
    check(
        "Эксперименты A, B и C дают ожидаемый эффект",
        experiment_effects["A"]["added_capacity"] == 600
        and experiment_effects["B"]["added_capacity"] == 600
        and experiment_effects["C"]["added_capacity"] == 600
        and experiment_effects["A"]["blocks_improved"] == 1
        and experiment_effects["B"]["blocks_improved"] == 2
        and experiment_effects["C"]["blocks_improved"] == 1,
        str({key: value["blocks_improved"] for key, value in experiment_effects.items()}),
    )

    reset = model.calculate_scenario([])
    check(
        "Сброс сценария возвращает baseline",
        summaries_equal(reset["summary"], baseline),
        str(reset["summary"]),
    )

    print("\nПолный автоподбор 600 мест по 99 жилым кварталам…")

    def progress(checked: int, total: int, block_id: int) -> None:
        if checked == total or checked % 50 == 0:
            print(f"  проверено {checked} из {total} (последний квартал {block_id})")

    auto = model.auto_search(600, progress=progress)
    checked_blocks = {row["block_id"] for row in auto["rows"]}
    check(
        "Автоподбор проверил все 99 жилых кварталов",
        auto["complete"] is True
        and auto["checked"] == 99
        and auto["total"] == 99
        and auto["successful"] == 99
        and not auto["errors"]
        and checked_blocks == residential_ids,
        f"checked={auto['checked']}, successful={auto['successful']}, errors={len(auto['errors'])}",
    )
    check(
        "Автоподбор не рассматривает нежилые кварталы",
        all(model.block_meta.loc[block_id, "land_use"] == "residential" for block_id in checked_blocks),
        f"non-residential in rows: {sorted(b for b in checked_blocks if model.block_meta.loc[b, 'land_use'] != 'residential')}",
    )
    check(
        "Автоподбор нашёл 90 равнозначных лучших",
        len(auto["best"]) == 90
        and close(auto["best_reduction"], 600)
        and len(auto["rows"]) == 99,
        f"best={len(auto['best'])}, best_reduction={auto['best_reduction']}",
    )

    best_id = auto["best"][0]
    best_row = next(row for row in auto["rows"] if row["block_id"] == best_id)
    manual_best = model.calculate_scenario([{"block_id": best_id, "capacity": 600}])
    check(
        f"Ручное размещение в лучшем квартале {best_id} совпадает с автоподбором",
        best_id == 287
        and auto["recommended"] == 287
        and close(manual_best["summary"]["deficit"], best_row["deficit"])
        and close(manual_best["summary"]["deficit_reduction"], best_row["deficit_reduction"])
        and close(manual_best["summary"]["provision"], best_row["provision"])
        and close(manual_best["summary"]["provision_change"], best_row["provision_change"]),
        str(manual_best["summary"]),
    )
    best_set = set(auto["best"])
    check(
        "Все лучшие строки имеют одинаковое сокращение дефицита",
        all(
            close(row["deficit_reduction"], auto["best_reduction"])
            for row in auto["rows"]
            if row["block_id"] in best_set
        ),
        f"rows={len(auto['rows'])}, best={len(best_set)}",
    )

    passed = sum(1 for _, ok, _ in checks if ok)
    failed = len(checks) - passed
    print(f"\nИтог: {passed} из {len(checks)} проверок пройдено, ошибок: {failed}.")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
