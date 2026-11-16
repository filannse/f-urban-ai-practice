# Данные для расчёта по Нижневартовску

В репозитории хранятся только итоговые и небольшие вспомогательные GeoJSON, а также манифест запуска. Крупный кэш OSM, графы, матрицы и промежуточные слои не коммитятся: их можно собрать из `.osm.pbf` одной командой.

## Что уже лежит в репозитории

| Путь | Что это |
|---|---|
| `nizhnevartovsk/results/blocks_indicators_drive.geojson` | Итоговый слой кварталов для автомобильного графа: население, плотность, морфотипы, доступность, обеспеченность |
| `nizhnevartovsk/results/blocks_indicators_walk.geojson` | То же для пешеходного графа |
| `nizhnevartovsk/raw/boundaries.geojson` | Граница исследуемой территории |
| `nizhnevartovsk/services/school.geojson` | Школы |
| `nizhnevartovsk/services/kindergarten.geojson` | Детские сады |
| `nizhnevartovsk/services/polyclinic.geojson` | Поликлиники |
| `nizhnevartovsk/manifest.json` | Параметры запуска, версии, размеры графов и итоговые показатели |

## Крупные данные

Если папки `nizhnevartovsk/` с кэшем нет, скачайте PBF Уральского федерального округа:

- основная ссылка: <https://download.openstreetmap.fr/extracts/russia/ural_federal_district-latest.osm.pbf>
- альтернатива: <https://download.geofabrik.de/russia/ural-fed-district-latest.osm.pbf>

Файл весит около 433 МБ. Положите его в `examples/data/` (например, `examples/data/ural.osm.pbf`) или в любую папку вне репозитория. Файлы `*.osm.pbf` исключены из git.

## Сборка кэша

Из корня проекта:

```powershell
.\.venv\Scripts\Activate.ps1
python examples\prepare_osm_cache.py --pbf examples\data\ural.osm.pbf
```

По умолчанию скрипт пишет кэш в `examples/data/nizhnevartovsk/`. Если PBF лежит в другом месте, укажите полный путь в `--pbf`. Другую папку кэша можно задать через `--data-dir`.

После сборки кэша ноутбук запускается с `USE_CACHE = True`:

```powershell
python -m jupyter lab examples\blocksnet_nizhnevartovsk.ipynb
```

## Структура кэша

```text
examples/data/nizhnevartovsk/
├── raw/          # исходные OSM-слои и импутированные здания
├── graphs/       # автомобильный и пешеходный графы (pickle)
├── matrices/     # матрицы времени между кварталами (parquet)
├── services/     # объекты сервисов после импутации
├── blocks/       # кварталы и их агрегаты
├── results/      # итоговые слои с показателями
├── manifest.json
└── osm_source.json
```

## Источник и лицензия

Данные OpenStreetMap распространяются по лицензии [ODbL 1.0](https://www.openstreetmap.org/copyright). При публикации карт и дашборда указывайте источник: © OpenStreetMap contributors.
