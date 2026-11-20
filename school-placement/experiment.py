from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

from model import SchoolPlacementModel  # noqa: E402

REPORT_PATH = APP_DIR / "EXPERIMENT.md"
RESULTS_PATH = APP_DIR / "experiment_results.json"


def fmt_int(value: Any) -> str:
    if value is None:
        return "—"
    return f"{round(float(value)):,.0f}".replace(",", " ")


def fmt_num(value: Any, digits: int = 1) -> str:
    if value is None:
        return "—"
    text = f"{float(value):,.{digits}f}"
    return text.replace(",", " ").replace(".", ",")


def fmt_percent(value: Any) -> str:
    if value is None:
        return "—"
    return f"{float(value) * 100:.1f}%".replace(".", ",")


def fmt_change(value: Any) -> str:
    if value is None:
        return "—"
    points = float(value) * 100
    sign = "+" if points > 0 else ""
    number = f"{points:.1f}".replace(".", ",")
    return f"{sign}{number} п.п."


def placements_text(placements: list[dict[str, Any]]) -> str:
    if not placements:
        return "—"
    return "; ".join(
        f"квартал {placement['block_id']} — {fmt_int(placement['capacity'])} мест"
        for placement in placements
    )


def scenario_table_row(key: str, result: dict[str, Any]) -> str:
    summary = result["summary"]
    return (
        f"| {key} | {result['name']} | {placements_text(result['placements'])} "
        f"| {fmt_int(summary['added_capacity'])} | {fmt_int(summary['deficit'])} "
        f"| {fmt_int(summary['deficit_reduction'])} | {fmt_percent(summary['provision'])} "
        f"| {fmt_change(summary['provision_change'])} | {fmt_int(summary['blocks_improved'])} "
        f"| {fmt_int(summary['blocks_with_deficit'])} |"
    )


def changed_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_Нет кварталов с изменениями._\n"
    lines = [
        "| Квартал | Население | Вместимость исходная | Вместимость сценария | "
        "Обеспеченность исходная | Обеспеченность сценария | Δ обеспеченности | "
        "Сокращение дефицита | Тип использования |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['block_id']} | {fmt_int(row['population'])} | {fmt_int(row['baseline_capacity'])} "
            f"| {fmt_int(row['scenario_capacity'])} | {fmt_percent(row['baseline_provision'])} "
            f"| {fmt_percent(row['scenario_provision'])} | {fmt_change(row['provision_change'])} "
            f"| {fmt_int(row['deficit_reduction'])} | {row['land_use']} |"
        )
    return "\n".join(lines) + "\n"


def build_report(model: SchoolPlacementModel, results: dict[str, dict[str, Any]]) -> str:
    baseline = model._summary(model.baseline)
    population_total = int(model.population.sum())
    scenario_a = results["A"]["summary"]
    scenario_b = results["B"]["summary"]
    scenario_c = results["C"]["summary"]
    residual_same = scenario_a["deficit"] == scenario_b["deficit"] == scenario_c["deficit"]
    reduction_same = (
        scenario_a["deficit_reduction"]
        == scenario_b["deficit_reduction"]
        == scenario_c["deficit_reduction"]
    )

    lines = [
        "# Эксперимент: размещение школ в Нижневартовске",
        "",
        "Отчёт сформирован скриптом `experiment.py` на данных практики 2. "
        "Все школы размещаются только в жилых кварталах (`land_use = residential`); "
        "промышленные, рекреационные и прочие зоны исключены из выбора.",
        "",
        "## Условия",
        "",
        f"- Город: Нижневартовск; 540 расчётных кварталов, из них {len(model.residential_block_ids)} жилых доступны для размещения.",
        "- Граф: автомобильный (`drive`).",
        "- Норматив: 120 мест на 1 000 жителей; порог доступности — 15 минут.",
        "- Метод: `competitive_provision`, `self_supply=True`, `max_depth=1`.",
        "- Недостижимые пары в матрице заменены штрафом 180 минут.",
        "- Школы разрешено размещать только в кварталах с `land_use = residential`.",
        "",
        "## Исходное состояние",
        "",
        "| Показатель | Значение |",
        "|---|---:|",
        f"| Кварталов в расчёте | {fmt_int(baseline['blocks'])} |",
        f"| Жилых кварталов для размещения | {fmt_int(len(model.residential_block_ids))} |",
        f"| Население, чел. | {fmt_int(population_total)} |",
        f"| Спрос на места | {fmt_int(baseline['demand'])} |",
        f"| Вместимость школ | {fmt_int(baseline['capacity'])} |",
        f"| Дефицит мест | {fmt_int(baseline['deficit'])} |",
        f"| Обеспеченность | {fmt_percent(baseline['provision'])} |",
        f"| Кварталов с дефицитом | {fmt_int(baseline['blocks_with_deficit'])} |",
        "",
        "## Сценарии",
        "",
        "| Код | Сценарий | Размещение | Добавлено мест | Остаточный дефицит | "
        "Сокращение дефицита | Обеспеченность | Δ обеспеченности | Улучшено кварталов | "
        "Кварталов с дефицитом |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
        scenario_table_row("A", results["A"]),
        scenario_table_row("B", results["B"]),
        scenario_table_row("C", results["C"]),
        "",
        "## Пространственный эффект",
        "",
    ]

    for key in ("A", "B", "C"):
        result = results[key]
        lines.extend(
            [
                f"### {result['name']}",
                "",
                result["description"],
                "",
                changed_table(result["changed"]),
            ]
        )

    lines.extend(
        [
            "## Сравнение сценариев",
            "",
            (
                "Все три сценария дают одинаковое сокращение суммарного дефицита — "
                f"{fmt_int(scenario_a['deficit_reduction'])} мест, остаточный дефицит — "
                f"{fmt_int(scenario_a['deficit'])} мест. Различается пространственный эффект:"
                if residual_same and reduction_same
                else "Сценарии отличаются по суммарному и пространственному эффекту."
            ),
            "",
            f"- A: улучшено кварталов — {fmt_int(scenario_a['blocks_improved'])}; "
            f"кварталов с дефицитом — {fmt_int(scenario_a['blocks_with_deficit'])}.",
            f"- B: улучшено кварталов — {fmt_int(scenario_b['blocks_improved'])}; "
            f"кварталов с дефицитом — {fmt_int(scenario_b['blocks_with_deficit'])}.",
            f"- C: улучшено кварталов — {fmt_int(scenario_c['blocks_improved'])}; "
            f"кварталов с дефицитом — {fmt_int(scenario_c['blocks_with_deficit'])}.",
            "",
            "Сценарий A показывает одну школу на 600 мест в центральном жилом квартале, "
            "B — две школы по 300 мест в двух разных жилых кварталах, "
            "C — результат автоматического поиска среди жилых кварталов.",
            "",
            "## Ограничения",
            "",
            "- Население и вместимость школ — расчётные оценки практики 2, а не официальная статистика.",
            "- Учитывается только автомобильная доступность; пешеходная и транспортная доступность не проверяются.",
            "- Модель не оценивает стоимость строительства, земельный участок, собственность, "
            "санитарные зоны и строительную готовность.",
            "- Критерий автоподбора — суммарный дефицит; при равенстве показываются все равнозначные лучшие кварталы.",
            "",
            "## Проверка",
            "",
            "```powershell",
            "python school-placement/verify.py",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    model = SchoolPlacementModel()
    definitions = model.scenarios
    if not definitions:
        raise SystemExit("Нет сценариев в scenarios.json")

    results: dict[str, dict[str, Any]] = {}
    for key, definition in definitions.items():
        data = model.calculate_scenario(definition["placements"])
        changed = sorted(
            (
                row
                for row in data["blocks"]
                if (row["deficit_reduction"] or 0) > 1e-9
                or (row["provision_change"] or 0) > 1e-9
            ),
            key=lambda row: (
                -(row["deficit_reduction"] or 0),
                -(row["provision_change"] or 0),
                row["block_id"],
            ),
        )
        results[key] = {
            "name": definition["name"],
            "description": definition["description"],
            "placements": data["placements"],
            "summary": data["summary"],
            "changed": changed,
        }
        summary = data["summary"]
        print(
            f"{key}: {definition['name']} | added={summary['added_capacity']} | "
            f"deficit={summary['deficit']} | reduction={summary['deficit_reduction']} | "
            f"provision={summary['provision']:.6f} | improved={summary['blocks_improved']}"
        )
        for row in changed:
            print(
                f"  block {row['block_id']}: provision {row['baseline_provision']} -> "
                f"{row['scenario_provision']} | deficit reduction {row['deficit_reduction']}"
            )

    payload = {
        "baseline": model.initial_payload()["meta"]["baseline"],
        "display_block_count": len(model.residential_block_ids),
        "scenarios": results,
    }
    RESULTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT_PATH.write_text(build_report(model, results), encoding="utf-8")
    print(f"\nЗаписаны: {RESULTS_PATH.name}, {REPORT_PATH.name}")


if __name__ == "__main__":
    main()
