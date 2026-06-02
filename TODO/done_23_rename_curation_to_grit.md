Хочу изменить запуск приложения, чтобы вместо curate было grit {tool}.

## План

1. **`pyproject.toml`** — заменить `curate` на `grit` в `[project.scripts]`
2. **`curation_pipeline/`** — переименовать пакет в `grit/` и обновить все внутренние импорты
3. **`pyproject.toml`** — обновить `name` проекта и точку входа (`grit/core/click_cli:cli`)
4. **`tests/`** — обновить импорты
5. Переустановить пакет: `uv sync`
