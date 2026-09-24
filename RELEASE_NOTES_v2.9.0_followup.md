# Ver.2.9.0 UI and manual follow-up

This follow-up collects the final usability adjustments made after the Ver.2.9.0 release.

## UI and workflow

- CSV and Excel workbook output are selected with a clear toggle-style control.
- Result recording can append to the history or initialize the log for the current run. The previous log is archived with a date when initializing.
- The result-history folder can be selected independently from the copy destination.
- The quick-preset display limit is adjustable, including increasing the number of quick presets.
- Splitter boundaries and the display scale can be adjusted to make narrow windows easier to use.
- Paths containing ampersands and Windows shortcut behavior are handled in tests.

## Validation

- `python -m unittest discover -s tests -p 'test_*.py'`: 69 tests passed.
- Windows executable launch and Microsoft Excel verification still require a Windows machine.

## Manual

The updated PDF manual appends three pages with the supplied screenshots for output/history selection, preset limits, and the latest copy screen. The existing Ver.2.9.0 GitHub release remains unchanged; publish the updated PDF with a subsequent release asset update.
