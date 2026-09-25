# Ver.2.9.0 UI follow-up

This follow-up is limited to the requested UI corrections and GitHub access information. The manual and other user documentation are left for a later consolidated update.

## UI changes

- Preset order controls respond immediately, selected rows have a clear highlight, and user preset names and notes can be edited in the table.
- Reference fields provide a Japanese right-click menu with an action to open the referenced folder.
- Copy confirmation text wraps in a wider dialog to prevent overlap.
- The subfolder option explains where copied files will be placed.
- The app and README identify the GitHub repository and release download page.
- If Windows cannot create a native `.lnk`, the copy result still completes and writes a `.url` shortcut.

## Validation

- 43 non-GUI tests passed after these changes. The GUI test modules require PySide6, which is unavailable in the active runtime.
- Windows EXE and Microsoft Excel checks require a Windows machine.
