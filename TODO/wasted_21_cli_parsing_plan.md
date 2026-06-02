# План реализации шага 21: Изменение парсинга аргументов в CLI

## Анализ текущего CLI

Текущий CLI использует `argparse` с плоской структурой:
- `curate <ticket_id> <command> [track] [file] [--options]`

Команды перечислены в choices, но каждая команда имеет свои специфические параметры (например, `--number` для find-reference, `--lineage` для busco, `file` для bedgraph).

Проблемы:
- Нет отдельного help для каждой команды.
- Параметры смешиваются, некоторые не релевантны для определенных команд.
- Не соответствует стилю современных CLI инструментов вроде sourmash, где каждая субкоманда имеет свой help и параметры.

## Предлагаемое решение

Перейти на структуру с субкомандами, где каждая команда имеет свой подпарсер с специфическими параметрами.

### Argparse с subparsers

Использовать `argparse.ArgumentParser.add_subparsers()` для создания субкоманд.

Пример структуры:
```
curate summary <ticket_id> [--yaml PATH] [--print-only]
curate pre <ticket_id> [--yaml PATH] [--print-only]
curate post <ticket_id> [--yaml PATH] [--print-only]
curate optional gap <ticket_id> [--yaml PATH] [--print-only]
curate optional telo <ticket_id> [--yaml PATH] [--print-only]
curate optional bedgraph <ticket_id> FILE [--yaml PATH] [--print-only]
curate sex-matcher <ticket_id> [--yaml PATH] [--print-only]
curate microchromosome <ticket_id> [--yaml PATH] [--print-only]
curate find-reference <ticket_id> [--number N] [--yaml PATH] [--print-only]
curate fastga <ticket_id> [--yaml PATH] [--print-only]
curate blast-contaminants <ticket_id> [--yaml PATH] [--print-only]
curate busco-synteny <ticket_id> --lineage LINEAGE [--yaml PATH] [--print-only]
curate busco-curated <ticket_id> --lineage LINEAGE [--yaml PATH] [--print-only]
curate rename-and-orient <ticket_id> [--yaml PATH] [--print-only]
```

Общие параметры (`--yaml`, `--print-only`) будут добавлены к каждому субпарсеру.

Парсер вынесем в отдельный скрипт (например, `cli_parser.py`), чтобы отделить логику парсинга от основной логики команд. Это упростит управление кодом: один файл отвечает за структуру CLI, другой — за выполнение команд.

## Шаги реализации

1. **Создать cli_parser.py**
   - Вынести всю логику создания парсера и subparsers в отдельный модуль.
   - Определить функцию, которая возвращает настроенный parser и parsed args.

2. **Рефакторить main() в cli.py**
   - Импортировать парсер из cli_parser.
   - Использовать dispatch-словарь для вызова команд на основе subcommand.
   - Убедиться, что общие параметры (ticket_id, yaml, print_only) передаются корректно.

3. **Протестировать help и функциональность**
   - Проверить `curate --help` показывает все субкоманды.
   - Проверить `curate <command> --help` показывает help для конкретной команды с её параметрами.
   - Запустить существующие команды для проверки совместимости.

   **Расширение шага 3: Добавить субсубкоманды для pre и post, как в sourmash, и улучшить help вывод**

   3.1. **Изменить структуру CLI для pre и post: добавить субкоманды**
      - Для `pre`: субкоманды `get_pretext_map`, `add_tracks`, `sex_matcher`, `find_reference`.
      - Для `post`: субкоманды `pretext_to_asm`, `haplotigs`, `curation-pretext`, `auto`, `fastga`, `to_qc`, `post-processing`.
      - Обновить cli_parser.py: использовать nested subparsers для pre и post.

   3.2. **Обновить cli.py для диспатча субкоманд**
      - Добавить функции cmd_pre_<subcommand> и cmd_post_<subcommand>.
      - Обновить dispatch словарь для обработки subcommand.
      - Изменить args.dest для subcommand.

   3.3. **Настроить help вывод с группами команд, как в sourmash**
      - Переопределить formatter_class в ArgumentParser для группировки команд.
      - Добавить группы: Pre-curation operations, Post-curation operations, Optional tracks, Analysis tools и т.д.

   3.4. **Протестировать обновленный help и функциональность**
      - Проверить `curate --help` показывает группы команд.
      - Проверить `curate pre --help` показывает субкоманды для pre.
      - Запустить новые субкоманды для проверки.

   3.5. **Добавить Rich для красивого help вывода**
      - Установить Rich в зависимости (уже есть в pyproject.toml).
      - Создать функцию print_custom_help() в cli_parser.py с Rich Panel и console для группировки команд.
      - Добавить RichHelpFormatter класс для переопределения help вывода.
      - Обновить main() в cli.py для вызова custom help при отсутствии команды или --help.

4. **Обновить документацию**
   - Обновить usage в docstring cli.py.
   - Возможно, добавить примеры в description.md.

## Ожидаемый результат

После реализации:
- `curate --help` покажет список доступных команд.
- `curate summary --help` покажет help только для summary с его параметрами.
- Каждая команда имеет только релевантные параметры.
- Код разделён: парсинг в cli_parser.py, логика в cli.py.
- Стиль соответствует sourmash и другим современным CLI инструментам.