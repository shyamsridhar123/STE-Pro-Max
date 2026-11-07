<#
.SYNOPSIS
Offline narration with generic Windows-installed voices; no uploads or cloning.
.EXAMPLE
powershell.exe -NoProfile -File narrate.ps1 -InputPath text.txt -OutputPath speech.wav
.EXAMPLE
powershell.exe -NoProfile -File narrate.ps1 -ListVoices
#>
[CmdletBinding()]
param(
    [string] $InputPath,
    [string] $OutputPath,
    [string] $Voice,
    [ValidateRange(-10, 10)]
    [int] $Rate = 0,
    [switch] $ListVoices
)

$ErrorActionPreference = 'Stop'
$synth = $null
$stream = $null
$reader = $null
$guardActive = $false
$policyInputs = $null
$policyState = $null
try {
    if ([Environment]::OSVersion.Platform -ne 'Win32NT' -or
        $PSVersionTable.PSEdition -ne 'Desktop' -or
        $PSVersionTable.PSVersion -lt [version]'5.1') {
        throw 'Requires Windows PowerShell 5.1: powershell.exe -NoProfile -File narrate.ps1'
    }

    function Get-LocalFilePath([string] $Path) {
        $full = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
        if ($full -notmatch '^[A-Za-z]:\\' -or $full.Substring(2).Contains(':') -or
            ([IO.DriveInfo]::new([IO.Path]::GetPathRoot($full))).DriveType -eq 'Network') {
            throw 'Use local filesystem paths, not network paths, providers, or alternate data streams.'
        }
        return $full
    }

    function Get-TrustedRuntimePath([string] $Path, [bool] $AllowLeafLink = $false) {
        $parts = [regex]::Split($Path, '[\\/]')
        if ($Path -notmatch '^[A-Za-z]:\\' -or $parts -contains '..') {
            throw 'SkillC runtime paths must be absolute local paths without parent traversal.'
        }
        foreach ($part in @($parts | Select-Object -Skip 1)) {
            if ($part.EndsWith(' ') -or $part.EndsWith('.') -or
                $part -match '^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)') {
                throw 'SkillC runtime paths must not contain ambiguous or device components.'
            }
        }
        $full = Get-LocalFilePath $Path
        $current = $full
        $leaf = $true
        while ($current) {
            if (Test-Path -LiteralPath $current) {
                $item = Get-Item -LiteralPath $current -Force
                if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -and
                    -not ($leaf -and $AllowLeafLink)) {
                    throw "SkillC runtime path contains a reparse point: $current"
                }
            }
            $leaf = $false
            $current = [IO.Path]::GetDirectoryName($current)
        }
        return $full
    }

    function ConvertTo-NativeArgument([string] $Value) {
        # Windows argv quoting: double backslashes before quotes and the closing quote.
        return '"' + [regex]::Replace(
            [regex]::Replace($Value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
    }

    function Invoke-SkillCWorker([string] $Action, [hashtable] $Payload, [switch] $Status) {
        $bootstrap = @'
import json, sys
from pathlib import Path
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
sys.path.insert(0, sys.argv[1])
from ste_promax.policy_runtime import resolve_worker_backend
_, skillc_src = resolve_worker_backend()
sys.path.append(str(skillc_src))
if sys.argv[2] == "status":
    from ste_promax.gate import get_policy_status
    result = get_policy_status()
    result["output_parent"] = str(Path(sys.argv[3]).resolve().parent)
    print(json.dumps({"ok": result["available"], "result": result, "error": result["error"]}, ensure_ascii=True))
    sys.exit(0 if result["available"] else 2)
from ste_promax._skillc_worker import main
sys.exit(main())
'@
        $mode = if ($Status) { 'status' } else { 'worker' }
        $arguments = @('-I', '-B', '-c', $bootstrap, $bundleRoot, $mode, $outputFile)
        $start = [Diagnostics.ProcessStartInfo]::new()
        $start.FileName = $policyPython
        $start.Arguments = ($arguments | ForEach-Object { ConvertTo-NativeArgument $_ }) -join ' '
        $start.WorkingDirectory = $bundleRoot
        $start.UseShellExecute = $false
        $start.CreateNoWindow = $true
        $start.RedirectStandardInput = $true
        $start.RedirectStandardOutput = $true
        $start.RedirectStandardError = $true
        $start.StandardOutputEncoding = [Text.UTF8Encoding]::new($false, $true)
        $start.StandardErrorEncoding = [Text.UTF8Encoding]::new($false, $true)
        $process = [Diagnostics.Process]::new()
        $process.StartInfo = $start
        $timer = [Diagnostics.Stopwatch]::StartNew()
        $started = $false
        try {
            $started = $process.Start()
            if (-not $started) { throw 'SkillC worker could not start.' }
            $stdout = $process.StandardOutput.ReadToEndAsync()
            $stderr = $process.StandardError.ReadToEndAsync()
            $request = @{ action = $Action; payload = $Payload } | ConvertTo-Json -Depth 30 -Compress
            $bytes = [Text.UTF8Encoding]::new($false, $true).GetBytes($request)
            $write = $process.StandardInput.BaseStream.WriteAsync($bytes, 0, $bytes.Length)
            if (-not $write.Wait([Math]::Max(1, 30000 - [int]$timer.ElapsedMilliseconds))) {
                throw 'SkillC worker timed out while receiving its request.'
            }
            $process.StandardInput.BaseStream.Close()
            if (-not $process.WaitForExit([Math]::Max(1, 30000 - [int]$timer.ElapsedMilliseconds)) -or
                -not $stdout.Wait([Math]::Max(1, 30000 - [int]$timer.ElapsedMilliseconds)) -or
                -not $stderr.Wait([Math]::Max(1, 30000 - [int]$timer.ElapsedMilliseconds))) {
                throw 'SkillC worker exceeded its 30-second execution limit.'
            }
            $response = $stdout.Result | ConvertFrom-Json
            if ($process.ExitCode -ne 0 -or $response.ok -ne $true) {
                throw "SkillC $Action failed: $($response.error.code) $($response.error.message) $($stderr.Result.Trim())"
            }
            if ($null -eq $response.result) { throw 'SkillC worker returned no result.' }
            return $response.result
        } finally {
            if ($started -and -not $process.HasExited) {
                $process.Kill()
                $null = $process.WaitForExit(1000)
            }
            $process.Dispose()
        }
    }

    function Get-Sha256Hex([byte[]] $Bytes) {
        $hasher = [Security.Cryptography.SHA256]::Create()
        try {
            return [BitConverter]::ToString($hasher.ComputeHash($Bytes)).Replace('-', '').ToLowerInvariant()
        } finally {
            $hasher.Dispose()
        }
    }

    function Get-WavObservation {
        $files = @{}
        if ([IO.File]::Exists($outputFile)) {
            $wavBytes = [IO.File]::ReadAllBytes($outputFile)
            $files[$outputFile] = @{
                sha256 = (Get-Sha256Hex $wavBytes)
                size = [int64]$wavBytes.Length
            }
        }
        return $files
    }

    if (-not $ListVoices) {
        if ([string]::IsNullOrWhiteSpace($InputPath) -or [string]::IsNullOrWhiteSpace($OutputPath)) {
            throw 'Both -InputPath (UTF-8 text file) and -OutputPath (new WAV file) are required.'
        }
        $inputFile = Get-LocalFilePath $InputPath
        $outputFile = Get-LocalFilePath $OutputPath
        if (-not [IO.File]::Exists($inputFile)) {
            throw 'InputPath must be an existing readable text file.'
        }
        if ([IO.File]::Exists($outputFile) -or [IO.Directory]::Exists($outputFile)) {
            throw 'OutputPath already exists; refusing to overwrite it.'
        }
        if ([IO.Path]::GetExtension($outputFile) -ine '.wav' -or
            -not [IO.Directory]::Exists([IO.Path]::GetDirectoryName($outputFile))) {
            throw 'OutputPath must end in .wav and its parent directory must exist.'
        }
        $utf8 = [Text.UTF8Encoding]::new($false, $true)
        $inputBytes = [IO.File]::ReadAllBytes($inputFile)
        $text = $utf8.GetString($inputBytes).TrimStart([char]0xFEFF)
        if ([string]::IsNullOrWhiteSpace($text)) {
            throw 'Input text is empty or contains only whitespace.'
        }
        $inputSha256 = Get-Sha256Hex $inputBytes
    }

    try {
        Add-Type -AssemblyName System.Speech
        $synth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
    } catch {
        throw "Windows System.Speech is unavailable: $($_.Exception.Message)"
    }
    $voices = @($synth.GetInstalledVoices() | Where-Object { $_.Enabled } |
        ForEach-Object { $_.VoiceInfo.Name })
    if ($ListVoices) {
        [pscustomobject]@{ voices = $voices } | ConvertTo-Json -Compress
    } else {
        if ($voices.Count -eq 0) {
            throw 'No enabled Windows speech voices are installed.'
        }
        if ($PSBoundParameters.ContainsKey('Voice')) {
            $selected = @($voices | Where-Object { $_ -ceq $Voice })
            if ($selected.Count -eq 0) {
                throw "Voice '$Voice' is unavailable. Use -ListVoices to list installed voices."
            }
            $synth.SelectVoice($selected[0])
        }
        $synth.Rate = $Rate
        $selectedVoice = $synth.Voice.Name
        $bundleRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
        $bundleRoot = Get-TrustedRuntimePath $bundleRoot
        if (-not [IO.File]::Exists((Join-Path $bundleRoot 'ste_promax\__init__.py')) -or
            -not [IO.File]::Exists((Join-Path $bundleRoot 'ste_promax\_skillc_worker.py'))) {
            throw 'The narration script bundle must contain the native STE SkillC worker.'
        }
        $policyPython = [Environment]::GetEnvironmentVariable('STE_SKILLC_PYTHON', 'Process')
        $policyRoot = [Environment]::GetEnvironmentVariable('STE_SKILLC_ROOT', 'Process')
        if (-not [string]::IsNullOrWhiteSpace($policyPython) -or
            -not [string]::IsNullOrWhiteSpace($policyRoot)) {
            if ([string]::IsNullOrWhiteSpace($policyPython) -or [string]::IsNullOrWhiteSpace($policyRoot)) {
                throw 'STE_SKILLC_PYTHON and STE_SKILLC_ROOT must both be configured.'
            }
            $policyPython = $policyPython.Trim()
        } else {
            $configPath = [Environment]::GetEnvironmentVariable('STE_SKILLC_RUNTIME_CONFIG', 'Process')
            if ([string]::IsNullOrWhiteSpace($configPath)) {
                $localData = [Environment]::GetEnvironmentVariable('LOCALAPPDATA', 'Process')
                if ([string]::IsNullOrWhiteSpace($localData)) {
                    $localData = Join-Path ([Environment]::GetFolderPath('UserProfile')) 'AppData\Local'
                }
                $configPath = Join-Path $localData 'STE-Pro-Max\skillc-runtime\runtime.json'
            }
            $configPath = Get-TrustedRuntimePath $configPath.Trim()
            if (-not [IO.File]::Exists($configPath) -or
                ([IO.FileInfo]::new($configPath)).Length -gt 1048576) {
                throw 'An owned SkillC runtime.json (at most 1 MiB) is required.'
            }
            $config = $utf8.GetString([IO.File]::ReadAllBytes($configPath)) | ConvertFrom-Json
            if ($config.schema -cne 'ste-promax.runtime.v1' -or $config.managed_by -cne 'ste-promax' -or
                $config.skillc_commit -isnot [string] -or [string]::IsNullOrWhiteSpace($config.skillc_commit) -or
                $config.versions -isnot [pscustomobject]) {
                throw 'SkillC runtime.json is not an owned ste-promax.runtime.v1 configuration.'
            }
            foreach ($key in @('python', 'skillc_root', 'ste_root', 'state_root')) {
                if ($config.$key -isnot [string] -or [string]::IsNullOrWhiteSpace($config.$key)) {
                    throw "SkillC runtime.json requires a nonempty $key path."
                }
                $null = Get-TrustedRuntimePath $config.$key ($key -eq 'python')
            }
            $policyPython = $config.python
        }
        $policyPython = Get-TrustedRuntimePath $policyPython $true
        if (-not [IO.File]::Exists($policyPython) -or ([IO.FileInfo]::new($policyPython)).Length -eq 0) {
            throw 'Configured SkillC Python must be an existing nonempty file.'
        }
        $status = Invoke-SkillCWorker 'guard_status' @{} -Status
        $policyState = Join-Path $status.state_root ('runs\ste-synthesize-wav-' + [guid]::NewGuid().ToString('N'))
        $policyState = Get-TrustedRuntimePath $policyState
        # Compare canonical paths so Windows 8.3 aliases cannot hide state/output overlap.
        $outputDirectory = ([string]$status.output_parent).TrimEnd('\')
        $stateDirectory = $policyState.TrimEnd('\')
        if ($stateDirectory.Equals($outputDirectory, [StringComparison]::OrdinalIgnoreCase) -or
            $stateDirectory.StartsWith($outputDirectory + '\', [StringComparison]::OrdinalIgnoreCase) -or
            $outputDirectory.StartsWith($stateDirectory + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'SkillC state must stay outside the WAV output directory.'
        }
        # Bind the WAV target, not its parent: standalone text and WAV may share a directory.
        $policyInputs = @{
            caller_kind = 'native'
            workspace_root = $bundleRoot
            source_paths = @($inputFile)
            source_path = $inputFile
            source_sha256 = $inputSha256
            target_paths = @($outputFile)
            text_path = $inputFile
            audio_path = $outputFile
            source_kind = 'text'
            voice = $selectedVoice
            speaker_injected = $false
            speech_available = $true
            expected_before = @{ $outputFile = $null }
        }
        $pre = Invoke-SkillCWorker 'guard_pre' @{
            op = 'ste.synthesize_wav'; inputs = $policyInputs; state_dir = $policyState
        }
        if ($pre.allowed -ne $true -or $pre.phase -ne 'pre') { throw 'SkillC did not allow WAV synthesis.' }
        $guardActive = $true
        # CreateNew is atomic: even a competing writer cannot cause an overwrite.
        $stream = [IO.File]::Open($outputFile, [IO.FileMode]::CreateNew,
            [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        $synth.SetOutputToWaveStream($stream)
        $synth.Speak($text)
        $synth.SetOutputToNull()
        $stream.Flush()
        $stream.Position = 0
        $reader = [IO.BinaryReader]::new($stream, [Text.Encoding]::ASCII, $true)
        if ([Text.Encoding]::ASCII.GetString($reader.ReadBytes(4)) -ne 'RIFF' -or
            $reader.ReadUInt32() -ne ($stream.Length - 8) -or
            [Text.Encoding]::ASCII.GetString($reader.ReadBytes(4)) -ne 'WAVE') {
            throw 'Synthesis did not emit a valid RIFF/WAVE file.'
        }
        $pcm = $false
        $dataBytes = 0
        $byteRate = 0
        $blockAlign = 0
        $hasSignal = $false
        while ($stream.Position + 8 -le $stream.Length) {
            $chunk = [Text.Encoding]::ASCII.GetString($reader.ReadBytes(4))
            $size = $reader.ReadUInt32()
            $end = $stream.Position + $size
            if ($end -gt $stream.Length) { throw 'Truncated WAV chunk.' }
            if ($chunk -eq 'fmt ' -and $size -ge 16) {
                $tag = $reader.ReadUInt16()
                $channels = $reader.ReadUInt16()
                $sampleRate = $reader.ReadUInt32()
                $byteRate = $reader.ReadUInt32()
                $blockAlign = $reader.ReadUInt16()
                $bits = $reader.ReadUInt16()
                $pcm = ($tag -eq 1 -and $channels -gt 0 -and $sampleRate -gt 0 -and
                    $bits -in @(8, 16, 24, 32) -and
                    $blockAlign -eq ($channels * $bits / 8) -and
                    $byteRate -eq ($sampleRate * $blockAlign))
            }
            if ($chunk -eq 'data') {
                if ($blockAlign -le 0 -or $size % $blockAlign -ne 0) {
                    throw 'Invalid PCM frame alignment.'
                }
                $dataBytes += $size
                if ($size -ge $blockAlign -and -not $hasSignal) {
                    $firstFrame = $reader.ReadBytes($blockAlign)
                    while ($stream.Position + $blockAlign -le $end -and -not $hasSignal) {
                        $frame = $reader.ReadBytes($blockAlign)
                        for ($i = 0; $i -lt $blockAlign; $i++) {
                            if ($frame[$i] -ne $firstFrame[$i]) { $hasSignal = $true; break }
                        }
                    }
                }
            }
            $stream.Position = $end + ($size % 2)
        }
        if (-not $pcm -or $dataBytes -le 0 -or $dataBytes % $blockAlign -ne 0) {
            throw 'Synthesis did not emit nonempty PCM audio.'
        }
        if (-not $hasSignal) {
            throw 'Synthesis emitted silent or constant PCM audio.'
        }
        $summary = [pscustomobject]@{
            output_path = $outputFile
            voice = $selectedVoice
            bytes = $stream.Length
            duration_seconds = $dataBytes / [double]$byteRate
            non_silent_pcm = $true
        }
        $reader.Dispose()
        $reader = $null
        $stream.Dispose()
        $stream = $null
        $post = Invoke-SkillCWorker 'guard_post' @{
            op = 'ste.synthesize_wav'; inputs = $policyInputs; state_dir = $policyState
            post_facts = @{
                native_status = 'synthesized'; outputs = (Get-WavObservation)
                checks = @('pcm_wav_synthesized'); warnings = @()
            }
        }
        if ($post.verdict -ne 'ALLOW' -or $post.phase -ne 'post') { throw 'SkillC WAV postcheck did not allow the result.' }
        $guardActive = $false
        $summary | ConvertTo-Json -Compress
    }
} catch {
    [Console]::Error.WriteLine("Narration failed: $($_.Exception.Message)")
    if ($guardActive) {
        $failureMessage = $_.Exception.Message
        try {
            if ($null -ne $synth) { $synth.Dispose(); $synth = $null }
            if ($null -ne $reader) { $reader.Dispose(); $reader = $null }
            if ($null -ne $stream) { $stream.Dispose(); $stream = $null }
            $null = Invoke-SkillCWorker 'guard_fail' @{
                op = 'ste.synthesize_wav'; inputs = $policyInputs; state_dir = $policyState
                error = $failureMessage; partial_effects = @{ files = (Get-WavObservation) }
            }
        } catch {
            [Console]::Error.WriteLine("SkillC failure recording failed: $($_.Exception.Message)")
        }
    }
    exit 1
} finally {
    if ($null -ne $synth) { $synth.Dispose() }
    if ($null -ne $reader) { $reader.Dispose() }
    if ($null -ne $stream) { $stream.Dispose() }
}
