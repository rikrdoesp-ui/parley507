# Registra la tarea de Windows que actualiza datos y publica la pagina cada 30 min, de 10:00 a 01:00.
# Corre solo con la sesion iniciada (git usa tus credenciales) y sin ventana (conhost --headless).
# Si una corrida sigue en curso, la siguiente no arranca. Quitarla:  Unregister-ScheduledTask "Parley507 actualizar"
$script = Join-Path $PSScriptRoot "actualizar_auto.cmd"
$accion = New-ScheduledTaskAction -Execute "conhost.exe" -Argument "--headless cmd /c `"$script`""
$disparo = New-ScheduledTaskTrigger -Daily -At "10:00"
$disparo.Repetition = (New-ScheduledTaskTrigger -Once -At "10:00" -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Hours 15)).Repetition
$ajustes = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 25) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "Parley507 actualizar" -Action $accion -Trigger $disparo -Settings $ajustes -Force | Out-Null
Get-ScheduledTask "Parley507 actualizar" | Get-ScheduledTaskInfo | Select-Object TaskName, NextRunTime
