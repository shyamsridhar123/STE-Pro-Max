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
        $text = $utf8.GetString([IO.File]::ReadAllBytes($inputFile)).TrimStart([char]0xFEFF)
        if ([string]::IsNullOrWhiteSpace($text)) {
            throw 'Input text is empty or contains only whitespace.'
        }
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
        [pscustomobject]@{
            output_path = $outputFile
            voice = $selectedVoice
            bytes = $stream.Length
            duration_seconds = $dataBytes / [double]$byteRate
            non_silent_pcm = $true
        } | ConvertTo-Json -Compress
    }
} catch {
    [Console]::Error.WriteLine("Narration failed: $($_.Exception.Message)")
    exit 1
} finally {
    if ($null -ne $synth) { $synth.Dispose() }
    if ($null -ne $reader) { $reader.Dispose() }
    if ($null -ne $stream) { $stream.Dispose() }
}
