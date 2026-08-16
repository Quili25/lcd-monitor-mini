' Launch turing-lcd UI hidden (for Startup folder).
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
pythonw = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pythonw) Then
  pythonw = root & "\.venv\Scripts\python.exe"
End If
sh.CurrentDirectory = root
sh.Run """" & pythonw & """ -m app.main", 0, False
