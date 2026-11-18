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

    single = model.calculate_scenario([{"block_id": 107, "capacity": 600}])
    summary = single["summary"]
    check(
        "Школа на 600 мест в квартале 107",
        summary["added_capacity"] == 600
        and close(summary["deficit"], 29599)
        and close(summary["deficit_reduction"], 600)
        and close(summary["provision"], 0.272734)
        and summary["blocks_improved"] == 1,
        str(summary),
    )

    reset = model.calculate_scenario([])
    check(
        "Сброс сценария возвращает baseline",
        summaries_equal(reset["summary"], baseline),
        str(reset["summary"]),
    )

    print("\nПолный автоподбор 600 мест по 540 кварталам…")

    def progress(checked: int, total: int, block_id: int) -> None:
        if checked == total or checked % 50 == 0:
            print(f"  проверено {checked} из {total} (последний квартал {block_id})")

    auto = model.auto_search(600, progress=progress)
    all_blocks = set(model.block_ids)
    checked_blocks = {row["block_id"] for row in auto["rows"]}
    check(
        "Автоподбор проверил все 540 кварталов",
        auto["complete"] is True
        and auto["checked"] == 540
        and auto["total"] == 540
        and auto["successful"] == 540
        and not auto["errors"]
        and checked_blocks == all_blocks,
        f"checked={auto['checked']}, successful={auto['successful']}, errors={len(auto['errors'])}",
    )
    check(
        "Автоподбор нашёл 347 равнозначных лучших",
        len(auto["best"]) == 347
        and close(auto["best_reduction"], 600)
        and len(auto["rows"]) == 540,
        f"best={len(auto['best'])}, best_reduction={auto['best_reduction']}",
    )

    best_id = auto["best"][0]
    best_row = next(row for row in auto["rows"] if row["block_id"] == best_id)
    manual_best = model.calculate_scenario([{"block_id": best_id, "capacity": 600}])
    check(
        f"Ручное размещение в лучшем квартале {best_id} совпадает с автоподбором",
        close(manual_best["summary"]["deficit"], best_row["deficit"])
        and close(manual_best["summary"]["deficit_reduction"], best_row["deficit_reduction"])
        and close(manual_best["summary"]["provision"], best_row["provision"])
        and close(manual_best["summary"]["provision_change"], best_row["provision_change"]),
        str(manual_best["summary"]),
    )
    check(
        "Ручной квартал 107 входит в группу лучших",
        107 in auto["best"],
        f"best contains 107: {107 in auto['best']}",
    )
    check(
        "Сценарный квартал 2 входит в группу лучших",
        2 in auto["best"],
        f"best contains 2: {2 in auto['best']}",
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
