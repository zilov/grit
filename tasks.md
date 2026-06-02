# Context

- Посмотри _helpers.py чтобы понимать названия общих функций, чтобы не дублироваться. если функция которую ты пишешь потенциально может быть полезна для многих шагов - можешь писать сразу в helpers.py

# Tasks

- [x] 1. Создать структуру проекта и `CurationContext` — `pyproject.toml`, `curation_pipeline/`, `context.py` с dataclass и `build_context()`, тесты `test_context.py`
- [x] 2. Инвентаризация функций ноутбука — прочитать весь ноутбук, разложить функции по модулям (`pre_curation.py`, `post_curation.py`, `optional.py`)
- [x] 3. Портировать pre-curation шаги с тестами — `setup_curation`, `copy_pretext_maps`, `print_curation_summary` → `pre_curation.py` + тесты
- [x] 4. Перевести весь русский текст в кодовой базе на английский
- [x] 5. Add real YAML fixtures for tests — hap1/hap2 and primary/alternate cases (user to provide real YAMLs)
- [x] 5a. Manual local testing — run `build_context` + each pre-curation function against a real ticket YAML; verify output and file operations are correct
- [x] 6. Improve `assembly_draft_dir` parsing in `build_context()` — currently derived from file path by splitting on tol_id (fragile); derive directly from YAML field if available
- [x] 7. Implement post-curation steps: `run_pretext_to_asm`, `ensure_haplotig_files`, `run_hic_remapping`, `run_qv`, `validate_curated_files`, `finalize_for_qc`
- [x] 7a. Вынести все большие функции `run_pretext_to_asm`, `ensure_haplotig_files`, `run_hic_remapping`, `run_qv`, `validate_curated_files`, `finalize_for_qc` в отдельные скрипты.
- [x] 7b. Запустить тесты и пофиксить ошибки от переноса функций в отдельные скрпты.
- [x] 8. Implement optional pre-curation tracks: `add_gap_track`, `add_telo_track`, `add_bedgraph_track`; add `optional` subcommand to CLI (`curate RC-1234 optional gap|telo|bedgraph [FILE]`)
- [x] 9. Добавить код для опционального шага pre curation - run sex matcher
- [x] 10. Microchromosome curation: discuss workflow, review notebook source, implement `run_microchromosome_curation` + `_combine_large_and_small_fasta`
- [x] 11. Добавить print_only режим, в котором не будут отправляться таски в lsf, а только будут выводиться комадны для мануального запуска
- [x] 12. Добавить код для опционального шага - run-fastga
- [x] 13. Добавить код для опционального шага - find closest reference
- [x] 14. Добавить код для опционального шага - run blast contaminants search in shrapnel
- [x] 16. Добавить код для опционального шага - run busco synteny
- [x] 17. Добавить код для опционального шага - run busco on curated genome
- [x] 18. Добавить код для опционального шага - rename and orient to reference

На этой стадии условно у нас готов прототип нашего приложения - он не без косяков но общую концепцию описывает, дальше у нас будут шаги тестирования, рефакторинга и добавление более осмысленного функционала, документация и ci/cd. Тут нам потребуется более осмысленная работа и более конкретно прописанные шаги плана выполнения задачек - они будут в отдельных md файликах в папке todo. Для каждого файла используй короткое название с номером шага который мы будем делать. 

- [x] 19. Создать папку TODO в которую будем писать планы реализации новых фич.
- [x] 20. Для TODO. Высокоуровнево посмотреть на организацию библиотеки и придумать реорганизацию которая будет логична и удобна для поддержки кода. Учесть в плане реорганизации шаги 21-25. 
- [x] 21. Для TODO. Изменить парсинг аргументов в cli, для каждого шага должен быть доступен свой help и специфичные для шага параметры. протестировать два подхода click и argparse. как пример ожидаемого вида парсинга и организации команд тулза sourmash (можно посмотреть conda activate sourmash && sourmash --help)
- [] 22. Для TODO. Прописать план тестирования на сервере каждого шага который есть у нас в туле через cli.
- [] 23. Для TODO. Прописать план тестирования на сервере каждого шага который есть у нас в туле через jupyter notebook.
- [] 24. Для TODO. Продумать как парсить workdir для расширения контекста перед запуском любого шага чтобы понимать статус работы по тикету или же придумать как хранить и обновлять контекст внутри workdir, условно если референс уже скачан - он должен быть в контексте, если sex-matcher результаты есть - тоже.
- [] 25. Для TODO. Продумать как будем организовывать документацию - sphynx и readthedocs как база, sourmash как пример хорошей документации для пользователей.
- [] XXX. Для TODO. Подумать как организовать работу этого тулкита для пользователей outside of sanger. Minimal YAML, slurm run, local run, доступ к скриптам.

