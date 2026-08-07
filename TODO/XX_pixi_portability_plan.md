# XX — Portability via pixi (conda-forge / bioconda)

## Проблема

Сейчас `grit` жёстко привязан к HPC-серверу через `module load` (см. `grit/utils/modules.py`).
Перенести пайплайн на другой сервер = вручную поднять все те же Lmod-модули (pretext-to-asm, curationpretext, pretextgraph, fastga и др.), что нереально в общем случае.

## Решение: pixi

**pixi** — менеджер пакетов поверх conda (mamba-resolver), поддерживает conda-forge и bioconda.
Ключевые преимущества для биоинформатики:
- `pixi.toml` описывает все зависимости декларативно, включая биоинформатические тулы из bioconda
- `pixi run <task>` — запуск задач внутри изолированного окружения (аналог `make`, но с окружением)
- воспроизводимость через `pixi.lock` (точные версии + хэши)
- работает без root, без системного conda

---

## System Design

```
grit/
  pixi.toml          ← главный файл: зависимости + задачи
  pixi.lock          ← локфайл (коммитить в git)
  pyproject.toml     ← остаётся для Python-пакета grit
  grit/
    utils/
      modules.py     ← РЕФАКТОРИНГ: добавить режим "pixi" вместо "module load"
    config/
      environments.py ← заполнить: определять текущий backend (lmod / pixi / conda)
      settings.py    ← флаги и пути под конкретный сервер
```

**Два режима запуска инструментов:**

| Режим       | Когда                          | Как вызывается тул              |
|-------------|--------------------------------|---------------------------------|
| `lmod`      | HPC с Lmod (текущий сервер)    | `module purge && module load X` |
| `pixi`      | Любой сервер с pixi            | тул уже в PATH окружения pixi   |

Режим определяется автоматически (наличие `pixi` в PATH или переменная `GRIT_ENV_BACKEND`).

---

## Основные шаги реализации

### Шаг 1 — Инициализировать pixi в репозитории
```
pixi init
```
Добавить в `pixi.toml`:
- `[project]` channels: `["conda-forge", "bioconda"]`
- `[dependencies]`: python, pip, и сам `grit` через `pip install -e .`
- `[dependencies]` (bioconda): pretexttools, fastga, busco, merqury, и др.
- `[tasks]`: `grit = "grit"` — чтобы `pixi run grit` работало

### Шаг 2 — Заполнить `environments.py`
Реализовать функцию `detect_backend() -> Literal["lmod", "pixi", "conda"]`:
- проверяет `GRIT_ENV_BACKEND` env-переменную (явный override)
- иначе: `shutil.which("pixi")` → `"pixi"`, наличие Lmod → `"lmod"`, иначе → `"conda"`

### Шаг 3 — Рефакторинг `modules.py`
Добавить маппинг `PIXI_TOOL_NAMES` (логический ключ → имя бинаря в conda-окружении).
Функция `tool_cmd(tool_key)` возвращает либо `module load ...`, либо просто имя бинаря —
в зависимости от `detect_backend()`.

### Шаг 4 — `settings.py`: серверные настройки
Перенести хардкод путей (референсы, scratch-директории и т.д.) в `settings.py`.
Загрузка из env-переменных или `~/.grit/config.yaml` (user-level конфиг).

### Шаг 5 — Документация
Добавить в `README.md` секцию "Installation on a new server":
```
curl -fsSL https://pixi.sh/install.sh | sh
git clone <repo>
cd grit
pixi install      # скачивает все зависимости
pixi run grit --help
```

---

## Что НЕ меняется
- `pyproject.toml` и uv остаются для разработки на текущем сервере
- CLI-интерфейс (`grit` команды) не меняется
- `module load`-режим продолжает работать на родном HPC

## Открытые вопросы
- Какие именно тулы из `MODULE_VERSIONS` есть в bioconda? (нужно проверить каждый)
- `curationpretext` — это внутренний Sanger пайплайн, возможно придётся контейнеризировать (Singularity/Docker) отдельно
