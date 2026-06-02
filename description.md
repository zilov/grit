# Curation Pipeline Notebook

## Цель

Переработанная версия рабочего ноутбука куратора (`notebooks/curatrion_script.ipynb`). Переходим от прототипа в ноутбуке к python-библиотеке с двумя способами взаимодействия.

## Способы взаимодействия

### 1. CLI (`curate`)

Команда устанавливается вместе с пакетом и доступна из терминала:

```bash
curate RC-1234 summary                    # распечатать сводку тикета
curate RC-1234 pre                        # запустить pre-curation шаги
curate RC-1234 post                       # запустить post-curation шаги
curate RC-1234 optional gap               # добавить gap track
curate RC-1234 optional telo              # добавить telo track
curate RC-1234 optional bedgraph FILE     # добавить bedgraph track
curate RC-1234 pre --print-only           # показать команды без выполнения
curate RC-1234 pre --yaml ticket.yaml     # использовать локальный YAML вместо Jira
```

Конфиг читается из `~/.grit_curation_config.yaml` автоматически.

Подходит для: быстрого запуска одного тикета из терминала, автоматизации, тестирования без доступа к Jira (`--yaml`), проверки команд перед запуском (`--print-only`).

### 2. Jupyter Notebook

Импорт библиотеки в ноутбуке даёт полный контроль: можно вызывать шаги по одному, менять параметры между шагами, использовать опциональные функции:

```python
from curation_pipeline.context import build_context
from curation_pipeline.steps.pre_curation import *
from curation_pipeline.steps.post_curation import *

ctx = build_context("RC-1234", USER_CONFIG)
print_curation_summary(ctx)
setup_curation(ctx)
copy_pretext_maps(ctx)
add_gap_track(ctx)        # опционально
```

Подходит для: интерактивной работы, опциональных шагов, случаев когда нужно вмешаться между шагами.

### Тестирование

Оба способа тестируются:
- **Unit-тесты** (pytest) — тестируют функции библиотеки напрямую, без Jira и файловой системы
- **CLI-тесты** с `--yaml` + `--print-only` — позволяют проверить полный флоу локально без доступа к farm
- **Ручное тестирование** на ферме с реальным тикетом — финальная валидация

## Среда выполнения

Ноутбук запускается **на HPC farm** (JupyterHub или аналог). Это означает:

- NFS (`/nfs/treeoflife-01/...`) и Lustre (`/lustre/scratch123/...`) смонтированы напрямую — операции с файлами через `cp`, не `scp`
- `bsub` доступен напрямую — команды на farm можно выполнять из ноутбука, а не только печатать.
- Jira доступна через общую библиотеку `GritJiraIssue` (путь к модулю одинаков для всех кураторов)
- `scp` нужен только в одну сторону: farm → локальная машина куратора (для работы в PretextView)

---

## Ключевые принципы дизайна

### 1. Каждый шаг — отдельная функция без глобального состояния

Все функции принимают явные аргументы (`ctx: CurationContext`) и не зависят от локального контекста внешней функции. Можно вызвать любой шаг независимо.

`CurationContext` создаётся один раз из `ticket_id` + `USER_CONFIG` и передаётся во все функции. Содержит распарсенный YAML из Jira и все вычисленные пути.

### 2. Выполнение и вывод

Функции делятся на два типа по способу выполнения:

| Тип | Примеры | Поведение |
|-----|---------|-----------|
| **Выполняется напрямую** | `cp` pretext maps, `mkdir`, `bsub` команды | Функция выполняет действие и сообщает результат |
| **Требует ручного действия** | PretextView, проверка AGP | Функция печатает инструкцию и ждёт подтверждения от куратора |

Для bsub-команд: запускаем через `subprocess`, печатаем job ID, не ждём завершения.

Для операций с pretext maps на локальной машине куратора: функция печатает `scp` команду, которую куратор выполняет у себя.

Пример вывода функции шага:

```
╔══════════════════════════════════════════════════════╗
║  RC-1234 | ilHelSara1 | Step: Copy pretext maps      ║
╚══════════════════════════════════════════════════════╝
Status:
  Assembly type : hap1/hap2 (combine_for_curation=True)
  Maps found    : 2 (_normal_, _hr_)

Done: copied to /lustre/.../<USERNAME>_curation/ilHelSara1/

To open in PretextView, run on your local machine:
  scp <FARM_HOST>:/lustre/.../<USERNAME>_curation/ilHelSara1/ilHelSara1_1_normal_.pretext ~/curations/ilHelSara1/
  scp <FARM_HOST>:/lustre/.../<USERNAME>_curation/ilHelSara1/ilHelSara1_1_hr_.pretext ~/curations/ilHelSara1/

Next step: add_gap_track(ctx)
```

### 3. Вход — номер тикета

Единственный обязательный внешний параметр — `ticket_id` (например `"RC-1234"` или `"GRIT-567"`). Вся остальная информация получается из Jira через `GritJiraIssue`.

YAML из Jira кэшируется локально в рабочую папку при первом запуске — повторные вызовы не обращаются к Jira.

### 4. Первая ячейка — пользовательский конфиг

```python
USER_CONFIG = {
    "username": "<USERNAME>",
    "pretext_maps_nfs": "/nfs/.../teams/grit/data/pretext_maps",
    "curated_pretext_maps_nfs": "/nfs/.../teams/grit/data/curated_pretext_maps",
    "curation_savestates_nfs": "/nfs/.../teams/grit/data/curation_savestates",
    "farm_host": "<FARM_HOST>",   # только для генерации scp команд для локальной машины куратора
    "email": "<USERNAME>@sanger.ac.uk",
    "gritjiraissue_path": "<GRITJIRAISSUE_PATH>",
}
```

> `USER_CONFIG` с реальными значениями хранится локально в `~/.grit_curation_config.yaml` и **не коммитится**. В репо только шаблон с плейсхолдерами.

### 5. Рабочая директория — внутри папки образца

Рабочая директория для каждого тикета вычисляется из пути к черновой сборке в YAML. Нет единой `curations_dir` — каждый образец живёт рядом со своими данными:

```
assembly_draft_path:  .../Species_name/assembly/draft/<tol_id.ver>/
workdir:              .../Species_name/working/{username}_curation/{tol_id}/
```

Логика: берём `assembly_draft_path` из YAML, заменяем `assembly/draft` на `working`, добавляем `/{username}_curation/{tol_id}/`.

Пример:
```
YAML: /lustre/scratch122/tol/data/3/5/f/9/5/8/Dipturus_intermedius/assembly/draft/sDipInt39.1/
workdir: /lustre/scratch122/tol/data/3/5/f/9/5/8/Dipturus_intermedius/working/<USERNAME>_curation/sDipInt39/
```

При повторной курации (после QC фейла) — файлы из предыдущего запуска удаляются, тот же `workdir` используется заново.

---

## Структура библиотеки

### Блок 0: Конфигурация и импорты
- Ячейка 1: `USER_CONFIG` — параметры куратора
- Ячейка 2: Импорты, `sys.path.insert` для GritJiraIssue

### Блок 1: Утилиты (низкоуровневые функции)
- Ячейка 3: `build_context(ticket_id, USER_CONFIG) → CurationContext` — парсит Jira YAML, вычисляет все пути, кэширует YAML локально; хелперы форматирования вывода

### Блок 2: Pre-curation steps (до ручной курации)

| Ячейка | Функция | Что делает |
|--------|---------|------------|
| 4 | `setup_curation(ctx)` | Создаёт рабочие папки (`mkdir -p`) на Lustre; копирует `original.fa` с draft сборки |
| 5 | `copy_pretext_maps(ctx)` | `cp` maps с NFS в рабочую папку; печатает `scp` команды для локальной машины |
| 6 | `print_curation_summary(ctx)` | Выводит тип сборки, ожидаемый кариотип, пол, пути к данным |

**Опциональные (не часто):**

| Ячейка | Функция | Условие |
|--------|---------|---------|
| 7 | `add_gap_track(ctx)` | Если нужен gap track в pretext map |
| 8 | `add_telo_track(ctx)` | Если найден `telo_*.bed.gz` из treeval |
| 9 | `add_bedgraph_track(ctx)` | Юзер передает путь до bedgraph файла который добавляется в *.pretext по аналогии с add_gap_track |

### Блок 3: MANUAL — Курация в PretextView

Markdown ячейка с чеклистом и напоминанием о тегах. Куратор работает локально в PretextView, сохраняет AGP и savestate.

```
[ ] Открыть pretext map в PretextView
[ ] Исправить misjoins
[ ] Chromosome painting
[ ] Назначить теги (Haplotig, Contaminant, Unloc, ...)
[ ] Экспортировать AGP
[ ] Скопировать AGP на farm: scp ~/curations/<tol_id>/curated.agp farm22:<curations_dir>/<tol_id>/
```

### Блок 4: Post-curation steps (после курации)

| Ячейка | Функция | Что делает |
|--------|---------|------------|
| 9 | `run_pretext_to_asm(ctx)` | Проверяет наличие AGP; запускает `bsub pretext-to-asm`; печатает job ID |
| 10 | `ensure_haplotig_files(ctx)` | Проверяет наличие ожидаемых haplotig файлов после pretext-to-asm; создаёт пустые если не были сгенерированы (например, если тег Haplotig не использовался) |
| 11 | `run_hic_remapping(ctx)` | Запускает `submit_curation_pretext` через `bsub`; печатает job ID |
| 12 | `run_qv(ctx)` | Запускает `bsub kmer_completeness.bash`; печатает job ID |
| 13 | `validate_curated_files(ctx)` | Проверяет что все ожидаемые файлы в curated папке присутствуют; использует `jira_utils -p {ticket_id}` (Python библиотека); выводит diff ожидаемых vs найденных файлов |
| 14 | `finalize_for_qc(ctx)` | `cp` curated map и savestate на NFS; `cp` curated FA в `/lustre/.../assembly/curated/`; напоминает поменять статус тикета |

> `jira_utils` — Python библиотека (аналогично GritJiraIssue, путь будет общим); пока используется через CLI, в будущем подключить как модуль.

### Блок 5: Опциональные шаги

| Ячейка | Функция | Условие |
|--------|---------|---------|
| 13 | `run_sex_matcher(ctx)` | Насекомые (`ic*`, `il*`, `id*`) |
| 14 | `run_microchromosome_curation(ctx)` | Птицы или большие геномы с мелкими хромосомами |
| 15 | `run_fastga(ctx)` | Если найден референс |

### Блок 6: Ячейки-вызовы для каждого тикета

Одна ячейка на тикет:

```python
# RC-1234 | ilHelSara1 | Heliconius sara | Lepidoptera
ctx = build_context("RC-1234", USER_CONFIG)
print_curation_summary(ctx)
setup_curation(ctx)
copy_pretext_maps(ctx)
add_gap_track(ctx)
add_telo_track(ctx)
run_sex_matcher(ctx)   # насекомое
```

---

## Стандарты проекта

### Структура

```
curation_notebook/
├── curation_pipeline.ipynb   # ноутбук — только импорты и вызовы
├── curation_pipeline/        # Python пакет — вся логика
│   ├── __init__.py
│   ├── context.py            # CurationContext dataclass, build_context()
│   ├── steps/
│   │   ├── pre_curation.py
│   │   ├── post_curation.py
│   └── output.py             # форматирование вывода
├── tests/
│   ├── conftest.py           # фикстуры: фиктивный CurationContext, тестовые YAML
│   ├── test_context.py
│   ├── test_pre_curation.py
│   └── test_post_curation.py
├── pyproject.toml
└── description.md
```

### Инструменты (astral.sh)

| Инструмент | Роль |
|------------|------|
| **uv** | Управление зависимостями и виртуальным окружением (`uv add`, `uv sync`) |
| **ruff** | Линтинг и форматирование (`ruff check`, `ruff format`) |

```toml
# pyproject.toml
[project]
name = "curation-pipeline"
requires-python = ">=3.10"

[tool.ruff]
line-length = 100
[tool.ruff.lint]
select = ["E", "F", "I"]   # pycodestyle, pyflakes, isort
```

Зависимости проекта — только стандартная библиотека + `rich` для вывода. `GritJiraIssue` и `jira_utils` подключаются через `sys.path` (общие серверные библиотеки), не через `pyproject.toml`.

### Тесты

- **pytest** для всех функций логики
- Тесты не обращаются к Jira, NFS, Lustre — всё мокируется фиктивными данными
- Фикстура `mock_ctx` в `conftest.py` создаёт `CurationContext` из тестового YAML без сети и файловой системы
- Для функций с `subprocess` (bsub, cp) — мокируем `subprocess.run`, проверяем что вызов правильный

```python
# пример теста
def test_workdir_derived_from_draft_path(mock_ctx):
    assert "working/dz11_curation/sDipInt39" in str(mock_ctx.workdir)

def test_ensure_haplotig_files_creates_empty(tmp_path, mock_ctx):
    mock_ctx.workdir = tmp_path
    ensure_haplotig_files(mock_ctx)
    assert (tmp_path / "sDipInt39.1.all_haplotigs.curated.fa").exists()
```

### Безопасность

Общие правила — в [CLAUDE.md](../CLAUDE.md#стандарты-разработки). Специфично для ноутбука:

- `USER_CONFIG` в ноутбуке загружается из `~/.grit_curation_config.yaml`, не хардкодится
- В репо коммитится только `user_config.template.yaml` с плейсхолдерами
- Кэш YAML из Jira (`*.jira_cache.yaml`) — в `.gitignore`
