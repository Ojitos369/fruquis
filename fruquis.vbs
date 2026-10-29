' Fruquis - doble clic: arranca SIN terminal. La primera vez abre una ventana para instalar el entorno.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
If Not fso.FileExists(dir & "\.venv\Scripts\pythonw.exe") Then
  sh.Run "cmd /c """ & dir & "\setup.bat""", 1, True
End If
If fso.FileExists(dir & "\.venv\Scripts\pythonw.exe") Then
  sh.Run """" & dir & "\.venv\Scripts\pythonw.exe"" -m fruquis", 0, False
End If
