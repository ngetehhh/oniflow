Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(WScript.ScriptFullName)
pythonw = files.BuildPath(root, "work\gmfss-venv\Scripts\pythonw.exe")
gui = files.BuildPath(root, "offline_license_gui.py")
shell.Run """" & pythonw & """ """ & gui & """", 0, False
