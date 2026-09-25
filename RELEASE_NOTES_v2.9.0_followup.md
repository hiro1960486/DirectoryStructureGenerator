# Ver.2.9.0 UI follow-up

This follow-up is limited to the requested UI corrections and GitHub access information. The manual and other user documentation are left for a later consolidated update.

## UI changes

- Preset order controls respond immediately, selected rows have a clear highlight, and user preset names and notes can be edited in the table.
- Reference fields provide a Japanese right-click menu with an action to open the referenced folder.
- Copy confirmation text wraps in a wider dialog to prevent overlap.
- The subfolder option explains where copied files will be placed.
- The app and README identify the GitHub repository and release download page.

## Validation

- `python -m unittest discover -s tests -p 'test_*.py'`: 69 tests passed before these UI follow-up changes; rerun before merging.
- Windows EXE and Microsoft Excel checks require a Windows machine.
