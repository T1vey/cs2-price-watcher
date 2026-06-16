' CS2 Price Watcher 启动器
Dim fso, shell, scriptDir, pythonExe
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

If fso.FileExists(scriptDir & "\venv\Scripts\python.exe") Then
    pythonExe = scriptDir & "\venv\Scripts\python.exe"
ElseIf fso.FileExists(scriptDir & "\.venv\Scripts\python.exe") Then
    pythonExe = scriptDir & "\.venv\Scripts\python.exe"
Else
    pythonExe = "python.exe"
End If

shell.CurrentDirectory = scriptDir
shell.Run """" & pythonExe & """ tray_app.py", 0, False
