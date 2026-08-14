Ниже представлено техническое задание (ТЗ) на рефакторинг CLI-интерфейса твоего проекта. Оно учитывает разделение логики и интерфейса, а также модульность в стиле MMseqs2.

**Обновлено:** На основе договорённостей — оставляем `CurationContext` в функциях, выносим общие параметры (`--ticket`, `--yaml`, `--print-only`) в глобальные опции `click_cli.py`. Модули принимают `ctx: CurationContext`, CLI-обёртки строят контекст и вызывают логику.

---

# ТЗ: Рефакторинг CLI-интерфейса `curation_pipeline`

## 1. Цель
Перевести текущую систему парсинга аргументов на библиотеку **Click**, внедрив модульную архитектуру, которая позволит использовать компоненты как независимые Python-функции и как команды терминала без дублирования кода.

## 2. Ключевые принципы архитектуры
1.  **Разделение ответственности (Decoupling)**: Бизнес-логика (функции) используют проектный контекст `CurationContext`.
2.  **Ленивая загрузка (Lazy Loading)**: Тяжелые импорты (pandas, matplotlib, scipy) должны происходить внутри функций-оберток или функций-логики, чтобы `curate --help` работал мгновенно.
3.  **Единый контекст**: Глобальные параметры (ticket, yaml, print_only) передаются через `click.Context`.

---

## 3. Структура изменений

### 3.1. Ядро (Core)
* **`curation_pipeline/core/click_cli.py`**: Становится главной точкой входа.
    * Определяет базовую группу `@click.group()` с глобальными опциями (`--ticket` [required], `--yaml`, `--print-only`).
    * Инициализирует объект контекста (`ctx.obj` как `GlobalState`).
    * Импортирует и регистрирует команды из папки `steps/` с помощью `main_cli.add_command()`.
* **`curation_pipeline/core/context.py`**: Определение структуры данных для хранения глобальных настроек и путей к конфигам (без изменений).

### 3.2. Модули (Steps)
Каждый файл в `steps/pre_curation`, `steps/post_curation` и `steps/optional` должен быть приведен к следующему виду:

1.  **Core Function**: Функция `run_<name>(ctx: CurationContext)`, где `ctx` — объект контекста с данными тикета.
2.  **CLI Wrapper**: Функция `<name>_cmd`, декорированная `@click.command`, которая:
    * Не имеет специфичных опций (все глобальные).
    * Извлекает параметры из `ctx.obj`.
    * Строит `CurationContext` через `build_context(state)`.
    * Вызывает Core Function.
    * Обрабатывает вывод в консоль (через `click.echo`).

---

## 4. Пример реализации (Шаблон для рефакторинга)

Примени этот паттерн ко всем модулям:

```python
# Файл: curation_pipeline/steps/pre_curation/sex_matcher.py


def run_sex_matcher(ctx: CurationContext) -> None:
    """Бизнес-логика: работает с контекстом"""
    # ... логика с ctx.workdir, ctx.tol_id и т.д. ...
    pass


import click


@click.command("sex-matcher")
@click.pass_context
def sex_matcher_cmd(ctx):
    """CLI обёртка: строит контекст и вызывает логику"""
    from curation_pipeline.core.click_cli import build_context, GlobalState

    state = ctx.obj
    curation_ctx = build_context(state)
    run_sex_matcher(curation_ctx)
```

---

## 5. План миграции (Workflow)

1.  **Этап 1: Каркас** ✅ ГОТОВО
    * `core/click_cli.py` с базовой группой `cli` и глобальными опциями.

2.  **Этап 2: Изоляция логики** ✅ ЧАСТИЧНО
    * Модули в `steps/` уже имеют функции `run_...` с `CurationContext`.
    * Если логика перемешана с `argparse` или `sys.argv`, вынести в `run_...` (но в текущем коде уже разделено).

3.  **Этап 3: Регистрация** ✅ ГОТОВО
    * Импортировать `cmd`-обёртки и добавить в основную группу.

4.  **Этап 4: Реализация "Воркфлоу"**
    * Для высокоуровневых команд (например, `busco_synteny`) реализовать вызов логики других модулей через прямой импорт функций `run_...`, а не через `ctx.invoke`.

5.  **Этап 5: Чеклист модулей**
    - [x] `pre_curation/sex_matcher.py` ✅ ГОТОВО
    - [x] `pre_curation/add_pretext_view_tracks.py` ✅ ГОТОВО
    - [x] `pre_curation/find_reference.py` ✅ ГОТОВО
    - [x] `pre_curation/microchromosome.py` ✅ ГОТОВО
    - [x] `pre_curation/setup.py` ✅ ГОТОВО
    - [x] `post_curation/finalize_qc.py` ✅ ГОТОВО
    - [x] `post_curation/haplotig_files.py` ✅ ГОТОВО
    - [x] `post_curation/hic_remapping.py` ✅ ГОТОВО
    - [x] `post_curation/post_curation.py` ✅ ГОТОВО
    - [x] `post_curation/pretext_to_asm.py` ✅ ГОТОВО
    - [x] `post_curation/qv.py` ✅ ГОТОВО
    - [x] `post_curation/validate_files.py` ✅ ГОТОВО
    - [x] `optional/blast_contaminants.py` ✅ ГОТОВО
    - [x] `optional/busco_curated.py` ✅ ГОТОВО
    - [x] `optional/busco_synteny.py` ✅ ГОТОВО
    - [x] `optional/fastga.py` ✅ ГОТОВО
    - [x] `optional/rename_and_orient.py` ✅ ГОТОВО

---

## 6. Требования к реализации
* **Валидация**: Использовать встроенные типы Click (`click.Path`, `click.Choice`, `click.IntRange`) вместо ручных проверок.
* **Справка**: Каждая команда должна иметь `help` строку.
* **Тестируемость**: Код должен позволять написать тест вида `test_logic()`, который вызывает `run_...` без участия Click.

---

## 7. Ожидаемый результат
Пользователь может использовать инструмент двумя способами:
1.  **Терминал**: `python click_cli.py --ticket RC-123 --print-only sex-matcher`
2.  **Python-код**:
    ```python
    from curation_pipeline.steps.pre_curation.sex_matcher import run_sex_matcher

    ctx = CurationContext.from_ticket("RC-123", user_config)
    run_sex_matcher(ctx)
    ```