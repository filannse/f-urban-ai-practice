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
        return "_Нет кварталов с положительным изменением._\n"
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
    c_first_block = results["C"]["placements"][0]["block_id"]
    a_first_block = results["A"]["placements"][0]["block_id"]

    lines = [
        "# Эксперимент: размещение школ в Нижневартовске",
        "",
        "Отчёт сгенерирован скриптом `experiment.py` по данным практики 2. "
        "Все расчёты выполняются той же моделью, что и в приложении.",
        "",
        "## Метод",
        "",
        "- Город: Нижневартовск; 540 расчётных кварталов.",
        "- Граф: автомобильный (`drive`).",
        "- Норматив: 120 мест на 1 000 жителей; порог доступности — 15 минут.",
        "- Метод: `competitive_provision`, `self_supply=True`, `max_depth=1`.",
        "- Недостижимые пары в матрице заменены штрафом 180 минут.",
        "- Новая школа добавляется к существующей вместимости квартала; "
        "модель учитывает перераспределение спроса между доступными школами.",
        "",
        "## Исходное состояние",
        "",
        "| Показатель | Значение |",
        "|---|---:|",
        f"| Кварталов | {fmt_int(baseline['blocks'])} |",
        f"| Население, чел. | {fmt_int(population_total)} |",
        f"| Спрос на места | {fmt_int(baseline['demand'])} |",
        f"| Вместимость школ | {fmt_int(baseline['capacity'])} |",
        f"| Дефицит мест | {fmt_int(baseline['deficit'])} |",
        f"| Обеспеченность | {fmt_percent(baseline['provision'])} |",
        f"| Кварталов с дефицитом | {fmt_int(baseline['blocks_with_deficit'])} |",
        "",
        "## Сценарии",
        "",
        "| Ключ | Сценарий | Размещение | Добавлено мест | Остаточный дефицит | "
        "Сокращение дефицита | Обеспеченность | Δ обеспеченности | Улучшено кварталов | "
        "Кварталов с дефицитом |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
        scenario_table_row("A", results["A"]),
        scenario_table_row("B", results["B"]),
        scenario_table_row("C", results["C"]),
        "",
        "## Пространственный эффект",
        "",
        "### A. Одна школа на 600 мест в квартале 107",
        "",
        results["A"]["description"],
        "",
        changed_table(results["A"]["changed"]),
        "### B. Две школы по 300 мест в кварталах 107 и 17",
        "",
        results["B"]["description"],
        "",
        changed_table(results["B"]["changed"]),
        "### C. Автоматический подбор одной школы на 600 мест",
        "",
        results["C"]["description"],
        "",
        changed_table(results["C"]["changed"]),
        "## Ответы на вопросы",
        "",
        "### Какой вариант обеспечил наибольшее сокращение суммарного дефицита?",
        "",
        (
            "Все три сценария дают одинаковое суммарное сокращение дефицита — "
            f"{fmt_int(scenario_a['deficit_reduction'])} мест, и одинаковый остаточный дефицит — "
            f"{fmt_int(scenario_a['deficit'])} мест. Единственного победителя по этому критерию нет."
            if residual_same and reduction_same
            else "Сценарии различаются по суммарному сокращению дефицита; см. таблицу выше."
        ),
        "",
        "Различие между сценариями — не в сумме, а в том, где именно улучшается обеспеченность:",
        "",
        f"- A: рост обеспеченности в квартале 107; улучшен {fmt_int(scenario_a['blocks_improved'])} квартал.",
        f"- B: рост в кварталах 107, 17 и 233; улучшено {fmt_int(scenario_b['blocks_improved'])} квартала. "
        "В квартале 233 новая вместимость не строится, но он получает эффект перераспределения спроса.",
        f"- C: рост в кварталах 2 и 436; улучшено {fmt_int(scenario_c['blocks_improved'])} квартала, "
        f"число кварталов с дефицитом сокращается до {fmt_int(scenario_c['blocks_with_deficit'])}.",
        "",
        "### Совпал ли ручной выбор одной школы с автоматическим поиском?",
        "",
        (
            f"Автоматический поиск не дал единственного лучшего квартала: 347 вариантов равнозначны. "
            f"Квартал {a_first_block} из ручного сценария A входит в эту группу, поэтому по величине "
            "сокращения дефицита выбор совпал. Но если понимать под результатом один конкретный квартал, "
            f"номера различаются: сценарий C использует квартал {c_first_block} (минимальный `block_id` "
            f"среди лучших), а не {a_first_block}. Полный перебор 540 кварталов даёт одинаковое сокращение "
            "суммарного дефицита 600 мест для всех 347 лучших вариантов."
        ),
        "",
        "### В каких кварталах обеспеченность повысилась, а в каких сохранился дефицит?",
        "",
        f"- A: обеспеченность повысилась в квартале 107; в остальных кварталах изменений нет. "
        f"Дефицит сохраняется в {fmt_int(scenario_a['blocks_with_deficit'])} кварталах.",
        f"- B: повысилась в кварталах 107, 17 и 233; дефицит сохраняется в "
        f"{fmt_int(scenario_b['blocks_with_deficit'])} кварталах.",
        f"- C: повысилась в кварталах 2 и 436; дефицит сохраняется в "
        f"{fmt_int(scenario_c['blocks_with_deficit'])} кварталах.",
        "",
        f"Во всех сценариях суммарный дефицит остаётся очень большим — {fmt_int(scenario_a['deficit'])} мест. "
        "Одна школа на 600 мест сокращает дефицит лишь на 600 мест и не решает проблему обеспеченности города.",
        "",
        "### Почему автоматический поиск дал 347 равнозначных лучших?",
        "",
        "Критерий автоподбора — только суммарный дефицит после добавления одной школы. "
        "Если школа попадает в квартал, где весь её ресурс востребован, суммарное сокращение дефицита "
        "одинаково и равно вместимости школы. Поэтому критерий не различает кварталы по числу улучшенных "
        "территорий, величине локального эффекта и пригодности участка. Приложение показывает все "
        "равнозначные варианты, а не выбирает один молча.",
        "",
        "### Какие ограничения данных и метода влияют на вывод?",
        "",
        "- Население и существующая вместимость школ — расчётные оценки практики 2, а не официальная статистика.",
        "- Использован автомобильный граф и порог 15 минут; пешеходная и транспортная доступность не проверялись.",
        "- Модель оценивает только обеспеченность местами, но не учитывает стоимость, земельный участок, "
        "санитарные зоны, собственность и строительную готовность.",
        "- Критерий автоподбора вырожден: 347 кварталов дают одинаковый суммарный эффект.",
        "- В автоподборе размещается только одна школа; сценарий B показывает, что распределение "
        "двух школ может дать другой пространственный эффект при той же сумме.",
        "- Результат зависит от качества OSM и полноты данных о школах и населении.",
        "",
        "## Проверки",
        "",
        "Для воспроизведения проверок выполните:",
        "",
        "```powershell",
        "python school-placement/verify.py",
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    model = SchoolPlacementModel()
    definitions = model.scenarios
    if not definitions:
        raise SystemExit("Не найден scenarios.json")

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
            key=lambda row: (-(row["deficit_reduction"] or 0), -(row["provision_change"] or 0), row["block_id"]),
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
        "scenarios": results,
    }
    RESULTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT_PATH.write_text(build_report(model, results), encoding="utf-8")
    print(f"\nЗаписано: {RESULTS_PATH.name}, {REPORT_PATH.name}")


if __name__ == "__main__":
    main()
