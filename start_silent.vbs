Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strPath = fso.GetParentFolderName(WScript.ScriptFullName)

' Run python slicer.py completely hidden in the background (0 = hide window)
WshShell.Run """C:\Users\austi\AppData\Local\Python\pythoncore-3.14-64\python.exe"" -u """ & strPath & "\slicer.py""", 0, False

' Open index.html in the default web browser
WScript.Sleep 800
WshShell.Run """" & strPath & "\index.html"""
