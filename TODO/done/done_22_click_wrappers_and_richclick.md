# Таска: CLI обёртки + переход на richclick

## Цель
1. Добавить Click `_cmd` обёртки для всех незавершённых модулей.
2. Перевести весь CLI с `click` на `rich-click` (красивый `--help` с Rich-форматированием).

---

## 1. Переход на richclick

Заменить импорт `click` → `rich-click` везде в проекте.

**`pyproject.toml`:** заменить `click>=8.0.0` на `richclick>=1.9.0` (rich-click тянет click как зависимость).

**Паттерн замены** во всех файлах:
```python
# было
import click

# стало
import rich_click as click
```

**Файлы для замены:**
- [x] `curation_pipeline/core/click_cli.py`
- [x] `curation_pipeline/steps/pre_curation/sex_matcher.py`
- [x] `curation_pipeline/steps/pre_curation/add_pretext_view_tracks.py`
- [x] `curation_pipeline/steps/pre_curation/find_reference.py`
- [x] `curation_pipeline/steps/pre_curation/microchromosome.py`
- [x] `curation_pipeline/steps/pre_curation/setup.py`
- [x] `curation_pipeline/steps/post_curation/finalize_qc.py`
- [x] `curation_pipeline/steps/post_curation/haplotig_files.py`
- [x] `curation_pipeline/steps/post_curation/hic_remapping.py`
- [x] `curation_pipeline/steps/post_curation/post_curation.py`
- [x] Новые файлы с обёртками (см. ниже)

Можно добавить настройку в `click_cli.py`:
```python
import rich_click as click

click.rich_click.USE_RICH_MARKUP = True
click.rich_click.SHOW_ARGUMENTS = True
click.rich_click.GROUP_ARGUMENTS_OPTIONS = True
```

---

## 2. Добавить Click обёртки

### Паттерн (стандартный):
```python
import rich_click as click


@click.command("command-name")
@click.pass_context
def command_name_cmd(ctx):
    """Описание команды."""
    from curation_pipeline.core.click_cli import build_context

    state = ctx.obj
    curation_ctx = build_context(state)
    run_command_name(curation_ctx)
```

### Паттерн для команд с доп. параметрами (busco, fastga):
```python
@click.command("busco-curated")
@click.option("--lineage", required=True, help="BUSCO lineage (e.g. insecta_odb10)")
@click.pass_context
def busco_curated_cmd(ctx, lineage):
    """Run BUSCO on curated genome."""
    from curation_pipeline.core.click_cli import build_context

    state = ctx.obj
    curation_ctx = build_context(state)
    run_busco_curated(curation_ctx, lineage)
```

### Чеклист модулей:

**post_curation:**
- [x] `post_curation/pretext_to_asm.py` → `pretext_to_asm_cmd` (нет доп. параметров)
- [x] `post_curation/qv.py` → `qv_cmd` (нет доп. параметров)
- [x] `post_curation/validate_files.py` → `validate_files_cmd` (нет доп. параметров)
  - ✅ переименована функция `validate_curated_files` → `run_validate_files`

**optional:**
- [x] `optional/blast_contaminants.py` → `blast_contaminants_cmd` (нет доп. параметров)
- [x] `optional/busco_curated.py` → `busco_curated_cmd` (доп. параметр: `--lineage`)
- [x] `optional/busco_synteny.py` → `busco_synteny_cmd` (доп. параметр: `--lineage`)
- [x] `optional/fastga.py` → `fastga_cmd` (доп. параметр: `--reference` опциональный)
- [x] `optional/rename_and_orient.py` → `rename_and_orient_cmd` (нет доп. параметров)

---

## 3. Регистрация в click_cli.py

Добавить импорты и `cli.add_command(...)` для всех новых команд:

```python
from curation_pipeline.steps.post_curation.pretext_to_asm import pretext_to_asm_cmd
from curation_pipeline.steps.post_curation.qv import qv_cmd
from curation_pipeline.steps.post_curation.validate_files import validate_files_cmd
from curation_pipeline.steps.optional.blast_contaminants import blast_contaminants_cmd
from curation_pipeline.steps.optional.busco_curated import busco_curated_cmd
from curation_pipeline.steps.optional.busco_synteny import busco_synteny_cmd
from curation_pipeline.steps.optional.fastga import fastga_cmd
from curation_pipeline.steps.optional.rename_and_orient import rename_and_orient_cmd

cli.add_command(pretext_to_asm_cmd)
cli.add_command(qv_cmd)
cli.add_command(validate_files_cmd)
cli.add_command(blast_contaminants_cmd)
cli.add_command(busco_curated_cmd)
cli.add_command(busco_synteny_cmd)
cli.add_command(fastga_cmd)
cli.add_command(rename_and_orient_cmd)
```

---

## 4. Обновить чеклист в 21_new_cli_parsing_plan.md

После завершения отметить все пункты как ✅ ГОТОВО.
